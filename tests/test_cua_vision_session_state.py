"""
Checks for CUA Vision session state and window-change policy.

Usage:
    python tests/test_cua_vision_session_state.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402
from agents.cua_vision.session_state import (  # noqa: E402
    CuaSession,
    action_implies_expected_window_change,
    unexpected_window_change_warning,
)
from tests.cua_vision_tasks.fixtures import observation  # noqa: E402


def test_session_tracks_progress_and_retry_count() -> None:
    session = CuaSession.start("Click save", observation("Editor"))
    action = ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=1, y=2))
    failed = ActionResult(
        executed=False,
        message="missed",
        before=observation("Editor"),
        after=observation("Editor"),
    )

    session.record_action_result(action, failed)

    assert session.action_count == 1
    assert session.retry_count == 1
    assert session.can_continue()


def test_unexpected_window_change_is_warned() -> None:
    action = ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=1, y=2))
    result = ActionResult(
        executed=True,
        message="clicked",
        before=observation("Editor"),
        after=observation("Settings"),
    )

    warning = unexpected_window_change_warning(action, result)

    assert warning is not None
    assert "Unexpected active-window change" in warning


def test_expected_navigation_window_change_is_allowed() -> None:
    action = ComputerAction(
        ActionType.HOTKEY,
        keys=("ctrl", "l"),
        raw_args={"status_text": "browser navigation to docs"},
    )
    result = ActionResult(
        executed=True,
        message="navigated",
        before=observation("Home"),
        after=observation("Docs"),
    )

    assert action_implies_expected_window_change(action)
    assert unexpected_window_change_warning(action, result) is None


def run_checks() -> None:
    test_session_tracks_progress_and_retry_count()
    test_unexpected_window_change_is_warned()
    test_expected_navigation_window_change_is_allowed()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_session_state] All checks passed.")
