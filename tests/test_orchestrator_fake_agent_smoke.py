from __future__ import annotations

import pytest

from models.orchestrator_contracts import OrchestratorTask, TaskExecutionContext, TaskStatus
from models.orchestrator_executor import execute_plan
from models.orchestrator_planner import normalize_orchestration_plan_payload
from models.orchestrator_resources import ResourceCoordinator


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_fake_agent_smoke_runs_web_qa_to_cli_to_direct_with_trace_artifacts_and_leases() -> None:
    plan = normalize_orchestration_plan_payload(
        "research release notes and update changelog",
        {
            "tasks": [
                {"id": "research", "agent": "web_qa", "task": "Find release notes with sources"},
                {
                    "id": "patch",
                    "agent": "cua_cli",
                    "task": "Update changelog using release notes",
                    "depends_on": ["research"],
                },
                {
                    "id": "final",
                    "agent": "direct",
                    "response_text": "Changelog updated.",
                    "depends_on": ["patch"],
                },
            ],
            "max_parallel": 2,
        },
    )
    seen_contexts: dict[str, TaskExecutionContext] = {}
    sources = [{"title": "Release", "url": "https://example.com/release"}]

    async def runner(task: OrchestratorTask, context: TaskExecutionContext) -> dict:
        seen_contexts[task.id] = context
        if task.id == "research":
            return {"success": True, "complete": True, "answer": "Release found.", "sources": sources}
        if task.id == "patch":
            assert [artifact.kind for artifact in context.artifacts] == ["sources"]
            return {
                "success": True,
                "complete": True,
                "message": "Updated changelog.",
                "artifacts": {"output_file_path": "D:\\projects\\major\\project\\CHANGELOG.md"},
            }
        assert [outcome.task_id for outcome in context.dependency_outcomes] == ["patch"]
        return {"success": True, "complete": True, "message": "Changelog updated."}

    result = await execute_plan(plan, runner, resource_coordinator=ResourceCoordinator())

    assert [task.status for task in result.plan.tasks] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]
    assert [(artifact.task_id, artifact.kind) for artifact in result.artifacts] == [
        ("research", "sources"),
        ("patch", "output_file_path"),
    ]
    assert [event.event_type.value for event in result.trace_events if event.task_id == "final"] == [
        "planned",
        "running",
        "completed",
    ]
    assert seen_contexts["research"].artifacts == ()
    assert [artifact.kind for artifact in seen_contexts["patch"].artifacts] == ["sources"]
