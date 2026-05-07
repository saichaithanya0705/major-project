"""
Checks JARVIS routed steps emit a chat screenshot artifact.
"""

from __future__ import annotations

import asyncio

from PIL import Image

import models.agent_step_runner as runner_module


class _FakeJarvisModel:
    async def generate_jarvis_response(self, prompt, screenshot):
        return {
            "summary": "I found the main panels.",
            "function_calls": [
                (
                    "draw_bounding_box",
                    {
                        "time": 0.1,
                        "y_min": 5,
                        "x_min": 6,
                        "y_max": 25,
                        "x_max": 36,
                        "stroke": "#ff0000",
                        "stroke_width": 3,
                        "opacity": 1.0,
                    },
                )
            ],
        }


async def _run_jarvis_step_sends_chat_vision_artifact() -> None:
    captured = {}
    captured_screenshots = []
    original_start = runner_module._start_non_rapid_status
    original_finish = runner_module._finish_non_rapid_status
    original_send_artifact = runner_module.send_chat_vision_artifact

    async def _fake_start(*_args, **_kwargs):
        return None

    async def _fake_finish(*_args, **_kwargs):
        return None

    async def _fake_send_artifact(**kwargs):
        captured.update(kwargs)

    async def _fake_prepare_screenshot(*, keep_chat_hidden=False):
        captured_screenshots.append({"keep_chat_hidden": keep_chat_hidden})
        return Image.new("RGB", (80, 60), "white")

    runner_module._start_non_rapid_status = _fake_start
    runner_module._finish_non_rapid_status = _fake_finish
    runner_module.send_chat_vision_artifact = _fake_send_artifact
    try:
        result = await runner_module.run_routed_agent_step(
            model=_FakeJarvisModel(),
            routing_result={"agent": "jarvis", "query": "Analyze my screen"},
            jarvis_model="jarvis",
            request_id="req_test",
            get_stored_screenshot=lambda: Image.new("RGB", (80, 60), "white"),
            prepare_vision_screenshot=_fake_prepare_screenshot,
        )
    finally:
        runner_module._start_non_rapid_status = original_start
        runner_module._finish_non_rapid_status = original_finish
        runner_module.send_chat_vision_artifact = original_send_artifact

    assert result["success"] is True
    assert captured_screenshots == [{"keep_chat_hidden": True}]
    assert captured["summary"] == "I found the main panels."
    assert captured["artifact"]["kind"] == "vision_screenshot"
    assert captured["artifact"]["outlineCount"] == 1


def test_jarvis_step_sends_chat_vision_artifact() -> None:
    asyncio.run(_run_jarvis_step_sends_chat_vision_artifact())


if __name__ == "__main__":
    asyncio.run(_run_jarvis_step_sends_chat_vision_artifact())
    print("[test_agent_step_runner_jarvis_artifact] All checks passed.")
