"""
Optional accessibility capability provider for CUA Vision.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Mapping
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

        elements = tuple(
            _normalize_element(index, element)
            for index, element in enumerate(raw_elements)
        )
        return AccessibilitySnapshot(
            tree=_build_tree(elements),
            elements=elements,
            capabilities={
                "accessibility": "available",
                "provider": "windows_uia",
                "element_count": len(elements),
            },
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
    bounds = data.get("bounds")
    actions = data.get("actions") or data.get("patterns") or ()
    if isinstance(actions, str):
        actions = (actions,)
    return {
        "id": str(element_id),
        "name": name,
        "role": role,
        "bounds": bounds,
        "actions": tuple(str(action) for action in actions),
        "confidence": float(data.get("confidence", 0.9)),
    }


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
