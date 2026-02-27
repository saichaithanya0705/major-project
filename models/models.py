"""
CLOVIS Model Integration - Gemini API and routing logic.

This module handles:
- Screenshot capture and storage
- Two-tier model routing (rapid response → specialized agents)
- Gemini API configuration
"""
import asyncio
import json
import os
import time
from collections import deque
from typing import Any, Optional

from PIL import Image, ImageGrab
from dotenv import load_dotenv
import requests

from models.function_calls import (
    ROUTER_TOOLS, ROUTER_TOOL_MAP,
    TOOL_CONFIG,
)
from models.prompts import RAPID_RESPONSE_SYSTEM_PROMPT

# Import CLOVIS agent components
from agents.clovis.tools import CLOVIS_TOOLS, CLOVIS_TOOL_MAP, set_model_name
from agents.clovis.prompts import CLOVIS_SYSTEM_PROMPT

# Import Vision Agent
from agents.cua_vision.agent import VisionAgent

# Import CLI Agent
from agents.cua_cli.agent import CLIAgent
from ui.visualization_api.status_bubble import (
    show_status_bubble,
    update_status_bubble,
    complete_status_bubble,
)

# Attempt to import Gemini libraries
try:
    from google import genai
    from google.genai import types
except ImportError:
    print('Google Gemini dependencies have not been installed')

load_dotenv()


# ================================================================================
# SCREENSHOT STORAGE (captured before overlay appears)
# ================================================================================

_stored_screenshot = None
_RAPID_CONVERSATION_HISTORY = deque(maxlen=32)
_MAX_ROUTER_CHAIN_STEPS = 6
_REPEATED_STEP_LIMIT = 3
_VISUAL_EXPLAIN_MARKERS = (
    "what do you see",
    "what do u see",
    "what's on my screen",
    "what is on my screen",
    "what am i looking at",
    "describe my screen",
    "describe what you see",
    "explain what you see",
    "tell me what you see",
    "can you see my screen",
)
_EXECUTION_INTENT_MARKERS = (
    "click ",
    "open ",
    "run ",
    "type ",
    "install ",
    "clone ",
    "start ",
    "stop ",
    "search ",
    "go to ",
    "create ",
    "delete ",
    "move ",
    "copy ",
    "paste ",
    "scroll ",
    "press ",
)


def store_screenshot():
    """Capture and store a screenshot (called before overlay appears)."""
    global _stored_screenshot
    _stored_screenshot = ImageGrab.grab()
    print("Screenshot captured (before overlay)")
    return _stored_screenshot


def get_stored_screenshot():
    """Get the stored screenshot and clear it, or capture a new one if none stored."""
    global _stored_screenshot
    screenshot = _stored_screenshot if _stored_screenshot else ImageGrab.grab()
    _stored_screenshot = None
    return screenshot


def _append_rapid_history(role: str, text: str, source: str) -> None:
    cleaned = _clean_text(text, "", max_len=600)
    if not cleaned:
        return
    _RAPID_CONVERSATION_HISTORY.append({
        "role": role,
        "source": source,
        "text": cleaned,
    })


def _format_rapid_history_for_prompt() -> str:
    if not _RAPID_CONVERSATION_HISTORY:
        return ""

    lines = []
    for entry in list(_RAPID_CONVERSATION_HISTORY)[-20:]:
        role = entry.get("role")
        source = entry.get("source")
        text = entry.get("text", "")

        if role == "user":
            label = "User"
        elif source in {"browser_use", "cua_cli", "cua_vision", "clovis", "screen_judge"}:
            label = "Agent"
        else:
            label = "Rapid Assistant"

        lines.append(f"{label}: {text}")

    if not lines:
        return ""

    return (
        "\n# Conversation History (Rapid-Model Messages Only)\n"
        "Use this history for context. Agent entries are short summaries only.\n"
        + "\n".join(lines)
        + "\n"
    )


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


def _format_chain_state_for_prompt(
    user_prompt: str,
    chain_steps: list[dict[str, Any]],
    max_steps: int,
    latest_screen_context: Optional[dict[str, Any]],
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

    if not chain_steps:
        return (
            "\n# Multi-Agent Chaining Mode\n"
            "This task may require multiple delegated tools.\n"
            "Pick the best first tool call, and treat this as step 1 of a multi-step execution.\n"
            "If the request depends on currently visible UI context, call `request_screen_context` first.\n"
            "For action/execution requests ('do X for me', clone/run/open/click/type), do NOT use `invoke_clovis`.\n"
            "Use `invoke_clovis` only for explanation/annotation requests.\n"
            "When the overall user request is fully complete, call `direct_response`.\n"
            + context_lines +
            f"Never exceed {max_steps} delegated steps.\n"
        )

    lines = []
    for idx, step in enumerate(chain_steps, start=1):
        lines.append(
            f"{idx}. agent={step.get('agent')} success={step.get('success')} "
            f"task={step.get('task')} outcome={step.get('message')}"
        )

    return (
        "\n# Multi-Agent Chaining Mode\n"
        "Continue from prior delegated work. Choose the single best next tool call.\n"
        "If the original request is complete, call `direct_response` now.\n"
        "Avoid repeating the exact same delegated step unless something materially changed.\n"
        "If you still need visible context, call `request_screen_context` again.\n"
        "For action/execution requests, do NOT use `invoke_clovis`.\n"
        f"Original request: {user_prompt}\n"
        f"Completed delegated steps ({len(chain_steps)}/{max_steps}):\n"
        + "\n".join(lines)
        + context_lines
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
    if recommended_agent not in {"cua_cli", "cua_vision", "browser", "clovis", "direct"}:
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


def _is_visual_explanation_request(user_prompt: str) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    if any(marker in lowered for marker in _EXECUTION_INTENT_MARKERS):
        return False

    if any(marker in lowered for marker in _VISUAL_EXPLAIN_MARKERS):
        return True

    # Treat simple "what is this/that/here" questions as visual explanation.
    if lowered.startswith("what is this") or lowered.startswith("what's this"):
        return True
    if lowered.startswith("what is that") or lowered.startswith("what's that"):
        return True
    if "on my screen" in lowered and lowered.endswith("?"):
        return True
    return False


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


# ================================================================================
# STATUS + CONFIRMATION HELPERS
# ================================================================================

def _clean_text(value: Any, fallback: str, max_len: int = 1400) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def _extract_browser_message(history: Any) -> Optional[str]:
    if history is None:
        return None

    if isinstance(history, str):
        cleaned = _clean_text(history, "")
        return cleaned if cleaned else None

    if isinstance(history, dict):
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


def _cli_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "CLI task failed.")
    output = _clean_text(result.get("result"), "")
    return output if output else "CLI task completed."


def _browser_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "Browser task failed.")

    summary = _extract_browser_message(result.get("result"))
    if summary:
        return summary
    return "Browser task completed."


def _vision_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "Computer task failed.")
    return _clean_text(result.get("result"), "Computer task completed.")


async def _safe_ui_call(coro, label: str):
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
            delay_ms=2000,
            source=source,
        ),
        "complete_status_bubble",
    )


async def _run_routed_agent_step(
    model: "GeminiModel",
    routing_result: dict[str, Any],
    clovis_model: str,
) -> dict[str, Any]:
    agent_name = routing_result.get("agent")

    if agent_name == "clovis":
        await _start_non_rapid_status("Analyzing current screen...", source="clovis")
        started = time.monotonic()
        screenshot = get_stored_screenshot()
        clovis_prompt = CLOVIS_SYSTEM_PROMPT + f"\n# User's Request:\n{routing_result.get('query', '')}"
        try:
            clovis_result = await model.generate_clovis_response(clovis_prompt, screenshot)
            clovis_summary = _clean_text(
                clovis_result.get("summary"),
                "CLOVIS completed the visual guidance task.",
                max_len=420,
            )
            elapsed = time.monotonic() - started
            print(f"[CLOVIS] Completed in {elapsed:.2f}s")
            await _finish_non_rapid_status(
                clovis_summary,
                True,
                source="clovis",
            )
            return {
                "agent": "clovis",
                "task": _routing_task_text(routing_result),
                "success": True,
                "message": clovis_summary,
                "source": "clovis",
            }
        except Exception as exc:
            error_message = _clean_text(str(exc), "CLOVIS task failed.", max_len=420)
            await _finish_non_rapid_status(
                error_message,
                False,
                source="clovis",
            )
            return {
                "agent": "clovis",
                "task": _routing_task_text(routing_result),
                "success": False,
                "message": error_message,
                "source": "clovis",
            }

    if agent_name == "browser":
        await _start_non_rapid_status("Running browser task...", source="browser_use")
        from agents.browser.agent import BrowserAgent

        task = routing_result.get("task", "")
        print(f"[Router] Browser Agent starting. Task: {task}")
        browser_agent = BrowserAgent(model_name=clovis_model)
        try:
            result = await browser_agent.execute(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {"success": False, "result": None, "error": str(exc)}

        message = _browser_completion_message(result)
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="browser_use",
        )
        return {
            "agent": "browser",
            "task": task,
            "success": bool(result.get("success", False)),
            "message": message,
            "source": "browser_use",
        }

    if agent_name == "cua_cli":
        await _start_non_rapid_status("Running CLI task...", source="cua_cli")
        task = routing_result.get("task", "")
        print(f"[Router] CLI Agent executing: {task}")
        cli_agent = CLIAgent()
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

        try:
            result = await cli_agent.execute(
                task,
                status_callback=_on_cli_status,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {"success": False, "result": None, "error": str(exc)}
        if result.get("success"):
            print(f"[CLI Agent] Success: {result.get('result')}")
        else:
            print(f"[CLI Agent] Error: {result.get('error')}")
        message = _cli_completion_message(result)
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="cua_cli",
        )
        return {
            "agent": "cua_cli",
            "task": task,
            "success": bool(result.get("success", False)),
            "message": message,
            "source": "cua_cli",
        }

    if agent_name == "cua_vision":
        await _start_non_rapid_status("Running computer-use task...", source="cua_vision")
        screenshot = get_stored_screenshot()
        vision_agent = VisionAgent(model_name=clovis_model)
        task = routing_result.get("task", "")
        try:
            result = await vision_agent.execute(task, screenshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = {"success": False, "result": None, "error": str(exc)}
        message = _vision_completion_message(result)
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="cua_vision",
        )
        return {
            "agent": "cua_vision",
            "task": task,
            "success": bool(result.get("success", False)),
            "message": message,
            "source": "cua_vision",
        }

    return {
        "agent": str(agent_name or "unknown"),
        "task": _routing_task_text(routing_result),
        "success": False,
        "message": "Router returned an unknown agent.",
        "source": "rapid",
    }


# ================================================================================
# MAIN ENTRY POINT
# ================================================================================

async def call_gemini(user_prompt: str, rapid_response_model: str, clovis_model: str):
    """
    Main entry point - uses two-tier model system:
    1. Rapid response model (router) decides how to handle the request
    2. Routes to appropriate agent: CLOVIS, Browser, or Desktop
    """
    model = GeminiModel(
        clovis_model=clovis_model,
        rapid_response_model=rapid_response_model
    )

    _append_rapid_history("user", user_prompt, "user")

    # Fast path: pure visual understanding queries should avoid extra router +
    # screen-context hops to reduce latency.
    if _is_visual_explanation_request(user_prompt):
        print("[Router][FastPath] Directly invoking CLOVIS for visual explanation.")
        step_result = await _run_routed_agent_step(
            model=model,
            routing_result={"agent": "clovis", "query": user_prompt},
            clovis_model=clovis_model,
        )
        _append_rapid_history(
            "assistant",
            step_result.get("message", ""),
            step_result.get("source", "clovis"),
        )
        if not step_result.get("success"):
            tool = ROUTER_TOOL_MAP.get("direct_response")
            if tool:
                tool(
                    text=_clean_text(
                        f"CLOVIS failed: {step_result.get('message')}",
                        "CLOVIS task failed.",
                        max_len=420,
                    ),
                    source="rapid_response",
                )
        return

    chain_steps: list[dict[str, Any]] = []
    seen_step_signatures: dict[tuple[str, str], int] = {}
    latest_screen_context: Optional[dict[str, Any]] = None

    for step_index in range(_MAX_ROUTER_CHAIN_STEPS):
        history_block = _format_rapid_history_for_prompt()
        chain_block = _format_chain_state_for_prompt(
            user_prompt=user_prompt,
            chain_steps=chain_steps,
            max_steps=_MAX_ROUTER_CHAIN_STEPS,
            latest_screen_context=latest_screen_context,
        )
        rapid_prompt = (
            RAPID_RESPONSE_SYSTEM_PROMPT
            + history_block
            + chain_block
            + f"\n# User's Latest Request:\n{user_prompt}"
        )
        routing_result = await model.route_request(rapid_prompt)
        if not isinstance(routing_result, dict):
            routing_result = {
                "agent": "direct",
                "response_text": "Router returned an invalid response shape.",
            }

        if routing_result.get("agent") == "direct":
            direct_args = routing_result.get("direct_response_args")
            if not isinstance(direct_args, dict):
                direct_args = {}
            raw_direct_text = direct_args.get("text") or routing_result.get("response_text")
            direct_text = _finalize_direct_response_text(
                user_prompt=user_prompt,
                chain_steps=chain_steps,
                text=_clean_text(raw_direct_text, "Rapid response provided.", max_len=420),
            )
            tool = ROUTER_TOOL_MAP.get("direct_response")
            if tool:
                safe_args = dict(direct_args)
                safe_args.pop("text", None)
                tool(text=direct_text, source="rapid_response", **safe_args)
            _append_rapid_history("assistant", direct_text, "rapid")
            return

        signature = _routing_signature(routing_result)
        seen_step_signatures[signature] = seen_step_signatures.get(signature, 0) + 1
        if seen_step_signatures[signature] >= _REPEATED_STEP_LIMIT:
            repeated_msg = (
                "I stopped automatic multi-agent chaining because the next delegated step "
                "kept repeating. Please rephrase or ask for one specific next action."
            )
            tool = ROUTER_TOOL_MAP.get("direct_response")
            if tool:
                tool(text=repeated_msg, source="rapid_response")
            _append_rapid_history("assistant", repeated_msg, "rapid")
            return

        if routing_result.get("agent") == "screen_context":
            judge_task = routing_result.get("task") or user_prompt
            focus = routing_result.get("focus") or ""
            print(
                f"[Router][Chain] Step {step_index + 1}/{_MAX_ROUTER_CHAIN_STEPS}: "
                f"agent=screen_context task={_clean_text(judge_task, '', max_len=200)}"
            )
            screenshot = get_stored_screenshot()
            try:
                latest_screen_context = await model.generate_screen_context(
                    user_request=judge_task,
                    image=screenshot,
                    focus=focus,
                )
                message = _screen_context_message(latest_screen_context)
                step_result = {
                    "agent": "screen_context",
                    "task": _clean_text(judge_task, "", max_len=220),
                    "success": True,
                    "message": message,
                    "source": "screen_judge",
                }
            except Exception as exc:
                step_result = {
                    "agent": "screen_context",
                    "task": _clean_text(judge_task, "", max_len=220),
                    "success": False,
                    "message": _clean_text(str(exc), "Failed to collect screen context.", max_len=420),
                    "source": "screen_judge",
                }

            chain_steps.append(step_result)
            _append_rapid_history(
                "assistant",
                step_result.get("message", ""),
                step_result.get("source", "rapid"),
            )
            if not step_result.get("success"):
                failure_msg = (
                    f"Stopping chained execution because screen context failed: "
                    f"{step_result.get('message')}"
                )
                tool = ROUTER_TOOL_MAP.get("direct_response")
                if tool:
                    tool(text=_clean_text(failure_msg, "Task failed.", max_len=420), source="rapid_response")
                _append_rapid_history("assistant", failure_msg, "rapid")
                return
            continue

        print(
            f"[Router][Chain] Step {step_index + 1}/{_MAX_ROUTER_CHAIN_STEPS}: "
            f"agent={routing_result.get('agent')} task={_routing_task_text(routing_result)}"
        )
        step_result = await _run_routed_agent_step(
            model=model,
            routing_result=routing_result,
            clovis_model=clovis_model,
        )
        chain_steps.append(step_result)
        _append_rapid_history(
            "assistant",
            step_result.get("message", ""),
            step_result.get("source", "rapid"),
        )
        if not step_result.get("success"):
            failure_msg = (
                f"Stopping chained execution because {step_result.get('agent')} failed: "
                f"{step_result.get('message')}"
            )
            tool = ROUTER_TOOL_MAP.get("direct_response")
            if tool:
                tool(text=_clean_text(failure_msg, "Task failed.", max_len=420), source="rapid_response")
            _append_rapid_history("assistant", failure_msg, "rapid")
            return

    max_step_msg = (
        f"I stopped after {_MAX_ROUTER_CHAIN_STEPS} delegated steps to avoid loops. "
        "If you want me to continue, ask for the next specific step."
    )
    tool = ROUTER_TOOL_MAP.get("direct_response")
    if tool:
        tool(text=max_step_msg, source="rapid_response")
    _append_rapid_history("assistant", max_step_msg, "rapid")


# ================================================================================
# GEMINI MODEL CLASS
# ================================================================================

class GeminiModel:
    """
    Gemini model wrapper with routing and CLOVIS capabilities.

    Two-tier system:
    - Router model: Fast, no image, decides where to route requests
    - CLOVIS model: Full capabilities, with screenshot, for screen annotations

    Documentation Reference: https://github.com/googleapis/python-genai
    """

    def __init__(self, clovis_model='gemini-3-flash-preview', rapid_response_model='gemini-flash-lite-latest'):
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.clovis_model = clovis_model
        self.rapid_response_model = rapid_response_model
        self.screen_judge_model = "gemini-3-flash-preview"
        try:
            thinking_budget = int(os.getenv("CLOVIS_THINKING_BUDGET", "256"))
        except ValueError:
            thinking_budget = 256
        self.clovis_thinking_budget = max(0, min(2048, thinking_budget))
        self.openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        self.openrouter_model = (
            os.getenv("OPENROUTER_MODEL") or "nvidia/nemotron-3-nano-30b-a3b:free"
        ).strip()
        self.openrouter_url = (
            os.getenv("OPENROUTER_URL") or "https://openrouter.ai/api/v1/chat/completions"
        ).strip()
        self.openrouter_site_url = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
        self.openrouter_site_name = (os.getenv("OPENROUTER_SITE_NAME") or "CLOVIS").strip()
        try:
            timeout_seconds = int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45"))
        except ValueError:
            timeout_seconds = 45
        self.openrouter_timeout_seconds = max(10, min(180, timeout_seconds))

        # Config for router model (lightweight, no thinking)
        self.router_config = types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1000,
            tools=ROUTER_TOOLS,
            tool_config=TOOL_CONFIG,
        )

        # Config for CLOVIS model (full capabilities)
        self.clovis_config = types.GenerateContentConfig(
            temperature=1.2,
            top_p=0.95,
            top_k=64,
            max_output_tokens=3000,
            thinking_config=types.ThinkingConfig(thinking_budget=self.clovis_thinking_budget),
            tools=CLOVIS_TOOLS,
            tool_config=TOOL_CONFIG,
        )

        # Config for one-shot screen context extraction (no tools, strict JSON response).
        self.screen_judge_config = types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.9,
            top_k=40,
            max_output_tokens=1200,
            response_mime_type="application/json",
        )

    @staticmethod
    def _is_gemini_quota_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "429",
            "resource_exhausted",
            "quota",
            "rate limit",
            "rate_limit",
            "too many requests",
        )
        return any(marker in text for marker in markers)

    @staticmethod
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

    def _openrouter_enabled(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model and self.openrouter_url)

    def _call_openrouter_text_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if not self._openrouter_enabled():
            raise RuntimeError("OpenRouter fallback is not configured.")

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.openrouter_site_url:
            headers["HTTP-Referer"] = self.openrouter_site_url
        if self.openrouter_site_name:
            headers["X-Title"] = self.openrouter_site_name

        payload = {
            "model": self.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = requests.post(
            self.openrouter_url,
            headers=headers,
            json=payload,
            timeout=self.openrouter_timeout_seconds,
        )
        if response.status_code >= 400:
            body = _clean_text(response.text, "", max_len=320)
            raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {body}")

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("OpenRouter returned a non-object response.")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenRouter returned no choices.")

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first.get("message"), dict) else {}
        content = message.get("content")

        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                piece = item.get("text")
                if isinstance(piece, str) and piece.strip():
                    parts.append(piece.strip())
            text = "\n".join(parts).strip()
        else:
            text = ""

        if not text:
            raise RuntimeError("OpenRouter returned empty message content.")

        return text

    async def _try_openrouter_text_fallback(
        self,
        *,
        label: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> Optional[str]:
        if not self._openrouter_enabled():
            print(f"[{label}] Gemini quota hit but OPENROUTER_API_KEY is not configured.")
            return None

        try:
            await set_model_name(f"{self.openrouter_model} (OpenRouter)")
        except Exception as exc:
            print(f"[{label}] Failed to update model label for OpenRouter fallback: {exc}")

        try:
            text = await asyncio.to_thread(
                self._call_openrouter_text_sync,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
            )
            print(f"[{label}] OpenRouter fallback succeeded with model {self.openrouter_model}")
            return text
        except Exception as fallback_exc:
            print(f"[{label}] OpenRouter fallback failed: {fallback_exc}")
            return None

    async def route_request(self, prompt: str) -> dict:
        """
        Use the router model to decide how to handle the request.

        Returns:
            dict with keys:
                - agent: "direct" | "clovis" | "browser" | "cua_cli" | "cua_vision" | "screen_context"
                - query/task: The query or task to pass to the agent
                - response_text: direct response text when agent == "direct"
                - Additional agent-specific params
        """
        print("[Router] Processing...")
        started = time.monotonic()
        await set_model_name(self.rapid_response_model)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.rapid_response_model,
                contents=[prompt],
                config=self.router_config
            )
            elapsed = time.monotonic() - started
            print(f"[Router] Completed in {elapsed:.2f}s")
        except Exception as exc:
            if self._is_gemini_quota_error(exc):
                latest_request = self._extract_latest_request(prompt)
                fallback_text = await self._try_openrouter_text_fallback(
                    label="Router",
                    system_prompt=(
                        "You are CLOVIS text fallback. Gemini hit quota/rate limits.\n"
                        "Reply directly and concisely. If the request requires live screen"
                        " perception or desktop actions, clearly say that is unavailable in"
                        " fallback mode and ask the user to retry in a moment."
                    ),
                    user_prompt=latest_request,
                    temperature=0.2,
                    max_tokens=500,
                )
                if fallback_text:
                    return {
                        "agent": "direct",
                        "response_text": _clean_text(
                            fallback_text,
                            "Gemini is rate-limited. Please retry shortly.",
                            max_len=420,
                        ),
                    }
            return {
                "agent": "direct",
                "response_text": _clean_text(
                    f"Router generation failed: {exc}",
                    "Router generation failed.",
                    max_len=420,
                ),
            }

        candidates = getattr(response, "candidates", None)
        if not candidates:
            fallback_text = _clean_text(
                getattr(response, "text", None),
                "Router returned no candidates.",
                max_len=420,
            )
            return {"agent": "direct", "response_text": fallback_text}

        first_candidate = candidates[0] if len(candidates) > 0 else None
        if first_candidate is None:
            return {"agent": "direct", "response_text": "Router returned an empty candidate."}

        content = getattr(first_candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            fallback_text = _clean_text(
                getattr(response, "text", None),
                "Router returned no callable parts.",
                max_len=420,
            )
            return {"agent": "direct", "response_text": fallback_text}

        function_calls = [part.function_call for part in parts if getattr(part, "function_call", None)]

        for function_call in function_calls:
            print(f"\n[Router] Function: {function_call.name}")
            print(f"[Router] Arguments: {function_call.args}")
            args = function_call.args if isinstance(function_call.args, dict) else {}

            if function_call.name == "invoke_clovis":
                return {
                    "agent": "clovis",
                    "query": args.get("query", "")
                }

            elif function_call.name == "invoke_browser":
                return {
                    "agent": "browser",
                    "task": args.get("task", "")
                }

            elif function_call.name == "invoke_cua_cli":
                return {
                    "agent": "cua_cli",
                    "task": args.get("task", "")
                }

            elif function_call.name == "invoke_cua_vision":
                return {
                    "agent": "cua_vision",
                    "task": args.get("task", "")
                }

            elif function_call.name == "request_screen_context":
                return {
                    "agent": "screen_context",
                    "task": args.get("task", ""),
                    "focus": args.get("focus", ""),
                }

            elif function_call.name == "direct_response":
                return {
                    "agent": "direct",
                    "response_text": args.get("text", ""),
                    "direct_response_args": args,
                }

        # No function call - shouldn't happen with mode="ANY"
        print("[Router] No function call in response")
        return {"agent": "direct"}

    async def generate_screen_context(
        self,
        user_request: str,
        image: Image = None,
        focus: str = "",
    ) -> dict[str, Any]:
        """
        Run one multimodal pass to extract concrete screen context for routing.
        """
        print("[ScreenJudge] Capturing context from screenshot...")
        started = time.monotonic()
        focus_text = _clean_text(focus, "", max_len=200)
        judge_prompt = (
            "You are Screen Judge for a computer-use orchestrator.\n"
            "Analyze the screenshot and extract only high-signal routing context.\n"
            "Return JSON ONLY, no markdown.\n\n"
            "Required JSON schema:\n"
            "{\n"
            '  "summary": "short factual summary",\n'
            '  "repo_url": "github/git url if visible else empty string",\n'
            '  "local_url": "localhost/127.0.0.1 URL if visible else empty string",\n'
            '  "recommended_agent": "cua_cli|cua_vision|browser|clovis|direct",\n'
            '  "recommended_task": "single concrete next step task",\n'
            '  "hints": "short extra details useful for routing"\n'
            "}\n\n"
            f"User request: {user_request}\n"
            f"Extraction focus: {focus_text if focus_text else 'general execution context'}\n"
            "Do not invent URLs. If uncertain, leave fields empty."
        )

        contents = [judge_prompt]
        if image is not None:
            contents.append(image)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.screen_judge_model,
                contents=contents,
                config=self.screen_judge_config,
            )
        except Exception as exc:
            if self._is_gemini_quota_error(exc):
                fallback_text = await self._try_openrouter_text_fallback(
                    label="ScreenJudge",
                    system_prompt=(
                        "You are Screen Judge fallback without image access.\n"
                        "Return JSON only with fields: summary, repo_url, local_url,"
                        " recommended_agent, recommended_task, hints.\n"
                        "If you are uncertain, keep fields empty and explain uncertainty in"
                        " summary."
                    ),
                    user_prompt=(
                        f"User request: {user_request}\n"
                        f"Focus: {focus_text if focus_text else 'general execution context'}\n"
                        "No screenshot is available in fallback mode."
                    ),
                    temperature=0.1,
                    max_tokens=420,
                )
                if fallback_text:
                    parsed = _parse_json_object_from_text(fallback_text)
                    normalized = _normalize_screen_context_payload(parsed, user_request=user_request)
                    if not normalized.get("summary"):
                        normalized["summary"] = _clean_text(
                            fallback_text,
                            "Gemini screen context hit quota. Used text-only fallback.",
                            max_len=420,
                        )
                    normalized["model"] = f"{self.openrouter_model} (openrouter_fallback)"
                    return normalized
            raise
        elapsed = time.monotonic() - started
        print(f"[ScreenJudge] Completed in {elapsed:.2f}s")

        raw_text = ""
        if hasattr(response, "text") and response.text:
            raw_text = str(response.text)
        else:
            try:
                raw_text = json.dumps(response.to_dict())
            except Exception:
                raw_text = ""

        parsed = _parse_json_object_from_text(raw_text)
        normalized = _normalize_screen_context_payload(parsed, user_request=user_request)
        if not normalized.get("summary"):
            normalized["summary"] = _clean_text(raw_text, "Screen context captured.", max_len=420)
        normalized["model"] = self.screen_judge_model
        return normalized

    async def generate_clovis_response(self, prompt: str, image: Image = None) -> dict[str, Any]:
        """
        Call the CLOVIS model with full screen annotation capabilities.
        """
        print("[CLOVIS] Processing with screenshot...")
        started = time.monotonic()
        await set_model_name(self.clovis_model)

        contents = [prompt]
        if image:
            contents.append(image)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.clovis_model,
                contents=contents,
                config=self.clovis_config
            )
        except Exception as exc:
            if self._is_gemini_quota_error(exc):
                fallback_text = await self._try_openrouter_text_fallback(
                    label="CLOVIS",
                    system_prompt=(
                        "You are CLOVIS fallback without screenshot access.\n"
                        "Give a concise response to the user request. If the request depends on"
                        " seeing the current screen, be explicit that visual analysis is"
                        " unavailable in fallback mode and ask them to retry shortly."
                    ),
                    user_prompt=self._extract_latest_request(prompt),
                    temperature=0.2,
                    max_tokens=700,
                )
                if fallback_text:
                    return {
                        "response": None,
                        "summary": _clean_text(
                            f"Gemini quota reached. {fallback_text}",
                            "Gemini quota reached. Please retry shortly.",
                            max_len=420,
                        ),
                    }
            raise
        elapsed = time.monotonic() - started
        print(
            f"[CLOVIS] Model call completed in {elapsed:.2f}s "
            f"(thinking_budget={self.clovis_thinking_budget})"
        )

        parts = response.candidates[0].content.parts
        function_calls = [part.function_call for part in parts if part.function_call]
        summary_text = None

        if function_calls:
            for function_call in function_calls:
                print(f"\n[CLOVIS] Function: {function_call.name}")
                print(f"[CLOVIS] Arguments: {function_call.args}")

                if function_call.name == "direct_response":
                    summary_text = function_call.args.get("text") or summary_text

                tool = CLOVIS_TOOL_MAP.get(function_call.name)
                if tool:
                    tool(**function_call.args)
                else:
                    raise Exception(f"[CLOVIS] Invalid tool: {function_call.name}")
        else:
            print("[CLOVIS] No function call in response")
            if response.text:
                print(response.text)
                summary_text = response.text

        return {
            "response": response,
            "summary": _clean_text(summary_text, "", max_len=420),
        }
