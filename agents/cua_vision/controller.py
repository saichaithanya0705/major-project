"""
CUA Vision controller loop.
"""

from __future__ import annotations

import inspect
from dataclasses import asdict, replace
from typing import Any, Protocol

from agents.cua_vision.action_normalizer import ActionNormalizationError, normalize_action_payload
from agents.cua_vision.computer_backend import ComputerBackend
from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, CriticVerdict, ScreenObservation
from agents.cua_vision.criticizer import CuaCriticizer
from agents.cua_vision.grounding import CuaGrounder, GroundingResult
from agents.cua_vision.session_state import CuaSession, unexpected_window_change_warning
from agents.cua_vision.trajectory import CuaTrajectoryRecorder


class CuaPlanner(Protocol):
    async def next_action(
        self,
        task: str,
        observation: ScreenObservation,
        session: CuaSession,
    ) -> ComputerAction | dict[str, Any] | object:
        ...


class CuaController:
    def __init__(
        self,
        *,
        backend: ComputerBackend,
        planner: CuaPlanner,
        grounder: CuaGrounder | None = None,
        criticizer: CuaCriticizer | None = None,
        trajectory: CuaTrajectoryRecorder | None = None,
        max_actions: int = 25,
        max_retries: int = 3,
        model_name: str | None = None,
    ):
        self.backend = backend
        self.planner = planner
        self.grounder = grounder or CuaGrounder()
        self.criticizer = criticizer or CuaCriticizer()
        self.trajectory = trajectory or CuaTrajectoryRecorder()
        self.max_actions = max_actions
        self.max_retries = max_retries
        self.model_name = model_name

    async def run(self, task: str) -> dict[str, Any]:
        try:
            observation = self.backend.observe()
        except Exception as exc:
            return _run_result(False, False, error=f"Failed to observe screen: {exc}")

        session = CuaSession.start(
            task,
            observation,
            max_actions=self.max_actions,
            max_retries=self.max_retries,
        )

        while session.can_continue():
            try:
                model_payload = await self._next_action(task, observation, session)
                action = self._normalize_action(model_payload, observation)
            except ActionNormalizationError as exc:
                return _run_result(
                    True,
                    False,
                    result="Planner proposed an invalid action.",
                    error=str(exc),
                )
            except Exception as exc:
                return _run_result(False, False, error=f"Planner failed: {exc}")

            grounding = self.grounder.ground(action, observation)
            if not grounding.grounded:
                result = ActionResult(
                    executed=False,
                    message=grounding.reason or "Target could not be grounded.",
                    before=observation,
                    after=observation,
                    metrics={"needs_stronger_model": grounding.needs_stronger_model},
                )
                verdict = await self.criticizer.review(
                    task=task,
                    action=action,
                    result=result,
                    session=session,
                    needs_stronger_model=grounding.needs_stronger_model,
                    grounding_confidence=grounding.target.confidence if grounding.target else None,
                )
                session.record_action_result(action, result, critic=verdict)
                self.trajectory.record(
                    session=session,
                    action=action,
                    result=result,
                    verdict=verdict,
                    grounding=grounding,
                    model_name=self.model_name,
                )
                return _verdict_result(verdict, result)

            executable_action = grounding.action
            result = self._execute_action(executable_action, observation)
            unexpected_window = unexpected_window_change_warning(executable_action, result) is not None
            if unexpected_window:
                result = replace(
                    result,
                    metrics={
                        **dict(result.metrics or {}),
                        "unexpected_window_change": True,
                    },
                )
            verdict = await self.criticizer.review(
                task=task,
                action=executable_action,
                result=result,
                session=session,
                model_claimed_complete=executable_action.action_type == ActionType.COMPLETE,
                grounding_confidence=grounding.target.confidence if grounding.target else None,
                needs_stronger_model=grounding.needs_stronger_model,
            )
            session.record_action_result(executable_action, result, critic=verdict)
            self.trajectory.record(
                session=session,
                action=executable_action,
                result=result,
                verdict=verdict,
                grounding=grounding,
                model_name=self.model_name,
            )

            if verdict.complete:
                return _verdict_result(verdict, result)
            if executable_action.action_type == ActionType.COMPLETE:
                return _verdict_result(verdict, result)
            if not verdict.should_continue:
                return _verdict_result(verdict, result)
            if result.after is not None:
                observation = result.after
            else:
                try:
                    observation = self.backend.observe()
                except Exception as exc:
                    observe_verdict = CriticVerdict(
                        complete=False,
                        should_continue=False,
                        confidence=0.3,
                        reason=f"Failed to observe after action: {exc}",
                        next_hint="Re-establish screen observation before continuing.",
                    )
                    return _run_result(
                        True,
                        False,
                        result=observe_verdict.reason,
                        error=str(exc),
                        critic=_critic_dict(observe_verdict),
                    )
            session.record_observation(observation)

        verdict = CriticVerdict(
            complete=False,
            should_continue=False,
            confidence=0.4,
            reason=(
                "CUA action budget exhausted."
                if session.action_count >= session.max_actions
                else "CUA retry budget exhausted."
            ),
        )
        return _run_result(
            True,
            False,
            result=verdict.reason,
            critic=_critic_dict(verdict),
        )

    async def _next_action(
        self,
        task: str,
        observation: ScreenObservation,
        session: CuaSession,
    ) -> ComputerAction | dict[str, Any] | object:
        payload = self.planner.next_action(task, observation, session)
        if inspect.isawaitable(payload):
            return await payload
        return payload

    def _normalize_action(self, payload: ComputerAction | dict[str, Any] | object, observation: ScreenObservation) -> ComputerAction:
        if isinstance(payload, ComputerAction):
            return payload
        return normalize_action_payload(
            payload,
            active_window=observation.active_window_title,
        )

    def _execute_action(self, action: ComputerAction, observation: ScreenObservation) -> ActionResult:
        try:
            return self.backend.execute(action)
        except Exception as exc:
            return ActionResult(
                executed=False,
                message=str(exc),
                before=observation,
                after=observation,
            )


def _verdict_result(verdict: CriticVerdict, result: ActionResult) -> dict[str, Any]:
    if verdict.complete:
        return _run_result(
            True,
            True,
            result=verdict.reason or result.message,
            critic=_critic_dict(verdict),
        )
    return _run_result(
        True,
        False,
        result=verdict.reason or result.message,
        error=None if result.executed else result.message,
        critic=_critic_dict(verdict),
    )


def _run_result(
    success: bool,
    complete: bool,
    *,
    result: str | None = None,
    error: str | None = None,
    critic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "complete": complete,
        "result": result,
        "error": error,
        "critic": critic,
    }


def _critic_dict(verdict: CriticVerdict) -> dict[str, Any]:
    return asdict(verdict)
