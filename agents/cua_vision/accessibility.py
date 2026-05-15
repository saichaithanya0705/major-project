"""
Optional accessibility capability provider for CUA Vision.
"""

from __future__ import annotations

import sys
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AccessibilitySnapshot:
    tree: str | None
    elements: tuple[dict[str, Any], ...]
    capabilities: dict[str, Any]


class AccessibilityProvider(Protocol):
    def snapshot(self) -> AccessibilitySnapshot:
        ...


class UnavailableAccessibilityProvider:
    def __init__(self, reason: str):
        self.reason = reason

    def snapshot(self) -> AccessibilitySnapshot:
        return AccessibilitySnapshot(
            tree=None,
            elements=(),
            capabilities={"accessibility": "unavailable", "reason": self.reason},
        )


class WindowsAccessibilityProvider:
    """
    Windows UIA boundary.

    The live enumerator is injectable so tests can validate behavior without a
    desktop automation dependency. A future provider can plug pywinauto/UIA here
    without changing the controller or backend contracts.
    """

    def __init__(
        self,
        enumerator: Callable[[], Iterable[Mapping[str, Any] | object]] | None = None,
        *,
        platform: str | None = None,
    ):
        self.enumerator = enumerator
        self.platform = platform or sys.platform

    def snapshot(self) -> AccessibilitySnapshot:
        if self.platform != "win32" and self.enumerator is None:
            return AccessibilitySnapshot(
                tree=None,
                elements=(),
                capabilities={
                    "accessibility": "unavailable",
                    "reason": f"Windows accessibility is not available on {self.platform}.",
                },
            )
        if self.enumerator is None:
            return AccessibilitySnapshot(
                tree=None,
                elements=(),
                capabilities={
                    "accessibility": "unavailable",
                    "reason": "No Windows UIA enumerator is configured.",
                },
            )
        try:
            raw_elements = list(self.enumerator())
        except Exception as exc:
            return AccessibilitySnapshot(
                tree=None,
                elements=(),
                capabilities={"accessibility": "unavailable", "reason": str(exc)},
            )

        elements, normalization_errors = _normalize_elements(raw_elements)
        capabilities = {
            "accessibility": "available",
            "provider": "windows_uia",
            "element_count": len(elements),
        }
        if normalization_errors:
            capabilities["normalization_errors"] = normalization_errors
        return AccessibilitySnapshot(
            tree=_build_tree(elements),
            elements=elements,
            capabilities=capabilities,
        )


def build_accessibility_provider(
    enumerator: Callable[[], Iterable[Mapping[str, Any] | object]] | None = None,
) -> AccessibilityProvider:
    if sys.platform == "win32" or enumerator is not None:
        return WindowsAccessibilityProvider(enumerator=enumerator)
    return UnavailableAccessibilityProvider(
        f"Windows accessibility is not available on {sys.platform}."
    )


def _normalize_element(index: int, element: Mapping[str, Any] | object) -> dict[str, Any]:
    data = dict(element) if isinstance(element, Mapping) else _object_to_dict(element)
    element_id = (
        data.get("id")
        or data.get("element_id")
        or data.get("automation_id")
        or data.get("runtime_id")
        or f"uia-{index}"
    )
    name = str(data.get("name") or data.get("title") or "").strip()
    role = str(data.get("role") or data.get("control_type") or "unknown").strip()
    bounds = _normalize_bounds(data.get("bounds"))
    actions = data.get("actions") or data.get("patterns") or ()
    if isinstance(actions, str):
        actions = (actions,)
    return {
        "id": str(element_id),
        "name": name,
        "role": role,
        "bounds": bounds,
        "actions": tuple(str(action) for action in actions),
        "confidence": _finite_confidence(data.get("confidence", 0.9)),
    }


def _normalize_elements(raw_elements: list[Mapping[str, Any] | object]) -> tuple[tuple[dict[str, Any], ...], list[str]]:
    elements: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, element in enumerate(raw_elements):
        try:
            elements.append(_normalize_element(index, element))
        except (TypeError, ValueError) as exc:
            errors.append(f"element {index}: {exc}")
    return tuple(elements), errors


def _finite_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be numeric") from None
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        raise ValueError("confidence must be finite and between 0 and 1")
    return confidence


def _normalize_bounds(value: object) -> dict[str, float] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if {"left", "top", "right", "bottom"}.issubset(value):
            left, top, right, bottom = (
                _finite_bound(value["left"], "left"),
                _finite_bound(value["top"], "top"),
                _finite_bound(value["right"], "right"),
                _finite_bound(value["bottom"], "bottom"),
            )
        elif {"x", "y", "width", "height"}.issubset(value):
            left = _finite_bound(value["x"], "x")
            top = _finite_bound(value["y"], "y")
            width = _finite_bound(value["width"], "width")
            height = _finite_bound(value["height"], "height")
            if width <= 0.0 or height <= 0.0:
                raise ValueError("bounds width and height must be positive")
            right = left + width
            bottom = top + height
        else:
            raise ValueError(
                "bounds mapping must contain left/top/right/bottom or x/y/width/height"
            )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) != 4:
            raise ValueError("bounds sequence must contain four values")
        left, top, right, bottom = (
            _finite_bound(value[0], "left"),
            _finite_bound(value[1], "top"),
            _finite_bound(value[2], "right"),
            _finite_bound(value[3], "bottom"),
        )
    else:
        raise ValueError("bounds must be a mapping, a four-value sequence, or null")

    if right <= left or bottom <= top:
        raise ValueError("bounds must have positive width and height")
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _finite_bound(value: object, name: str) -> float:
    try:
        bound = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"bounds {name} must be numeric") from None
    if not math.isfinite(bound):
        raise ValueError(f"bounds {name} must be finite")
    return bound


def _object_to_dict(value: object) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attr_name in (
        "id",
        "element_id",
        "automation_id",
        "runtime_id",
        "name",
        "title",
        "role",
        "control_type",
        "bounds",
        "actions",
        "patterns",
        "confidence",
    ):
        if hasattr(value, attr_name):
            result[attr_name] = getattr(value, attr_name)
    return result


def _build_tree(elements: tuple[dict[str, Any], ...]) -> str | None:
    if not elements:
        return None
    lines = []
    for element in elements:
        label = " ".join(part for part in (element["role"], element["name"]) if part).strip()
        lines.append(f"[{element['id']}] {label} bounds={element.get('bounds')}")
    return "\n".join(lines)
