"""
Checks for provider planner output normalization.

Usage:
    python tests/test_cua_vision_provider_planner.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.provider_planner import _select_single_action  # noqa: E402


def test_position_then_click_is_collapsed_to_click_target() -> None:
    action = _select_single_action(
        [
            {
                "name": "go_to_element",
                "arguments": {
                    "target_description": "Save button",
                    "ymin": 10,
                    "xmin": 20,
                    "ymax": 30,
                    "xmax": 40,
                },
            },
            {"name": "click_left_click", "arguments": {}},
        ]
    )

    assert action == {
        "name": "click_target",
        "arguments": {
            "target_description": "Save button",
            "ymin": 10,
            "xmin": 20,
            "ymax": 30,
            "xmax": 40,
            "type_of_click": "left click",
        },
    }


def test_first_single_tool_call_is_preserved() -> None:
    action = _select_single_action(
        [{"name": "type_string", "arguments": {"string": "hello"}}]
    )

    assert action == {"name": "type_string", "arguments": {"string": "hello"}}


def run_checks() -> None:
    test_position_then_click_is_collapsed_to_click_target()
    test_first_single_tool_call_is_preserved()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_provider_planner] All checks passed.")
