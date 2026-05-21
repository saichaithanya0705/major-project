"""
Agent step execution for routed tasks.

Extracted from models.models to keep routing orchestration focused on chaining
and provider calls, while this module owns delegated agent execution details.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from agents.cua_cli.agent import CLIAgent
from agents.jarvis.artifact import build_jarvis_visual_artifact
from agents.jarvis.prompts import JARVIS_SYSTEM_PROMPT
from agents.web_qa.agent import WebQAAgent
from core.assistant_logging import log_assistant_event
from models.agent_step_execution_runtime import (
    AgentExecutionOutcome,
    _coerce_agent_payload,
    capture_async_operation,
    execute_cli_agent,
    execute_task_agent,
    execute_vision_agent,
)
from models.contracts import RoutedStepResult
from models.output_file_artifacts import extract_output_file_path_from_tool_calls
from models.rapid_orchestrator_contracts import RapidAgentStepResult, RapidRouteResult
from models.rapid_step_payloads import RapidToolCallRecord
from models.routing_step_identity import routing_task_text as _routing_task_text
from models.text_normalization import clean_text as _clean_text
from models.text_normalization import (
    format_direct_response_text as _format_direct_response_text,
)
from ui.visualization_api.chat_artifact import send_chat_vision_artifact
from ui.visualization_api.chat_visibility import send_vision_chat_restore
from ui.visualization_api.status_bubble import (
    complete_status_bubble,
    show_status_bubble,
    update_status_bubble,
)


class JarvisStepModel(Protocol):
    async def generate_jarvis_response(
        self,
        prompt: str,
        screenshot: object,
    ) -> Mapping[str, object]: ...


def _extract_browser_message(history: object) -> str | None:
    if history is None:
        return None

    def _page_context_text(container: Mapping[str, object]) -> str | None:
        page_context = container.get("page_context")
        if isinstance(page_context, Mapping):
            for key in ("summary", "content"):
                value = page_context.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    return text if len(text) <= 1400 else f"{text[:1397]}..."

        result = container.get("result")
        if isinstance(result, Mapping) and result is not container:
            return _page_context_text(result)
        return None

    if isinstance(history, str):
        cleaned = _clean_text(history, "")
        return cleaned if cleaned else None

    if isinstance(history, Mapping):
        page_context_message = _page_context_text(history)
        if page_context_message:
            return page_context_message

        for key in ("final_result", "summary", "result", "message"):
            value = history.get(key)
            if isinstance(value, str) and value.strip():
                return _clean_text(value, "")
        return None

    for attr_name in ("final_result", "summary", "result", "message"):
        attr = getattr(history, attr_name, None)
        if callable(attr):
            try:
                value = attr()
            except Exception:
                continue
        else:
            value = attr

        if isinstance(value, str) and value.strip():
            return _clean_text(value, "")

    return None


def _as_execution_outcome(execution: AgentExecutionOutcome | Mapping[str, object]) -> AgentExecutionOutcome:
    if isinstance(execution, AgentExecutionOutcome):
        return execution
    return AgentExecutionOutcome(payload=_coerce_agent_payload(execution))


def _cli_completion_message(execution: AgentExecutionOutcome | Mapping[str, object]) -> str:
    execution = _as_execution_outcome(execution)
    if not execution.success:
        return _clean_text(execution.error, "CLI task failed.")
    output = _clean_text(execution.result, "")
    if output:
        return output
    output_file_path = extract_output_file_path_from_tool_calls(execution.tool_calls)
    if output_file_path:
        return f"Created file: `{output_file_path}`."
    return "CLI task completed."


def _browser_completion_message(execution: AgentExecutionOutcome | Mapping[str, object]) -> str:
    execution = _as_execution_outcome(execution)
    if not execution.success:
        return _clean_text(execution.error, "Browser task failed.")

    summary = _extract_browser_message(execution.result)
    if summary:
        return summary
    return "Browser task completed."


def _web_qa_completion_message(execution: AgentExecutionOutcome | Mapping[str, object]) -> str:
    execution = _as_execution_outcome(execution)
    if not execution.success:
        return _clean_text(execution.error, "Web QA task failed.")
    return _format_direct_response_text(execution.result, "Web QA task completed.")


def _vision_completion_message(execution: AgentExecutionOutcome | Mapping[str, object]) -> str:
    execution = _as_execution_outcome(execution)
    if not execution.success:
        return _clean_text(execution.error, "Computer task failed.")
    if execution.complete is not True:
        critic = execution.critic
        if critic is not None:
            reason = _clean_text(critic.get("reason"), "", max_len=420)
            if reason:
                return reason
        return _clean_text(execution.result, "Computer task needs more work.")
    return _clean_text(execution.result, "Computer task completed.")


async def _safe_ui_call(coro: Awaitable[object], label: str) -> None:
    try:
        await coro
    except Exception as exc:
        print(f"[UI] Failed during {label}: {exc}")


async def _start_non_rapid_status(text: str, source: str):
    await _safe_ui_call(
        show_status_bubble(text, source=source),
        "show_status_bubble",
    )


async def _finish_non_rapid_status(message: str, success: bool, source: str):
    done_text = "Task done" if success else "Task failed"
    await _safe_ui_call(
        complete_status_bubble(
            message,
            done_text=done_text,
            delay_ms=700,
            source=source,
        ),
        "complete_status_bubble",
    )


def _merge_failure_metadata(
    *,
    metadata: Mapping[str, object] | None,
    execution: AgentExecutionOutcome,
) -> dict[str, object] | None:
    merged = dict(metadata) if metadata else {}
    if execution.traceback_text:
        merged["traceback"] = execution.traceback_text
    return merged or None


def _log_non_rapid_agent_result(
    *,
    request_id: str,
    agent: str,
    task_text: str,
    message: str,
    started: float,
    execution: AgentExecutionOutcome,
    failure_fallback: str,
    success_metadata: Mapping[str, object] | None = None,
    failure_metadata: Mapping[str, object] | None = None,
) -> None:
    duration_seconds = time.monotonic() - started
    if execution.success:
        log_assistant_event(
            "agent_step_completed",
            request_id=request_id,
            agent=agent,
            task=task_text,
            message=message,
            success=True,
            duration_seconds=duration_seconds,
            metadata=dict(success_metadata) if success_metadata else None,
        )
        return

    log_assistant_event(
        "agent_step_failed",
        request_id=request_id,
        agent=agent,
        task=task_text,
        message=message,
        error=_clean_text(execution.error, failure_fallback, max_len=420),
        success=False,
        duration_seconds=duration_seconds,
        metadata=_merge_failure_metadata(
            metadata=failure_metadata,
            execution=execution,
        ),
    )


async def run_routed_agent_step(
    model: object,
    routing_result: RapidRouteResult,
    jarvis_model: str,
    request_id: str,
    get_stored_screenshot: Callable[[], object],
    prepare_vision_screenshot: Callable[..., Awaitable[object]] | None = None,
) -> RapidAgentStepResult:
    def _step(
        *,
        agent: str,
        task: str,
        success: bool,
        message: str,
        source: str,
        complete: bool | None = None,
        tool_calls: list[RapidToolCallRecord] | None = None,
    ) -> RapidAgentStepResult:
        return RoutedStepResult(
            agent=agent,
            task=task,
            success=success,
            message=message,
            source=source,
            complete=complete,
            tool_calls=tool_calls,
        ).as_dict()

    agent_name = routing_result.get("agent")
    task_text = _routing_task_text(routing_result)
    log_assistant_event(
        "agent_step_started",
        request_id=request_id,
        agent=str(agent_name or "unknown"),
        task=task_text,
    )

    if agent_name == "jarvis":
        await _start_non_rapid_status("Analyzing current screen...", source="jarvis")
        started = time.monotonic()
        if prepare_vision_screenshot is not None:
            screenshot = await prepare_vision_screenshot(keep_chat_hidden=True)
        else:
            screenshot = get_stored_screenshot()
        jarvis_prompt = JARVIS_SYSTEM_PROMPT + f"\n# User's Request:\n{routing_result.get('query', '')}"
        jarvis_execution = await capture_async_operation(
            lambda: cast(JarvisStepModel, model).generate_jarvis_response(
                jarvis_prompt,
                screenshot,
            )
        )
        if jarvis_execution.succeeded:
            jarvis_result = jarvis_execution.value
            if not isinstance(jarvis_result, Mapping):
                jarvis_result = None
        else:
            jarvis_result = None
        if jarvis_result is not None:
            function_calls = jarvis_result.get("function_calls") or []
            jarvis_summary = _clean_text(
                jarvis_result.get("summary"),
                "JARVIS completed the visual guidance task.",
                max_len=420,
            )
            visual_artifact = build_jarvis_visual_artifact(
                screenshot,
                function_calls,
            )
            has_visual_annotations = any(
                str(tool_name) in {
                    "draw_bounding_box",
                    "draw_pointer_to_object",
                    "create_text",
                    "create_text_for_box",
                }
                for tool_name, _args in function_calls
            )
            if visual_artifact:
                await _safe_ui_call(
                    send_chat_vision_artifact(
                        summary=jarvis_summary or "Screen analysis snapshot",
                        artifact=visual_artifact,
                        source="jarvis",
                    ),
                    "send_chat_vision_artifact",
                )
            if not has_visual_annotations:
                await _safe_ui_call(
                    send_vision_chat_restore(),
                    "send_vision_chat_restore",
                )
            elapsed = time.monotonic() - started
            print(f"[JARVIS] Completed in {elapsed:.2f}s")
            log_assistant_event(
                "agent_step_completed",
                request_id=request_id,
                agent="jarvis",
                task=task_text,
                message=jarvis_summary,
                success=True,
                duration_seconds=elapsed,
            )
            await _finish_non_rapid_status(
                jarvis_summary,
                True,
                source="jarvis",
            )
            await _finish_non_rapid_status(
                "Screen analysis is done.",
                True,
                source="jarvis_completion",
            )
            return _step(
                agent="jarvis",
                task=_routing_task_text(routing_result),
                success=True,
                message=jarvis_summary,
                source="jarvis",
            )
        await _safe_ui_call(
            send_vision_chat_restore(),
            "send_vision_chat_restore",
        )
        jarvis_error = (
            "JARVIS returned an invalid result payload."
            if jarvis_execution.succeeded
            else str(jarvis_execution.error)
        )
        error_message = _clean_text(jarvis_error, "JARVIS task failed.", max_len=420)
        failure_metadata = (
            {"traceback": jarvis_execution.traceback_text}
            if jarvis_execution.traceback_text
            else None
        )
        log_assistant_event(
            "agent_step_failed",
            request_id=request_id,
            agent="jarvis",
            task=task_text,
            message=error_message,
            error=jarvis_error,
            success=False,
            duration_seconds=time.monotonic() - started,
            metadata=failure_metadata,
        )
        await _finish_non_rapid_status(
            error_message,
            False,
            source="jarvis",
        )
        return _step(
            agent="jarvis",
            task=_routing_task_text(routing_result),
            success=False,
            message=error_message,
            source="jarvis",
        )

    if agent_name == "browser":
        await _start_non_rapid_status("Running browser task...", source="browser_use")
        from agents.browser.agent import BrowserAgent

        task = str(routing_result.get("task") or "")
        print(f"[Router] Browser Agent starting. Task: {task}")
        started = time.monotonic()
        execution = await execute_task_agent(
            task=task,
            agent_factory=lambda: BrowserAgent(model_name=jarvis_model),
        )

        message = _browser_completion_message(execution)
        _log_non_rapid_agent_result(
            request_id=request_id,
            agent="browser",
            task_text=task_text,
            message=message,
            started=started,
            execution=execution,
            failure_fallback="Browser task failed.",
            failure_metadata={"result": execution.result_metadata},
        )
        await _finish_non_rapid_status(
            message,
            execution.success,
            source="browser_use",
        )
        return _step(
            agent="browser",
            task=task,
            success=execution.success,
            message=message,
            source="browser_use",
            complete=execution.complete if execution.complete is not None else True,
        )

    if agent_name == "web_qa":
        await _start_non_rapid_status("Searching the web...", source="web_qa")
        task = str(routing_result.get("task") or "")
        print(f"[Router] Web QA Agent answering: {task}")
        started = time.monotonic()
        execution = await execute_task_agent(
            task=task,
            agent_factory=lambda: WebQAAgent(model=model),
            failure_complete=True,
        )

        message = _web_qa_completion_message(execution)
        _log_non_rapid_agent_result(
            request_id=request_id,
            agent="web_qa",
            task_text=task_text,
            message=message,
            started=started,
            execution=execution,
            failure_fallback="Web QA task failed.",
        )
        await _finish_non_rapid_status(
            message,
            execution.success,
            source="web_qa",
        )
        return _step(
            agent="web_qa",
            task=task,
            success=execution.success,
            message=message,
            source="web_qa",
            complete=execution.complete if execution.complete is not None else True,
        )

    if agent_name == "cua_cli":
        await _start_non_rapid_status("Running CLI task...", source="cua_cli")
        task = str(routing_result.get("task") or "")
        print(f"[Router] CLI Agent executing: {task}")
        started = time.monotonic()
        last_cli_status_text = ""
        last_cli_status_ts = 0.0

        async def _on_cli_status(text: str):
            nonlocal last_cli_status_text, last_cli_status_ts
            cleaned = _clean_text(text, "", max_len=120)
            if not cleaned:
                return
            now = asyncio.get_running_loop().time()
            if cleaned == last_cli_status_text and (now - last_cli_status_ts) < 0.2:
                return
            if (now - last_cli_status_ts) < 0.1:
                return
            last_cli_status_text = cleaned
            last_cli_status_ts = now
            await _safe_ui_call(
                update_status_bubble(cleaned, source="cua_cli"),
                "update_status_bubble",
            )

        execution = await execute_cli_agent(
            task=task,
            agent_factory=CLIAgent,
            status_callback=_on_cli_status,
        )
        if execution.success:
            print(f"[CLI Agent] Success: {execution.result}")
        else:
            print(f"[CLI Agent] Error: {execution.error}")
        message = _cli_completion_message(execution)
        _log_non_rapid_agent_result(
            request_id=request_id,
            agent="cua_cli",
            task_text=task_text,
            message=message,
            started=started,
            execution=execution,
            failure_fallback="CLI task failed.",
            success_metadata={"tool_calls": execution.tool_calls},
            failure_metadata={"tool_calls": execution.tool_calls},
        )
        await _finish_non_rapid_status(
            message,
            execution.success,
            source="cua_cli",
        )
        return _step(
            agent="cua_cli",
            task=task,
            success=execution.success,
            message=message,
            source="cua_cli",
            tool_calls=execution.tool_calls,
        )

    if agent_name == "cua_vision":
        await _start_non_rapid_status("Running computer-use task...", source="cua_vision")
        task = str(routing_result.get("task") or "")
        started = time.monotonic()
        try:
            if prepare_vision_screenshot is not None:
                screenshot = await prepare_vision_screenshot(keep_chat_hidden=False)
            else:
                screenshot = get_stored_screenshot()
        except Exception as exc:
            execution = AgentExecutionOutcome(
                payload={
                    "success": False,
                    "complete": False,
                    "result": None,
                    "error": f"Vision screenshot preparation failed: {exc}",
                },
                traceback_text=traceback.format_exc(),
            )
            message = _vision_completion_message(execution)
            _log_non_rapid_agent_result(
                request_id=request_id,
                agent="cua_vision",
                task_text=task_text,
                message=message,
                started=started,
                execution=execution,
                failure_fallback="Computer task failed.",
            )
            await _finish_non_rapid_status(
                message,
                False,
                source="cua_vision",
            )
            return _step(
                agent="cua_vision",
                task=task,
                success=False,
                message=message,
                source="cua_vision",
                complete=False,
            )

        from agents.cua_vision.agent import VisionAgent
        execution = await execute_vision_agent(
            task=task,
            screenshot=screenshot,
            agent_factory=lambda: VisionAgent(model_name=jarvis_model),
        )
        message = _vision_completion_message(execution)
        complete = execution.complete if execution.complete is not None else False
        _log_non_rapid_agent_result(
            request_id=request_id,
            agent="cua_vision",
            task_text=task_text,
            message=message,
            started=started,
            execution=execution,
            failure_fallback="Computer task failed.",
            success_metadata={
                "complete": complete,
                "critic": execution.critic,
            },
        )
        await _finish_non_rapid_status(
            message,
            bool(execution.success and complete),
            source="cua_vision",
        )
        return _step(
            agent="cua_vision",
            task=task,
            success=execution.success,
            message=message,
            source="cua_vision",
            complete=complete,
        )

    return _step(
        agent=str(agent_name or "unknown"),
        task=_routing_task_text(routing_result),
        success=False,
        message="Router returned an unknown agent.",
        source="rapid",
    )
