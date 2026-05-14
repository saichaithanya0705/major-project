"""
Checks for CUA Vision typed execution contracts.

Usage:
    python tests/test_cua_vision_contracts.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import (  # noqa: E402
    ActionResult,
    ActionType,
    ComputerAction,
    CriticVerdict,
    CuaRunResult,
    ScreenObservation,
    TargetKind,
    TargetRef,
)


def test_contracts_keep_success_and_completion_distinct() -> None:
    result = CuaRunResult(
        success=True,
        complete=False,
        result="Clicked Save; waiting for confirmation.",
    )

    assert result.success is True
    assert result.complete is False


def test_critic_verdict_rejects_invalid_confidence() -> None:
    try:
        CriticVerdict(
            complete=False,
            should_continue=True,
            confidence=1.5,
            reason="impossible confidence",
        )
    except ValueError as exc:
        assert "confidence" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected confidence validation failure")


def test_critic_verdict_rejects_complete_and_continue() -> None:
    try:
        CriticVerdict(
            complete=True,
            should_continue=True,
            confidence=0.8,
            reason="contradictory state",
        )
    except ValueError as exc:
        assert "continuation" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected contradictory verdict failure")


def test_target_ref_requires_payload_for_non_empty_targets() -> None:
    try:
        TargetRef(TargetKind.COORDINATE, x=10)
    except ValueError as exc:
        assert "x and y" in str(exc), exc
    else:
        raise AssertionError("Expected coordinate validation failure")

    try:
        TargetRef(TargetKind.DESCRIPTION, description="")
    except ValueError as exc:
        assert "description" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected description validation failure")


def test_computer_action_and_observation_are_sdk_free() -> None:
    target = TargetRef(TargetKind.COORDINATE, x=12, y=40)
    action = ComputerAction(
        action_type=ActionType.MOVE,
        target=target,
        raw_name="move",
        raw_args={"x": 12, "y": 40},
    )
    observation = ScreenObservation(
        screenshot_png_base64="abc",
        active_window_title="Editor",
        capture_context={"width": 100, "height": 100},
    )
    result = ActionResult(
        executed=True,
        message="moved",
        before=observation,
        after=observation,
    )

    assert action.target is target
    assert result.before is observation
    assert result.after is observation


def run_checks() -> None:
    test_contracts_keep_success_and_completion_distinct()
    test_critic_verdict_rejects_invalid_confidence()
    test_critic_verdict_rejects_complete_and_continue()
    test_target_ref_requires_payload_for_non_empty_targets()
    test_computer_action_and_observation_are_sdk_free()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_contracts] All checks passed.")

