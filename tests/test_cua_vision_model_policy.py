"""
Checks for CUA Vision model reasoning policy.

Usage:
    python tests/test_cua_vision_model_policy.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionType, ComputerAction  # noqa: E402
from agents.cua_vision.model_policy import (  # noqa: E402
    CuaModelPolicy,
    ModelPolicyContext,
    ModelRole,
    ModelStrength,
)


def test_low_reasoning_planner_allowed_for_simple_action() -> None:
    policy = CuaModelPolicy()

    strength = policy.choose_strength(
        ModelRole.PLANNER,
        ModelPolicyContext(action=ComputerAction(ActionType.CLICK)),
    )

    assert strength == ModelStrength.LOW


def test_completion_claim_requires_strong_model() -> None:
    policy = CuaModelPolicy()

    strength = policy.choose_strength(
        ModelRole.PLANNER,
        ModelPolicyContext(completion_claim=True),
    )

    assert strength == ModelStrength.STRONG


def test_low_grounding_confidence_requires_strong_grounder() -> None:
    policy = CuaModelPolicy()

    strength = policy.choose_strength(
        ModelRole.GROUNDER,
        ModelPolicyContext(grounding_confidence=0.3),
    )

    assert strength == ModelStrength.STRONG


def test_critic_defaults_to_strong_reasoning() -> None:
    assert CuaModelPolicy().choose_strength(ModelRole.CRITIC) == ModelStrength.STRONG


def run_checks() -> None:
    test_low_reasoning_planner_allowed_for_simple_action()
    test_completion_claim_requires_strong_model()
    test_low_grounding_confidence_requires_strong_grounder()
    test_critic_defaults_to_strong_reasoning()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_model_policy] All checks passed.")
