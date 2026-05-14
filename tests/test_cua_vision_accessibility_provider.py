"""
Checks for CUA Vision accessibility capability provider.

Usage:
    python tests/test_cua_vision_accessibility_provider.py
"""

import os
import sys

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
    assert "[save-button] Button Save" in snapshot.tree


def test_windows_provider_failure_stays_explicitly_unavailable() -> None:
    def _boom():
        raise RuntimeError("uia unavailable")

    snapshot = WindowsAccessibilityProvider(enumerator=_boom, platform="win32").snapshot()

    assert snapshot.capabilities["accessibility"] == "unavailable"
    assert "uia unavailable" in snapshot.capabilities["reason"]


def run_checks() -> None:
    test_unavailable_provider_reports_capability_metadata()
    test_windows_provider_normalizes_injected_elements()
    test_windows_provider_failure_stays_explicitly_unavailable()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_accessibility_provider] All checks passed.")
