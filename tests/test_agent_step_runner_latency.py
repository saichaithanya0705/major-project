"""
Checks latency-sensitive agent step UI policy.

Usage:
    python tests/test_agent_step_runner_latency.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.agent_step_runner as runner_module


async def test_completion_status_uses_short_delay() -> None:
    captured = {}
    original_complete = runner_module.complete_status_bubble

    async def _fake_complete_status_bubble(response_text, done_text, delay_ms, source):
        captured.update(
            {
                "response_text": response_text,
                "done_text": done_text,
                "delay_ms": delay_ms,
                "source": source,
            }
        )

    runner_module.complete_status_bubble = _fake_complete_status_bubble
    try:
        await runner_module._finish_non_rapid_status(
            "Finished quickly.",
            True,
            source="cua_cli",
        )
    finally:
        runner_module.complete_status_bubble = original_complete

    assert captured["delay_ms"] <= 900, captured
    assert captured["response_text"] == "Finished quickly.", captured


async def test_web_qa_step_returns_sourced_answer() -> None:
    captured_status = {}
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_web_qa_agent = runner_module.WebQAAgent

    class _FakeWebQAAgent:
        def __init__(self, model):
            self.model = model

        async def execute(self, task: str):
            return {
                "success": True,
                "result": "Sourced answer\n\nSources:\n- [Example](https://example.com)",
                "error": "",
                "complete": True,
            }

    async def _fake_start(text: str, source: str):
        captured_status["start"] = {"text": text, "source": source}

    async def _fake_finish(message: str, success: bool, source: str):
        captured_status["finish"] = {
            "message": message,
            "success": success,
            "source": source,
        }

    runner_module.WebQAAgent = _FakeWebQAAgent
    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    try:
        result = await runner_module.run_routed_agent_step(
            model=object(),
            routing_result={"agent": "web_qa", "task": "latest AI news"},
            jarvis_model="jarvis",
            request_id="req-web",
            get_stored_screenshot=lambda: None,
        )
    finally:
        runner_module.WebQAAgent = original_web_qa_agent
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish

    assert result == {
        "agent": "web_qa",
        "task": "latest AI news",
        "success": True,
        "message": "Sourced answer\n\nSources:\n- [Example](https://example.com)",
        "source": "web_qa",
        "complete": True,
    }, result
    assert captured_status["start"]["source"] == "web_qa", captured_status
    assert captured_status["finish"]["source"] == "web_qa", captured_status


async def test_cli_step_preserves_tool_calls_for_artifact_tracking() -> None:
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_cli_agent = runner_module.CLIAgent

    tool_calls = [
        {
            "tool_name": "write_file",
            "parameters": {"file_path": r"C:\Users\SAI\Desktop\context_dump.txt"},
            "status": "success",
        }
    ]

    class _FakeCLIAgent:
        async def execute(self, task: str, status_callback=None):
            return {
                "success": True,
                "result": "The context has been written to C:\\Users\\SAI\\Desktop\\context_dump.txt.",
                "error": "",
                "tool_calls": tool_calls,
            }

    async def _fake_start(text: str, source: str):
        return None

    async def _fake_finish(message: str, success: bool, source: str):
        return None

    runner_module.CLIAgent = _FakeCLIAgent
    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    try:
        result = await runner_module.run_routed_agent_step(
            model=object(),
            routing_result={"agent": "cua_cli", "task": "write it down"},
            jarvis_model="jarvis",
            request_id="req-cli",
            get_stored_screenshot=lambda: None,
        )
    finally:
        runner_module.CLIAgent = original_cli_agent
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish

    assert result["tool_calls"] == tool_calls, result


async def test_cli_step_reports_created_file_from_tool_call_when_output_is_generic() -> None:
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_cli_agent = runner_module.CLIAgent

    created_path = r"C:\Users\SAI\Desktop\bill_gates_net_worth.md"
    tool_calls = [
        {
            "tool_name": "write_file",
            "parameters": {"file_path": created_path},
            "status": "success",
        }
    ]

    class _FakeCLIAgent:
        async def execute(self, task: str, status_callback=None):
            return {
                "success": True,
                "result": "",
                "error": "",
                "tool_calls": tool_calls,
            }

    async def _fake_start(text: str, source: str):
        return None

    async def _fake_finish(message: str, success: bool, source: str):
        return None

    runner_module.CLIAgent = _FakeCLIAgent
    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    try:
        result = await runner_module.run_routed_agent_step(
            model=object(),
            routing_result={"agent": "cua_cli", "task": "write it down"},
            jarvis_model="jarvis",
            request_id="req-cli-file",
            get_stored_screenshot=lambda: None,
        )
    finally:
        runner_module.CLIAgent = original_cli_agent
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish

    assert created_path in result["message"], result


if __name__ == "__main__":
    asyncio.run(test_completion_status_uses_short_delay())
    asyncio.run(test_web_qa_step_returns_sourced_answer())
    asyncio.run(test_cli_step_preserves_tool_calls_for_artifact_tracking())
    asyncio.run(test_cli_step_reports_created_file_from_tool_call_when_output_is_generic())
    print("[test_agent_step_runner_latency] All checks passed.")
