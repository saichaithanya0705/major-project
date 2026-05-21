"""
Response normalization and runtime finalization helpers for CLIAgent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, TypeVar


class CLIResponseLike(Protocol):
    success: bool
    output: str
    error: Optional[str]
    tool_calls: Optional[list[dict[str, Any]]]


T = TypeVar("T", bound=CLIResponseLike)


def clean_join_text(*parts: Any) -> str:
    cleaned_parts: list[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if text:
            cleaned_parts.append(text)
    return " | ".join(cleaned_parts)


def stringify_terminal_value(value: Any, max_len: int = 6000) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, indent=2, ensure_ascii=True)
        except Exception:
            text = str(value)

    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    if len(normalized) > max_len:
        clipped = normalized[: max_len - 18].rstrip()
        return f"{clipped}\n...[truncated]..."
    return normalized


def _looks_like_generic_api_failure(error_text: Optional[str]) -> bool:
    lowered = str(error_text or "").lower()
    if not lowered:
        return False
    markers = (
        "fetch failed",
        "sending request",
        "[api error:",
        "exception typeerror",
        "session error",
    )
    return any(marker in lowered for marker in markers)


def _collect_tool_error_messages(
    tool_calls: Optional[list[dict[str, Any]]],
) -> list[str]:
    messages: list[str] = []
    for tool_call in tool_calls or []:
        if not isinstance(tool_call, dict):
            continue
        if str(tool_call.get("status") or "").strip().lower() != "error":
            continue

        message = ""
        raw_error = tool_call.get("error")
        if isinstance(raw_error, dict):
            message = str(raw_error.get("message") or raw_error.get("error") or "")
        elif raw_error is not None:
            message = str(raw_error)

        if not message:
            raw_result = tool_call.get("result")
            if isinstance(raw_result, str):
                message = raw_result
            elif raw_result is not None:
                message = stringify_terminal_value(raw_result, max_len=800)

        cleaned = " ".join(str(message or "").split())
        if cleaned and cleaned not in messages:
            messages.append(cleaned)
    return messages


def _last_tool_call_failed(tool_calls: Optional[list[dict[str, Any]]]) -> bool:
    for tool_call in reversed(tool_calls or []):
        if not isinstance(tool_call, dict):
            continue
        status = str(tool_call.get("status") or "").strip().lower()
        if status:
            return status == "error"
    return False


def normalize_cli_response(response: T) -> T:
    tool_errors = _collect_tool_error_messages(response.tool_calls)
    if not tool_errors:
        return response

    primary_error = tool_errors[-1]
    if _last_tool_call_failed(response.tool_calls):
        response.success = False

    if not response.output and not response.success:
        response.output = primary_error

    if response.error:
        if _looks_like_generic_api_failure(response.error):
            response.error = clean_join_text(primary_error, response.error)
    elif not response.success:
        response.error = primary_error

    return response


@dataclass(frozen=True)
class ResponseRuntimeDependencies:
    infer_server_launch_from_tool_calls: Callable[
        [Optional[list[dict[str, Any]]]],
        Optional[dict[str, Any]],
    ]
    extract_port_candidates: Callable[[str], list[int]]
    wait_for_any_port: Callable[..., Awaitable[int | None]]
    start_background_process: Callable[..., Awaitable[dict[str, Any]]]
    build_cli_env: Callable[[], dict[str, str]]
    is_timeout_error_text: Callable[[Optional[str]], bool]


async def validate_local_server_claim(
    output_text: str,
    *,
    extract_port_candidates: Callable[[str], list[int]],
    wait_for_any_port: Callable[..., Awaitable[int | None]],
) -> Optional[str]:
    if not output_text:
        return None
    lowered = output_text.lower()
    has_localhost_hint = ("localhost" in lowered) or ("127.0.0.1" in lowered) or ("port " in lowered)
    has_running_hint = any(
        word in lowered
        for word in ("running", "started", "listening", "serving", "available at")
    )
    if not (has_localhost_hint and has_running_hint):
        return None

    ports = extract_port_candidates(output_text)
    if not ports:
        return None
    opened = await wait_for_any_port(ports=ports, timeout_seconds=15.0)
    if opened is not None:
        return None
    return (
        "Task reported a local server as running, but none of the claimed ports are reachable: "
        f"{ports}. The process likely exited or never started successfully."
    )


async def maybe_promote_server_launch_from_tool_calls(
    task: str,
    response: T,
    *,
    deps: ResponseRuntimeDependencies,
) -> Optional[dict[str, Any]]:
    launch = deps.infer_server_launch_from_tool_calls(response.tool_calls)
    if not launch:
        return None

    launch_command = str(launch["command"])
    launch_cwd = str(launch["cwd"])

    combined = "\n".join(filter(None, [task, response.output, launch_command]))
    ports = deps.extract_port_candidates(combined)
    if ports:
        opened = await deps.wait_for_any_port(ports=ports, timeout_seconds=1.2)
        if opened is not None:
            if deps.is_timeout_error_text(response.error):
                return {
                    "success": True,
                    "result": clean_join_text(
                        response.output,
                        f"Local server is reachable on http://127.0.0.1:{opened}.",
                    ),
                    "error": None,
                    "tool_calls": response.tool_calls,
                }
            return None

    started = await deps.start_background_process(
        command=launch_command,
        env=deps.build_cli_env(),
        working_dir=launch_cwd,
        task=task,
    )

    merged_tool_calls: list[dict[str, Any]] = []
    if response.tool_calls:
        merged_tool_calls.extend(response.tool_calls)
    started_tool_calls = started.get("tool_calls")
    if isinstance(started_tool_calls, list):
        merged_tool_calls.extend(started_tool_calls)

    return {
        "success": True,
        "result": clean_join_text(response.output, started.get("result")),
        "error": None,
        "tool_calls": merged_tool_calls or None,
    }


async def finalize_cli_response(
    task: str,
    response: T,
    *,
    deps: ResponseRuntimeDependencies,
) -> dict[str, Any]:
    normalized = normalize_cli_response(response)

    if normalized.tool_calls:
        promoted = await maybe_promote_server_launch_from_tool_calls(
            task,
            normalized,
            deps=deps,
        )
        if promoted is not None:
            return promoted

    localhost_claim_error = await validate_local_server_claim(
        normalized.output,
        extract_port_candidates=deps.extract_port_candidates,
        wait_for_any_port=deps.wait_for_any_port,
    )
    if localhost_claim_error:
        if normalized.tool_calls:
            promoted = await maybe_promote_server_launch_from_tool_calls(
                task,
                normalized,
                deps=deps,
            )
            if promoted is not None:
                return promoted
        return {
            "success": False,
            "result": normalized.output,
            "error": localhost_claim_error,
            "tool_calls": normalized.tool_calls,
        }

    return {
        "success": normalized.success,
        "result": normalized.output,
        "error": normalized.error,
        "tool_calls": normalized.tool_calls,
    }
