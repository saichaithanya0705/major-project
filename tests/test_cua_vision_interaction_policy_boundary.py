"""
Checks for extracted CUA vision interaction-policy helpers.

Usage:
    python tests/test_cua_vision_interaction_policy_boundary.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.interaction_policy import (
    build_fallback_context,
    default_status_text,
    describe_action_for_feedback,
    resolve_target_description,
)


def run_checks() -> None:
    resolved = resolve_target_description(
        task="Save the document",
        args={"target_description": "  Save button  "},
        last_target_description=None,
    )
    assert resolved == "Save button", resolved

    resolved = resolve_target_description(
        task="Open settings",
        args={"status_text": "Clicking Settings icon."},
        last_target_description=None,
    )
    assert resolved == "Settings icon", resolved

    resolved = resolve_target_description(
        task="Open settings",
        args={},
        last_target_description="Gear icon",
    )
    assert resolved == "Gear icon", resolved

    resolved = resolve_target_description(
        task="Open settings",
        args={},
        last_target_description=None,
    )
    assert resolved == "best target for task: Open settings", resolved

    click_map = {
        "click_left_click": "left click",
        "click_double_left_click": "double left click",
        "click_right_click": "right click",
    }
    assert default_status_text("go_to_element", click_map) == "Positioning cursor to target..."
    assert default_status_text("click_left_click", click_map) == "Clicking target..."
    assert default_status_text("unknown_tool", click_map) == "Working..."

    description = describe_action_for_feedback(
        tool_name="click_right_click",
        task="Open context menu",
        args={"status_text": "Clicking row options"},
        click_tool_to_type=click_map,
        last_target_description=None,
    )
    assert description == "right click on row options", description

    context = build_fallback_context(
        task="Save",
        click_type="left click",
        args={"status_text": "Clicking Save"},
        last_click_context=None,
        last_target_description=None,
    )
    assert context == {"type_of_click": "left click", "target_description": "Save"}, context

    context = build_fallback_context(
        task="Save",
        click_type=None,
        args=None,
        last_click_context={"type_of_click": "double left click", "target_description": "Open"},
        last_target_description=None,
    )
    assert context == {
        "type_of_click": "double left click",
        "target_description": "Open",
    }, context

    context = build_fallback_context(
        task="Save",
        click_type=None,
        args=None,
        last_click_context={"type_of_click": "", "target_description": "Open"},
        last_target_description=None,
    )
    assert context is None, context


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_interaction_policy_boundary] All checks passed.")
