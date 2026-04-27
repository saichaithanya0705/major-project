"""
Checks for extracted CUA vision action-guard policy helpers.

Usage:
    python tests/test_cua_vision_action_guard_boundary.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.action_guard import (
    ClickLoopState,
    action_signature,
    register_action_and_detect_click_loop,
    task_expects_repeated_clicks,
)


def run_checks() -> None:
    signature_a = action_signature(
        name="go_to_element",
        args={
            "ymin": 100,
            "xmin": 200,
            "ymax": 300,
            "xmax": 400,
            "target_description": "Save button",
            "status_text": "Positioning...",
        },
        metadata_keys={"status_text", "target_description"},
        click_tool_to_type={"click_left_click": "left click"},
        positioning_tools={"go_to_element", "crop_and_search"},
        last_target_description=None,
        bucket_size=40,
    )
    signature_b = action_signature(
        name="go_to_element",
        args={
            "ymin": 101,
            "xmin": 201,
            "ymax": 301,
            "xmax": 401,
            "target_description": "Primary Save CTA",
            "status_text": "Positioning...",
        },
        metadata_keys={"status_text", "target_description"},
        click_tool_to_type={"click_left_click": "left click"},
        positioning_tools={"go_to_element", "crop_and_search"},
        last_target_description=None,
        bucket_size=40,
    )
    assert signature_a == signature_b, (signature_a, signature_b)

    state = ClickLoopState()
    position_sig = ("go_to_element", ("bucket", 12, 8))
    click_sig = ("click_left_click", (("target_description", "save"),))

    for _ in range(3):
        assert not register_action_and_detect_click_loop(
            state=state,
            task="click save",
            name="go_to_element",
            signature=position_sig,
            click_type=None,
            positioning_tools={"go_to_element", "crop_and_search"},
            click_cycle_loop_stop_threshold=4,
        )
        assert not register_action_and_detect_click_loop(
            state=state,
            task="click save",
            name="click_left_click",
            signature=click_sig,
            click_type="left click",
            positioning_tools={"go_to_element", "crop_and_search"},
            click_cycle_loop_stop_threshold=4,
        )

    assert register_action_and_detect_click_loop(
        state=state,
        task="click save",
        name="click_left_click",
        signature=click_sig,
        click_type="left click",
        positioning_tools={"go_to_element", "crop_and_search"},
        click_cycle_loop_stop_threshold=4,
    )

    assert task_expects_repeated_clicks("Click the plus icon 10 times.") is True
    assert task_expects_repeated_clicks("Click Save once.") is False


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_action_guard_boundary] All checks passed.")
