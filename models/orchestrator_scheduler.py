"""
Deterministic scheduler helpers for multi-agent orchestration plans.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from models.orchestrator_contracts import (
    AgentStepOutcome,
    OrchestrationPlan,
    OrchestratorTask,
    ResourceLock,
    TaskStatus,
)

TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.SKIPPED,
    }
)
FAILED_DEPENDENCY_STATUSES = frozenset({TaskStatus.FAILED, TaskStatus.SKIPPED})


def ready_tasks(plan: OrchestrationPlan) -> tuple[OrchestratorTask, ...]:
    """Return pending tasks whose dependencies have completed."""
    tasks_by_id = _tasks_by_id(plan)
    return tuple(
        task
        for task in plan.tasks
        if task.status is TaskStatus.PENDING
        and all(tasks_by_id[dependency].status is TaskStatus.COMPLETED for dependency in task.depends_on)
    )


def blocked_by_failed_dependencies(plan: OrchestrationPlan) -> tuple[OrchestratorTask, ...]:
    """Return pending tasks that can never run because a dependency failed or skipped."""
    tasks_by_id = _tasks_by_id(plan)
    return tuple(
        task
        for task in plan.tasks
        if task.status is TaskStatus.PENDING
        and any(tasks_by_id[dependency].status in FAILED_DEPENDENCY_STATUSES for dependency in task.depends_on)
    )


def mark_failed_dependency_skips(plan: OrchestrationPlan) -> OrchestrationPlan:
    """Return a plan with tasks blocked by failed dependencies marked skipped."""
    tasks_by_id = _tasks_by_id(plan)
    blocked_ids = {task.id for task in blocked_by_failed_dependencies(plan)}
    if not blocked_ids:
        return plan

    updated_tasks: list[OrchestratorTask] = []
    for task in plan.tasks:
        if task.id not in blocked_ids:
            updated_tasks.append(task)
            continue

        failed_dependencies = tuple(
            dependency
            for dependency in task.depends_on
            if tasks_by_id[dependency].status in FAILED_DEPENDENCY_STATUSES
        )
        message = (
            f"Task skipped because dependency failure prevented execution: "
            f"{', '.join(failed_dependencies)}"
        )
        metadata = {
            **task.metadata,
            "skip_reason": "dependency_failed",
            "failed_dependencies": failed_dependencies,
            "message": message,
        }
        updated_tasks.append(replace(task, status=TaskStatus.SKIPPED, metadata=metadata))

    return replace(plan, tasks=tuple(updated_tasks))


def select_runnable_batch(
    plan: OrchestrationPlan,
    max_parallel: int | None = None,
) -> tuple[OrchestratorTask, ...]:
    """Select ready tasks in stable order without resource conflicts."""
    limit = plan.max_parallel if max_parallel is None else max_parallel
    if limit < 1:
        raise ValueError("max_parallel must be at least 1.")

    selected: list[OrchestratorTask] = []
    held_resources: set[ResourceLock] = set()
    for task in ready_tasks(plan):
        if len(selected) >= limit:
            break
        task_resources = set(task.resources)
        if held_resources.intersection(task_resources):
            continue
        selected.append(task)
        held_resources.update(task_resources)
    return tuple(selected)


def update_task_status(
    plan: OrchestrationPlan,
    task_id: str,
    status: TaskStatus,
    metadata: dict[str, object] | None = None,
    attempts_delta: int = 0,
) -> OrchestrationPlan:
    """Return a plan with one task status, attempts, and metadata updated."""
    status = TaskStatus(status)
    found = False
    updated_tasks: list[OrchestratorTask] = []
    for task in plan.tasks:
        if task.id != task_id:
            updated_tasks.append(task)
            continue

        found = True
        merged_metadata = dict(task.metadata)
        if metadata:
            merged_metadata.update(metadata)
        updated_tasks.append(
            replace(
                task,
                status=status,
                attempts=task.attempts + attempts_delta,
                metadata=merged_metadata,
            )
        )

    if not found:
        raise KeyError(f"Task id not found: {task_id}")
    return replace(plan, tasks=tuple(updated_tasks))


def has_resource_conflict(task_a: OrchestratorTask, task_b: OrchestratorTask) -> bool:
    """Return True when tasks require at least one common resource lock."""
    return bool(set(task_a.resources).intersection(task_b.resources))


def is_terminal(plan: OrchestrationPlan) -> bool:
    """Return True when every task has reached a terminal status."""
    return all(task.status in TERMINAL_STATUSES for task in plan.tasks)


def successful_outcomes(outcomes: Iterable[AgentStepOutcome]) -> tuple[AgentStepOutcome, ...]:
    """Return outcomes that succeeded and reported the task complete."""
    return tuple(outcome for outcome in outcomes if outcome.success and outcome.complete)


def _tasks_by_id(plan: OrchestrationPlan) -> dict[str, OrchestratorTask]:
    return {task.id: task for task in plan.tasks}
