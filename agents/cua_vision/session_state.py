"""
Session state and window-change policy for CUA Vision.

This module keeps task progress separate from model output so a planner cannot
turn "I think I am done" into completion without the controller and criticizer
recording evidence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, CriticVerdict, ScreenObservation


EXPECTED_WINDOW_CHANGE_MARKERS = (
    "app launch",
    "application launch",
    "browser navigation",
    "navigate",
    "open app",
    "open application",
    "open browser",
    "new tab",
    "file picker",
    "file dialog",
    "dialog",
    "download",
    "upload",
    "sign in window",
    "switch window",
)

EXPECTED_WINDOW_CHANGE_HOTKEYS = {
    ("alt", "tab"),
    ("ctrl", "l"),
    ("ctrl", "t"),
    ("ctrl", "n"),
}


@dataclass(slots=True)
class CuaSession:
    task: str
    task_id: str
    initial_active_window_title: str | None
    last_trusted_observation: ScreenObservation | None
    started_at: float
    max_actions: int = 25
    max_retries: int = 3
    action_count: int = 0
    retry_count: int = 0
    complete: bool = False
    completion_status: str = "running"
    warnings: list[str] = field(default_factory=list)
    last_critic: CriticVerdict | None = None

    @classmethod
    def start(
        cls,
        task: str,
        initial_observation: ScreenObservation | None = None,
        *,
        max_actions: int = 25,
        max_retries: int = 3,
    ) -> "CuaSession":
        return cls(
            task=str(task or ""),
            task_id=uuid.uuid4().hex,
            initial_active_window_title=(
                initial_observation.active_window_title if initial_observation else None
            ),
            last_trusted_observation=initial_observation,
            started_at=time.monotonic(),
            max_actions=max_actions,
            max_retries=max_retries,
        )

    def can_continue(self) -> bool:
        return (
            not self.complete
            and self.action_count < self.max_actions
            and self.retry_count <= self.max_retries
        )

    def record_observation(self, observation: ScreenObservation) -> None:
        self.last_trusted_observation = observation
        if self.initial_active_window_title is None:
            self.initial_active_window_title = observation.active_window_title

    def record_action_result(
        self,
        action: ComputerAction,
        result: ActionResult,
        *,
        critic: CriticVerdict | None = None,
    ) -> None:
        self.action_count += 1
        if result.after is not None:
            self.last_trusted_observation = result.after
        if result.executed:
            self.retry_count = 0
        else:
            self.retry_count += 1
        if critic is not None:
            self.last_critic = critic
            if critic.complete:
                self.mark_complete(critic.reason)
        warning = unexpected_window_change_warning(action, result)
        if warning:
            self.warnings.append(warning)

    def mark_complete(self, reason: str = "") -> None:
        self.complete = True
        self.completion_status = reason or "complete"


def action_implies_expected_window_change(action: ComputerAction) -> bool:
    text_parts = [
        action.raw_name or "",
        action.text or "",
        " ".join(action.keys),
        str(action.raw_args or ""),
        action.target.description or "",
    ]
    haystack = " ".join(text_parts).strip().lower()
    if any(marker in haystack for marker in EXPECTED_WINDOW_CHANGE_MARKERS):
        return True

    if action.action_type == ActionType.HOTKEY and tuple(action.keys) in EXPECTED_WINDOW_CHANGE_HOTKEYS:
        return True
    if action.action_type == ActionType.KEYPRESS and tuple(action.keys) in {("enter",), ("tab",)}:
        return any(marker in haystack for marker in ("launch", "open", "dialog", "picker"))
    return False


def observation_window_changed(before: ScreenObservation | None, after: ScreenObservation | None) -> bool:
    if before is None or after is None:
        return False
    before_title = str(before.active_window_title or "").strip()
    after_title = str(after.active_window_title or "").strip()
    return bool(before_title and after_title and before_title != after_title)


def unexpected_window_change_warning(action: ComputerAction, result: ActionResult) -> str | None:
    if not observation_window_changed(result.before, result.after):
        return None
    if action_implies_expected_window_change(action):
        return None
    before_title = result.before.active_window_title if result.before else ""
    after_title = result.after.active_window_title if result.after else ""
    return (
        "Unexpected active-window change after "
        f"{action.action_type.value}: {before_title!r} -> {after_title!r}"
    )
