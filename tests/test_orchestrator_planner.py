from __future__ import annotations

import pytest

from models.orchestrator_contracts import ResourceLock
from models.orchestrator_planner import normalize_orchestration_plan_payload


def test_normalize_orchestration_plan_payload_preserves_legacy_route_shape() -> None:
    payload = {"agent": "browser", "task": "Open https://example.com"}

    plan = normalize_orchestration_plan_payload("open example", payload, default_max_parallel=3)

    assert plan.request == "open example"
    assert plan.max_parallel == 1
    assert len(plan.tasks) == 1
    assert plan.tasks[0].id == "step-1-browser"
    assert plan.tasks[0].agent == "browser"
    assert plan.tasks[0].task == "Open https://example.com"
    assert plan.metadata["payload"] == payload


def test_normalize_orchestration_plan_payload_builds_multi_task_plan() -> None:
    payload = {
        "tasks": [
            {
                "id": "research",
                "agent": "web_qa",
                "task": "Find current release notes with sources",
                "max_attempts": 2,
            },
            {
                "id": "patch",
                "agent": "cua_cli",
                "task": "Update the changelog using the sourced release notes",
                "depends_on": ["research"],
                "resources": ["cli"],
            },
        ],
        "max_parallel": 2,
        "reason": "Research and local file update are separate steps.",
    }

    plan = normalize_orchestration_plan_payload("update changelog", payload)

    assert plan.max_parallel == 2
    assert [task.id for task in plan.tasks] == ["research", "patch"]
    assert [task.agent for task in plan.tasks] == ["web_qa", "cua_cli"]
    assert plan.tasks[0].max_attempts == 2
    assert plan.tasks[0].resources == (ResourceLock.WEB_QA,)
    assert plan.tasks[1].depends_on == ("research",)
    assert plan.tasks[1].resources == (ResourceLock.CLI,)
    assert plan.tasks[1].metadata["planner_index"] == 2
    assert plan.metadata["payload"] == payload


def test_normalize_orchestration_plan_payload_generates_stable_ids_and_direct_args() -> None:
    payload = {
        "tasks": [
            {"agent": "cua_cli", "task": "Run tests"},
            {"agent": "cua_cli", "task": "Open the report"},
            {
                "agent": "direct",
                "response_text": "Finished.",
                "direct_response_args": {"variant": "compact"},
            },
        ]
    }

    plan = normalize_orchestration_plan_payload("run tests and report", payload)

    assert [task.id for task in plan.tasks] == [
        "step-1-cua-cli",
        "step-2-cua-cli",
        "step-3-direct",
    ]
    assert plan.tasks[2].route["direct_response_args"] == {"variant": "compact"}


def test_normalize_orchestration_plan_payload_copies_task_payload_metadata() -> None:
    payload = {
        "tasks": [
                {
                    "agent": "direct",
                    "direct_response_args": {"text": "Finished.", "variant": "compact"},
                    "resources": ["model_router"],
                    "max_attempts": "2",
                }
        ],
        "reason": "keep payload metadata stable",
    }

    plan = normalize_orchestration_plan_payload("finish", payload)

    payload["tasks"][0]["direct_response_args"]["variant"] = "verbose"
    payload["tasks"][0]["resources"].append("cli")

    assert plan.metadata["payload"] == {
        "tasks": [
            {
                "agent": "direct",
                "response_text": "Finished.",
                "direct_response_args": {"variant": "compact"},
                "resources": ["model_router"],
                "max_attempts": 2,
            }
        ],
        "reason": "keep payload metadata stable",
    }
    assert plan.tasks[0].route == {
        "agent": "direct",
        "response_text": "Finished.",
        "direct_response_args": {"variant": "compact"},
    }


def test_normalize_orchestration_plan_payload_promotes_direct_response_text_from_args() -> None:
    payload = {
        "tasks": [
            {
                "agent": "direct",
                "direct_response_args": {"text": "Finished.", "variant": "compact"},
            }
        ]
    }

    plan = normalize_orchestration_plan_payload("finish", payload)

    assert plan.tasks[0].route["response_text"] == "Finished."
    assert plan.tasks[0].route["direct_response_args"] == {"variant": "compact"}


def test_normalize_orchestration_plan_payload_rejects_non_json_direct_response_args() -> None:
    payload = {
        "tasks": [
            {
                "agent": "direct",
                "response_text": "Finished.",
                "direct_response_args": {"handler": object()},
            }
        ]
    }

    with pytest.raises(ValueError, match="direct_response_args must be a JSON object"):
        normalize_orchestration_plan_payload("finish", payload)


def test_normalize_orchestration_plan_payload_rejects_empty_task_list() -> None:
    with pytest.raises(ValueError, match="tasks must contain at least one task"):
        normalize_orchestration_plan_payload("empty", {"tasks": []})


def test_normalize_orchestration_plan_payload_rejects_weakened_resource_locks() -> None:
    payload = {
        "tasks": [
            {
                "agent": "browser",
                "task": "Open the dashboard",
                "resources": ["model_router"],
            }
        ]
    }

    with pytest.raises(ValueError, match="browser.*required resource lock"):
        normalize_orchestration_plan_payload("open dashboard", payload)


def test_normalize_orchestration_plan_payload_allows_extra_resource_locks() -> None:
    payload = {
        "tasks": [
            {
                "agent": "web_qa",
                "task": "Research the release notes",
                "resources": ["web_qa", "cli"],
            },
            {
                "agent": "cua_cli",
                "task": "Prepare a patch from the release notes",
                "depends_on": ["step-1-web-qa"],
            }
        ]
    }

    plan = normalize_orchestration_plan_payload("research and prepare patch", payload)

    assert plan.tasks[0].resources == (ResourceLock.WEB_QA, ResourceLock.CLI)


def test_normalize_orchestration_plan_payload_rejects_agent_parade_plans() -> None:
    payload = {
        "tasks": [
            {"agent": "web_qa", "task": "Research docs"},
            {"agent": "browser", "task": "Open docs"},
            {"agent": "cua_cli", "task": "Patch files"},
            {"agent": "cua_vision", "task": "Click save"},
            {"agent": "direct", "response_text": "Done"},
        ]
    }

    with pytest.raises(ValueError, match="2 to 4 tasks"):
        normalize_orchestration_plan_payload("do everything", payload)


def test_normalize_orchestration_plan_payload_rejects_empty_executable_work() -> None:
    payload = {
        "tasks": [
            {"agent": "web_qa", "task": ""},
            {"agent": "cua_cli", "task": "Patch files"},
        ]
    }

    with pytest.raises(ValueError, match="non-empty task"):
        normalize_orchestration_plan_payload("patch files", payload)


def test_normalize_orchestration_plan_payload_rejects_duplicate_same_agent_work() -> None:
    payload = {
        "tasks": [
            {"agent": "cua_cli", "task": "Run pytest"},
            {"agent": "cua_cli", "task": "Run pytest"},
        ]
    }

    with pytest.raises(ValueError, match="Duplicate plan work"):
        normalize_orchestration_plan_payload("run tests", payload)
