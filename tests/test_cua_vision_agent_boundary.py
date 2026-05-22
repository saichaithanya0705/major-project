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


def test_execute_uses_controller_runtime_and_preserves_result() -> None:
    original_controller = vision_agent_module.CuaController
    original_backend = vision_agent_module.PyAutoGuiComputerBackend
    original_planner = vision_agent_module.ProviderVisionPlanner
    original_judge = vision_agent_module.ProviderSemanticJudge
    original_accessibility = vision_agent_module.build_accessibility_provider
    original_legacy_env = os.environ.pop("CUA_VISION_USE_LEGACY_ENGINE", None)
    created = {}

    class _FakeBackend:
        def __init__(self, *, accessibility_provider=None, initial_screenshot=None):
            self.accessibility_provider = accessibility_provider
            self.initial_screenshot = initial_screenshot

    class _FakePlanner:
        def __init__(self, *, model_policy=None):
            self.model_policy = model_policy

    class _FakeJudge:
        def __init__(self, *, model_policy=None):
            self.model_policy = model_policy

    class _FakeController:
        def __init__(self, **kwargs):
            created.update(kwargs)

        async def run(self, task):
            assert task == "Save file"
            assert created["backend"].initial_screenshot is not None
            return {
                "success": True,
                "complete": False,
                "result": "Need semantic evidence.",
                "error": None,
                "critic": {
                    "complete": False,
                    "should_continue": True,
                    "confidence": 0.25,
                    "reason": "Completion needs semantic evidence.",
                    "next_hint": None,
                },
            }

    agent = VisionAgent()
    vision_agent_module.CuaController = _FakeController
    vision_agent_module.PyAutoGuiComputerBackend = _FakeBackend
    vision_agent_module.ProviderVisionPlanner = _FakePlanner
    vision_agent_module.ProviderSemanticJudge = _FakeJudge
    vision_agent_module.build_accessibility_provider = lambda: "accessibility"
    try:
        result = asyncio.run(
            agent.execute(
                "Save file",
                screenshot=Image.new("RGB", (2, 2), color="white"),
            )
        )
    finally:
        vision_agent_module.CuaController = original_controller
        vision_agent_module.PyAutoGuiComputerBackend = original_backend
        vision_agent_module.ProviderVisionPlanner = original_planner
        vision_agent_module.ProviderSemanticJudge = original_judge
        vision_agent_module.build_accessibility_provider = original_accessibility
        if original_legacy_env is not None:
            os.environ["CUA_VISION_USE_LEGACY_ENGINE"] = original_legacy_env

    assert result["success"] is True
    assert result["complete"] is False
    assert result["result"] == "Need semantic evidence."
    assert result["critic"]["reason"] == "Completion needs semantic evidence."
    assert created["backend"].accessibility_provider == "accessibility"


def run_checks() -> None:
    test_execute_preserves_cua_run_result_completion()
    test_execute_uses_controller_runtime_and_preserves_result()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_agent_boundary] All checks passed.")
