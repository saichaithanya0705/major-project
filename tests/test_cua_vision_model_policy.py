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
    assert (
        policy.provider_purpose(
            ModelRole.PLANNER,
            ModelPolicyContext(completion_claim=True),
        )
        == "cua_planner_strong"
    )


def test_low_grounding_confidence_requires_strong_grounder() -> None:
    policy = CuaModelPolicy()

    strength = policy.choose_strength(
        ModelRole.GROUNDER,
        ModelPolicyContext(grounding_confidence=0.3),
    )

    assert strength == ModelStrength.STRONG


def test_critic_defaults_to_strong_reasoning() -> None:
    assert CuaModelPolicy().choose_strength(ModelRole.CRITIC) == ModelStrength.STRONG


def test_model_policy_reads_reasoning_strength_from_env_mapping() -> None:
    policy = CuaModelPolicy.from_env(
        {
            "CUA_VISION_PLANNER_REASONING": "strong",
            "CUA_VISION_GROUNDER_REASONING": "weak",
            "CUA_VISION_CRITIC_REASONING": "high",
            "CUA_VISION_LOW_CONFIDENCE_THRESHOLD": "0.75",
        }
    )

    assert policy.choose_strength(ModelRole.PLANNER) == ModelStrength.STRONG
    assert policy.choose_strength(ModelRole.GROUNDER) == ModelStrength.LOW
    assert policy.choose_strength(ModelRole.CRITIC) == ModelStrength.STRONG
    assert policy.low_confidence_threshold == 0.75


def test_model_policy_rejects_invalid_env_values() -> None:
    try:
        CuaModelPolicy.from_env({"CUA_VISION_PLANNER_REASONING": "medium"})
    except ValueError as exc:
        assert "CUA_VISION_PLANNER_REASONING" in str(exc)
    else:
        raise AssertionError("Expected invalid reasoning strength to be rejected")

    try:
        CuaModelPolicy.from_env({"CUA_VISION_LOW_CONFIDENCE_THRESHOLD": "NaN"})
    except ValueError as exc:
        assert "CUA_VISION_LOW_CONFIDENCE_THRESHOLD" in str(exc)
    else:
        raise AssertionError("Expected non-finite confidence threshold to be rejected")


def run_checks() -> None:
    test_low_reasoning_planner_allowed_for_simple_action()
    test_completion_claim_requires_strong_model()
    test_low_grounding_confidence_requires_strong_grounder()
    test_critic_defaults_to_strong_reasoning()
    test_model_policy_reads_reasoning_strength_from_env_mapping()
    test_model_policy_rejects_invalid_env_values()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_model_policy] All checks passed.")
