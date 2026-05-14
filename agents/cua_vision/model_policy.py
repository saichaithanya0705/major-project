"""
Reasoning-strength policy for CUA Vision model roles.
"""

from __future__ import annotations

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

    def choose_strength(self, role: ModelRole, context: ModelPolicyContext | None = None) -> ModelStrength:
        context = context or ModelPolicyContext()
        if role == ModelRole.CRITIC:
            return self.default_critic
        if _requires_strong_model(context, self.low_confidence_threshold):
            return ModelStrength.STRONG
        if role == ModelRole.GROUNDER:
            return self.default_grounder
        return self.default_planner


def _requires_strong_model(context: ModelPolicyContext, low_confidence_threshold: float) -> bool:
    if context.completion_claim or context.repeated_noop or context.unclear_screen or context.destructive_action:
        return True
    if context.grounding_confidence is not None and context.grounding_confidence < low_confidence_threshold:
        return True
    if context.action and context.action.action_type in {ActionType.ABORT}:
        return True
    return False
