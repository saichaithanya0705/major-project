from __future__ import annotations

import pytest

from models.orchestrator_contracts import (
    AgentStepOutcome,
    OrchestrationPlan,
    OrchestratorTask,
    ResourceLock,
    TaskStatus,
    resources_for_agent,
)
from models.orchestrator_scheduler import (
    blocked_by_failed_dependencies,
    has_resource_conflict,
    is_terminal,
    mark_failed_dependency_skips,
    ready_tasks,
    select_runnable_batch,
    successful_outcomes,
    update_task_status,
)


def task(
    task_id: str,
    *,
    agent: str = "direct",
    depends_on: tuple[str, ...] = (),
    resources: tuple[ResourceLock, ...] = (),
    status: TaskStatus = TaskStatus.PENDING,
    metadata: dict[str, object] | None = None,
) -> OrchestratorTask:
    return OrchestratorTask(
        id=task_id,
        agent=agent,
        task=f"task {task_id}",
        depends_on=depends_on,
        resources=resources,
        status=status,
        metadata=metadata or {},
    )


def plan_with(*tasks: OrchestratorTask, max_parallel: int = 2) -> OrchestrationPlan:
    return OrchestrationPlan(request="do useful work", tasks=tasks, max_parallel=max_parallel)


def test_contracts_validate_ids_agents_attempts_and_dependencies() -> None:
    with pytest.raises(ValueError, match="id"):
        task("")

    with pytest.raises(ValueError, match="agent"):
        task("unknown-agent", agent="not_real")

    with pytest.raises(ValueError, match="attempts"):
        OrchestratorTask(id="bad-attempts", agent="direct", task="x", attempts=-1)

    with pytest.raises(ValueError, match="max_attempts"):
        OrchestratorTask(id="bad-max", agent="direct", task="x", max_attempts=0)

    with pytest.raises(ValueError, match="self"):
        task("self", depends_on=("self",))


def test_plan_rejects_duplicate_task_ids_and_unknown_dependencies() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        plan_with(task("same"), task("same"))

    with pytest.raises(ValueError, match="Unknown"):
        plan_with(task("child", depends_on=("missing",)))


def test_ready_tasks_returns_pending_tasks_after_completed_dependencies_only() -> None:
    plan = plan_with(
        task("first"),
        task("done", status=TaskStatus.COMPLETED),
        task("child", depends_on=("done",)),
        task("waiting", depends_on=("first",)),
        task("already-running", status=TaskStatus.RUNNING),
    )

    assert [item.id for item in ready_tasks(plan)] == ["first", "child"]


def test_failed_or_skipped_dependencies_are_blocked_then_marked_skipped_immutably() -> None:
    original = plan_with(
        task("failed", status=TaskStatus.FAILED, metadata={"error": "boom"}),
        task("skipped", status=TaskStatus.SKIPPED),
        task("child-a", depends_on=("failed",)),
        task("child-b", depends_on=("skipped",)),
        task("unrelated"),
    )

    assert [item.id for item in blocked_by_failed_dependencies(original)] == ["child-a", "child-b"]

    updated = mark_failed_dependency_skips(original)

    assert original.tasks[2].status is TaskStatus.PENDING
    assert updated is not original
    assert [item.status for item in updated.tasks] == [
        TaskStatus.FAILED,
        TaskStatus.SKIPPED,
        TaskStatus.SKIPPED,
        TaskStatus.SKIPPED,
        TaskStatus.PENDING,
    ]
    assert updated.tasks[2].metadata["skip_reason"] == "dependency_failed"
    assert updated.tasks[2].metadata["failed_dependencies"] == ("failed",)
    assert "failed" in updated.tasks[2].metadata["message"]


def test_resource_mapping_is_conservative_and_serializable() -> None:
    assert OrchestratorTask(id="browser", agent="browser", task="browse").resources == resources_for_agent(
        "browser"
    )
    assert resources_for_agent("cua_cli") == (ResourceLock.CLI,)
    assert resources_for_agent("web_qa") == (ResourceLock.WEB_QA,)
    assert ResourceLock.CLI.value == "cli"

    vision_resources = set(resources_for_agent("cua_vision"))
    jarvis_resources = set(resources_for_agent("jarvis"))
    screen_resources = set(resources_for_agent("screen_context"))

    assert {ResourceLock.DESKTOP, ResourceLock.SCREENSHOT, ResourceLock.MODEL_VISION} <= vision_resources
    assert ResourceLock.SCREENSHOT in jarvis_resources
    assert ResourceLock.MODEL_VISION in screen_resources


def test_task_resource_overrides_cannot_drop_required_locks() -> None:
    with pytest.raises(ValueError, match="required resource lock"):
        OrchestratorTask(
            id="unsafe-browser",
            agent="browser",
            task="browse",
            resources=(ResourceLock.MODEL_ROUTER,),
        )

    browser_task = OrchestratorTask(
        id="browser-with-extra-lock",
        agent="browser",
        task="browse",
        resources=(ResourceLock.BROWSER, ResourceLock.MODEL_ROUTER, ResourceLock.WEB_QA),
    )

    assert browser_task.resources == (
        ResourceLock.BROWSER,
        ResourceLock.MODEL_ROUTER,
        ResourceLock.WEB_QA,
    )


def test_task_resource_overrides_deduplicate_locks_in_stable_order() -> None:
    task = OrchestratorTask(
        id="dedupe-cli",
        agent="cua_cli",
        task="run command",
        resources=(ResourceLock.CLI, ResourceLock.CLI, ResourceLock.WEB_QA, ResourceLock.CLI),
    )

    assert task.resources == (ResourceLock.CLI, ResourceLock.WEB_QA)


def test_resource_conflicts_use_intersection_and_allow_cli_webqa_parallelism() -> None:
    cli_task = task("cli", agent="cua_cli", resources=resources_for_agent("cua_cli"))
    web_task = task("web", agent="web_qa", resources=resources_for_agent("web_qa"))
    vision_task = task("vision", agent="cua_vision", resources=resources_for_agent("cua_vision"))
    screen_task = task("screen", agent="screen_context", resources=resources_for_agent("screen_context"))

    assert has_resource_conflict(cli_task, web_task) is False
    assert has_resource_conflict(vision_task, screen_task) is True


def test_select_runnable_batch_respects_stable_order_conflicts_and_parallel_limit() -> None:
    plan = plan_with(
        task("vision-a", agent="cua_vision", resources=resources_for_agent("cua_vision")),
        task("vision-b", agent="cua_vision", resources=resources_for_agent("cua_vision")),
        task("cli", agent="cua_cli", resources=resources_for_agent("cua_cli")),
        task("web", agent="web_qa", resources=resources_for_agent("web_qa")),
        max_parallel=3,
    )

    assert [item.id for item in select_runnable_batch(plan)] == ["vision-a", "cli", "web"]
    assert [item.id for item in select_runnable_batch(plan, max_parallel=2)] == ["vision-a", "cli"]


def test_update_task_status_returns_new_plan_and_merges_metadata() -> None:
    original = plan_with(task("work", metadata={"existing": True}))

    updated = update_task_status(
        original,
        "work",
        TaskStatus.RUNNING,
        metadata={"runner": "unit"},
        attempts_delta=1,
    )

    assert original.tasks[0].status is TaskStatus.PENDING
    assert original.tasks[0].attempts == 0
    assert updated.tasks[0].status is TaskStatus.RUNNING
    assert updated.tasks[0].attempts == 1
    assert updated.tasks[0].metadata == {"existing": True, "runner": "unit"}

    with pytest.raises(KeyError, match="missing"):
        update_task_status(original, "missing", TaskStatus.FAILED)


def test_terminal_and_successful_outcome_helpers() -> None:
    outcomes = (
        AgentStepOutcome(task_id="a", agent="direct", success=True, complete=True, message="ok"),
        AgentStepOutcome(task_id="b", agent="web_qa", success=False, complete=False, message="nope"),
    )
    plan = plan_with(
        task("done", status=TaskStatus.COMPLETED),
        task("skipped", status=TaskStatus.SKIPPED),
    )

    assert is_terminal(plan) is True
    assert successful_outcomes(outcomes) == (outcomes[0],)
