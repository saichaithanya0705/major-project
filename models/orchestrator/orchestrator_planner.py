"""
Normalize router payloads into orchestration plans.

The current router still emits one legacy route at a time.  This module adds a
pure parser for future multi-task router payloads without coupling planning to
agent execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from models.orchestrator_adapters import plan_from_route, route_to_orchestrator_task
from models.orchestrator_contracts import OrchestrationPlan, OrchestratorTask, ResourceLock
from models.orchestrator_quality import validate_plan_quality
from models.routing_payload_parser import (
    PlanDecisionPayload,
    PlanTaskPayload,
    RoutePayload,
    RoutingResult,
    copy_plan_task_payload,
    copy_route_payload,
)


def normalize_orchestration_plan_payload(
    request: str,
    payload: RoutingResult,
    *,
    default_max_parallel: int = 2,
) -> OrchestrationPlan:
    """Return an orchestration plan for a legacy route or a multi-task payload."""
    payload_dict: RoutePayload | PlanDecisionPayload = dict(payload)
    if "tasks" not in payload_dict:
        normalized_route = copy_route_payload(payload_dict, error_source="plan payload route")
        single_task_plan = plan_from_route(request, normalized_route, max_parallel=1)
        return replace(
            single_task_plan,
            metadata={**single_task_plan.metadata, "payload": normalized_route},
        )

    raw_tasks = payload_dict.get("tasks")
    if not isinstance(raw_tasks, Sequence) or isinstance(raw_tasks, (str, bytes)) or not raw_tasks:
        raise ValueError("Plan payload tasks must contain at least one task.")

    copied_tasks = tuple(
        copy_plan_task_payload(
            _mapping_task(raw_task, index=index),
            error_source=f"plan task #{index}",
        )
        for index, raw_task in enumerate(raw_tasks, start=1)
    )
    tasks = tuple(_task_from_payload(copied_task, index=index) for index, copied_task in enumerate(copied_tasks, start=1))
    metadata_payload = dict(payload_dict)
    metadata_payload["tasks"] = [dict(task_payload) for task_payload in copied_tasks]
    plan = OrchestrationPlan(
        request=request,
        tasks=tasks,
        max_parallel=_positive_int(payload_dict.get("max_parallel"), default_max_parallel, "max_parallel"),
        metadata={"payload": metadata_payload},
    )
    validate_plan_quality(plan)
    return plan


def _mapping_task(raw_task: object, *, index: int) -> Mapping[str, object]:
    if not isinstance(raw_task, Mapping):
        raise ValueError(f"Plan task #{index} must be an object.")
    return raw_task


def _task_from_payload(raw_task: PlanTaskPayload, *, index: int) -> OrchestratorTask:
    route: PlanTaskPayload = dict(raw_task)
    task = route_to_orchestrator_task(route, index=index, depends_on=_depends_on(route.get("depends_on")))
    task_id = str(route.get("id") or task.id).strip()
    metadata = {
        **task.metadata,
        "planner_index": index,
    }
    return replace(
        task,
        id=task_id,
        resources=_resources(route.get("resources"), task.resources),
        max_attempts=_positive_int(route.get("max_attempts"), task.max_attempts, "max_attempts"),
        metadata=metadata,
    )


def _depends_on(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        cleaned = value.strip()
        return (cleaned,) if cleaned else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError("Plan task depends_on must be a string or a list of strings.")


def _resources(
    value: object,
    default: tuple[ResourceLock, ...],
) -> tuple[ResourceLock, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        return (ResourceLock(cleaned),) if cleaned else default
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        resources = tuple(ResourceLock(str(item).strip()) for item in value if str(item).strip())
        return resources or default
    raise ValueError("Plan task resources must be a string or a list of resource lock names.")


def _positive_int(value: object, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be a positive integer.")
    return parsed
