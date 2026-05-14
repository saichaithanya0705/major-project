"""
Checks fake CUA benchmark task coverage.

Usage:
    python tests/test_cua_vision_benchmark_harness.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402


FAKE_TASKS = {
    "app_launch": ComputerAction(ActionType.HOTKEY, keys=("ctrl", "l"), raw_args={"status_text": "browser navigation"}),
    "button_click": ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=10, y=20)),
    "form_fill": ComputerAction(ActionType.TYPE_TEXT, text="hello"),
    "menu_selection": ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.BBOX, bbox=(10, 10, 20, 20))),
    "repeated_click": ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=10, y=20)),
    "failed_grounding": ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.DESCRIPTION, description="missing")),
    "false_completion": ComputerAction(ActionType.COMPLETE, text="done"),
}


def test_benchmark_fixture_covers_required_task_shapes() -> None:
    assert set(FAKE_TASKS) == {
        "app_launch",
        "button_click",
        "form_fill",
        "menu_selection",
        "repeated_click",
        "failed_grounding",
        "false_completion",
    }


def run_checks() -> None:
    test_benchmark_fixture_covers_required_task_shapes()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_benchmark_harness] All checks passed.")
