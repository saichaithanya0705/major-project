"""
Trajectory recording for CUA Vision controller runs.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agents.cua_vision.contracts import ActionResult, ComputerAction, CriticVerdict, ScreenObservation
from agents.cua_vision.grounding import GroundingResult
from agents.cua_vision.session_state import CuaSession


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    index: int
    task_id: str
    timestamp: float
    action: dict[str, Any]
    result: dict[str, Any]
    critic: dict[str, Any]
    grounding: dict[str, Any] | None
    model_name: str | None = None


class CuaTrajectoryRecorder:
    def __init__(
        self,
        *,
        enabled: bool = False,
        directory: str | Path | None = None,
        max_live_screenshots: int = 3,
    ):
        self.enabled = enabled
        self.directory = Path(directory) if directory else None
        self.max_live_screenshots = max(max_live_screenshots, 0)
        self.steps: list[TrajectoryStep] = []
        self.live_screenshots: deque[str] = deque(maxlen=self.max_live_screenshots)

    def record(
        self,
        *,
        session: CuaSession,
        action: ComputerAction,
        result: ActionResult,
        verdict: CriticVerdict,
        grounding: GroundingResult | None = None,
        model_name: str | None = None,
    ) -> TrajectoryStep:
        if result.after and result.after.screenshot_png_base64:
            self.live_screenshots.append(result.after.screenshot_png_base64)

        step = TrajectoryStep(
            index=len(self.steps) + 1,
            task_id=session.task_id,
            timestamp=time.time(),
            action=_clean(asdict(action)),
            result=_result_summary(result),
            critic=_clean(asdict(verdict)),
            grounding=_grounding_summary(grounding),
            model_name=model_name,
        )
        self.steps.append(step)
        if self.enabled:
            self._write_step(step)
        return step

    def _write_step(self, step: TrajectoryStep) -> None:
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{step.task_id}-{step.index:03d}.json"
        path.write_text(json.dumps(_clean(asdict(step)), indent=2), encoding="utf-8")


def _result_summary(result: ActionResult) -> dict[str, Any]:
    return {
        "executed": result.executed,
        "message": result.message,
        "metrics": _clean(result.metrics),
        "before": _observation_summary(result.before),
        "after": _observation_summary(result.after),
    }


def _observation_summary(observation: ScreenObservation | None) -> dict[str, Any] | None:
    if observation is None:
        return None
    return {
        "active_window_title": observation.active_window_title,
        "capture_context": _clean(observation.capture_context),
        "has_screenshot": bool(observation.screenshot_png_base64),
        "element_count": len(observation.elements),
        "capabilities": _clean(observation.capabilities),
    }


def _grounding_summary(grounding: GroundingResult | None) -> dict[str, Any] | None:
    if grounding is None:
        return None
    return {
        "status": grounding.status,
        "reason": grounding.reason,
        "target": _clean(asdict(grounding.target)) if grounding.target else None,
    }


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, deque)):
        return [_clean(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value
