"""Delegated-step execution runtime shared by the rapid router loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol

from models.orchestrator_adapters import apply_outcome_to_plan, outcome_from_step_result
from models.orchestrator_contracts import OrchestrationPlan, OrchestratorTask
from models.rapid_completion_recovery_policy import should_finish_after_successful_agent_step
from models.rapid_orchestrator_contracts import RapidAgentStepResult, RapidRouteResult, RapidToolMap
from models.routing_payload_parser import ScreenContextPayload
from models.screen_context_execution_runtime import ScreenContextStepRequest, execute_screen_context_step


DelegatedStepDisposition = Literal["continue", "failed", "fast_finish"]


@dataclass(frozen=True, slots=True)
class DelegatedStepExecutionResult:
    disposition: DelegatedStepDisposition
    step_result: RapidAgentStepResult
    orchestration_plan: OrchestrationPlan
    latest_screen_context: Optional[ScreenContextPayload]


class RapidDelegatedStepDeps(Protocol):
    async def run_routed_agent_step(
        self,
        *,
        model: Any,
        routing_result: RapidRouteResult,
        jarvis_model: str,
        request_id: str,
        prepare_vision_screenshot: Any = None,
    ) -> RapidAgentStepResult: ...

    async def prepare_vision_screenshot(self, *, keep_chat_hidden: bool = False) -> Any: ...

    def record_step_context(self, step_result: RapidAgentStepResult) -> None: ...

    def append_rapid_history(self, role: str, text: str, source: str) -> None: ...

    def finalize_direct_response_text(
        self,
        *,
        user_prompt: str,
        chain_steps: list[RapidAgentStepResult],
        text: object,
    ) -> str: ...

    def clean_text(self, value: object, fallback: str, max_len: int | None) -> str: ...

    def routing_task_text(self, route: RapidRouteResult) -> str: ...

    def screen_context_message(self, payload: ScreenContextPayload) -> str: ...

    def log_assistant_event(self, event_type: str, **kwargs: Any) -> None: ...

    @property
    def router_tool_map(self) -> RapidToolMap: ...


async def execute_delegated_step(
    *,
    model: Any,
    user_prompt: str,
    routing_result: RapidRouteResult,
    orchestration_plan: OrchestrationPlan,
    orchestration_task: OrchestratorTask,
    chain_steps: list[RapidAgentStepResult],
    jarvis_model: str,
    request_id: str,
    deps: RapidDelegatedStepDeps,
) -> DelegatedStepExecutionResult:
    step_result: RapidAgentStepResult
    latest_screen_context: Optional[ScreenContextPayload] = None
    screen_context_request: ScreenContextStepRequest | None = None

    if routing_result.get("agent") == "screen_context":
        screen_context_request = ScreenContextStepRequest.from_route(
            routing_result,
            user_prompt=user_prompt,
        )
        screen_context_result = await execute_screen_context_step(
            model=model,
            step_request=screen_context_request,
            request_id=request_id,
            deps=deps,
        )
        step_result = screen_context_result.step_result
        latest_screen_context = screen_context_result.latest_screen_context
    else:
        step_result = await deps.run_routed_agent_step(
            model=model,
            routing_result=routing_result,
            jarvis_model=jarvis_model,
            request_id=request_id,
            prepare_vision_screenshot=deps.prepare_vision_screenshot,
        )

    chain_steps.append(step_result)
    updated_plan = apply_outcome_to_plan(
        orchestration_plan,
        outcome_from_step_result(orchestration_task, step_result),
    )

    if routing_result.get("agent") != "screen_context":
        deps.record_step_context(step_result)

    deps.append_rapid_history(
        "assistant",
        step_result.get("message", ""),
        step_result.get("source", "rapid"),
    )

    if routing_result.get("agent") == "screen_context":
        if step_result.get("success"):
            return DelegatedStepExecutionResult(
                disposition="continue",
                step_result=step_result,
                orchestration_plan=updated_plan,
                latest_screen_context=latest_screen_context,
            )

        failure_msg = (
            "Stopping chained execution because screen context failed: "
            f"{step_result.get('message')}"
        )
        _send_direct_response(
            deps,
            deps.clean_text(failure_msg, "Task failed.", 420),
        )
        deps.append_rapid_history("assistant", failure_msg, "rapid")
        deps.log_assistant_event(
            "request_failed",
            request_id=request_id,
            agent="screen_context",
            task=deps.clean_text(screen_context_request.task if screen_context_request else user_prompt, "", 420),
            message=failure_msg,
            error=step_result.get("message", ""),
            success=False,
        )
        return DelegatedStepExecutionResult(
            disposition="failed",
            step_result=step_result,
            orchestration_plan=updated_plan,
            latest_screen_context=latest_screen_context,
        )

    if should_finish_after_successful_agent_step(
        user_prompt=user_prompt,
        routing_result=routing_result,
        step_result=step_result,
        chain_steps=chain_steps,
        routing_task_text=deps.routing_task_text,
    ):
        direct_text = deps.finalize_direct_response_text(
            user_prompt=user_prompt,
            chain_steps=chain_steps,
            text=step_result.get("message"),
        )
        _send_direct_response(deps, direct_text)
        deps.append_rapid_history("assistant", direct_text, "rapid")
        deps.log_assistant_event(
            "request_completed",
            request_id=request_id,
            agent=str(step_result.get("agent") or routing_result.get("agent") or ""),
            task=deps.clean_text(user_prompt, "", 420),
            message=direct_text,
            success=True,
            metadata={
                "delegated_steps": len(chain_steps),
                "fast_finish": True,
            },
        )
        return DelegatedStepExecutionResult(
            disposition="fast_finish",
            step_result=step_result,
            orchestration_plan=updated_plan,
            latest_screen_context=latest_screen_context,
        )

    if step_result.get("success"):
        return DelegatedStepExecutionResult(
            disposition="continue",
            step_result=step_result,
            orchestration_plan=updated_plan,
            latest_screen_context=latest_screen_context,
        )

    failure_msg = (
        f"Stopping chained execution because {step_result.get('agent')} failed: "
        f"{step_result.get('message')}"
    )
    _send_direct_response(
        deps,
        deps.clean_text(failure_msg, "Task failed.", 420),
    )
    deps.append_rapid_history("assistant", failure_msg, "rapid")
    deps.log_assistant_event(
        "request_failed",
        request_id=request_id,
        agent=str(step_result.get("agent") or ""),
        task=deps.clean_text(step_result.get("task"), "", 420),
        message=failure_msg,
        error=step_result.get("message", ""),
        success=False,
    )
    return DelegatedStepExecutionResult(
        disposition="failed",
        step_result=step_result,
        orchestration_plan=updated_plan,
        latest_screen_context=latest_screen_context,
    )


def _send_direct_response(
    deps: RapidDelegatedStepDeps,
    text: str,
) -> None:
    tool = deps.router_tool_map.get("direct_response")
    if tool:
        tool(text=text, source="rapid_response")


__all__ = [
    "DelegatedStepDisposition",
    "DelegatedStepExecutionResult",
    "RapidDelegatedStepDeps",
    "execute_delegated_step",
]
