"""
Checks for CUA Vision independent criticizer.

Usage:
    python tests/test_cua_vision_criticizer.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402
from agents.cua_vision.criticizer import CuaCriticizer  # noqa: E402
from tests.cua_vision_tasks.fixtures import observation  # noqa: E402


def test_blocks_model_only_completion_claim() -> None:
    action = ComputerAction(ActionType.COMPLETE, text="done")
    result = ActionResult(
        executed=True,
        message="complete",
        before=observation(),
        after=observation(),
    )

    verdict = asyncio.run(
        CuaCriticizer().review(
            task="Save the file",
            action=action,
            result=result,
            model_claimed_complete=True,
        )
    )

    assert verdict.complete is False
    assert verdict.should_continue is True
    assert "without independent" in verdict.reason


def test_accepts_completion_with_explicit_evidence() -> None:
    action = ComputerAction(ActionType.COMPLETE, text="done")
    result = ActionResult(
        executed=True,
        message="complete",
        before=observation(),
        after=observation(),
        metrics={"visible_goal_satisfied": True},
    )

    verdict = asyncio.run(
        CuaCriticizer().review(
            task="Save the file",
            action=action,
            result=result,
            model_claimed_complete=True,
        )
    )

    assert verdict.complete is True
    assert verdict.should_continue is False


def test_rejects_generic_completion_evidence_without_goal_source() -> None:
    action = ComputerAction(ActionType.COMPLETE, text="done")
    result = ActionResult(
        executed=True,
        message="complete",
        before=observation(),
        after=observation(),
        metrics={"completion_evidence": True},
    )

    verdict = asyncio.run(
        CuaCriticizer().review(
            task="Save the file",
            action=action,
            result=result,
            model_claimed_complete=True,
        )
    )

    assert verdict.complete is False
    assert "goal evidence" in verdict.reason


def test_failed_action_requires_recovery() -> None:
    action = ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=1, y=2))
    result = ActionResult(
        executed=False,
        message="missed",
        before=observation(),
        after=observation(),
    )

    verdict = asyncio.run(CuaCriticizer().review(task="Click Save", action=action, result=result))

    assert verdict.complete is False
    assert verdict.should_continue is True
    assert "Action failed" in verdict.reason


def test_visual_noop_is_not_completion() -> None:
    action = ComputerAction(ActionType.CLICK, target=TargetRef(TargetKind.COORDINATE, x=1, y=2))
    result = ActionResult(
        executed=True,
        message="clicked",
        before=observation(),
        after=observation(),
        metrics={"global_similarity": 1.0, "target_similarity": 1.0},
    )

    verdict = asyncio.run(CuaCriticizer().review(task="Click Save", action=action, result=result))

    assert verdict.complete is False
    assert verdict.should_continue is True
    assert "visible UI" in verdict.reason


def test_semantic_judge_must_return_strict_verdict() -> None:
    async def _judge(**_kwargs):
        return {
            "complete": True,
            "should_continue": False,
            "confidence": 0.91,
            "reason": "The saved marker is visible.",
            "next_hint": None,
        }

    action = ComputerAction(ActionType.COMPLETE, text="done")
    result = ActionResult(
        executed=True,
        message="complete",
        before=observation(),
        after=observation(),
    )

    verdict = asyncio.run(
        CuaCriticizer(semantic_judge=_judge).review(
            task="Save the file",
            action=action,
            result=result,
            model_claimed_complete=True,
        )
    )

    assert verdict.complete is True
    assert verdict.confidence == 0.91


def run_checks() -> None:
    test_blocks_model_only_completion_claim()
    test_accepts_completion_with_explicit_evidence()
    test_rejects_generic_completion_evidence_without_goal_source()
    test_failed_action_requires_recovery()
    test_visual_noop_is_not_completion()
    test_semantic_judge_must_return_strict_verdict()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_criticizer] All checks passed.")
