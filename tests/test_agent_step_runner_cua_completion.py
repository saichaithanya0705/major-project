"""
Checks routed CUA Vision steps preserve success/complete distinction.

Usage:
    python tests/test_agent_step_runner_cua_completion.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.agent as vision_agent_module  # noqa: E402
import models.agent_step_runner as runner_module  # noqa: E402


def test_cua_step_propagates_incomplete_success() -> None:
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_vision_agent = vision_agent_module.VisionAgent
    captured_finish = {}

    class _FakeVisionAgent:
        def __init__(self, model_name):
            self.model_name = model_name

        async def execute(self, task: str, screenshot=None):
            return {
                "success": True,
                "complete": False,
                "result": "Need more evidence.",
                "error": None,
                "critic": {
                    "complete": False,
                    "should_continue": True,
                    "confidence": 0.2,
                    "reason": "Completion was claimed without evidence.",
                    "next_hint": "Observe again.",
                },
            }

    async def _fake_start(text: str, source: str):
        return None

    async def _fake_finish(message: str, success: bool, source: str):
        captured_finish.update({"message": message, "success": success, "source": source})

    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    vision_agent_module.VisionAgent = _FakeVisionAgent
    try:
        result = asyncio.run(
            runner_module.run_routed_agent_step(
                model=object(),
                routing_result={"agent": "cua_vision", "task": "Save file"},
                jarvis_model="jarvis",
                request_id="req-cua",
                get_stored_screenshot=lambda: None,
            )
        )
    finally:
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish
        vision_agent_module.VisionAgent = original_vision_agent

    assert result["success"] is True
    assert result["complete"] is False
    assert "without evidence" in result["message"]
    assert captured_finish["success"] is False


def test_cua_step_returns_failure_when_screenshot_prepare_fails() -> None:
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_log = runner_module.log_assistant_event
    captured_finish = {}
    logged_events = []

    async def _fake_start(text: str, source: str):
        return None

    async def _fake_finish(message: str, success: bool, source: str):
        captured_finish.update({"message": message, "success": success, "source": source})

    async def _fail_prepare_screenshot(*, keep_chat_hidden: bool = False):
        raise TimeoutError("screenshot capture timed out after 0.1s")

    def _fake_log(event_type: str, **kwargs):
        logged_events.append({"event_type": event_type, **kwargs})

    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    runner_module.log_assistant_event = _fake_log
    try:
        result = asyncio.run(
            runner_module.run_routed_agent_step(
                model=object(),
                routing_result={"agent": "cua_vision", "task": "Save file"},
                jarvis_model="jarvis",
                request_id="req-cua",
                get_stored_screenshot=lambda: None,
                prepare_vision_screenshot=_fail_prepare_screenshot,
            )
        )
    finally:
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish
        runner_module.log_assistant_event = original_log

    assert result["success"] is False
    assert result["complete"] is False
    assert "screenshot capture timed out" in result["message"].lower()
    assert captured_finish["success"] is False
    assert [event["event_type"] for event in logged_events] == [
        "agent_step_started",
        "agent_step_failed",
    ]
    assert logged_events[1]["agent"] == "cua_vision"
    assert "screenshot capture timed out" in logged_events[1]["error"].lower()


def run_checks() -> None:
    test_cua_step_propagates_incomplete_success()
    test_cua_step_returns_failure_when_screenshot_prepare_fails()


if __name__ == "__main__":
    run_checks()
    print("[test_agent_step_runner_cua_completion] All checks passed.")
