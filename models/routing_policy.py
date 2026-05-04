"""
Routing policy helpers for rapid-model orchestration.

This module is intentionally pure and side-effect light so routing behavior can
be tested and evolved independently from model/provider orchestration.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from models.contracts import RouteDecision

_VISUAL_EXPLAIN_MARKERS = (
    "analyze my screen",
    "analyse my screen",
    "analyze the screen",
    "analyse the screen",
    "analyze this screen",
    "analyse this screen",
    "analyze what's on my screen",
    "analyse what's on my screen",
    "look at my screen",
    "look at the screen",
    "look at this screen",
    "check my screen",
    "check the screen",
    "inspect my screen",
    "inspect the screen",
    "what do you see",
    "what do u see",
    "what's on my screen",
    "what is on my screen",
    "what am i looking at",
    "describe my screen",
    "describe what you see",
    "explain what you see",
    "explain my screen",
    "explain this screen",
    "tell me what you see",
    "can you see my screen",
)
_EXECUTION_INTENT_MARKERS = (
    "click",
    "open",
    "run",
    "type",
    "install",
    "clone",
    "start",
    "stop",
    "search",
    "go to",
    "create",
    "delete",
    "move",
    "copy",
    "paste",
    "scroll",
    "press",
    "launch",
    "execute",
    "minimize",
    "maximize",
    "restore",
    "close",
    "switch",
    "focus",
    "drag",
    "drop",
    "select",
    "debug",
    "fix",
    "build",
    "deploy",
    "test",
    "edit",
    "update",
)
_BROWSER_EXECUTION_MARKERS = (
    "http://",
    "https://",
    "www.",
    "browser",
    "website",
    "web site",
    "webpage",
    "tab",
    "url",
    ".com",
    ".org",
    ".net",
)
_VISION_EXECUTION_MARKERS = (
    "click",
    "button",
    "menu",
    "dropdown",
    "checkbox",
    "radio button",
    "icon",
    "drag",
    "drop",
    "cursor",
    "on screen",
    "desktop app",
    "window",
    "dialog",
)
_CLI_EXECUTION_MARKERS = (
    "terminal",
    "from terminal",
    "shell",
    "command",
    "powershell",
    "bash",
    "zsh",
    "cmd",
    "ping",
    "curl",
    "wget",
    "nslookup",
    "tracert",
    "ipconfig",
    "git",
    "npm",
    "pnpm",
    "yarn",
    "pip",
    "python",
    "node",
    "repo",
    "repository",
    "file",
    "folder",
    "directory",
    "localhost",
    "127.0.0.1",
)
_WINDOW_MANAGEMENT_MARKERS = (
    "minimize",
    "maximize",
    "restore",
    "close the app",
    "close the window",
    "switch window",
    "focus window",
)
_DESKTOP_SURFACE_MARKERS = (
    "desktop app",
    "installed app",
    "native app",
    "local app",
    "application",
    "app window",
    "desktop window",
    "existing window",
    "already open",
    "currently open",
    "active window",
    "current window",
    "my browser",
    "my installed browser",
    "use my browser",
    "open my browser",
)
_SPECIFIC_BROWSER_CONTEXT_MARKERS = (
    "profile",
    "work profile",
    "personal profile",
    "browser profile",
    "specific profile",
)
_BROWSER_SURFACE_MARKERS = (
    "browser",
    "new tab",
    "tab",
    "web",
    "website",
    "web site",
    "webpage",
    "url",
    "http://",
    "https://",
    "www.",
)
_ROUTER_AGENT_CHOICES = {"direct", "jarvis", "browser", "cua_cli", "cua_vision", "screen_context"}


def _clean_text(value: Any, fallback: str, max_len: int = 1400) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def _extract_latest_request_from_router_prompt(prompt: str) -> str:
    markers = (
        "# User's Latest Request:\n",
        "# User's Request:\n",
    )
    for marker in markers:
        if marker in prompt:
            tail = prompt.rsplit(marker, 1)[-1].strip()
            if tail:
                return tail
    return _clean_text(prompt, "", max_len=1800)


def _routing_task_text(routing_result: dict[str, Any]) -> str:
    return _clean_text(
        routing_result.get("task") or routing_result.get("query") or "",
        "",
        max_len=220,
    )


def _routing_signature(routing_result: dict[str, Any]) -> tuple[str, str]:
    return (
        str(routing_result.get("agent") or "").strip().lower(),
        _routing_task_text(routing_result).strip().lower(),
    )


def _format_blocked_step_signatures_for_prompt(
    blocked_step_signatures: Optional[set[tuple[str, str]]],
) -> str:
    if not blocked_step_signatures:
        return ""

    lines = []
    for agent, task in sorted(blocked_step_signatures):
        lines.append(f"- agent={agent} task={task}")

    return (
        "\n# Loop Guard\n"
        "The following delegated steps already repeated in this turn and are now blocked.\n"
        "Do NOT choose them again unless the user explicitly asked to repeat the exact same action.\n"
        "Choose a materially different next step, request `screen_context` if verification is needed, "
        "or call `direct_response` if the overall task is complete.\n"
        + "\n".join(lines)
        + "\n"
    )


def _format_chain_state_for_prompt(
    user_prompt: str,
    chain_steps: list[dict[str, Any]],
    max_steps: int,
    latest_screen_context: Optional[dict[str, Any]],
    blocked_step_signatures: Optional[set[tuple[str, str]]] = None,
) -> str:
    context_lines = ""
    if latest_screen_context:
        summary = _clean_text(latest_screen_context.get("summary"), "", max_len=260)
        repo_url = _clean_text(latest_screen_context.get("repo_url"), "", max_len=220)
        local_url = _clean_text(latest_screen_context.get("local_url"), "", max_len=220)
        recommended_agent = _clean_text(latest_screen_context.get("recommended_agent"), "", max_len=40)
        recommended_task = _clean_text(latest_screen_context.get("recommended_task"), "", max_len=240)
        hints = _clean_text(latest_screen_context.get("hints"), "", max_len=240)

        rows = []
        if summary:
            rows.append(f"- Summary: {summary}")
        if repo_url:
            rows.append(f"- Repo URL: {repo_url}")
        if local_url:
            rows.append(f"- Local URL: {local_url}")
        if recommended_agent:
            rows.append(f"- Recommended agent: {recommended_agent}")
        if recommended_task:
            rows.append(f"- Recommended next task: {recommended_task}")
        if hints:
            rows.append(f"- Extra hints: {hints}")
        if rows:
            context_lines = "\n# Latest Screen Context\n" + "\n".join(rows) + "\n"
    loop_guard_lines = _format_blocked_step_signatures_for_prompt(blocked_step_signatures)

    if not chain_steps:
        return (
            "\n# Multi-Agent Chaining Mode\n"
            "This task may require multiple delegated tools.\n"
            "Pick the best first tool call, and treat this as step 1 of a multi-step execution.\n"
            "Before choosing, compare agent capabilities against the underlying data source and required action.\n"
            "Prefer CLI for programmatically inspectable local state; use CUA vision only for intrinsic visual UI interaction.\n"
            "If the request depends on currently visible UI context, call `request_screen_context` first.\n"
            "For action/execution requests ('do X for me', clone/run/open/click/type), do NOT use `invoke_jarvis`.\n"
            "Use `invoke_jarvis` only for explanation/annotation requests.\n"
            "When the overall user request is fully complete, call `direct_response`.\n"
            + context_lines
            + loop_guard_lines
            + f"Never exceed {max_steps} delegated steps.\n"
        )

    lines = []
    for idx, step in enumerate(chain_steps, start=1):
        complete = step.get("complete", True) is not False
        lines.append(
            f"{idx}. agent={step.get('agent')} success={step.get('success')} complete={complete} "
            f"task={step.get('task')} outcome={step.get('message')}"
        )

    return (
        "\n# Multi-Agent Chaining Mode\n"
        "Continue from prior delegated work. Choose the single best next tool call.\n"
        "If the original request is complete, call `direct_response` now.\n"
        "If any recent delegated step has complete=False, do NOT call `direct_response`; choose a different agent or verification step to finish the remaining work.\n"
        "Before choosing, compare agent capabilities against the underlying data source and required action.\n"
        "Prefer CLI for programmatically inspectable local state; use CUA vision only for intrinsic visual UI interaction.\n"
        "Avoid repeating the exact same delegated step unless something materially changed.\n"
        "If you still need visible context, call `request_screen_context` again.\n"
        "For action/execution requests, do NOT use `invoke_jarvis`.\n"
        f"Original request: {user_prompt}\n"
        f"Completed delegated steps ({len(chain_steps)}/{max_steps}):\n"
        + "\n".join(lines)
        + context_lines
        + loop_guard_lines
        + "\n"
    )


def _parse_json_object_from_text(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        return {}

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start:end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {}


def _normalize_screen_context_payload(
    payload: dict[str, Any],
    user_request: str,
) -> dict[str, Any]:
    recommended_agent = str(payload.get("recommended_agent") or "").strip().lower()
    if recommended_agent not in {"cua_cli", "cua_vision", "browser", "jarvis", "direct"}:
        recommended_agent = ""

    recommended_task = _clean_text(payload.get("recommended_task"), "", max_len=420)
    if not recommended_task:
        recommended_task = _clean_text(user_request, "", max_len=420)

    normalized = {
        "summary": _clean_text(payload.get("summary"), "", max_len=420),
        "repo_url": _clean_text(payload.get("repo_url"), "", max_len=420),
        "local_url": _clean_text(payload.get("local_url"), "", max_len=420),
        "recommended_agent": recommended_agent,
        "recommended_task": recommended_task,
        "hints": _clean_text(payload.get("hints"), "", max_len=420),
    }

    return normalized


def _screen_context_message(screen_context: dict[str, Any]) -> str:
    summary = _clean_text(screen_context.get("summary"), "Screen context captured.", max_len=260)
    repo_url = _clean_text(screen_context.get("repo_url"), "", max_len=120)
    local_url = _clean_text(screen_context.get("local_url"), "", max_len=120)
    recommended_agent = _clean_text(screen_context.get("recommended_agent"), "", max_len=40)

    extras = []
    if repo_url:
        extras.append(f"repo={repo_url}")
    if local_url:
        extras.append(f"local={local_url}")
    if recommended_agent:
        extras.append(f"next={recommended_agent}")

    if extras:
        return f"{summary} ({', '.join(extras)})"
    return summary


def _user_requested_repeat(user_prompt: str) -> bool:
    lowered = (user_prompt or "").lower()
    markers = [
        "repeat",
        "again",
        "do it again",
        "rerun",
        "redo",
        "one more time",
    ]
    return any(marker in lowered for marker in markers)


def _looks_like_repeat_artifact(text: str) -> bool:
    lowered = (text or "").lower()
    patterns = [
        "repeat the exact same task",
        "already completed",
        "already created",
        "already moved",
        "already done",
        "is there anything else i can help you with",
    ]
    return any(pattern in lowered for pattern in patterns)


def _contains_phrase_or_word(text: str, marker: str) -> bool:
    if " " in marker:
        return marker in text
    return bool(re.search(rf"\b{re.escape(marker)}\b", text))


def _matches_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    return any(_contains_phrase_or_word(lowered, marker) for marker in markers)


def _is_execution_request(text: str) -> bool:
    return _matches_any_marker(text, _EXECUTION_INTENT_MARKERS)


def _is_window_management_request(text: str) -> bool:
    return _matches_any_marker(text, _WINDOW_MANAGEMENT_MARKERS)


def _requires_desktop_control_surface(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False

    if _is_window_management_request(lowered):
        return True

    has_desktop_surface = _matches_any_marker(lowered, _DESKTOP_SURFACE_MARKERS)
    has_specific_browser_context = _matches_any_marker(lowered, _SPECIFIC_BROWSER_CONTEXT_MARKERS)
    has_browser_surface = _matches_any_marker(lowered, _BROWSER_SURFACE_MARKERS)

    if has_desktop_surface and (has_browser_surface or has_specific_browser_context):
        return True
    if has_specific_browser_context and has_browser_surface and _is_execution_request(lowered):
        return True
    return False


def _is_visual_explanation_request(user_prompt: str) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    if _is_execution_request(lowered):
        return False
    if _is_window_management_request(lowered):
        return False

    screen_analysis_terms = (
        "analyze",
        "analyse",
        "describe",
        "explain",
        "look at",
        "check",
        "inspect",
        "what",
        "what's",
        "what is",
        "tell me",
    )
    mentions_screen = "screen" in lowered or "what you see" in lowered
    if mentions_screen and any(term in lowered for term in screen_analysis_terms):
        return True

    if any(marker in lowered for marker in _VISUAL_EXPLAIN_MARKERS):
        return True

    if lowered.startswith("what is this") or lowered.startswith("what's this"):
        return True
    if lowered.startswith("what is that") or lowered.startswith("what's that"):
        return True
    if "on my screen" in lowered and lowered.endswith("?"):
        return True
    return False


def _choose_actionable_agent(task_text: str, latest_screen_context: Optional[dict[str, Any]]) -> str:
    recommended = ""
    if latest_screen_context:
        recommended = str(latest_screen_context.get("recommended_agent") or "").strip().lower()
    if recommended in {"cua_cli", "cua_vision", "browser"}:
        return recommended

    lowered = (task_text or "").lower()
    if _is_window_management_request(lowered):
        return "cua_vision"
    if _matches_any_marker(lowered, _BROWSER_EXECUTION_MARKERS):
        return "browser"
    if _matches_any_marker(lowered, _CLI_EXECUTION_MARKERS):
        return "cua_cli"
    if _matches_any_marker(lowered, _VISION_EXECUTION_MARKERS):
        return "cua_vision"
    return "cua_cli"


def _looks_like_router_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    patterns = (
        "i cannot",
        "i can't",
        "i am unable",
        "i'm unable",
        "as a text-based",
        "as an ai",
        "i don't have the ability",
        "i do not have the ability",
        "guide you on how",
        "manually",
    )
    return any(pattern in lowered for pattern in patterns)


def _extract_latest_request(prompt: str) -> str:
    markers = (
        "# User's Latest Request:\n",
        "# User's Request:\n",
    )
    for marker in markers:
        if marker in prompt:
            tail = prompt.rsplit(marker, 1)[-1].strip()
            if tail:
                return tail
    return _clean_text(prompt, "", max_len=1800)


def _normalize_router_decision_payload(
    payload: dict[str, Any],
    prompt: str,
    *,
    provider_name: str,
) -> dict[str, Any]:
    latest_request = _extract_latest_request(prompt)
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in _ROUTER_AGENT_CHOICES:
        raise RuntimeError(f"{provider_name} router returned invalid agent '{agent}'.")

    if agent == "direct":
        return RouteDecision(
            agent="direct",
            response_text=_clean_text(
                payload.get("response_text") or payload.get("text"),
                "Routing complete.",
                max_len=420,
            ),
        ).as_dict()

    if agent == "jarvis":
        return RouteDecision(
            agent="jarvis",
            query=_clean_text(
                payload.get("query") or payload.get("task"),
                latest_request,
                max_len=420,
            ),
        ).as_dict()

    if agent in {"browser", "cua_cli", "cua_vision"}:
        task_text = _clean_text(
            payload.get("task") or payload.get("query"),
            latest_request,
            max_len=420,
        )
        if _looks_like_router_refusal(task_text):
            task_text = latest_request
        return RouteDecision(
            agent=agent,
            task=task_text,
        ).as_dict()

    return RouteDecision(
        agent="screen_context",
        task=_clean_text(
            payload.get("task") or payload.get("query"),
            latest_request,
            max_len=420,
        ),
        focus=_clean_text(payload.get("focus"), "", max_len=220),
    ).as_dict()


def _router_provider_order(
    *,
    router_provider: str,
    openrouter_enabled: bool,
    ollama_enabled: bool,
) -> list[str]:
    providers: list[str] = []

    def add(provider: str, enabled: bool) -> None:
        if enabled and provider not in providers:
            providers.append(provider)

    prefer_openrouter = router_provider == "openrouter"
    if prefer_openrouter:
        add("openrouter", openrouter_enabled)
        add("ollama", ollama_enabled)
    else:
        add("ollama", ollama_enabled)
        add("openrouter", openrouter_enabled)
    return providers


def _apply_routing_guardrails(
    user_prompt: str,
    routing_result: dict[str, Any],
    latest_screen_context: Optional[dict[str, Any]],
) -> dict[str, Any]:
    agent = str(routing_result.get("agent") or "").strip().lower()
    execution_request = _is_execution_request(user_prompt)

    try:
        from agents.browser.agent import BrowserAgent

        resume_task = BrowserAgent.resolve_resume_task(user_prompt)
    except Exception:
        resume_task = None

    if resume_task:
        return {
            "agent": "browser",
            "task": resume_task,
        }

    if (
        execution_request
        and agent == "screen_context"
        and latest_screen_context
    ):
        recommended_agent = str(latest_screen_context.get("recommended_agent") or "").strip().lower()
        if recommended_agent in {"cua_cli", "cua_vision", "browser"}:
            task_text = _clean_text(
                latest_screen_context.get("recommended_task"),
                "",
                max_len=420,
            ) or _clean_text(user_prompt, "", max_len=420)
            print(
                f"[Router][Guardrail] Promoting repeated screen_context to actionable agent: {recommended_agent}"
            )
            return {
                "agent": recommended_agent,
                "task": task_text,
            }

    if execution_request and agent == "jarvis":
        task_text = _routing_task_text(routing_result)
        if not task_text:
            task_text = _clean_text(user_prompt, "", max_len=420)
        actionable_agent = _choose_actionable_agent(task_text, latest_screen_context)
        print(
            f"[Router][Guardrail] Re-routing execution request away from jarvis -> {actionable_agent}"
        )
        return {
            "agent": actionable_agent,
            "task": task_text,
        }

    if execution_request and agent == "browser":
        task_text = _routing_task_text(routing_result) or _clean_text(user_prompt, "", max_len=420)
        if _requires_desktop_control_surface(task_text):
            print("[Router][CapabilityGate] Browser route needs desktop/profile/window control -> cua_vision")
            return {
                "agent": "cua_vision",
                "task": task_text,
            }

    return routing_result


def _summarize_completed_steps(chain_steps: list[dict[str, Any]]) -> str:
    successful = [step for step in chain_steps if step.get("success")]
    if not successful:
        return "Task completed."

    messages = []
    for step in successful:
        msg = _clean_text(step.get("message"), "", max_len=220)
        if msg:
            messages.append(msg)
    if not messages:
        return "Task completed."

    if len(messages) == 1:
        return f"Task completed: {messages[0]}"
    return f"Task completed: {messages[-2]} Then: {messages[-1]}"


def _finalize_direct_response_text(
    user_prompt: str,
    chain_steps: list[dict[str, Any]],
    text: str,
) -> str:
    cleaned = _clean_text(text, "Task completed.", max_len=420)
    if not chain_steps:
        return cleaned
    if _user_requested_repeat(user_prompt):
        return cleaned
    if _looks_like_repeat_artifact(cleaned):
        return _summarize_completed_steps(chain_steps)
    return cleaned
