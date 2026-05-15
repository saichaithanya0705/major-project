"""
Reasoning-strength policy for CUA Vision model roles.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from agents.cua_vision.contracts import ActionType, ComputerAction


class ModelRole(str, Enum):
    PLANNER = "planner"
    GROUNDER = "grounder"
    CRITIC = "critic"


class ModelStrength(str, Enum):
    LOW = "low"
    STRONG = "strong"


STRENGTH_ENV_VARS = {
    ModelRole.PLANNER: "CUA_VISION_PLANNER_REASONING",
    ModelRole.GROUNDER: "CUA_VISION_GROUNDER_REASONING",
    ModelRole.CRITIC: "CUA_VISION_CRITIC_REASONING",
}
LOW_CONFIDENCE_THRESHOLD_ENV_VAR = "CUA_VISION_LOW_CONFIDENCE_THRESHOLD"


@dataclass(frozen=True, slots=True)
class ModelPolicyContext:
    action: ComputerAction | None = None
    grounding_confidence: float | None = None
    repeated_noop: bool = False
    unclear_screen: bool = False
    completion_claim: bool = False
    destructive_action: bool = False


@dataclass(frozen=True, slots=True)
class CuaModelPolicy:
    default_planner: ModelStrength = ModelStrength.LOW
    default_grounder: ModelStrength = ModelStrength.LOW
    default_critic: ModelStrength = ModelStrength.STRONG
    low_confidence_threshold: float = 0.6

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "CuaModelPolicy":
        values = os.environ if env is None else env
        return cls(
            default_planner=_env_strength(
                values,
                STRENGTH_ENV_VARS[ModelRole.PLANNER],
                ModelStrength.LOW,
            ),
            default_grounder=_env_strength(
                values,
                STRENGTH_ENV_VARS[ModelRole.GROUNDER],
                ModelStrength.LOW,
            ),
            default_critic=_env_strength(
                values,
                STRENGTH_ENV_VARS[ModelRole.CRITIC],
                ModelStrength.STRONG,
            ),
            low_confidence_threshold=_env_float(
                values,
                LOW_CONFIDENCE_THRESHOLD_ENV_VAR,
                0.6,
            ),
        )

    def choose_strength(self, role: ModelRole, context: ModelPolicyContext | None = None) -> ModelStrength:
        context = context or ModelPolicyContext()
        if role == ModelRole.CRITIC:
            return self.default_critic
        if _requires_strong_model(context, self.low_confidence_threshold):
            return ModelStrength.STRONG
        if role == ModelRole.GROUNDER:
            return self.default_grounder
        return self.default_planner

    def provider_purpose(self, role: ModelRole, context: ModelPolicyContext | None = None) -> str:
        strength = self.choose_strength(role, context)
        return f"cua_{role.value}_{strength.value}"


def _requires_strong_model(context: ModelPolicyContext, low_confidence_threshold: float) -> bool:
    if context.completion_claim or context.repeated_noop or context.unclear_screen or context.destructive_action:
        return True
    if context.grounding_confidence is not None and context.grounding_confidence < low_confidence_threshold:
        return True
    if context.action and context.action.action_type in {ActionType.ABORT}:
        return True
    return False


def _env_strength(
    env: Mapping[str, str],
    name: str,
    default: ModelStrength,
) -> ModelStrength:
    raw_value = str(env.get(name, "") or "").strip().lower()
    if not raw_value:
        return default
    aliases = {
        "low": ModelStrength.LOW,
        "weak": ModelStrength.LOW,
        "fast": ModelStrength.LOW,
        "cheap": ModelStrength.LOW,
        "strong": ModelStrength.STRONG,
        "high": ModelStrength.STRONG,
        "reasoning": ModelStrength.STRONG,
        "deep": ModelStrength.STRONG,
    }
    try:
        return aliases[raw_value]
    except KeyError:
        allowed = ", ".join(sorted(aliases))
        raise ValueError(f"{name} must be one of: {allowed}") from None


def _env_float(
    env: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw_value = str(env.get(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        raise ValueError(f"{name} must be a number between 0 and 1") from None
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return value
