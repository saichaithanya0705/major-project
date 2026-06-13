"""Outcome reporting helpers for the rapid orchestrator loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from models.rapid_orchestrator_contracts import (
    RapidAgentStepResult,
    RapidAssistantLogger,
    RapidDirectResponseFinalizer,
    RapidHistoryAppender,
    RapidTextCleaner,
    RapidToolMap,
)


_STRUCTURAL_SUBFLOW_ERRORS = (
    AssertionError,
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
)


def raise_structural_subflow_error(exc: Exception) -> None:
    if isinstance(exc, _STRUCTURAL_SUBFLOW_ERRORS):
        raise exc


def _safe_direct_args(direct_args: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(direct_args, Mapping):
        return {}
    return dict(direct_args)


@dataclass(frozen=True, slots=True)
class RapidRequestOutcomeReporter:
    request_id: str
    user_prompt: str
    append_rapid_history: RapidHistoryAppender
    clean_text: RapidTextCleaner
    finalize_direct_response_text: RapidDirectResponseFinalizer
    log_assistant_event: RapidAssistantLogger
    router_tool_map: RapidToolMap

    def emit_direct_response(
        self,
        text: str,
        *,
        direct_args: Mapping[str, Any] | None = None,
    ) -> None:
        tool = self.router_tool_map.get("direct_response")
        if tool:
            tool(
                text=text,
                source="rapid_response",
                **_safe_direct_args(direct_args),
            )

    def complete_direct_response(
        self,
        *,
        response_text: object,
        chain_steps: Sequence[RapidAgentStepResult],
        agent: str = "direct",
        task: object | None = None,
        direct_args: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        direct_text = self.finalize_direct_response_text(
            user_prompt=self.user_prompt,
            chain_steps=chain_steps,
            text=response_text,
        )
        self.emit_direct_response(direct_text, direct_args=direct_args)
        self.append_rapid_history("assistant", direct_text, "rapid")
        event: dict[str, Any] = {
            "request_id": self.request_id,
            "agent": agent,
            "task": self.clean_text(task if task is not None else self.user_prompt, "", 420),
            "message": direct_text,
            "success": True,
        }
        if metadata is not None:
            event["metadata"] = dict(metadata)
        self.log_assistant_event("request_completed", **event)
        return direct_text

    def fail_request(
        self,
        *,
        agent: str,
        message: str,
        error: object,
        task: object | None = None,
        metadata: Mapping[str, Any] | None = None,
        emit_direct_response: bool = True,
    ) -> None:
        if emit_direct_response:
            self.emit_direct_response(message)
        self.append_rapid_history("assistant", message, "rapid")
        event: dict[str, Any] = {
            "request_id": self.request_id,
            "agent": agent,
            "task": self.clean_text(task if task is not None else self.user_prompt, "", 420),
            "message": message,
            "error": self.clean_text(error, "", 420),
            "success": False,
        }
        if metadata is not None:
            event["metadata"] = dict(metadata)
        self.log_assistant_event("request_failed", **event)

    def stop_request(
        self,
        *,
        message: str,
        task: object | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.emit_direct_response(message)
        self.append_rapid_history("assistant", message, "rapid")
        event: dict[str, Any] = {
            "request_id": self.request_id,
            "task": self.clean_text(task if task is not None else self.user_prompt, "", 420),
            "message": message,
            "success": False,
        }
        if metadata is not None:
            event["metadata"] = dict(metadata)
        self.log_assistant_event("request_stopped", **event)


__all__ = [
    "RapidRequestOutcomeReporter",
    "raise_structural_subflow_error",
]
