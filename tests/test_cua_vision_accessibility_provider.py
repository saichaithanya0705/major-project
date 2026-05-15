"""
Checks for CUA Vision accessibility capability provider.

Usage:
    python tests/test_cua_vision_accessibility_provider.py
"""

import os
import sys
import math

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.accessibility import (  # noqa: E402
    UnavailableAccessibilityProvider,
    WindowsAccessibilityProvider,
)


def test_unavailable_provider_reports_capability_metadata() -> None:
    snapshot = UnavailableAccessibilityProvider("not installed").snapshot()

    assert snapshot.elements == ()
    assert snapshot.capabilities["accessibility"] == "unavailable"
    assert "not installed" in snapshot.capabilities["reason"]


def test_windows_provider_normalizes_injected_elements() -> None:
    provider = WindowsAccessibilityProvider(
        enumerator=lambda: [
            {
                "automation_id": "save-button",
                "name": "Save",
                "control_type": "Button",
                "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                "patterns": ["invoke"],
            }
        ],
        platform="win32",
    )

    snapshot = provider.snapshot()

    assert snapshot.capabilities["accessibility"] == "available"
    assert snapshot.elements[0]["id"] == "save-button"
    assert snapshot.elements[0]["bounds"] == {"left": 1.0, "top": 2.0, "right": 3.0, "bottom": 4.0}
    assert "[save-button] Button Save" in snapshot.tree


def test_windows_provider_failure_stays_explicitly_unavailable() -> None:
    def _boom():
        raise RuntimeError("uia unavailable")

    snapshot = WindowsAccessibilityProvider(enumerator=_boom, platform="win32").snapshot()

    assert snapshot.capabilities["accessibility"] == "unavailable"
    assert "uia unavailable" in snapshot.capabilities["reason"]


def test_windows_provider_skips_invalid_elements_with_metadata() -> None:
    provider = WindowsAccessibilityProvider(
        enumerator=lambda: [
            {
                "automation_id": "save-button",
                "name": "Save",
                "control_type": "Button",
                "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                "confidence": 0.8,
            },
            {
                "automation_id": "bad-confidence",
                "name": "Broken",
                "control_type": "Button",
                "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                "confidence": 7,
            },
            {
                "automation_id": "nan-confidence",
                "name": "Broken",
                "control_type": "Button",
                "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                "confidence": math.nan,
            },
            {
                "automation_id": "inverted-bounds",
                "name": "Broken",
                "control_type": "Button",
                "bounds": {"left": 10, "top": 2, "right": 3, "bottom": 4},
                "confidence": 0.8,
            },
            {
                "automation_id": "infinite-bounds",
                "name": "Broken",
                "control_type": "Button",
                "bounds": [1, 2, math.inf, 4],
                "confidence": 0.8,
            },
        ],
        platform="win32",
    )

    snapshot = provider.snapshot()

    assert snapshot.capabilities["accessibility"] == "available"
    assert snapshot.capabilities["element_count"] == 1
    assert "normalization_errors" in snapshot.capabilities
    assert snapshot.elements[0]["id"] == "save-button"


def run_checks() -> None:
    test_unavailable_provider_reports_capability_metadata()
    test_windows_provider_normalizes_injected_elements()
    test_windows_provider_failure_stays_explicitly_unavailable()
    test_windows_provider_skips_invalid_elements_with_metadata()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_accessibility_provider] All checks passed.")
