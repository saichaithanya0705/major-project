"""
Independent completion and recovery criticizer for CUA Vision.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from typing import Any

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, CriticVerdict
from agents.cua_vision.session_state import CuaSession, unexpected_window_change_warning


SemanticJudge = Callable[..., Any]


class CuaCriticizer:
    def __init__(
        self,
        *,
        semantic_judge: SemanticJudge | None = None,
        noop_similarity_threshold: float = 0.995,
        minimum_grounding_confidence: float = 0.6,
    ):
        self.semantic_judge = semantic_judge
        self.noop_similarity_threshold = noop_similarity_threshold
        self.minimum_grounding_confidence = minimum_grounding_confidence

    async def review(
        self,
        *,
        task: str,
        action: ComputerAction,
        result: ActionResult,
        session: CuaSession | None = None,
        model_claimed_complete: bool = False,
        visual_metrics: Mapping[str, Any] | None = None,
        grounding_confidence: float | None = None,
        needs_stronger_model: bool = False,
    ) -> CriticVerdict:
        metrics = {**dict(result.metrics or {}), **dict(visual_metrics or {})}
        if grounding_confidence is not None and grounding_confidence < self.minimum_grounding_confidence:
            return CriticVerdict(
                complete=False,
                should_continue=False,
                confidence=0.25,
                reason=(
                    f"Grounding confidence {grounding_confidence:.2f} is below "
                    f"{self.minimum_grounding_confidence:.2f}."
                ),
                next_hint="Use a stronger grounding model or request a clearer target.",
            )
        if needs_stronger_model:
            return CriticVerdict(
                complete=False,
                should_continue=False,
                confidence=0.2,
                reason="Grounding or screen state requires a stronger model before execution.",
                next_hint="Escalate the planner or grounder before retrying this action.",
            )
        if not result.executed and action.action_type != ActionType.COMPLETE:
            return CriticVerdict(
                complete=False,
                should_continue=True,
                confidence=0.35,
                reason=f"Action failed: {result.message}",
                next_hint="Recover from the action failure before claiming completion.",
            )
        warning = unexpected_window_change_warning(action, result)
        if warning:
            return CriticVerdict(
                complete=False,
                should_continue=True,
                confidence=0.45,
                reason=warning,
                next_hint="Re-observe the current window and adjust the plan.",
            )
        if (
            _looks_like_visual_noop(metrics, self.noop_similarity_threshold)
            and action.action_type not in {ActionType.WAIT, ActionType.COMPLETE}
        ):
            return CriticVerdict(
                complete=False,
                should_continue=True,
                confidence=0.5,
                reason="The action executed but the visible UI did not materially change.",
                next_hint="Try a more precise target or alternate action.",
            )
        if model_claimed_complete or action.action_type == ActionType.COMPLETE:
            if self.semantic_judge is not None:
                return await self._semantic_completion_verdict(task, action, result, session)
            if not _has_completion_evidence(result, session):
                return CriticVerdict(
                    complete=False,
                    should_continue=True,
                    confidence=0.2,
                    reason=(
                        "Completion was claimed without independent semantic, "
                        "accessibility, or structural goal evidence."
                    ),
                    next_hint="Observe the screen and provide concrete goal-state evidence.",
                )
            return CriticVerdict(
                complete=True,
                should_continue=False,
                confidence=0.8,
                reason="Completion claim has independent goal-state evidence.",
            )
        return CriticVerdict(
            complete=False,
            should_continue=True,
            confidence=0.65,
            reason="Action executed; continue observing until the goal is complete.",
        )

    async def _semantic_completion_verdict(
        self,
        task: str,
        action: ComputerAction,
        result: ActionResult,
        session: CuaSession | None,
    ) -> CriticVerdict:
        assert self.semantic_judge is not None
        payload = self.semantic_judge(
            task=task,
            action=action,
            result=result,
            session=session,
            prompt=CRITICIZER_JSON_PROMPT,
        )
        if inspect.isawaitable(payload):
            payload = await payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            raise ValueError("Semantic criticizer must return a mapping or JSON object.")
        return CriticVerdict(
            complete=bool(payload.get("complete")),
            should_continue=bool(payload.get("should_continue")),
            confidence=float(payload.get("confidence", 0.0)),
            reason=str(payload.get("reason") or ""),
            next_hint=(
                str(payload.get("next_hint"))
                if payload.get("next_hint") is not None
                else None
            ),
        )


def _looks_like_visual_noop(metrics: Mapping[str, Any], threshold: float) -> bool:
    similarities = []
    for key in ("global_similarity", "target_similarity"):
        value = metrics.get(key)
        if value is None:
            continue
        try:
            similarities.append(float(value))
        except (TypeError, ValueError):
            continue
    return bool(similarities and min(similarities) >= threshold)


def _has_completion_evidence(result: ActionResult, session: CuaSession | None) -> bool:
    metrics = dict(result.metrics or {})
    for key in ("visible_goal_satisfied", "accessibility_goal_satisfied", "semantic_goal_satisfied"):
        if metrics.get(key) is True:
            return True
    if metrics.get("completion_evidence") is True:
        source = str(metrics.get("completion_evidence_source") or "").strip().lower()
        return source in {"semantic", "accessibility", "structural", "goal_state"}
    return False


CRITICIZER_JSON_PROMPT = """Return only JSON:
{
  "complete": boolean,
  "should_continue": boolean,
  "confidence": number between 0 and 1,
  "reason": string,
  "next_hint": string or null
}

Judge whether the user's original desktop task is actually complete.
Do not trust the previous model's completion claim by itself.
Use the current screen, accessibility summary, action result, and visual-change metrics.
"""
