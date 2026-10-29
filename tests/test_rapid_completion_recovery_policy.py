"""Checks extracted completion and recovery policy for rapid orchestration."""

import os
import sys
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.rapid_completion_recovery_policy import (
    evaluate_incomplete_step_recovery,
    find_latest_unresolved_incomplete_step,
    should_finish_after_successful_agent_step,
)


def _routing_task_text(routing_result: dict[str, object]) -> str:
    return str(routing_result.get("task") or routing_result.get("query") or "")


@pytest.mark.parametrize("success,complete,task,expected", [
    (True, True, "Analyze the screen", True),
    (False, True, "Analyze the screen", False),
    (True, False, "Analyze the screen", False),
    (True, True, "Read the title", False),
])
def test_screen_explanation_completion_requires_success_and_full_request(
    success, complete, task, expected,
):
    step = {"agent": "jarvis", "task": task, "success": success, "complete": complete}
    assert should_finish_after_successful_agent_step(
        user_prompt="Analyze the screen",
        routing_result={"agent": "jarvis", "task": task},
        step_result=step,
        chain_steps=[step],
        routing_task_text=_routing_task_text,
    ) is expected


def test_find_latest_unresolved_incomplete_step_ignores_router_guard_and_resets_after_complete() -> None:
    incomplete = {
        "agent": "browser",
        "task": "open site",
        "success": True,
        "complete": False,
    }
    assert find_latest_unresolved_incomplete_step([incomplete]) == incomplete

    assert find_latest_unresolved_incomplete_step(
        [
            incomplete,
            {
                "agent": "router_guard",
                "task": "open site",
                "success": False,
            },
            {
                "agent": "cua_vision",
                "task": "finish site",
                "success": True,
                "complete": True,
            },
        ]
    ) is None


def test_evaluate_incomplete_step_recovery_promotes_browser_to_cua_vision() -> None:
    decision = evaluate_incomplete_step_recovery(
        user_prompt="finish the browser task",
        routing_result={"agent": "browser", "task": "open site"},
        chain_steps=[
            {
                "agent": "browser",
                "task": "open site",
                "success": True,
                "complete": False,
            }
        ],
        routing_task_text=_routing_task_text,
    )

    assert decision is not None
    assert decision.recovery_route == {
        "agent": "cua_vision",
        "task": (
            "Continue in the currently open browser window and finish the original "
            "user request: finish the browser task"
        ),
    }


def test_evaluate_incomplete_step_recovery_observes_after_repeated_cua_incomplete() -> None:
    decision = evaluate_incomplete_step_recovery(
        user_prompt='open whatsappweb and send "hi" to konda',
        routing_result={"agent": "cua_vision", "task": 'open whatsappweb and send "hi" to konda'},
        chain_steps=[
            {
                "agent": "cua_vision",
                "task": 'open whatsappweb and send "hi" to konda',
                "success": True,
                "complete": False,
                "message": "Completion was claimed without independent semantic evidence.",
            }
        ],
        routing_task_text=_routing_task_text,
    )

    assert decision is not None
    assert decision.recovery_route["agent"] == "screen_context"
    assert "goal-state evidence" in decision.recovery_route["focus"]
    assert "Completion was claimed" in decision.recovery_route["task"]


def test_should_finish_after_successful_agent_step_uses_request_coverage() -> None:
    assert should_finish_after_successful_agent_step(
        user_prompt="summarize example.com",
        routing_result={"agent": "browser", "task": "open example.com and summarize it"},
        step_result={
            "agent": "browser",
            "task": "open example.com and summarize it",
            "success": True,
            "complete": True,
        },
        chain_steps=[
            {
                "agent": "browser",
                "task": "open example.com and summarize it",
                "success": True,
                "complete": True,
            }
        ],
        routing_task_text=_routing_task_text,
    )

    assert not should_finish_after_successful_agent_step(
        user_prompt="summarize example.com",
        routing_result={"agent": "browser", "task": "open example.com and summarize it"},
        step_result={
            "agent": "browser",
            "task": "open example.com and summarize it",
            "success": True,
            "complete": False,
        },
        chain_steps=[
            {
                "agent": "browser",
                "task": "open example.com and summarize it",
                "success": True,
                "complete": False,
            }
        ],
        routing_task_text=_routing_task_text,
    )


def test_cli_command_receipt_finishes_despite_router_removing_chat_instructions():
    step = {"agent": "cua_cli", "task": "run git --version in the terminal", "success": True,
            "tool_calls": [{"tool_name": "run_shell_command", "status": "success",
                            "parameters": {"command": "git --version"}, "result": "git version fixture"}]}
    assert should_finish_after_successful_agent_step(
        user_prompt="Use the CLI agent to run git --version in the terminal and report the actual output. Do not modify any files.",
        routing_result={"agent": "cua_cli", "task": step["task"]}, step_result=step,
        chain_steps=[step], routing_task_text=_routing_task_text,
    )


def test_cli_read_goal_ignores_dispatch_wording_but_keeps_requested_results():
    prompt = ("Use the CLI agent to read fixture.json using the terminal. Report its probe value, "
              "number of amounts, and their sum. Actually read the file; do not change files.")
    task = "read fixture.json and report probe value, number of amounts, and their sum"
    step = {"agent": "cua_cli", "task": task, "success": True}
    assert should_finish_after_successful_agent_step(
        user_prompt=prompt, routing_result={"agent": "cua_cli", "task": task},
        step_result=step, chain_steps=[step], routing_task_text=_routing_task_text,
    )
    assert not should_finish_after_successful_agent_step(
        user_prompt=prompt + " Then email the report to my professor.",
        routing_result={"agent": "cua_cli", "task": task},
        step_result=step, chain_steps=[step], routing_task_text=_routing_task_text,
    )
