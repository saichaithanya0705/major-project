"""
Checks VisionAgent boundary returns explicit completion semantics.

Usage:
    python tests/test_cua_vision_agent_boundary.py
"""

import asyncio
import os
import sys
from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.agent as vision_agent_module  # noqa: E402
from agents.cua_vision.agent import VisionAgent  # noqa: E402
from agents.cua_vision.contracts import CriticVerdict, CuaRunResult  # noqa: E402


def test_execute_preserves_cua_run_result_completion() -> None:
    async def _fake_loop(_task, screenshot=None):
        return CuaRunResult(
            success=True,
            complete=False,
            result="Need more evidence.",
            critic=CriticVerdict(
                complete=False,
                should_continue=True,
                confidence=0.2,
                reason="Completion was claimed without evidence.",
            ),
        )

    agent = VisionAgent()
    agent._call_interaction_loop = _fake_loop  # type: ignore[method-assign]

    result = asyncio.run(agent.execute("Save file"))

    assert result["success"] is True
    assert result["complete"] is False
    assert result["critic"]["reason"] == "Completion was claimed without evidence."


def test_execute_preserves_real_interaction_loop_result() -> None:
    original_engine = vision_agent_module.SingleCallVisionEngine

    class _FakeEngine:
        def __init__(self, _agent):
            pass

        async def run(self, task, initial_screenshot=None):
            assert task == "Save file"
            assert initial_screenshot is not None
            return CuaRunResult(
                success=True,
                complete=False,
                result="Need semantic evidence.",
                critic=CriticVerdict(
                    complete=False,
                    should_continue=True,
                    confidence=0.25,
                    reason="Completion needs semantic evidence.",
                ),
            )

    agent = VisionAgent()
    vision_agent_module.SingleCallVisionEngine = _FakeEngine
    try:
        result = asyncio.run(
            agent.execute(
                "Save file",
                screenshot=Image.new("RGB", (2, 2), color="white"),
            )
        )
    finally:
        vision_agent_module.SingleCallVisionEngine = original_engine

    assert result["success"] is True
    assert result["complete"] is False
    assert result["result"] == "Need semantic evidence."
    assert result["critic"]["reason"] == "Completion needs semantic evidence."


def run_checks() -> None:
    test_execute_preserves_cua_run_result_completion()
    test_execute_preserves_real_interaction_loop_result()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_agent_boundary] All checks passed.")
