from __future__ import annotations

import pytest

from models.orchestrator_adapters import (
    apply_outcome_to_plan,
    outcome_from_step_result,
    plan_from_route,
    route_from_task,
    route_to_orchestrator_task,
    step_status_from_outcome,
    task_id_for_route,
)
from models.orchestrator_contracts import ResourceLock, TaskStatus


def test_route_to_task_preserves_direct_response_fields() -> None:
    route = {
        "agent": "direct",
        "response_text": "Here is the answer.",
        "direct_response_args": {"foo": "bar"},
        "task": "ignored direct task",
    }

    task = route_to_orchestrator_task(route, index=3)

    assert task.id == "step-3-direct"
    assert task.agent == "direct"
    assert task.task == "ignored direct task"
    assert task.query == ""
    assert task.resources == (ResourceLock.MODEL_ROUTER,)
    assert task.route == route


def test_route_to_task_promotes_direct_response_text_from_args() -> None:
    route = {
        "agent": "direct",
        "direct_response_args": {"text": "Here is the answer.", "variant": "compact"},
    }

    task = route_to_orchestrator_task(route, index=1)

    assert task.route == {
        "agent": "direct",
        "response_text": "Here is the answer.",
        "direct_response_args": {"variant": "compact"},
    }


def test_route_to_task_rejects_non_json_direct_response_args() -> None:
    route = {
        "agent": "direct",
        "response_text": "Here is the answer.",
        "direct_response_args": {"callback": object()},
    }

    with pytest.raises(ValueError, match="direct_response_args must be a JSON object"):
        route_to_orchestrator_task(route)


def test_route_to_task_preserves_browser_and_screen_context_fields() -> None:
    browser = route_to_orchestrator_task(
        {"agent": "browser", "task": "Open https://example.com"},
        index=2,
        depends_on=("step-1-cua-cli",),
    )
    screen = route_to_orchestrator_task(
        {"agent": "screen_context", "task": "Inspect the current window", "focus": "repo URL"},
        index=4,
    )

    assert browser.id == "step-2-browser"
    assert browser.task == "Open https://example.com"
    assert browser.depends_on == ("step-1-cua-cli",)
    assert browser.resources == (ResourceLock.BROWSER, ResourceLock.MODEL_ROUTER)

    assert screen.id == "step-4-screen-context"
    assert screen.task == "Inspect the current window"
    assert screen.route["focus"] == "repo URL"
    assert screen.resources == (ResourceLock.SCREENSHOT, ResourceLock.MODEL_VISION)


def test_plan_from_route_and_route_from_task_round_trip_current_shapes() -> None:
    routes = (
        {"agent": "direct", "response_text": "Done.", "direct_response_args": {"ok": True}},
        {"agent": "browser", "task": "Visit https://example.com"},
        {"agent": "screen_context", "task": "Look at the current page", "focus": "errors"},
        {"agent": "cua_cli", "task": "Run pytest"},
        {"agent": "cua_vision", "task": "Click the save button"},
        {"agent": "web_qa", "task": "Find the latest release notes"},
        {"agent": "jarvis", "query": "Explain the screen"},
    )

    for index, route in enumerate(routes, start=1):
        plan = plan_from_route("user request", route, max_parallel=1)
        task = plan.tasks[0]

        assert plan.request == "user request"
        assert plan.max_parallel == 1
        assert plan.metadata["route"] == route
        assert task.id == task_id_for_route(route, 1)
        assert route_from_task(task) == route


def test_route_from_task_promotes_direct_response_text_out_of_kwargs() -> None:
    task = route_to_orchestrator_task(
        {
            "agent": "direct",
            "direct_response_args": {"text": "Done.", "variant": "compact"},
        }
    )

    assert route_from_task(task) == {
        "agent": "direct",
        "response_text": "Done.",
        "direct_response_args": {"variant": "compact"},
    }


def test_route_from_task_rejects_corrupted_direct_response_args_metadata() -> None:
    task = route_to_orchestrator_task(
        {"agent": "direct", "response_text": "Done.", "direct_response_args": {"ok": True}}
    )
    corrupted = task.__class__(
        id=task.id,
        agent=task.agent,
        task=task.task,
        query=task.query,
        depends_on=task.depends_on,
        resources=task.resources,
        status=task.status,
        attempts=task.attempts,
        max_attempts=task.max_attempts,
        route={**task.route, "direct_response_args": {"callback": object()}},
    )

    with pytest.raises(ValueError, match="direct_response_args must be a JSON object"):
        route_from_task(corrupted)


def test_outcome_normalizes_browser_incomplete_result() -> None:
    task = route_to_orchestrator_task({"agent": "browser", "task": "Submit the form"})
    result = {
        "agent": "browser",
        "task": "Submit the form",
        "success": True,
        "complete": False,
        "message": "Form loaded, but submission still needs confirmation.",
        "source": "browser",
    }

    outcome = outcome_from_step_result(task, result)

    assert outcome.task_id == "step-1-browser"
    assert outcome.success is True
    assert outcome.complete is False
    assert outcome.message == "Form loaded, but submission still needs confirmation."
    assert outcome.metadata["source"] == "browser"
    assert outcome.metadata["task"] == "Submit the form"
    assert outcome.metadata["raw_step_result"] == result
    assert step_status_from_outcome(outcome) is TaskStatus.PENDING


def test_outcome_normalizes_cli_tool_calls_and_artifact_path() -> None:
    task = route_to_orchestrator_task({"agent": "cua_cli", "task": "Create the report"})
    result = {
        "success": True,
        "message": "Report written to D:\\reports\\summary.md",
        "tool_calls": [
            {
                "tool_name": "write_file",
                "status": "success",
                "parameters": {"file_path": "D:\\reports\\summary.md"},
            }
        ],
    }

    outcome = outcome_from_step_result(task, result)

    assert outcome.success is True
    assert outcome.complete is True
    assert outcome.artifacts == {"output_file_path": "D:\\reports\\summary.md"}
    assert outcome.metadata["tool_calls"] == result["tool_calls"]


def test_outcome_normalizes_web_qa_sourced_answer() -> None:
    task = route_to_orchestrator_task({"agent": "web_qa", "task": "Latest project release"})
    result = {
        "success": True,
        "answer": "Version 2 shipped today.",
        "sources": [{"title": "Release notes", "url": "https://example.com/release"}],
    }

    outcome = outcome_from_step_result(task, result)

    assert outcome.message == "Version 2 shipped today."
    assert outcome.artifacts == {"sources": result["sources"]}
    assert outcome.metadata["source"] == "web_qa"


def test_apply_outcome_to_plan_updates_completed_failed_and_incomplete_success() -> None:
    completed_plan = plan_from_route("request", {"agent": "browser", "task": "Open docs"})
    completed = outcome_from_step_result(
        completed_plan.tasks[0],
        {"success": True, "complete": True, "message": "Opened docs."},
    )

    after_completed = apply_outcome_to_plan(completed_plan, completed)

    assert after_completed.tasks[0].status is TaskStatus.COMPLETED
    assert after_completed.tasks[0].attempts == 1
    assert after_completed.tasks[0].metadata["last_outcome"]["message"] == "Opened docs."

    failed_plan = plan_from_route("request", {"agent": "cua_cli", "task": "Run command"})
    failed = outcome_from_step_result(
        failed_plan.tasks[0],
        {"success": False, "complete": False, "message": "Command failed."},
    )

    after_failed = apply_outcome_to_plan(failed_plan, failed)

    assert after_failed.tasks[0].status is TaskStatus.FAILED
    assert after_failed.tasks[0].attempts == 1

    incomplete_plan = plan_from_route("request", {"agent": "browser", "task": "Checkout"})
    incomplete = outcome_from_step_result(
        incomplete_plan.tasks[0],
        {"success": True, "complete": False, "message": "Needs verification."},
    )

    after_incomplete = apply_outcome_to_plan(incomplete_plan, incomplete)

    assert after_incomplete.tasks[0].status is TaskStatus.PENDING
    assert after_incomplete.tasks[0].attempts == 1
    assert after_incomplete.tasks[0].metadata["last_outcome"]["complete"] is False
