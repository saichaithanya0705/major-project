"""Shared screen-context step execution runtime for rapid orchestrators."""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from models.rapid_orchestrator_contracts import RapidAgentStepResult
from models.routing_payload_parser import ScreenContextPayload


DEFAULT_SCREEN_CONTEXT_STEP_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ScreenContextStepExecutionResult:
    step_result: RapidAgentStepResult
    latest_screen_context: Optional[ScreenContextPayload]


@dataclass(frozen=True, slots=True)
class ScreenContextStepRequest:
    task: str
    focus: str = ""

    @classmethod
    def from_route(
        cls,
        routing_result: Mapping[str, object],
        *,
        user_prompt: str,
    ) -> ScreenContextStepRequest:
        return cls(
            task=str(routing_result.get("task") or user_prompt),
            focus=str(routing_result.get("focus") or ""),
        )


class ScreenContextRuntimeModel(Protocol):
    async def generate_screen_context(
        self,
        user_request: str,
        image: Any = None,
        focus: str = "",
    ) -> ScreenContextPayload: ...


class ScreenContextRuntimeDeps(Protocol):
    async def prepare_vision_screenshot(self, *, keep_chat_hidden: bool = False) -> Any: ...

    def clean_text(self, value: object, fallback: str, max_len: int | None) -> str: ...

    def screen_context_message(self, payload: ScreenContextPayload) -> str: ...

    def log_assistant_event(self, event_type: str, **kwargs: Any) -> None: ...


def _resolve_screen_context_timeout(timeout_seconds: float | None) -> float:
    if timeout_seconds is not None:
        return max(0.001, float(timeout_seconds))
    raw = os.getenv("SCREEN_CONTEXT_STEP_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_SCREEN_CONTEXT_STEP_TIMEOUT_SECONDS


async def execute_screen_context_step(
    *,
    model: ScreenContextRuntimeModel,
    step_request: ScreenContextStepRequest,
    request_id: str,
    deps: ScreenContextRuntimeDeps,
    timeout_seconds: float | None = None,
) -> ScreenContextStepExecutionResult:
    screen_context_started = time.monotonic()
    deps.log_assistant_event(
        "agent_step_started",
        request_id=request_id,
        agent="screen_context",
        task=deps.clean_text(step_request.task, "", 420),
        metadata={"focus": deps.clean_text(step_request.focus, "", 220)},
    )
    try:
        screenshot = await deps.prepare_vision_screenshot(keep_chat_hidden=False)
        resolved_timeout = _resolve_screen_context_timeout(timeout_seconds)
        try:
            latest_screen_context = await asyncio.wait_for(
                model.generate_screen_context(
                    user_request=step_request.task,
                    image=screenshot,
                    focus=step_request.focus,
                ),
                timeout=resolved_timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Screen context generation timed out after {resolved_timeout:.1f}s."
            ) from exc
        message = deps.screen_context_message(latest_screen_context)
        step_result = {
            "agent": "screen_context",
            "task": deps.clean_text(step_request.task, "", 220),
            "success": True,
            "message": message,
            "source": "screen_judge",
        }
        deps.log_assistant_event(
            "agent_step_completed",
            request_id=request_id,
            agent="screen_context",
            task=deps.clean_text(step_request.task, "", 420),
            message=message,
            success=True,
            duration_seconds=time.monotonic() - screen_context_started,
            metadata=latest_screen_context,
        )
        return ScreenContextStepExecutionResult(
            step_result=step_result,
            latest_screen_context=latest_screen_context,
        )
    except Exception as exc:
        step_result = {
            "agent": "screen_context",
            "task": deps.clean_text(step_request.task, "", 220),
            "success": False,
            "message": deps.clean_text(str(exc), "Failed to collect screen context.", 420),
            "source": "screen_judge",
        }
        deps.log_assistant_event(
            "agent_step_failed",
            request_id=request_id,
            agent="screen_context",
            task=deps.clean_text(step_request.task, "", 420),
            message=step_result["message"],
            error=str(exc),
            success=False,
            duration_seconds=time.monotonic() - screen_context_started,
            metadata={"traceback": traceback.format_exc()},
        )
        return ScreenContextStepExecutionResult(
            step_result=step_result,
            latest_screen_context=None,
        )
