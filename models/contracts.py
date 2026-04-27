"""
Typed contracts for routing and routed-step boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RouteAgent = Literal["direct", "jarvis", "browser", "cua_cli", "cua_vision", "screen_context"]


@dataclass(frozen=True, slots=True)
class RouteDecision:
    agent: RouteAgent
    response_text: str = ""
    query: str = ""
    task: str = ""
    focus: str = ""

    def __post_init__(self) -> None:
        if self.agent == "direct" and not self.response_text.strip():
            raise ValueError("Direct route decisions require response_text.")
        if self.agent == "jarvis" and not self.query.strip():
            raise ValueError("Jarvis route decisions require query.")
        if self.agent in {"browser", "cua_cli", "cua_vision"} and not self.task.strip():
            raise ValueError(f"{self.agent} route decisions require task.")
        if self.agent == "screen_context" and not self.task.strip():
            raise ValueError("screen_context route decisions require task.")

    def as_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {"agent": self.agent}
        if self.response_text:
            payload["response_text"] = self.response_text
        if self.query:
            payload["query"] = self.query
        if self.task:
            payload["task"] = self.task
        if self.focus:
            payload["focus"] = self.focus
        return payload


@dataclass(frozen=True, slots=True)
class RoutedStepResult:
    agent: str
    task: str
    success: bool
    message: str
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "task": self.task,
            "success": self.success,
            "message": self.message,
            "source": self.source,
        }
