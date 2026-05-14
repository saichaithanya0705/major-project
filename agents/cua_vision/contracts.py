"""
Typed contracts for CUA Vision computer-use execution.

These contracts are intentionally free of PIL, PyAutoGUI, and model SDK types so
they can sit between model output, grounding, execution, and criticism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    MOVE = "move"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE_TEXT = "type_text"
    KEYPRESS = "keypress"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"
    COMPLETE = "complete"
    ABORT = "abort"


class TargetKind(str, Enum):
    NONE = "none"
    COORDINATE = "coordinate"
    BBOX = "bbox"
    ELEMENT_ID = "element_id"
    DESCRIPTION = "description"


@dataclass(frozen=True, slots=True)
class TargetRef:
    kind: TargetKind
    x: float | None = None
    y: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    element_id: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if self.kind == TargetKind.NONE:
            return
        if self.kind == TargetKind.COORDINATE and (self.x is None or self.y is None):
            raise ValueError("Coordinate targets require both x and y.")
        if self.kind == TargetKind.BBOX and self.bbox is None:
            raise ValueError("Bbox targets require bbox.")
        if self.kind == TargetKind.ELEMENT_ID and not self.element_id:
            raise ValueError("Element targets require element_id.")
        if self.kind == TargetKind.DESCRIPTION and not self.description:
            raise ValueError("Description targets require description.")


@dataclass(frozen=True, slots=True)
class ComputerAction:
    action_type: ActionType
    target: TargetRef = TargetRef(TargetKind.NONE)
    text: str | None = None
    keys: tuple[str, ...] = ()
    scroll_delta: int | None = None
    duration_seconds: float | None = None
    raw_name: str | None = None
    raw_args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScreenObservation:
    screenshot_png_base64: str | None
    active_window_title: str | None
    capture_context: dict[str, Any]
    accessibility_tree: str | None = None
    elements: tuple[dict[str, Any], ...] = ()
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionResult:
    executed: bool
    message: str
    before: ScreenObservation | None = None
    after: ScreenObservation | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CriticVerdict:
    complete: bool
    should_continue: bool
    confidence: float
    reason: str
    next_hint: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Critic confidence must be between 0 and 1.")
        if self.complete and self.should_continue:
            raise ValueError("A complete verdict cannot also request continuation.")


@dataclass(frozen=True, slots=True)
class CuaRunResult:
    success: bool
    complete: bool
    result: str | None = None
    error: str | None = None
    critic: CriticVerdict | None = None

