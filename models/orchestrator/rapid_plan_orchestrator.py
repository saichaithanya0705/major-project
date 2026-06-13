"""
Runtime bridge for executing router-emitted orchestration plans.

The rapid router loop owns provider calls and legacy chained routing.  This
module owns the separate plan-shaped payload path so plan execution does not
turn the router loop into a mixed-responsibility coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from models.orchestrator_adapters import route_from_task
from models.orchestrator_contracts import (
    AgentStepOutcome,
    OrchestratorTask,
    TaskExecutionContext,
    TaskStatus,
    task_execution_context_to_dict,
)
from models.orchestrator_executor import execute_plan
from models.orchestrator_planner import normalize_orchestration_plan_payload
from models.orchestrator_snapshots import orchestration_execution_metadata, orchestration_plan_snapshot
from models.rapid_orchestrator_contracts import RapidAgentStepResult, RapidModel, RapidPlanDeps
from models.routing_payload_parser import PlanDecisionPayload, RoutePayload, RoutingResult, ScreenContextPayload
from models.screen_context_execution_runtime import ScreenContextStepRequest, execute_screen_context_step


@dataclass(frozen=True, slots=True)
class RapidPlanExecutionResult:
    success: bool
    message: str
    chain_steps: tuple[RapidAgentStepResult, ...]
    latest_screen_context: Optional[ScreenContextPayload]
    agent: str = "orchestrator"
    task: str = ""
    error: str = ""
    planned_tasks: int = 0


def is_plan_payload(routing_result: RoutingResult) -> bool:
    tasks = routing_result.get("tasks")
    return isinstance(tasks, list | tuple)


async def execute_rapid_plan_payload(
    *,
    routing_result: PlanDecisionPayload | RoutingResult,
    user_prompt: str,
    model: RapidModel,
    jarvis_model: str,
    request_id: str,
    deps: RapidPlanDeps,
    step_index: int,
    latest_screen_context: Optional[ScreenContextPayload],
) -> RapidPlanExecutionResult:
    """Execute a plan-shaped router payload and emit the user-facing result."""
    try:
        orchestration_plan = normalize_orchestration_plan_payload(
            user_prompt,
            routing_result,
            default_max_parallel=2,
        )
    except Exception as exc:
        error_text = deps.clean_text(str(exc), "Invalid orchestration plan.", 420)
        router_error = f"Router failed: invalid orchestration plan: {error_text}"
        _send_direct_response(deps, router_error)
        deps.append_rapid_history("assistant", router_error, "rapid")
        deps.log_assistant_event(
            "request_failed",
            request_id=request_id,
            agent="orchestrator",
            task=deps.clean_text(user_prompt, "", 420),
            message=router_error,
            error=error_text,
            success=False,
            metadata={"step_index": step_index + 1},
        )
        return RapidPlanExecutionResult(
            success=False,
            message=router_error,
            chain_steps=(),
            latest_screen_context=latest_screen_context,
            error=error_text,
        )

    deps.log_assistant_event(
        "router_decision",
        request_id=request_id,
        agent="orchestrator",
        task=deps.clean_text(user_prompt, "", 420),
        metadata={
            "step_index": step_index + 1,
            "planned_tasks": len(orchestration_plan.tasks),
            "max_parallel": orchestration_plan.max_parallel,
            "orchestration_plan": orchestration_plan_snapshot(orchestration_plan),
        },
    )

    async def run_planned_task(
        task: OrchestratorTask,
        context: TaskExecutionContext,
    ) -> RapidAgentStepResult:
        nonlocal latest_screen_context
        planned_route = route_from_task(task)
        if context.dependency_outcomes or context.artifacts:
            planned_route["orchestrator_context"] = task_execution_context_to_dict(context)
        if planned_route.get("agent") == "direct":
            return _direct_step_result(task, planned_route, deps)
        if planned_route.get("agent") == "screen_context":
            step_request = ScreenContextStepRequest.from_route(
                planned_route,
                user_prompt=user_prompt,
            )
            screen_context_result = await execute_screen_context_step(
                model=model,
                step_request=step_request,
                request_id=request_id,
                deps=deps,
            )
            if screen_context_result.latest_screen_context is not None:
                latest_screen_context = screen_context_result.latest_screen_context
            return screen_context_result.step_result
        return await deps.run_routed_agent_step(
            model=model,
            routing_result=planned_route,
            jarvis_model=jarvis_model,
            request_id=request_id,
            prepare_vision_screenshot=deps.prepare_vision_screenshot,
        )

    execution = await execute_plan(orchestration_plan, run_planned_task)
    chain_steps: list[RapidAgentStepResult] = []
    for outcome in execution.outcomes:
        step_result = _step_result_from_outcome(outcome)
        chain_steps.append(step_result)
        if step_result.get("agent") not in {"direct", "screen_context"}:
            deps.record_step_context(step_result)
        deps.append_rapid_history(
            "assistant",
            step_result.get("message", ""),
            step_result.get("source", "rapid"),
        )

    failed_task = next(
        (
            task
            for task in execution.plan.tasks
            if task.status in {TaskStatus.FAILED, TaskStatus.SKIPPED}
        ),
        None,
    )
    if failed_task is not None:
        failed_message = _failed_task_message(failed_task, deps)
        failure_msg = (
            f"Stopping orchestrated execution because {failed_task.agent} failed: "
            f"{failed_message or 'Task failed.'}"
        )
        _send_direct_response(deps, deps.clean_text(failure_msg, "Task failed.", 420))
        deps.append_rapid_history("assistant", failure_msg, "rapid")
        deps.log_assistant_event(
            "request_failed",
            request_id=request_id,
            agent=failed_task.agent,
            task=deps.clean_text(failed_task.task or failed_task.query, "", 420),
            message=failure_msg,
            error=failed_message,
            success=False,
            metadata={
                "orchestrated_plan": True,
                **orchestration_execution_metadata(execution),
            },
        )
        return RapidPlanExecutionResult(
            success=False,
            message=failure_msg,
            chain_steps=tuple(chain_steps),
            latest_screen_context=latest_screen_context,
            agent=failed_task.agent,
            task=failed_task.task or failed_task.query,
            error=failed_message,
            planned_tasks=len(execution.plan.tasks),
        )

    final_outcome = next(
        (outcome for outcome in reversed(execution.outcomes) if outcome.success and outcome.complete),
        None,
    )
    direct_text = deps.finalize_direct_response_text(
        user_prompt=user_prompt,
        chain_steps=chain_steps,
        text=final_outcome.message if final_outcome is not None else "Task completed.",
    )
    _send_direct_response(deps, direct_text)
    deps.append_rapid_history("assistant", direct_text, "rapid")
    deps.log_assistant_event(
        "request_completed",
        request_id=request_id,
        agent="orchestrator",
        task=deps.clean_text(user_prompt, "", 420),
        message=direct_text,
        success=True,
        metadata={
            "delegated_steps": len(chain_steps),
            "orchestrated_plan": True,
            "planned_tasks": len(execution.plan.tasks),
            **orchestration_execution_metadata(execution),
        },
    )
    return RapidPlanExecutionResult(
        success=True,
        message=direct_text,
        chain_steps=tuple(chain_steps),
        latest_screen_context=latest_screen_context,
        planned_tasks=len(execution.plan.tasks),
    )


def _direct_step_result(
    task: OrchestratorTask,
    planned_route: RoutePayload,
    deps: RapidPlanDeps,
) -> RapidAgentStepResult:
    direct_text = planned_route.get("response_text") or task.task
    return {
        "agent": "direct",
        "task": task.task,
        "success": True,
        "complete": True,
        "message": deps.clean_text(direct_text, "Task completed.", None),
        "source": "rapid",
    }

def _step_result_from_outcome(outcome: AgentStepOutcome) -> RapidAgentStepResult:
    raw_step_result = outcome.metadata.get("raw_step_result")
    if isinstance(raw_step_result, dict):
        step_result = dict(raw_step_result)
    else:
        step_result = {
            "agent": outcome.agent,
            "task": str(outcome.metadata.get("task") or ""),
            "success": outcome.success,
            "message": outcome.message,
            "source": str(outcome.metadata.get("source") or "rapid"),
        }
    step_result.setdefault("agent", outcome.agent)
    step_result.setdefault("success", outcome.success)
    step_result.setdefault("message", outcome.message)
    step_result.setdefault("source", str(outcome.metadata.get("source") or "rapid"))
    step_result["complete"] = outcome.complete
    return step_result


def _failed_task_message(task: OrchestratorTask, deps: Any) -> str:
    last_outcome = task.metadata.get("last_outcome")
    if isinstance(last_outcome, dict):
        message = deps.clean_text(last_outcome.get("message"), "", 420)
        if message:
            return message
    return deps.clean_text(task.metadata.get("message"), "", 420)


def _send_direct_response(deps: Any, text: str) -> None:
    tool = deps.router_tool_map.get("direct_response")
    if tool:
        tool(text=text, source="rapid_response")
