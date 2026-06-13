"""
Pure adapters between legacy route dictionaries and orchestration contracts.

These helpers intentionally avoid importing live agents or runtime execution
code.  They only normalize data shapes for future orchestrator integration.
"""

from __future__ import annotations

import re
from typing import Any, cast

from models.orchestrator_contracts import (
    AgentStepOutcome,
    KNOWN_ORCHESTRATOR_AGENTS,
    OrchestrationPlan,
    OrchestratorAgent,
    OrchestratorTask,
    TaskStatus,
    agent_step_outcome_to_dict,
    resources_for_agent,
)
from models.orchestrator_scheduler import update_task_status
from models.output_file_artifacts import (
    extract_output_file_path_from_tool_calls,
    extract_path_from_text,
)
from models.rapid_orchestrator_contracts import RapidAgentStepResult
from models.routing_payload_parser import (
    RoutePayload,
    copy_route_payload,
    normalize_direct_response_route_payload,
)


def task_id_for_route(route: RoutePayload, index: int = 1) -> str:
    """Return a stable, readable task id for a legacy route dictionary."""
    agent = _agent_for_route(route)
    slug = re.sub(r"[^a-z0-9]+", "-", agent.lower()).strip("-") or "unknown"
    return f"step-{index}-{slug}"


def route_to_orchestrator_task(
    route: RoutePayload,
    *,
    index: int = 1,
    depends_on: tuple[str, ...] = (),
) -> OrchestratorTask:
    """Convert a legacy router dictionary to an orchestrator task."""
    normalized_route = _copy_route_payload(route)
    agent = _agent_for_route(normalized_route)
    return OrchestratorTask(
        id=task_id_for_route(normalized_route, index),
        agent=agent,
        task=_text(normalized_route.get("task")),
        query=_text(normalized_route.get("query")),
        route=normalized_route,
        depends_on=depends_on,
        resources=resources_for_agent(agent),
    )


def plan_from_route(
    request: str,
    route: RoutePayload,
    *,
    max_parallel: int = 1,
) -> OrchestrationPlan:
    """Create a one-task orchestration plan from the current router output."""
    normalized_route = _copy_route_payload(route)
    return OrchestrationPlan(
        request=request,
        tasks=(route_to_orchestrator_task(normalized_route),),
        max_parallel=max_parallel,
        metadata={"route": normalized_route},
    )


def route_from_task(task: OrchestratorTask) -> RoutePayload:
    """Convert an orchestrator task back to a legacy route dictionary."""
    if task.route:
        return _copy_route_payload(task.route)

    route: RoutePayload = {"agent": task.agent}
    if task.agent == "direct":
        if task.task:
            route["response_text"] = task.task
        return normalize_direct_response_route_payload(
            route,
            error_source="orchestrator task route",
        )

    if task.agent == "jarvis":
        query = task.query or task.task
        if query:
            route["query"] = query
        return route

    task_text = task.task or task.query
    if task_text:
        route["task"] = task_text
    return route


def outcome_from_step_result(
    task: OrchestratorTask,
    step_result: RapidAgentStepResult,
) -> AgentStepOutcome:
    """Normalize a delegated step result into an orchestrator outcome."""
    success = bool(step_result.get("success", True))
    complete = bool(step_result.get("complete", True))
    message = _result_message(step_result)
    source = _text(step_result.get("source")) or task.agent
    step_task = _text(step_result.get("task")) or task.task or task.query

    artifacts = _result_artifacts(step_result, message)
    metadata = _result_metadata(step_result, source=source, task=step_task)

    return AgentStepOutcome(
        task_id=task.id,
        agent=task.agent,
        success=success,
        complete=complete,
        message=message,
        artifacts=artifacts,
        metadata=metadata,
        needs_followup=bool(step_result.get("needs_followup", success and not complete)),
    )


def step_status_from_outcome(outcome: AgentStepOutcome) -> TaskStatus:
    """Map a normalized outcome to the scheduler task status."""
    if not outcome.success:
        return TaskStatus.FAILED
    if outcome.complete:
        return TaskStatus.COMPLETED
    return TaskStatus.PENDING


def apply_outcome_to_plan(
    plan: OrchestrationPlan,
    outcome: AgentStepOutcome,
) -> OrchestrationPlan:
    """Apply a normalized outcome to a plan using scheduler status semantics."""
    return update_task_status(
        plan,
        outcome.task_id,
        step_status_from_outcome(outcome),
        metadata={"last_outcome": agent_step_outcome_to_dict(outcome)},
        attempts_delta=1,
    )


def _agent_for_route(route: RoutePayload) -> OrchestratorAgent:
    agent = _text(route.get("agent")).lower()
    if agent not in KNOWN_ORCHESTRATOR_AGENTS:
        allowed = ", ".join(KNOWN_ORCHESTRATOR_AGENTS)
        raise ValueError(f"Unknown orchestrator agent {agent!r}; expected one of: {allowed}.")
    return cast(OrchestratorAgent, agent)


def _copy_route_payload(route: RoutePayload) -> RoutePayload:
    return copy_route_payload(route, error_source="route payload")


def _result_metadata(
    step_result: RapidAgentStepResult,
    *,
    source: str,
    task: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    result_metadata = step_result.get("metadata")
    if isinstance(result_metadata, dict):
        metadata.update(result_metadata)
    metadata.update(
        {
            "source": source,
            "task": task,
            "raw_step_result": dict(step_result),
        }
    )
    if "tool_calls" in step_result:
        metadata["tool_calls"] = step_result["tool_calls"]
    return metadata


def _result_message(step_result: RapidAgentStepResult) -> str:
    for key in ("message", "answer", "response_text", "text"):
        value = _text(step_result.get(key))
        if value:
            return value
    return ""


def _result_artifacts(
    step_result: RapidAgentStepResult,
    message: str,
) -> tuple[Any, ...] | dict[str, Any]:
    explicit_artifacts = step_result.get("artifacts")
    if isinstance(explicit_artifacts, dict):
        return dict(explicit_artifacts)
    if explicit_artifacts:
        return tuple(explicit_artifacts)

    artifacts: dict[str, Any] = {}
    if "sources" in step_result:
        artifacts["sources"] = step_result["sources"]

    output_path = _text(step_result.get("output_file_path"))
    if not output_path:
        output_path = extract_output_file_path_from_tool_calls(step_result.get("tool_calls"))
    if not output_path:
        output_path = extract_path_from_text(message)
    if output_path:
        artifacts["output_file_path"] = output_path

    return artifacts or ()

def _text(value: object) -> str:
    return str(value or "").strip()
