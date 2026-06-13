"""
Deterministic quality gates for model-emitted orchestration plans.

These checks keep the router from laundering vague or redundant work into a
syntactically valid plan.
"""

from __future__ import annotations

from models.orchestrator_contracts import OrchestrationPlan, OrchestratorTask
from models.routing_payload_parser import copy_route_payload, route_payload_work_text


def validate_plan_quality(plan: OrchestrationPlan) -> None:
    """Reject technically valid but strategically poor multi-agent plans."""
    if "payload" not in plan.metadata or len(plan.tasks) == 1:
        return

    if not 2 <= len(plan.tasks) <= 4:
        raise ValueError("Orchestration plan payloads must contain 2 to 4 tasks.")

    seen_work: set[tuple[str, str]] = set()
    for task in plan.tasks:
        work = _task_work_text(task)
        if task.agent != "direct" and not work:
            raise ValueError(f"Plan task {task.id!r} must contain non-empty task work.")
        signature = (task.agent, work.lower())
        if work and signature in seen_work:
            raise ValueError(f"Duplicate plan work for agent {task.agent!r}: {work}")
        seen_work.add(signature)


def _task_work_text(task: OrchestratorTask) -> str:
    if task.task:
        return task.task.strip()
    if task.query:
        return task.query.strip()
    if task.route:
        return route_payload_work_text(
            copy_route_payload(task.route, error_source="orchestrator quality route")
        )
    return ""
