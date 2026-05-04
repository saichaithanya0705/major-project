"""
Regression checks for CUA vision alternating click-loop detection.

Usage:
    python tests/test_cua_vision_loop_guard.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.single_call as single_call_module
import agents.cua_vision.agent as vision_agent_module
from agents.cua_vision.single_call import (
    OpenRouterFallbackError,
    SingleCallVisionEngine,
    CLICK_CYCLE_LOOP_STOP_THRESHOLD,
)
from agents.cua_vision.agent import VisionAgent


class _DummyAgent:
    client = None
    model_name = "dummy"
    analysis_config = "analysis-config"
    interaction_config = "interaction-config"
    retries = 0
    max_retries = 3


def test_detects_alternating_position_click_loop() -> None:
    engine = SingleCallVisionEngine(_DummyAgent())
    task = "Open Settings and change appearance to Light Mode."

    position_sig = ("go_to_element", ("bucket", 24, 7))
    click_sig = ("click_left_click", (("target_description", "Light mode option"),))

    for _ in range(CLICK_CYCLE_LOOP_STOP_THRESHOLD - 1):
        assert not engine._register_action_and_detect_click_loop(
            task, "go_to_element", position_sig, None
        )
        assert not engine._register_action_and_detect_click_loop(
            task, "click_left_click", click_sig, "left click"
        )

    assert not engine._register_action_and_detect_click_loop(
        task, "go_to_element", position_sig, None
    )
    assert engine._register_action_and_detect_click_loop(
        task, "click_left_click", click_sig, "left click"
    )


def test_allows_intentional_repeat_click_tasks() -> None:
    engine = SingleCallVisionEngine(_DummyAgent())
    task = "Click the plus button 10 times."

    position_sig = ("go_to_element", ("bucket", 11, 15))
    click_sig = ("click_left_click", (("target_description", "plus button"),))

    for _ in range(CLICK_CYCLE_LOOP_STOP_THRESHOLD + 3):
        assert not engine._register_action_and_detect_click_loop(
            task, "go_to_element", position_sig, None
        )
        assert not engine._register_action_and_detect_click_loop(
            task, "click_left_click", click_sig, "left click"
        )


def test_cua_vision_modules_do_not_use_gemini_api_key() -> None:
    vision_files = [
        os.path.join(ROOT_DIR, "agents", "cua_vision", "agent.py"),
        os.path.join(ROOT_DIR, "agents", "cua_vision", "single_call.py"),
        os.path.join(ROOT_DIR, "agents", "cua_vision", "legacy_locator.py"),
        os.path.join(ROOT_DIR, "agents", "cua_vision", "agentic_vision.py"),
    ]
    for path in vision_files:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        assert "GEMINI_API_KEY" not in content, path
        assert "GEMINI_BACKUP_MODEL" not in content, path


async def test_generate_step_response_requires_provider_key_without_gemini() -> None:
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = single_call_module.get_active_window_title
    original_get_memory = single_call_module.get_memory
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key

    class _FakeModels:
        async def generate_content(self, **_kwargs):
            raise AssertionError("Gemini should not be called for CUA vision")

    class _FakeClient:
        aio = SimpleNamespace(models=_FakeModels())

    agent = _DummyAgent()
    agent.client = _FakeClient()

    engine = SingleCallVisionEngine(agent)
    engine._set_status = _noop_status  # type: ignore[method-assign]

    single_call_module.capture_active_window = lambda: Image.new("RGB", (4, 4), color="white")
    single_call_module.get_active_window_title = lambda: "Test window"
    single_call_module.get_memory = lambda: ("", None)
    single_call_module.get_nvidia_api_key = lambda: ""
    single_call_module.get_openrouter_api_key = lambda: ""
    try:
        try:
            await engine._generate_step_response("Minimize the app window")
        except OpenRouterFallbackError as exc:
            assert "NVIDIA_API_KEY or OPENROUTER_API_KEY" in str(exc), exc
            assert "Gemini is not used" in str(exc), exc
        else:
            raise AssertionError("Expected provider-key error")
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.get_active_window_title = original_get_active_window_title
        single_call_module.get_memory = original_get_memory
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key


async def test_quota_error_uses_openrouter_step_fallback() -> None:
    calls: list[str] = []
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = single_call_module.get_active_window_title
    original_get_memory = single_call_module.get_memory
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key
    original_get_openrouter_models = single_call_module.get_openrouter_models
    original_call_openrouter_tool_sync = single_call_module.call_openrouter_tool_sync

    class _FakeModels:
        async def generate_content(self, **_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED Gemini quota exceeded")

    class _FakeClient:
        aio = SimpleNamespace(models=_FakeModels())

    agent = _DummyAgent()
    agent.client = _FakeClient()

    def _fake_call_openrouter_tool_sync(**kwargs):
        calls.append(kwargs["model_name"])
        return {
            "text": "",
            "tool_calls": [{"name": "task_is_complete", "arguments": {}}],
        }

    single_call_module.capture_active_window = lambda: Image.new("RGB", (4, 4), color="white")
    single_call_module.get_active_window_title = lambda: "Test window"
    single_call_module.get_memory = lambda: ("", None)
    single_call_module.get_nvidia_api_key = lambda: ""
    single_call_module.get_openrouter_api_key = lambda: "openrouter-key"
    single_call_module.get_openrouter_models = lambda _purpose: ["google/gemma-4-31b-it:free"]
    single_call_module.call_openrouter_tool_sync = _fake_call_openrouter_tool_sync
    try:
        engine = SingleCallVisionEngine(agent)
        engine._set_status = _noop_status  # type: ignore[method-assign]
        response = await engine._generate_step_response("Minimize the app")
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.get_active_window_title = original_get_active_window_title
        single_call_module.get_memory = original_get_memory
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key
        single_call_module.get_openrouter_models = original_get_openrouter_models
        single_call_module.call_openrouter_tool_sync = original_call_openrouter_tool_sync

    assert calls == ["google/gemma-4-31b-it:free"], calls
    parts = response.candidates[0].content.parts
    assert parts[0].function_call.name == "task_is_complete"


async def test_quota_error_uses_direct_nvidia_fallback() -> None:
    calls: list[tuple[str, str]] = []
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = single_call_module.get_active_window_title
    original_get_memory = single_call_module.get_memory
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_nvidia_models = single_call_module.get_nvidia_models
    original_get_nvidia_chat_url = single_call_module.get_nvidia_chat_url
    original_call_openrouter_tool_sync = single_call_module.call_openrouter_tool_sync

    class _FakeModels:
        async def generate_content(self, **_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED Gemini quota exceeded")

    class _FakeClient:
        aio = SimpleNamespace(models=_FakeModels())

    agent = _DummyAgent()
    agent.client = _FakeClient()

    def _fake_call_openrouter_tool_sync(**kwargs):
        calls.append((kwargs["openrouter_url"], kwargs["model_name"]))
        return {
            "text": "",
            "tool_calls": [{"name": "task_is_complete", "arguments": {}}],
        }

    single_call_module.capture_active_window = lambda: Image.new("RGB", (4, 4), color="white")
    single_call_module.get_active_window_title = lambda: "Test window"
    single_call_module.get_memory = lambda: ("", None)
    single_call_module.get_openrouter_api_key = lambda: ""
    single_call_module.get_nvidia_api_key = lambda: "nvidia-key"
    single_call_module.get_nvidia_models = lambda _purpose: ["google/gemma-4-31b-it"]
    single_call_module.get_nvidia_chat_url = (
        lambda: "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    single_call_module.call_openrouter_tool_sync = _fake_call_openrouter_tool_sync
    try:
        engine = SingleCallVisionEngine(agent)
        engine._set_status = _noop_status  # type: ignore[method-assign]
        response = await engine._generate_step_response("Minimize the app")
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.get_active_window_title = original_get_active_window_title
        single_call_module.get_memory = original_get_memory
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_nvidia_models = original_get_nvidia_models
        single_call_module.get_nvidia_chat_url = original_get_nvidia_chat_url
        single_call_module.call_openrouter_tool_sync = original_call_openrouter_tool_sync

    assert calls == [
        ("https://integrate.api.nvidia.com/v1/chat/completions", "google/gemma-4-31b-it")
    ], calls
    parts = response.candidates[0].content.parts
    assert parts[0].function_call.name == "task_is_complete"


async def test_step_response_uses_nvidia_first_without_gemini() -> None:
    calls: list[tuple[str, str, str]] = []
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = single_call_module.get_active_window_title
    original_get_memory = single_call_module.get_memory
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_nvidia_models = single_call_module.get_nvidia_models
    original_get_nvidia_chat_url = single_call_module.get_nvidia_chat_url
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key
    original_get_openrouter_models = single_call_module.get_openrouter_models
    original_get_openrouter_chat_url = single_call_module.get_openrouter_chat_url
    original_call_openrouter_tool_sync = single_call_module.call_openrouter_tool_sync

    class _GeminiShouldNotRun:
        async def generate_content(self, **_kwargs):
            raise AssertionError("Gemini should not be called for CUA vision")

    class _FakeClient:
        aio = SimpleNamespace(models=_GeminiShouldNotRun())

    agent = _DummyAgent()
    agent.client = _FakeClient()

    def _fake_call_openrouter_tool_sync(**kwargs):
        calls.append((
            kwargs["openrouter_api_key"],
            kwargs["openrouter_url"],
            kwargs["model_name"],
        ))
        return {
            "text": "",
            "tool_calls": [{"name": "task_is_complete", "arguments": {}}],
        }

    single_call_module.capture_active_window = lambda: Image.new("RGB", (4, 4), color="white")
    single_call_module.get_active_window_title = lambda: "Test window"
    single_call_module.get_memory = lambda: ("", None)
    single_call_module.get_nvidia_api_key = lambda: "nvidia-key"
    single_call_module.get_nvidia_models = lambda _purpose: ["qwen/qwen3.5-397b-a17b"]
    single_call_module.get_nvidia_chat_url = (
        lambda: "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    single_call_module.get_openrouter_api_key = lambda: "openrouter-key"
    single_call_module.get_openrouter_models = lambda _purpose: ["google/gemma-4-31b-it:free"]
    single_call_module.get_openrouter_chat_url = (
        lambda: "https://openrouter.ai/api/v1/chat/completions"
    )
    single_call_module.call_openrouter_tool_sync = _fake_call_openrouter_tool_sync
    try:
        engine = SingleCallVisionEngine(agent)
        engine._set_status = _noop_status  # type: ignore[method-assign]
        response = await engine._generate_step_response("Minimize the app")
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.get_active_window_title = original_get_active_window_title
        single_call_module.get_memory = original_get_memory
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_nvidia_models = original_get_nvidia_models
        single_call_module.get_nvidia_chat_url = original_get_nvidia_chat_url
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key
        single_call_module.get_openrouter_models = original_get_openrouter_models
        single_call_module.get_openrouter_chat_url = original_get_openrouter_chat_url
        single_call_module.call_openrouter_tool_sync = original_call_openrouter_tool_sync

    assert calls == [
        (
            "nvidia-key",
            "https://integrate.api.nvidia.com/v1/chat/completions",
            "qwen/qwen3.5-397b-a17b",
        )
    ], calls
    parts = response.candidates[0].content.parts
    assert parts[0].function_call.name == "task_is_complete"


async def test_step_response_uses_openrouter_after_nvidia_failure() -> None:
    calls: list[tuple[str, str]] = []
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = single_call_module.get_active_window_title
    original_get_memory = single_call_module.get_memory
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_nvidia_models = single_call_module.get_nvidia_models
    original_get_nvidia_chat_url = single_call_module.get_nvidia_chat_url
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key
    original_get_openrouter_models = single_call_module.get_openrouter_models
    original_get_openrouter_chat_url = single_call_module.get_openrouter_chat_url
    original_call_openrouter_tool_sync = single_call_module.call_openrouter_tool_sync

    class _GeminiShouldNotRun:
        async def generate_content(self, **_kwargs):
            raise AssertionError("Gemini should not be called for CUA vision")

    class _FakeClient:
        aio = SimpleNamespace(models=_GeminiShouldNotRun())

    agent = _DummyAgent()
    agent.client = _FakeClient()

    def _fake_call_openrouter_tool_sync(**kwargs):
        calls.append((kwargs["openrouter_api_key"], kwargs["model_name"]))
        if kwargs["openrouter_api_key"] == "nvidia-key":
            raise RuntimeError("NVIDIA provider unavailable")
        return {
            "text": "",
            "tool_calls": [{"name": "task_is_complete", "arguments": {}}],
        }

    single_call_module.capture_active_window = lambda: Image.new("RGB", (4, 4), color="white")
    single_call_module.get_active_window_title = lambda: "Test window"
    single_call_module.get_memory = lambda: ("", None)
    single_call_module.get_nvidia_api_key = lambda: "nvidia-key"
    single_call_module.get_nvidia_models = lambda _purpose: ["qwen/qwen3.5-397b-a17b"]
    single_call_module.get_nvidia_chat_url = (
        lambda: "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    single_call_module.get_openrouter_api_key = lambda: "openrouter-key"
    single_call_module.get_openrouter_models = lambda _purpose: ["google/gemma-4-31b-it:free"]
    single_call_module.get_openrouter_chat_url = (
        lambda: "https://openrouter.ai/api/v1/chat/completions"
    )
    single_call_module.call_openrouter_tool_sync = _fake_call_openrouter_tool_sync
    try:
        engine = SingleCallVisionEngine(agent)
        engine._set_status = _noop_status  # type: ignore[method-assign]
        response = await engine._generate_step_response("Minimize the app")
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.get_active_window_title = original_get_active_window_title
        single_call_module.get_memory = original_get_memory
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_nvidia_models = original_get_nvidia_models
        single_call_module.get_nvidia_chat_url = original_get_nvidia_chat_url
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key
        single_call_module.get_openrouter_models = original_get_openrouter_models
        single_call_module.get_openrouter_chat_url = original_get_openrouter_chat_url
        single_call_module.call_openrouter_tool_sync = original_call_openrouter_tool_sync

    assert calls == [
        ("nvidia-key", "qwen/qwen3.5-397b-a17b"),
        ("openrouter-key", "google/gemma-4-31b-it:free"),
    ], calls
    parts = response.candidates[0].content.parts
    assert parts[0].function_call.name == "task_is_complete"


async def test_openrouter_fallback_error_does_not_retry_backup_gemini() -> None:
    calls: list[str] = []
    original_reset_state = vision_agent_module.reset_state
    original_clear_stop_request = vision_agent_module.clear_stop_request

    agent = object.__new__(VisionAgent)
    agent.model_name = "gemini-primary"
    agent.backup_model_name = "gemini-backup"
    agent.max_retries = 3
    agent.retries = 0
    agent.chat_history = []

    async def _fake_interact_with_screen(_task: str):
        calls.append(agent.model_name)
        raise OpenRouterFallbackError(
            "Gemini quota reached, and vision fallback failed. "
            "Last OpenRouter error: OpenRouter HTTP 429"
        )

    agent._interact_with_screen = _fake_interact_with_screen
    vision_agent_module.reset_state = lambda: None
    vision_agent_module.clear_stop_request = lambda: None
    try:
        result = await agent.execute("Minimize the app")
    finally:
        vision_agent_module.reset_state = original_reset_state
        vision_agent_module.clear_stop_request = original_clear_stop_request

    assert calls == ["gemini-primary"], calls
    assert result["success"] is False
    assert "vision fallback failed" in result["error"]


async def test_wait_for_ui_settle_polls_until_stable() -> None:
    original_capture_active_window = single_call_module.capture_active_window
    original_image_change = single_call_module.image_change
    original_reset_image_state = single_call_module.reset_image_state
    original_sleep = single_call_module.asyncio.sleep

    frames_seen: list[int] = []
    sleep_calls: list[float] = []
    reset_calls: list[str] = []

    def _fake_capture_active_window():
        frames_seen.append(len(frames_seen) + 1)
        return f"frame-{len(frames_seen)}"

    def _fake_image_change(_frame):
        return len(frames_seen) >= 3

    def _fake_reset_image_state():
        reset_calls.append("reset")

    async def _fake_sleep(delay: float):
        sleep_calls.append(delay)

    engine = SingleCallVisionEngine(_DummyAgent())
    engine._action_settle_timeout_seconds = 1.0
    engine._action_settle_poll_interval_seconds = 0.05

    single_call_module.capture_active_window = _fake_capture_active_window
    single_call_module.image_change = _fake_image_change
    single_call_module.reset_image_state = _fake_reset_image_state
    single_call_module.asyncio.sleep = _fake_sleep
    try:
        final_frame = await engine._wait_for_ui_settle()
    finally:
        single_call_module.capture_active_window = original_capture_active_window
        single_call_module.image_change = original_image_change
        single_call_module.reset_image_state = original_reset_image_state
        single_call_module.asyncio.sleep = original_sleep

    assert reset_calls == ["reset"], reset_calls
    assert frames_seen == [1, 2, 3], frames_seen
    assert sleep_calls == [0.05, 0.05], sleep_calls
    assert final_frame == "frame-3", final_frame


def test_build_model_prompt_includes_runtime_observations() -> None:
    engine = SingleCallVisionEngine(_DummyAgent())
    engine._runtime_observations = [
        "After left click on Save button, the visible UI looked unchanged.",
        "Precision fallback was used for Save button after direct interaction struggled.",
    ]

    prompt = engine._build_model_prompt(
        task="Save the document",
        active_window="Codex",
        memory_text=["user opened the file menu"],
    )

    assert "Recent controller observations" in prompt, prompt
    assert "visible UI looked unchanged" in prompt, prompt
    assert "Precision fallback was used" in prompt, prompt


async def test_repeated_visual_noop_click_uses_fallback() -> None:
    original_execute_tool_call = single_call_module.execute_tool_call

    fallback_calls: list[tuple[str | None, dict | None]] = []
    executed_tools: list[tuple[str, dict]] = []

    async def _fake_wait_for_ui_settle():
        return Image.new("RGB", (4, 4), color="white")

    async def _fake_attempt_fallback(task: str, click_type: str | None, args: dict | None) -> bool:
        fallback_calls.append((click_type, args))
        return True

    async def _noop_status(_text: str):
        return None

    def _fake_execute_tool_call(name: str, args: dict):
        executed_tools.append((name, dict(args or {})))

    function_call = SimpleNamespace(
        name="click_left_click",
        args={"target_description": "Save button"},
    )

    engine = SingleCallVisionEngine(_DummyAgent())
    engine._set_status = _noop_status  # type: ignore[method-assign]
    engine._wait_for_ui_settle = _fake_wait_for_ui_settle  # type: ignore[method-assign]
    engine._attempt_fallback = _fake_attempt_fallback  # type: ignore[method-assign]
    engine._capture_verification_snapshot = lambda: (Image.new("RGB", (4, 4), color="white"), None)  # type: ignore[method-assign]
    engine._snapshot_current_capture_context = lambda: None  # type: ignore[method-assign]

    single_call_module.execute_tool_call = _fake_execute_tool_call
    try:
        await engine._handle_function_call("Save the current document", function_call)
        await engine._handle_function_call("Save the current document", function_call)
    finally:
        single_call_module.execute_tool_call = original_execute_tool_call

    assert [tool for tool, _args in executed_tools] == ["click_left_click", "click_left_click"], executed_tools
    assert len(fallback_calls) == 1, fallback_calls
    assert fallback_calls[0][0] == "left click", fallback_calls
    assert any("visible UI looked unchanged" in item for item in engine._runtime_observations), engine._runtime_observations


def test_target_region_similarity_detects_local_change() -> None:
    engine = SingleCallVisionEngine(_DummyAgent())
    engine._last_position_bbox_args = {
        "ymin": 190.0,
        "xmin": 190.0,
        "ymax": 210.0,
        "xmax": 210.0,
    }

    before = Image.new("RGB", (500, 500), color="white")
    after = Image.new("RGB", (500, 500), color="white")
    for x in range(98, 103):
        for y in range(98, 103):
            after.putpixel((x, y), (0, 0, 0))

    context = {
        "width": 500,
        "height": 500,
        "logical_width": 500,
        "logical_height": 500,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "mode": "active_window",
    }

    metrics = engine._visual_similarity_metrics(
        tool_name="click_left_click",
        args={"target_description": "Save button"},
        before_frame=before,
        before_context=context,
        after_frame=after,
        after_context=context,
    )

    assert metrics["global_similarity"] is not None, metrics
    assert metrics["global_similarity"] > single_call_module.VISUAL_NOOP_SIMILARITY_THRESHOLD, metrics
    assert metrics["target_similarity"] is not None, metrics
    assert metrics["target_similarity"] < single_call_module.TARGET_REGION_NOOP_SIMILARITY_THRESHOLD, metrics


async def _noop_status(_text: str):
    return None


if __name__ == "__main__":
    test_detects_alternating_position_click_loop()
    test_allows_intentional_repeat_click_tasks()
    test_cua_vision_modules_do_not_use_gemini_api_key()
    asyncio.run(test_generate_step_response_requires_provider_key_without_gemini())
    asyncio.run(test_quota_error_uses_openrouter_step_fallback())
    asyncio.run(test_quota_error_uses_direct_nvidia_fallback())
    asyncio.run(test_step_response_uses_nvidia_first_without_gemini())
    asyncio.run(test_step_response_uses_openrouter_after_nvidia_failure())
    asyncio.run(test_openrouter_fallback_error_does_not_retry_backup_gemini())
    asyncio.run(test_wait_for_ui_settle_polls_until_stable())
    test_build_model_prompt_includes_runtime_observations()
    asyncio.run(test_repeated_visual_noop_click_uses_fallback())
    test_target_region_similarity_detects_local_change()
    print("[test_cua_vision_loop_guard] All checks passed.")
