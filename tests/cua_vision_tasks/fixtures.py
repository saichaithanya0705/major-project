"""
Deterministic fake CUA backend and planner fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, ScreenObservation


def observation(title: str = "Test Window", *, marker: str = "screen") -> ScreenObservation:
    return ScreenObservation(
        screenshot_png_base64=marker,
        active_window_title=title,
        capture_context={
            "width": 1000,
            "height": 1000,
            "logical_width": 1000,
            "logical_height": 1000,
            "offset_x": 10.0,
            "offset_y": 20.0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "mode": "test",
        },
    )


@dataclass
class FakePlanner:
    actions: list[Any]
    calls: int = 0

    async def next_action(self, task: str, observation: ScreenObservation, session):
        self.calls += 1
        if not self.actions:
            return ComputerAction(action_type=ActionType.COMPLETE, text="done")
        return self.actions.pop(0)


@dataclass
class FakeComputerBackend:
    observations: list[ScreenObservation] = field(default_factory=lambda: [observation()])
    executed_actions: list[ComputerAction] = field(default_factory=list)
    fail_next: str | None = None
    completion_evidence: bool = False

    def observe(self) -> ScreenObservation:
        if self.observations:
            return self.observations[-1]
        return observation()

    def execute(self, action: ComputerAction) -> ActionResult:
        before = self.observe()
        self.executed_actions.append(action)
        if self.fail_next:
            message = self.fail_next
            self.fail_next = None
            return ActionResult(executed=False, message=message, before=before, after=before)
        metrics = {}
        if action.action_type == ActionType.COMPLETE and self.completion_evidence:
            metrics["completion_evidence"] = True
        after = observation(before.active_window_title or "Test Window", marker=f"after-{len(self.executed_actions)}")
        self.observations.append(after)
        return ActionResult(
            executed=True,
            message=f"Executed {action.action_type.value}",
            before=before,
            after=after,
            metrics=metrics,
        )

    def get_active_window(self) -> str | None:
        return self.observe().active_window_title

    def close(self) -> None:
        return None
