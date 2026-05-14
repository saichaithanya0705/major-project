"""
Ground model targets into executable screen coordinates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from agents.cua_vision.contracts import ActionType, ComputerAction, ScreenObservation, TargetKind, TargetRef
from agents.cua_vision.screen_context import _bbox_center_to_screen_coords


GROUNDING_GROUNDED = "grounded"
GROUNDING_NEEDS_STRONGER_MODEL = "needs_stronger_model"
GROUNDING_FAILED = "failed"


class GroundingError(ValueError):
    """Raised when a target cannot be mapped into an executable form."""


@dataclass(frozen=True, slots=True)
class GroundedTarget:
    x: float | None
    y: float | None
    confidence: float
    source: str
    evidence: dict[str, Any]
    element_id: str | None = None


@dataclass(frozen=True, slots=True)
class GroundingResult:
    action: ComputerAction
    target: GroundedTarget | None
    status: str
    reason: str = ""

    @property
    def grounded(self) -> bool:
        return self.status == GROUNDING_GROUNDED

    @property
    def needs_stronger_model(self) -> bool:
        return self.status == GROUNDING_NEEDS_STRONGER_MODEL


class DescriptionGrounder(Protocol):
    def __call__(self, description: str, observation: ScreenObservation) -> GroundedTarget | Mapping[str, Any] | None:
        ...


class CuaGrounder:
    def __init__(
        self,
        *,
        minimum_confidence: float = 0.6,
        description_grounder: DescriptionGrounder | None = None,
    ):
        self.minimum_confidence = minimum_confidence
        self.description_grounder = description_grounder

    def ground(self, action: ComputerAction, observation: ScreenObservation) -> GroundingResult:
        target = action.target
        if action.action_type in {ActionType.COMPLETE, ActionType.ABORT, ActionType.WAIT}:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_GROUNDED,
                reason="Action does not require target grounding.",
            )
        if target.kind == TargetKind.NONE:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_GROUNDED,
                reason="Action uses current cursor or keyboard focus.",
            )
        if target.kind == TargetKind.COORDINATE:
            grounded = GroundedTarget(
                x=float(target.x),
                y=float(target.y),
                confidence=1.0,
                source="coordinate",
                evidence={"target_kind": target.kind.value},
            )
            return GroundingResult(action=action, target=grounded, status=GROUNDING_GROUNDED)
        if target.kind == TargetKind.BBOX:
            return self._ground_bbox(action, observation)
        if target.kind == TargetKind.ELEMENT_ID:
            return self._ground_element(action, observation)
        if target.kind == TargetKind.DESCRIPTION:
            return self._ground_description(action, observation)
        return GroundingResult(
            action=action,
            target=None,
            status=GROUNDING_FAILED,
            reason=f"Unsupported target kind: {target.kind.value}",
        )

    def _ground_bbox(self, action: ComputerAction, observation: ScreenObservation) -> GroundingResult:
        if action.target.bbox is None:
            raise GroundingError("Bbox target is missing bbox coordinates.")
        ymin, xmin, ymax, xmax = action.target.bbox
        x, y = _bbox_center_to_screen_coords(
            ymin,
            xmin,
            ymax,
            xmax,
            context=observation.capture_context,
        )
        grounded = GroundedTarget(
            x=x,
            y=y,
            confidence=0.95,
            source="bbox_center",
            evidence={
                "bbox": action.target.bbox,
                "capture_context": dict(observation.capture_context),
                "description": action.target.description,
            },
        )
        return GroundingResult(
            action=_with_grounded_coordinate(action, grounded),
            target=grounded,
            status=GROUNDING_GROUNDED,
        )

    def _ground_element(self, action: ComputerAction, observation: ScreenObservation) -> GroundingResult:
        element_id = action.target.element_id
        element = _find_element(observation.elements, element_id)
        if element is None:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_NEEDS_STRONGER_MODEL,
                reason=f"Element id {element_id!r} is not available in the accessibility snapshot.",
            )
        bounds = _bounds_from_element(element)
        if bounds is None:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_NEEDS_STRONGER_MODEL,
                reason=f"Element id {element_id!r} has no usable bounds.",
            )
        left, top, right, bottom = bounds
        grounded = GroundedTarget(
            x=left + ((right - left) / 2.0),
            y=top + ((bottom - top) / 2.0),
            confidence=float(element.get("confidence", 0.9)),
            source="accessibility_element",
            evidence={"element": dict(element)},
            element_id=element_id,
        )
        return self._result_for_grounded_target(action, grounded)

    def _ground_description(self, action: ComputerAction, observation: ScreenObservation) -> GroundingResult:
        description = action.target.description or ""
        if self.description_grounder is None:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_NEEDS_STRONGER_MODEL,
                reason=(
                    "Description target requires a locator or stronger grounding model; "
                    "no description grounder is configured."
                ),
            )
        grounded = _coerce_grounded_target(self.description_grounder(description, observation))
        if grounded is None:
            return GroundingResult(
                action=action,
                target=None,
                status=GROUNDING_NEEDS_STRONGER_MODEL,
                reason=f"Description target {description!r} could not be grounded.",
            )
        return self._result_for_grounded_target(action, grounded)

    def _result_for_grounded_target(self, action: ComputerAction, grounded: GroundedTarget) -> GroundingResult:
        if grounded.confidence < self.minimum_confidence:
            return GroundingResult(
                action=action,
                target=grounded,
                status=GROUNDING_NEEDS_STRONGER_MODEL,
                reason=(
                    f"Grounding confidence {grounded.confidence:.2f} is below "
                    f"{self.minimum_confidence:.2f}."
                ),
            )
        return GroundingResult(
            action=_with_grounded_coordinate(action, grounded),
            target=grounded,
            status=GROUNDING_GROUNDED,
        )


def _with_grounded_coordinate(action: ComputerAction, grounded: GroundedTarget) -> ComputerAction:
    if grounded.x is None or grounded.y is None:
        raise GroundingError("Grounded target requires x and y coordinates.")
    raw_args = {
        **dict(action.raw_args or {}),
        "grounding": {
            "source": grounded.source,
            "confidence": grounded.confidence,
            "evidence": grounded.evidence,
        },
    }
    return replace(
        action,
        target=TargetRef(
            TargetKind.COORDINATE,
            x=grounded.x,
            y=grounded.y,
            description=action.target.description,
            element_id=grounded.element_id or action.target.element_id,
        ),
        raw_args=raw_args,
    )


def _find_element(elements: tuple[dict[str, Any], ...], element_id: str | None) -> dict[str, Any] | None:
    if not element_id:
        return None
    for element in elements:
        candidate = element.get("id") or element.get("element_id")
        if str(candidate) == str(element_id):
            return element
    return None


def _bounds_from_element(element: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    bounds = element.get("bounds")
    if isinstance(bounds, Mapping):
        if all(key in bounds for key in ("left", "top", "right", "bottom")):
            return (
                float(bounds["left"]),
                float(bounds["top"]),
                float(bounds["right"]),
                float(bounds["bottom"]),
            )
        if all(key in bounds for key in ("x", "y", "width", "height")):
            left = float(bounds["x"])
            top = float(bounds["y"])
            return (left, top, left + float(bounds["width"]), top + float(bounds["height"]))
    if isinstance(bounds, Sequence) and not isinstance(bounds, (str, bytes, bytearray)) and len(bounds) == 4:
        left, top, right, bottom = bounds
        return (float(left), float(top), float(right), float(bottom))
    return None


def _coerce_grounded_target(value: GroundedTarget | Mapping[str, Any] | None) -> GroundedTarget | None:
    if value is None:
        return None
    if isinstance(value, GroundedTarget):
        return value
    return GroundedTarget(
        x=float(value["x"]) if value.get("x") is not None else None,
        y=float(value["y"]) if value.get("y") is not None else None,
        confidence=float(value.get("confidence", 0.0)),
        source=str(value.get("source", "description_grounder")),
        evidence=dict(value.get("evidence", {})),
        element_id=str(value["element_id"]) if value.get("element_id") else None,
    )
