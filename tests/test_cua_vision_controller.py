"""
Checks for the CUA Vision controller loop.

Usage:
    python tests/test_cua_vision_controller.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402
from agents.cua_vision.controller import CuaController  # noqa: E402
from tests.cua_vision_tasks.fixtures import FakeComputerBackend, FakePlanner  # noqa: E402


def test_false_completion_is_rejected() -> None:
    backend = FakeComputerBackend(completion_evidence=False)
    planner = FakePlanner([ComputerAction(ActionType.COMPLETE, text="done")])

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Save the file"))

    assert result["success"] is True
    assert result["complete"] is False
    assert "without independent" in result["result"]


def test_click_then_evidenced_completion_succeeds() -> None:
    backend = FakeComputerBackend(completion_evidence=True)
    planner = FakePlanner(
        [
            ComputerAction(
                ActionType.CLICK,
                target=TargetRef(TargetKind.COORDINATE, x=10, y=20),
            ),
            ComputerAction(ActionType.COMPLETE, text="done"),
        ]
    )

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Click Save"))

    assert result["success"] is True
    assert result["complete"] is True
    assert [action.action_type for action in backend.executed_actions] == [
        ActionType.CLICK,
        ActionType.COMPLETE,
    ]


def test_invalid_planner_action_returns_incomplete_result() -> None:
    backend = FakeComputerBackend()
    planner = FakePlanner([{"name": "invent_new_tool", "arguments": {}}])

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Do something"))

    assert result["success"] is True
    assert result["complete"] is False
    assert "unsupported" in result["error"].lower()


def test_ungrounded_description_requests_stronger_model() -> None:
    backend = FakeComputerBackend()
    planner = FakePlanner(
        [
            ComputerAction(
                ActionType.CLICK,
                target=TargetRef(TargetKind.DESCRIPTION, description="Save button"),
            )
        ]
    )

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Click Save"))

    assert result["success"] is True
    assert result["complete"] is False
    assert "stronger model" in result["result"].lower()


def run_checks() -> None:
    test_false_completion_is_rejected()
    test_click_then_evidenced_completion_succeeds()
    test_invalid_planner_action_returns_incomplete_result()
    test_ungrounded_description_requests_stronger_model()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_controller] All checks passed.")
