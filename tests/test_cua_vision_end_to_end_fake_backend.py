"""
End-to-end CUA Vision fake-backend regressions.

Usage:
    python tests/test_cua_vision_end_to_end_fake_backend.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402
from agents.cua_vision.controller import CuaController  # noqa: E402
from agents.cua_vision.grounding import CuaGrounder, GroundedTarget  # noqa: E402
from tests.cua_vision_tasks.fixtures import FakeComputerBackend, FakePlanner  # noqa: E402


def test_low_reasoning_style_output_succeeds_when_normalized_and_grounded() -> None:
    backend = FakeComputerBackend(completion_evidence=True)
    planner = FakePlanner(
        [
            {"name": "left_click", "arguments": {"coordinate": [15, 30]}},
            {"name": "task_is_complete", "arguments": {"text": "done"}},
        ]
    )

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Click the visible button"))

    assert result["complete"] is True
    assert backend.executed_actions[0].target.kind == TargetKind.COORDINATE


def test_false_completion_is_rejected_end_to_end() -> None:
    backend = FakeComputerBackend(completion_evidence=False)
    planner = FakePlanner([{"name": "task_is_complete", "arguments": {"text": "done"}}])

    result = asyncio.run(CuaController(backend=backend, planner=planner).run("Click Save"))

    assert result["complete"] is False
    assert "without independent" in result["result"]


def test_ambiguous_grounding_requests_stronger_model() -> None:
    backend = FakeComputerBackend()
    planner = FakePlanner(
        [
            ComputerAction(
                ActionType.CLICK,
                target=TargetRef(TargetKind.DESCRIPTION, description="ambiguous button"),
            )
        ]
    )
    grounder = CuaGrounder(
        description_grounder=lambda _description, _observation: GroundedTarget(
            x=10,
            y=20,
            confidence=0.3,
            source="fake",
            evidence={},
        )
    )

    result = asyncio.run(CuaController(backend=backend, planner=planner, grounder=grounder).run("Click ambiguous"))

    assert result["complete"] is False
    assert "confidence" in result["result"]


def run_checks() -> None:
    test_low_reasoning_style_output_succeeds_when_normalized_and_grounded()
    test_false_completion_is_rejected_end_to_end()
    test_ambiguous_grounding_requests_stronger_model()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_end_to_end_fake_backend] All checks passed.")
