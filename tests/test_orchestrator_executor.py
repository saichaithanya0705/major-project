from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from models.orchestrator_contracts import (
    OrchestrationPlan,
    OrchestratorTask,
    OrchestrationTraceEventType,
    ResourceLock,
    TaskExecutionContext,
    TaskStatus,
)
from models.orchestrator_executor import execute_plan
from models.orchestrator_resources import ResourceCoordinator


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def task(
    task_id: str,
    *,
    agent: str = "direct",
    depends_on: tuple[str, ...] = (),
    resources: tuple[ResourceLock, ...] = (),
    max_attempts: int = 1,
) -> OrchestratorTask:
    return OrchestratorTask(
        id=task_id,
        agent=agent,
        task=f"task {task_id}",
        depends_on=depends_on,
        resources=resources,
        max_attempts=max_attempts,
    )


def plan_with(*tasks: OrchestratorTask, max_parallel: int = 2) -> OrchestrationPlan:
    return OrchestrationPlan(request="coordinate work", tasks=tasks, max_parallel=max_parallel)


@pytest.mark.anyio
async def test_execute_plan_runs_ready_non_conflicting_tasks_in_batches() -> None:
    started: list[str] = []
    first_batch_started = asyncio.Event()
    release_first_batch = asyncio.Event()

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        assert item.status is TaskStatus.RUNNING
        assert context.request == "coordinate work"
        assert context.dependency_outcomes == ()
        assert context.artifacts == ()
        started.append(item.id)
        if len(started) == 2:
            first_batch_started.set()
        if item.id in {"cli", "web"}:
            await release_first_batch.wait()
        return {"success": True, "complete": True, "message": f"{item.id} done"}

    plan = plan_with(
        task("cli", agent="cua_cli", resources=(ResourceLock.CLI,)),
        task("cli-conflict", agent="cua_cli", resources=(ResourceLock.CLI,)),
        task("web", agent="web_qa", resources=(ResourceLock.WEB_QA,)),
        max_parallel=3,
    )

    execution = asyncio.create_task(execute_plan(plan, runner))
    await asyncio.wait_for(first_batch_started.wait(), timeout=1)

    assert started == ["cli", "web"]
    release_first_batch.set()
    result = await execution

    assert started == ["cli", "web", "cli-conflict"]
    assert [item.status for item in result.plan.tasks] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]
    assert [outcome.task_id for outcome in result.outcomes] == ["cli", "web", "cli-conflict"]


@pytest.mark.anyio
async def test_execute_plan_turns_runner_exceptions_into_failed_outcomes_and_skips_dependents() -> None:
    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        assert context.request == "coordinate work"
        if item.id == "root":
            raise RuntimeError("boom")
        return {"success": True, "complete": True, "message": "should not run"}

    result = await execute_plan(
        plan_with(
            task("root", agent="cua_cli"),
            task("child", agent="web_qa", depends_on=("root",)),
        ),
        runner,
    )

    assert [item.status for item in result.plan.tasks] == [TaskStatus.FAILED, TaskStatus.SKIPPED]
    assert [outcome.task_id for outcome in result.outcomes] == ["root", "child"]
    assert result.outcomes[0].success is False
    assert "RuntimeError: boom" in result.outcomes[0].message
    assert result.outcomes[1].success is False
    assert result.outcomes[1].metadata["skip_reason"] == "dependency_failed"


@pytest.mark.anyio
async def test_execute_plan_retries_incomplete_success_until_max_attempts_then_fails() -> None:
    seen_attempts: list[int] = []

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        assert context.dependency_outcomes == ()
        seen_attempts.append(item.attempts)
        return {"success": True, "complete": False, "message": "not done yet"}

    result = await execute_plan(plan_with(task("flaky", max_attempts=2)), runner)

    assert seen_attempts == [0, 1]
    assert result.plan.tasks[0].status is TaskStatus.FAILED
    assert result.plan.tasks[0].attempts == 2
    assert [outcome.complete for outcome in result.outcomes] == [False, False, False]
    assert result.outcomes[-1].success is False
    assert "max_attempts" in result.outcomes[-1].metadata


@pytest.mark.anyio
async def test_execute_plan_accepts_existing_outcome_objects_from_runner() -> None:
    async def runner(item: OrchestratorTask, context: TaskExecutionContext):
        assert context.artifacts == ()
        from models.orchestrator_contracts import AgentStepOutcome

        return AgentStepOutcome(
            task_id=item.id,
            agent=item.agent,
            success=True,
            complete=True,
            message="already normalized",
        )

    result = await execute_plan(plan_with(task("direct")), runner)

    assert result.plan.tasks[0].status is TaskStatus.COMPLETED
    assert result.outcomes[0].message == "already normalized"


@pytest.mark.anyio
async def test_execute_plan_fails_mismatched_existing_outcome_without_crashing() -> None:
    async def runner(item: OrchestratorTask, context: TaskExecutionContext):
        assert context.dependency_outcomes == ()
        from models.orchestrator_contracts import AgentStepOutcome

        return AgentStepOutcome(
            task_id="other-task",
            agent=item.agent,
            success=True,
            complete=True,
            message="wrong task",
        )

    result = await execute_plan(plan_with(task("actual-task")), runner)

    assert result.plan.tasks[0].status is TaskStatus.FAILED
    assert result.outcomes[0].task_id == "actual-task"
    assert result.outcomes[0].metadata["failure_reason"] == "mismatched_outcome"
    assert result.outcomes[0].metadata["returned_task_id"] == "other-task"


@pytest.mark.anyio
async def test_execute_plan_fails_pending_tasks_that_enter_executor_with_no_attempts_left() -> None:
    exhausted = replace(task("exhausted"), attempts=1, max_attempts=1)

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        assert context.artifacts == ()
        raise AssertionError("exhausted pending tasks should not run")

    result = await execute_plan(plan_with(exhausted), runner)

    assert result.plan.tasks[0].status is TaskStatus.FAILED
    assert result.outcomes[0].task_id == "exhausted"
    assert result.outcomes[0].metadata["max_attempts"] == 1


@pytest.mark.anyio
async def test_execute_plan_passes_dependency_outcomes_and_artifacts_to_dependents() -> None:
    seen_contexts: dict[str, TaskExecutionContext] = {}
    sources = [{"title": "Release notes", "url": "https://example.com/release"}]

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        seen_contexts[item.id] = context
        if item.id == "research":
            return {
                "success": True,
                "complete": True,
                "answer": "Version 2 shipped.",
                "sources": sources,
            }
        assert [outcome.task_id for outcome in context.dependency_outcomes] == ["research"]
        assert [(artifact.task_id, artifact.kind, artifact.value) for artifact in context.artifacts] == [
            ("research", "sources", sources)
        ]
        return {"success": True, "complete": True, "message": "patched"}

    result = await execute_plan(
        plan_with(
            task("research", agent="web_qa"),
            task("patch", agent="cua_cli", depends_on=("research",)),
        ),
        runner,
    )

    assert [item.status for item in result.plan.tasks] == [TaskStatus.COMPLETED, TaskStatus.COMPLETED]
    assert [artifact.kind for artifact in result.artifacts] == ["sources"]
    assert seen_contexts["research"].dependency_outcomes == ()
    assert seen_contexts["research"].artifacts == ()


@pytest.mark.anyio
async def test_execute_plan_does_not_trust_message_guessed_file_paths_as_artifacts() -> None:
    child_context: TaskExecutionContext | None = None

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        nonlocal child_context
        if item.id == "write":
            return {
                "success": True,
                "complete": True,
                "message": "Created file: `D:\\reports\\summary.md`.",
            }
        child_context = context
        return {"success": True, "complete": True, "message": "checked"}

    result = await execute_plan(
        plan_with(
            task("write", agent="cua_cli"),
            task("check", agent="cua_cli", depends_on=("write",)),
        ),
        runner,
    )

    assert child_context is not None
    assert [outcome.task_id for outcome in child_context.dependency_outcomes] == ["write"]
    assert child_context.artifacts == ()
    assert result.artifacts == ()


@pytest.mark.anyio
async def test_execute_plan_records_plan_trace_events_for_batches_waiting_and_skips() -> None:
    started: list[str] = []
    release_first_batch = asyncio.Event()

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        started.append(item.id)
        if item.id == "root":
            await release_first_batch.wait()
            raise RuntimeError("root failed")
        return {"success": True, "complete": True, "message": f"{item.id} done"}

    execution = asyncio.create_task(
        execute_plan(
            plan_with(
                task("root", agent="cua_cli", resources=(ResourceLock.CLI,)),
                task("cli-conflict", agent="cua_cli", resources=(ResourceLock.CLI,)),
                task("child", agent="web_qa", depends_on=("root",)),
                max_parallel=2,
            ),
            runner,
        )
    )
    await asyncio.sleep(0)
    release_first_batch.set()
    result = await execution

    trace = [(event.event_type, event.task_id) for event in result.trace_events]
    assert trace[:3] == [
        (OrchestrationTraceEventType.PLANNED, "root"),
        (OrchestrationTraceEventType.PLANNED, "cli-conflict"),
        (OrchestrationTraceEventType.PLANNED, "child"),
    ]
    assert (OrchestrationTraceEventType.RUNNING, "root") in trace
    assert (OrchestrationTraceEventType.WAITING, "cli-conflict") in trace
    assert (OrchestrationTraceEventType.FAILED, "root") in trace
    assert (OrchestrationTraceEventType.SKIPPED, "child") in trace
    assert [event.sequence for event in result.trace_events] == list(range(1, len(result.trace_events) + 1))


@pytest.mark.anyio
async def test_execute_plan_uses_shared_resource_coordinator_across_concurrent_plans() -> None:
    coordinator = ResourceCoordinator()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    order: list[str] = []

    async def runner(item: OrchestratorTask, context: TaskExecutionContext) -> dict:
        order.append(item.id)
        if item.id == "first":
            first_started.set()
            await release_first.wait()
        return {"success": True, "complete": True, "message": f"{item.id} done"}

    first = asyncio.create_task(
        execute_plan(
            plan_with(task("first", agent="cua_cli", resources=(ResourceLock.CLI,))),
            runner,
            resource_coordinator=coordinator,
        )
    )
    await asyncio.wait_for(first_started.wait(), timeout=1)
    second = asyncio.create_task(
        execute_plan(
            plan_with(task("second", agent="cua_cli", resources=(ResourceLock.CLI,))),
            runner,
            resource_coordinator=coordinator,
        )
    )
    await asyncio.sleep(0.05)

    assert order == ["first"]

    release_first.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert order == ["first", "second"]
    assert first_result.plan.tasks[0].status is TaskStatus.COMPLETED
    assert second_result.plan.tasks[0].status is TaskStatus.COMPLETED
    assert coordinator.held_resources() == ()


@pytest.mark.anyio
async def test_resource_coordinator_deduplicates_duplicate_resource_requests() -> None:
    coordinator = ResourceCoordinator()

    lease = await asyncio.wait_for(
        coordinator.acquire((ResourceLock.CLI, ResourceLock.CLI)),
        timeout=0.1,
    )
    try:
        assert lease.resources == (ResourceLock.CLI,)
        assert coordinator.held_resources() == (ResourceLock.CLI,)
    finally:
        await lease.__aexit__(None, None, None)

    assert coordinator.held_resources() == ()
