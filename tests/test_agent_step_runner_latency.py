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


if __name__ == "__main__":
    asyncio.run(test_completion_status_uses_short_delay())
    print("[test_agent_step_runner_latency] All checks passed.")
