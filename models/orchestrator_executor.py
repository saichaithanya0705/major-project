"""
Pure async execution loop for orchestration plans.

The executor coordinates already-built OrchestrationPlan objects.  It does not
know how to launch agents; callers provide an async runner for each task.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from models.orchestrator_adapters import apply_outcome_to_plan, outcome_from_step_result
from models.orchestrator_artifacts import artifacts_from_outcome, context_for_task
from models.orchestrator_contracts import (
    AgentStepOutcome,
    OrchestrationPlan,
    OrchestratorTask,
    OrchestrationTraceEvent,
    OrchestrationTraceEventType,
    TaskArtifact,
    TaskExecutionContext,
    TaskStatus,
    agent_step_outcome_to_dict,
)
from models.orchestrator_resources import ResourceCoordinator
from models.orchestrator_scheduler import (
    TERMINAL_STATUSES,
    is_terminal,
    mark_failed_dependency_skips,
    ready_tasks,
    select_runnable_batch,
    update_task_status,
)

TaskRunner = Callable[[OrchestratorTask, TaskExecutionContext], Awaitable[dict[str, Any] | AgentStepOutcome]]


@dataclass(frozen=True, slots=True)
class OrchestrationExecution:
    plan: OrchestrationPlan
    outcomes: tuple[AgentStepOutcome, ...]
    artifacts: tuple[TaskArtifact, ...] = ()
    trace_events: tuple[OrchestrationTraceEvent, ...] = ()


async def execute_plan(
    plan: OrchestrationPlan,
    runner: TaskRunner,
    *,
    resource_coordinator: ResourceCoordinator | None = None,
) -> OrchestrationExecution:
    """Execute a plan with the provided async task runner."""
    current = plan
    outcomes: list[AgentStepOutcome] = []
    outcomes_by_task: dict[str, AgentStepOutcome] = {}
    artifacts: list[TaskArtifact] = []
    trace_events: list[OrchestrationTraceEvent] = []

    def record_event(
        event_type: OrchestrationTraceEventType,
        task: OrchestratorTask | None = None,
        *,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        trace_events.append(
            OrchestrationTraceEvent(
                sequence=len(trace_events) + 1,
                event_type=event_type,
                task_id=task.id if task is not None else "",
                agent=task.agent if task is not None else "",
                message=message,
                metadata=metadata or {},
            )
        )

    for task in current.tasks:
        record_event(
            OrchestrationTraceEventType.PLANNED,
            task,
            message=task.task or task.query,
            metadata={
                "depends_on": task.depends_on,
                "resources": tuple(resource.value for resource in task.resources),
            },
        )

    while True:
        current, exhausted_outcomes = _fail_exhausted_pending_tasks(current)
        outcomes.extend(exhausted_outcomes)
        _record_outcomes(exhausted_outcomes, outcomes_by_task, artifacts)
        for outcome in exhausted_outcomes:
            record_event(OrchestrationTraceEventType.FAILED, _task_by_id(current, outcome.task_id), message=outcome.message)

        current, skipped_outcomes = _mark_and_record_dependency_skips(current)
        outcomes.extend(skipped_outcomes)
        _record_outcomes(skipped_outcomes, outcomes_by_task, artifacts)
        for outcome in skipped_outcomes:
            record_event(OrchestrationTraceEventType.SKIPPED, _task_by_id(current, outcome.task_id), message=outcome.message)

        if is_terminal(current):
            return OrchestrationExecution(
                plan=current,
                outcomes=tuple(outcomes),
                artifacts=tuple(artifacts),
                trace_events=tuple(trace_events),
            )

        ready_batch = ready_tasks(current)
        batch = select_runnable_batch(current)
        if not batch:
            current, stalled_outcomes = _fail_stalled_tasks(current)
            outcomes.extend(stalled_outcomes)
            _record_outcomes(stalled_outcomes, outcomes_by_task, artifacts)
            for outcome in stalled_outcomes:
                record_event(OrchestrationTraceEventType.FAILED, _task_by_id(current, outcome.task_id), message=outcome.message)
            return OrchestrationExecution(
                plan=current,
                outcomes=tuple(outcomes),
                artifacts=tuple(artifacts),
                trace_events=tuple(trace_events),
            )

        selected_ids = {task.id for task in batch}
        for task in ready_batch:
            if task.id not in selected_ids:
                record_event(
                    OrchestrationTraceEventType.WAITING,
                    task,
                    message="Task is waiting for a resource or parallelism slot.",
                    metadata={"selected_batch": tuple(selected_ids)},
                )

        current, running_batch = _mark_batch_running(current, batch)
        for task in running_batch:
            record_event(OrchestrationTraceEventType.RUNNING, task, message=task.task or task.query)
        contexts = {
            task.id: context_for_task(
                current,
                task,
                outcomes_by_task=outcomes_by_task,
                artifacts=artifacts,
            )
            for task in running_batch
        }
        batch_outcomes = await asyncio.gather(
            *(_run_task(task, contexts[task.id], runner, resource_coordinator) for task in running_batch),
        )
        for outcome in batch_outcomes:
            outcomes.append(outcome)
            _record_outcomes((outcome,), outcomes_by_task, artifacts)
            current = apply_outcome_to_plan(current, outcome)
            record_event(
                _event_type_from_outcome(outcome),
                _task_by_id(current, outcome.task_id),
                message=outcome.message,
            )


def _mark_batch_running(
    plan: OrchestrationPlan,
    batch: tuple[OrchestratorTask, ...],
) -> tuple[OrchestrationPlan, tuple[OrchestratorTask, ...]]:
    current = plan
    running_tasks: list[OrchestratorTask] = []
    for task in batch:
        current = update_task_status(current, task.id, TaskStatus.RUNNING)
        running_tasks.append(_task_by_id(current, task.id))
    return current, tuple(running_tasks)


async def _run_task(
    task: OrchestratorTask,
    context: TaskExecutionContext,
    runner: TaskRunner,
    resource_coordinator: ResourceCoordinator | None,
) -> AgentStepOutcome:
    try:
        if resource_coordinator is None:
            result = await runner(task, context)
        else:
            async with await resource_coordinator.acquire(task.resources):
                result = await runner(task, context)
    except Exception as exc:  # noqa: BLE001 - runner failures are execution data.
        return _exception_outcome(task, exc)

    if isinstance(result, AgentStepOutcome):
        return _validate_existing_outcome(task, result)
    if not isinstance(result, dict):
        return AgentStepOutcome(
            task_id=task.id,
            agent=task.agent,
            success=False,
            complete=False,
            message=f"Task runner returned unsupported result type: {type(result).__name__}",
            metadata={"result_type": type(result).__name__},
        )
    return outcome_from_step_result(task, result)


def _event_type_from_outcome(outcome: AgentStepOutcome) -> OrchestrationTraceEventType:
    if not outcome.success:
        return OrchestrationTraceEventType.FAILED
    if outcome.complete:
        return OrchestrationTraceEventType.COMPLETED
    return OrchestrationTraceEventType.RETRIED


def _record_outcomes(
    outcomes: tuple[AgentStepOutcome, ...],
    outcomes_by_task: dict[str, AgentStepOutcome],
    artifacts: list[TaskArtifact],
) -> None:
    for outcome in outcomes:
        outcomes_by_task[outcome.task_id] = outcome
        artifacts.extend(artifacts_from_outcome(outcome))


def _validate_existing_outcome(
    task: OrchestratorTask,
    outcome: AgentStepOutcome,
) -> AgentStepOutcome:
    if outcome.task_id == task.id and outcome.agent == task.agent:
        return outcome

    return AgentStepOutcome(
        task_id=task.id,
        agent=task.agent,
        success=False,
        complete=False,
        message=(
            "Task runner returned an outcome for a different task "
            f"({outcome.task_id}/{outcome.agent})."
        ),
        metadata={
            "failure_reason": "mismatched_outcome",
            "expected_task_id": task.id,
            "returned_task_id": outcome.task_id,
            "expected_agent": task.agent,
            "returned_agent": outcome.agent,
        },
    )


def _fail_exhausted_pending_tasks(
    plan: OrchestrationPlan,
) -> tuple[OrchestrationPlan, tuple[AgentStepOutcome, ...]]:
    current = plan
    outcomes: list[AgentStepOutcome] = []
    for task in plan.tasks:
        if task.status is not TaskStatus.PENDING:
            continue
        if task.attempts < task.max_attempts:
            continue
        outcome = AgentStepOutcome(
            task_id=task.id,
            agent=task.agent,
            success=False,
            complete=False,
            message=f"Task failed because max_attempts was reached: {task.max_attempts}.",
            metadata={
                "failure_reason": "max_attempts_reached",
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
            },
        )
        current = _apply_terminal_outcome(current, outcome, TaskStatus.FAILED)
        outcomes.append(outcome)
    return current, tuple(outcomes)


def _mark_and_record_dependency_skips(
    plan: OrchestrationPlan,
) -> tuple[OrchestrationPlan, tuple[AgentStepOutcome, ...]]:
    before = {task.id: task for task in plan.tasks}
    updated = mark_failed_dependency_skips(plan)
    outcomes: list[AgentStepOutcome] = []
    for task in updated.tasks:
        previous = before[task.id]
        if previous.status is TaskStatus.PENDING and task.status is TaskStatus.SKIPPED:
            outcomes.append(
                AgentStepOutcome(
                    task_id=task.id,
                    agent=task.agent,
                    success=False,
                    complete=False,
                    message=str(task.metadata.get("message", "Task skipped.")),
                    metadata={
                        "skip_reason": task.metadata.get("skip_reason", "dependency_failed"),
                        "failed_dependencies": task.metadata.get("failed_dependencies", ()),
                    },
                )
            )
    return updated, tuple(outcomes)


def _fail_stalled_tasks(
    plan: OrchestrationPlan,
) -> tuple[OrchestrationPlan, tuple[AgentStepOutcome, ...]]:
    current = plan
    outcomes: list[AgentStepOutcome] = []
    for task in plan.tasks:
        if task.status in TERMINAL_STATUSES:
            continue
        outcome = AgentStepOutcome(
            task_id=task.id,
            agent=task.agent,
            success=False,
            complete=False,
            message="Task failed because no runnable batch could be selected.",
            metadata={"failure_reason": "no_runnable_batch"},
        )
        current = _apply_terminal_outcome(current, outcome, TaskStatus.FAILED)
        outcomes.append(outcome)
    return current, tuple(outcomes)


def _apply_terminal_outcome(
    plan: OrchestrationPlan,
    outcome: AgentStepOutcome,
    status: TaskStatus,
) -> OrchestrationPlan:
    return update_task_status(
        plan,
        outcome.task_id,
        status,
        metadata={"last_outcome": agent_step_outcome_to_dict(outcome)},
    )


def _exception_outcome(task: OrchestratorTask, exc: Exception) -> AgentStepOutcome:
    exception_type = type(exc).__name__
    return AgentStepOutcome(
        task_id=task.id,
        agent=task.agent,
        success=False,
        complete=False,
        message=f"{exception_type}: {exc}",
        metadata={
            "exception_type": exception_type,
            "exception_message": str(exc),
        },
    )


def _task_by_id(plan: OrchestrationPlan, task_id: str) -> OrchestratorTask:
    for task in plan.tasks:
        if task.id == task_id:
            return task
    raise KeyError(f"Task id not found: {task_id}")
