"""
Checks the shared delegated-agent execution runtime normalizes failures.
"""

from __future__ import annotations

import os
import sys
import asyncio

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.agent_step_execution_runtime as runtime_module


async def test_capture_agent_execution_preserves_failure_complete_flag() -> None:
    async def _raise_failure():
        raise RuntimeError("boom")

    execution = await runtime_module.capture_agent_execution(
        _raise_failure,
        failure_complete=True,
    )

    assert execution.payload == {
        "success": False,
        "result": None,
        "error": "boom",
        "complete": True,
    }, execution.payload
    assert execution.traceback_text is not None
    assert "RuntimeError: boom" in execution.traceback_text


async def test_execute_cli_agent_forwards_status_callback() -> None:
    captured = {}

    async def _status_callback(text: str) -> None:
        captured["status_text"] = text

    class _FakeCliAgent:
        async def execute(self, task: str, status_callback=None):
            captured["task"] = task
            captured["status_callback"] = status_callback
            if status_callback is not None:
                await status_callback("working")
            return {"success": True, "result": "done", "tool_calls": []}

    execution = await runtime_module.execute_cli_agent(
        task="run it",
        agent_factory=_FakeCliAgent,
        status_callback=_status_callback,
    )

    assert execution.payload["success"] is True
    assert captured["task"] == "run it"
    assert captured["status_callback"] is _status_callback
    assert captured["status_text"] == "working"


async def test_execute_task_agent_rejects_invalid_payload_shape() -> None:
    class _FakeTaskAgent:
        async def execute(self, task: str):
            return "not-a-mapping"

    execution = await runtime_module.execute_task_agent(
        task="inspect",
        agent_factory=_FakeTaskAgent,
    )

    assert execution.payload == {
        "success": False,
        "result": "not-a-mapping",
        "error": "Agent returned an invalid result payload.",
    }, execution.payload


async def test_capture_agent_execution_normalizes_structured_payload_fields() -> None:
    sentinel = object()

    async def _return_payload():
        return {
            "success": True,
            "result": {"status": "ok"},
            "complete": False,
            "critic": {
                "reason": "Need more evidence.",
                "raw": sentinel,
            },
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "status": "success",
                    "parameters": {"file_path": "notes.txt"},
                    "result": {"created": True},
                    "raw": sentinel,
                },
                "not-a-dict",
            ],
        }

    execution = await runtime_module.capture_agent_execution(_return_payload)

    assert execution.success is True
    assert execution.complete is False
    assert execution.critic == {"reason": "Need more evidence."}
    assert execution.tool_calls == [
        {
            "tool_name": "write_file",
            "status": "success",
            "parameters": {"file_path": "notes.txt"},
            "result": {"created": True},
        }
    ]


async def test_execute_vision_agent_returns_failure_when_agent_times_out() -> None:
    class _SlowVisionAgent:
        async def execute(self, task: str, screenshot=None):
            await asyncio.sleep(10)
            return {"success": True, "complete": True, "result": "late"}

    execution = await runtime_module.execute_vision_agent(
        task="send message",
        screenshot=None,
        agent_factory=_SlowVisionAgent,
        timeout_seconds=0.01,
    )

    assert execution.success is False
    assert execution.complete is False
    assert "timed out" in str(execution.error).lower()


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_capture_agent_execution_preserves_failure_complete_flag())
    asyncio.run(test_execute_cli_agent_forwards_status_callback())
    asyncio.run(test_execute_task_agent_rejects_invalid_payload_shape())
    asyncio.run(test_capture_agent_execution_normalizes_structured_payload_fields())
    asyncio.run(test_execute_vision_agent_returns_failure_when_agent_times_out())
    print("[test_agent_step_execution_runtime] All checks passed.")
