"""
Checks for CUA Vision action normalization.

Usage:
    python tests/test_cua_vision_action_normalizer.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.action_normalizer import (  # noqa: E402
    ActionNormalizationError,
    normalize_action_call,
    normalize_action_payload,
)
from agents.cua_vision.contracts import ActionType, TargetKind  # noqa: E402


def test_normalizes_left_click_coordinate_alias() -> None:
    action = normalize_action_call("left_click", {"coordinate": [12, 40]})

    assert action.action_type == ActionType.CLICK
    assert action.target.kind == TargetKind.COORDINATE
    assert action.target.x == 12
    assert action.target.y == 40


def test_normalizes_generic_hotkey_keys() -> None:
    action = normalize_action_call("hotkey", {"keys": ["control", "l"]})

    assert action.action_type == ActionType.HOTKEY
    assert action.keys == ("ctrl", "l")


def test_normalizes_click_target_bbox_and_click_type() -> None:
    action = normalize_action_call(
        "click_target",
        {
            "target_description": "Save",
            "type_of_click": "double click",
            "ymin": 1,
            "xmin": 2,
            "ymax": 9,
            "xmax": 12,
        },
    )

    assert action.action_type == ActionType.DOUBLE_CLICK
    assert action.target.kind == TargetKind.BBOX
    assert action.target.bbox == (1.0, 2.0, 9.0, 12.0)
    assert action.target.description == "Save"


def test_normalizes_current_go_to_element_as_move() -> None:
    action = normalize_action_call(
        "go_to_element",
        {
            "target_description": "Search field",
            "ymin": 100,
            "xmin": 200,
            "ymax": 140,
            "xmax": 500,
        },
    )

    assert action.action_type == ActionType.MOVE
    assert action.target.kind == TargetKind.BBOX
    assert action.target.description == "Search field"


def test_normalizes_type_alias_and_preserves_submit_metadata() -> None:
    action = normalize_action_call("type", {"text": "hello", "submit": True})

    assert action.action_type == ActionType.TYPE_TEXT
    assert action.text == "hello"
    assert action.raw_args == {"string": "hello", "submit": True}


def test_blocks_sensitive_type_alias() -> None:
    try:
        normalize_action_call(
            "type",
            {"text": "4111 1111 1111 1111"},
            active_window="Checkout payment token",
        )
    except ActionNormalizationError as exc:
        assert "sensitive" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected sensitive-window typing to be blocked")


def test_blocks_dangerous_generic_hotkey() -> None:
    try:
        normalize_action_call("hotkey", {"keys": ["ctrl", "w"]})
    except ActionNormalizationError as exc:
        assert "blocked" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected dangerous hotkey to be blocked")


def test_normalizes_computer_call_wrapper() -> None:
    action = normalize_action_payload({
        "type": "computer_call",
        "action": {"type": "click", "x": 5, "y": 6, "button": "right"},
    })

    assert action.action_type == ActionType.RIGHT_CLICK
    assert action.target.kind == TargetKind.COORDINATE
    assert action.target.x == 5
    assert action.target.y == 6


def test_rejects_computer_call_output_as_non_executable() -> None:
    try:
        normalize_action_call("computer_call_output", {"output": "screenshot"})
    except ActionNormalizationError as exc:
        assert "not an executable action" in str(exc), exc
    else:
        raise AssertionError("Expected computer_call_output rejection")


def test_ignores_provider_call_id_as_element_target() -> None:
    action = normalize_action_payload({
        "id": "call-123",
        "name": "click",
        "arguments": {"description": "Save button"},
    })

    assert action.target.kind == TargetKind.DESCRIPTION
    assert action.target.description == "Save button"


def test_rejects_unknown_actions() -> None:
    try:
        normalize_action_call("invent_new_tool", {})
    except ActionNormalizationError as exc:
        assert "unsupported" in str(exc).lower(), exc
    else:
        raise AssertionError("Expected unsupported action rejection")


def run_checks() -> None:
    test_normalizes_left_click_coordinate_alias()
    test_normalizes_generic_hotkey_keys()
    test_normalizes_click_target_bbox_and_click_type()
    test_normalizes_current_go_to_element_as_move()
    test_normalizes_type_alias_and_preserves_submit_metadata()
    test_blocks_sensitive_type_alias()
    test_blocks_dangerous_generic_hotkey()
    test_normalizes_computer_call_wrapper()
    test_rejects_computer_call_output_as_non_executable()
    test_ignores_provider_call_id_as_element_target()
    test_rejects_unknown_actions()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_action_normalizer] All checks passed.")
