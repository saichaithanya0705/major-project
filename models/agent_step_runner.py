"""
Agent step execution for routed tasks.

Extracted from models.models to keep routing orchestration focused on chaining
and provider calls, while this module owns delegated agent execution details.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Callable

from agents.cua_cli.agent import CLIAgent
from agents.jarvis.artifact import build_jarvis_visual_artifact
from agents.jarvis.prompts import JARVIS_SYSTEM_PROMPT
from agents.web_qa.agent import WebQAAgent
from core.assistant_logging import log_assistant_event
from models.contracts import RoutedStepResult
from models.output_file_artifacts import extract_output_file_path_from_tool_calls
from models.routing_policy import _clean_text, _format_direct_response_text, _routing_task_text
from ui.visualization_api.chat_artifact import send_chat_vision_artifact
from ui.visualization_api.chat_visibility import send_vision_chat_restore
from ui.visualization_api.status_bubble import (
    complete_status_bubble,
    show_status_bubble,
    update_status_bubble,
)


def _extract_browser_message(history: Any) -> str | None:
    if history is None:
        return None

    def _page_context_text(container: dict[str, Any]) -> str | None:
        page_context = container.get("page_context")
        if isinstance(page_context, dict):
            for key in ("summary", "content"):
                value = page_context.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    return text if len(text) <= 1400 else f"{text[:1397]}..."

        result = container.get("result")
        if isinstance(result, dict) and result is not container:
            return _page_context_text(result)
        return None

    if isinstance(history, str):
        cleaned = _clean_text(history, "")
        return cleaned if cleaned else None

    if isinstance(history, dict):
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


def _cli_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "CLI task failed.")
    output = _clean_text(result.get("result"), "")
    if output:
        return output
    output_file_path = extract_output_file_path_from_tool_calls(result.get("tool_calls"))
    if output_file_path:
        return f"Created file: `{output_file_path}`."
    return "CLI task completed."


def _browser_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "Browser task failed.")

    summary = _extract_browser_message(result.get("result"))
    if summary:
        return summary
    return "Browser task completed."


def _web_qa_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "Web QA task failed.")
    return _format_direct_response_text(result.get("result"), "Web QA task completed.")


def _vision_completion_message(result: dict[str, Any]) -> str:
    if not result.get("success"):
        return _clean_text(result.get("error"), "Computer task failed.")
    if result.get("complete") is not True:
        critic = result.get("critic")
        if isinstance(critic, dict):
            reason = _clean_text(critic.get("reason"), "", max_len=420)
            if reason:
                return reason
        return _clean_text(result.get("result"), "Computer task needs more work.")
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
            delay_ms=700,
            source=source,
        ),
        "complete_status_bubble",
    )


async def run_routed_agent_step(
    model: Any,
    routing_result: dict[str, Any],
    jarvis_model: str,
    request_id: str,
    get_stored_screenshot: Callable[[], Any],
    prepare_vision_screenshot: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    def _step(
        *,
        agent: str,
        task: str,
        success: bool,
        message: str,
        source: str,
        complete: bool | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = RoutedStepResult(
            agent=agent,
            task=task,
            success=success,
            message=message,
            source=source,
        ).as_dict()
        if complete is not None:
            payload["complete"] = complete
        if tool_calls is not None:
            payload["tool_calls"] = tool_calls
        return payload

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
        try:
            jarvis_result = await model.generate_jarvis_response(jarvis_prompt, screenshot)
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
        except Exception as exc:
            await _safe_ui_call(
                send_vision_chat_restore(),
                "send_vision_chat_restore",
            )
            error_message = _clean_text(str(exc), "JARVIS task failed.", max_len=420)
            log_assistant_event(
                "agent_step_failed",
                request_id=request_id,
                agent="jarvis",
                task=task_text,
                message=error_message,
                error=str(exc),
                success=False,
                duration_seconds=time.monotonic() - started,
                metadata={"traceback": traceback.format_exc()},
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

        task = routing_result.get("task", "")
        print(f"[Router] Browser Agent starting. Task: {task}")
        browser_agent = BrowserAgent(model_name=jarvis_model)
        started = time.monotonic()
        browser_traceback = None
        try:
            result = await browser_agent.execute(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            browser_traceback = traceback.format_exc()
            result = {"success": False, "result": None, "error": str(exc)}

        message = _browser_completion_message(result)
        if result.get("success", False):
            log_assistant_event(
                "agent_step_completed",
                request_id=request_id,
                agent="browser",
                task=task_text,
                message=message,
                success=True,
                duration_seconds=time.monotonic() - started,
            )
        else:
            metadata = {"result": result.get("result")}
            if browser_traceback:
                metadata["traceback"] = browser_traceback
            log_assistant_event(
                "agent_step_failed",
                request_id=request_id,
                agent="browser",
                task=task_text,
                message=message,
                error=_clean_text(result.get("error"), "Browser task failed.", max_len=420),
                success=False,
                duration_seconds=time.monotonic() - started,
                metadata=metadata,
            )
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="browser_use",
        )
        return _step(
            agent="browser",
            task=task,
            success=bool(result.get("success", False)),
            message=message,
            source="browser_use",
            complete=bool(result.get("complete", True)),
        )

    if agent_name == "web_qa":
        await _start_non_rapid_status("Searching the web...", source="web_qa")
        task = routing_result.get("task", "")
        print(f"[Router] Web QA Agent answering: {task}")
        web_qa_agent = WebQAAgent(model=model)
        started = time.monotonic()
        web_qa_traceback = None
        try:
            result = await web_qa_agent.execute(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            web_qa_traceback = traceback.format_exc()
            result = {"success": False, "result": None, "error": str(exc), "complete": True}

        message = _web_qa_completion_message(result)
        if result.get("success", False):
            log_assistant_event(
                "agent_step_completed",
                request_id=request_id,
                agent="web_qa",
                task=task_text,
                message=message,
                success=True,
                duration_seconds=time.monotonic() - started,
            )
        else:
            metadata = {}
            if web_qa_traceback:
                metadata["traceback"] = web_qa_traceback
            log_assistant_event(
                "agent_step_failed",
                request_id=request_id,
                agent="web_qa",
                task=task_text,
                message=message,
                error=_clean_text(result.get("error"), "Web QA task failed.", max_len=420),
                success=False,
                duration_seconds=time.monotonic() - started,
                metadata=metadata or None,
            )
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="web_qa",
        )
        return _step(
            agent="web_qa",
            task=task,
            success=bool(result.get("success", False)),
            message=message,
            source="web_qa",
            complete=bool(result.get("complete", True)),
        )

    if agent_name == "cua_cli":
        await _start_non_rapid_status("Running CLI task...", source="cua_cli")
        task = routing_result.get("task", "")
        print(f"[Router] CLI Agent executing: {task}")
        cli_agent = CLIAgent()
        started = time.monotonic()
        cli_traceback = None
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
            cli_traceback = traceback.format_exc()
            result = {"success": False, "result": None, "error": str(exc)}
        if result.get("success"):
            print(f"[CLI Agent] Success: {result.get('result')}")
        else:
            print(f"[CLI Agent] Error: {result.get('error')}")
        message = _cli_completion_message(result)
        if result.get("success", False):
            log_assistant_event(
                "agent_step_completed",
                request_id=request_id,
                agent="cua_cli",
                task=task_text,
                message=message,
                success=True,
                duration_seconds=time.monotonic() - started,
                metadata={"tool_calls": result.get("tool_calls")},
            )
        else:
            metadata = {"tool_calls": result.get("tool_calls")}
            if cli_traceback:
                metadata["traceback"] = cli_traceback
            log_assistant_event(
                "agent_step_failed",
                request_id=request_id,
                agent="cua_cli",
                task=task_text,
                message=message,
                error=_clean_text(result.get("error"), "CLI task failed.", max_len=420),
                success=False,
                duration_seconds=time.monotonic() - started,
                metadata=metadata,
            )
        await _finish_non_rapid_status(
            message,
            result.get("success", False),
            source="cua_cli",
        )
        return _step(
            agent="cua_cli",
            task=task,
            success=bool(result.get("success", False)),
            message=message,
            source="cua_cli",
            tool_calls=result.get("tool_calls"),
        )

    if agent_name == "cua_vision":
        await _start_non_rapid_status("Running computer-use task...", source="cua_vision")
        if prepare_vision_screenshot is not None:
            screenshot = await prepare_vision_screenshot(keep_chat_hidden=False)
        else:
            screenshot = get_stored_screenshot()
        from agents.cua_vision.agent import VisionAgent
        vision_agent = VisionAgent(model_name=jarvis_model)
        task = routing_result.get("task", "")
        started = time.monotonic()
        vision_traceback = None
        try:
            result = await vision_agent.execute(task, screenshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            vision_traceback = traceback.format_exc()
            result = {"success": False, "result": None, "error": str(exc)}
        message = _vision_completion_message(result)
        complete = bool(result.get("complete", False))
        if result.get("success", False):
            log_assistant_event(
                "agent_step_completed",
                request_id=request_id,
                agent="cua_vision",
                task=task_text,
                message=message,
                success=True,
                duration_seconds=time.monotonic() - started,
                metadata={
                    "complete": complete,
                    "critic": result.get("critic"),
                },
            )
        else:
            metadata = {}
            if vision_traceback:
                metadata["traceback"] = vision_traceback
            log_assistant_event(
                "agent_step_failed",
                request_id=request_id,
                agent="cua_vision",
                task=task_text,
                message=message,
                error=_clean_text(result.get("error"), "Computer task failed.", max_len=420),
                success=False,
                duration_seconds=time.monotonic() - started,
                metadata=metadata or None,
            )
        await _finish_non_rapid_status(
            message,
            bool(result.get("success", False) and complete),
            source="cua_vision",
        )
        return _step(
            agent="cua_vision",
            task=task,
            success=bool(result.get("success", False)),
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
