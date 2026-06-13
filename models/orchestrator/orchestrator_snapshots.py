"""
Serializable snapshots for orchestration logs and UI surfaces.
"""

from __future__ import annotations

from typing import Any

from models.orchestrator_contracts import (
    OrchestrationPlan,
    orchestration_trace_event_to_dict,
    task_artifact_to_dict,
)


def orchestration_plan_snapshot(plan: OrchestrationPlan) -> dict[str, Any]:
    return {
        "request": plan.request,
        "max_parallel": plan.max_parallel,
        "tasks": [
            {
                "id": task.id,
                "agent": task.agent,
                "task": task.task or task.query,
                "status": task.status.value,
                "depends_on": list(task.depends_on),
                "resources": [resource.value for resource in task.resources],
            }
            for task in plan.tasks
        ],
    }


def orchestration_execution_metadata(execution: Any) -> dict[str, Any]:
    return {
        "orchestration_plan": orchestration_plan_snapshot(execution.plan),
        "orchestration_trace": [
            orchestration_trace_event_to_dict(event)
            for event in getattr(execution, "trace_events", ())
        ],
        "orchestration_artifacts": [
            task_artifact_to_dict(artifact)
            for artifact in getattr(execution, "artifacts", ())
        ],
    }
