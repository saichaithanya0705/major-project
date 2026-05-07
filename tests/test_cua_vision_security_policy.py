"""
Security regression checks for CUA Vision action execution.

Usage:
    python tests/test_cua_vision_security_policy.py
"""

import asyncio
import os
import sys
from types import MethodType
from types import SimpleNamespace

from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.keyboard as keyboard_module
import agents.cua_vision.agent as vision_agent_module
import agents.cua_vision.single_call as single_call_module
import agents.cua_vision.tools as tools_module
from agents.cua_vision.runtime_state import (
    set_last_capture_context,
    set_last_capture_image,
)
from agents.cua_vision.single_call import SingleCallVisionEngine


class _DummyAgent:
    client = None
    model_name = "dummy"
    analysis_config = "analysis-config"
    interaction_config = "interaction-config"
    retries = 0
    max_retries = 3


class _FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def write(self, value, interval=0.0):
        self.calls.append(("write", value, interval))

    def press(self, key):
        self.calls.append(("press", key))

    def keyDown(self, key):
        self.calls.append(("keyDown", key))

    def keyUp(self, key):
        self.calls.append(("keyUp", key))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def moveTo(self, **kwargs):
        self.calls.append(("moveTo", kwargs))

    def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    def mouseDown(self, button):
        self.calls.append(("mouseDown", button))

    def mouseUp(self, button):
        self.calls.append(("mouseUp", button))


def test_execute_tool_call_blocks_dangerous_hotkeys_before_os_input() -> None:
    calls = []
    original_tool = tools_module.VISION_TOOL_MAP["press_ctrl_hotkey"]
    tools_module.VISION_TOOL_MAP["press_ctrl_hotkey"] = lambda key: calls.append(key)
    try:
        try:
            tools_module.execute_tool_call("press_ctrl_hotkey", {"key": "w"})
        except ValueError as exc:
            assert "blocked" in str(exc).lower(), exc
        else:
            raise AssertionError("Expected dangerous hotkey to be blocked")
    finally:
        tools_module.VISION_TOOL_MAP["press_ctrl_hotkey"] = original_tool

    assert calls == [], calls


def test_execute_tool_call_blocks_oversized_text_before_typing() -> None:
    calls = []
    original_tool = tools_module.VISION_TOOL_MAP["type_string"]
    tools_module.VISION_TOOL_MAP["type_string"] = lambda string, submit=False: calls.append((string, submit))
    try:
        try:
            tools_module.execute_tool_call("type_string", {"string": "x" * 5001})
        except ValueError as exc:
            assert "too long" in str(exc).lower(), exc
        else:
            raise AssertionError("Expected oversized typed text to be blocked")
    finally:
        tools_module.VISION_TOOL_MAP["type_string"] = original_tool

    assert calls == [], calls


def test_execute_tool_call_supplies_active_window_to_sensitive_policy() -> None:
    calls = []
    original_tool = tools_module.VISION_TOOL_MAP["type_string"]
    original_get_active_window_title = tools_module.get_active_window_title
    tools_module.VISION_TOOL_MAP["type_string"] = lambda string, submit=False: calls.append((string, submit))
    tools_module.get_active_window_title = lambda: "Checkout - payment token"
    try:
        try:
            tools_module.execute_tool_call("type_string", {"string": "4111 1111 1111 1111"})
        except ValueError as exc:
            assert "sensitive" in str(exc).lower(), exc
        else:
            raise AssertionError("Expected sensitive active window to block typing")
    finally:
        tools_module.VISION_TOOL_MAP["type_string"] = original_tool
        tools_module.get_active_window_title = original_get_active_window_title

    assert calls == [], calls


async def test_vision_execute_passes_initial_screenshot_to_interaction_loop() -> None:
    agent = vision_agent_module.VisionAgent()
    provided = Image.new("RGB", (7, 5), color="blue")
    captured = {}

    async def _fake_interact(self, task, screenshot=None):
        captured["task"] = task
        captured["screenshot"] = screenshot

    agent._interact_with_screen = MethodType(_fake_interact, agent)
    result = await agent.execute("click visible save", provided)

    assert result["success"] is True, result
    assert captured == {"task": "click visible save", "screenshot": provided}, captured


def test_click_target_moves_and_clicks_from_bbox_atomically() -> None:
    calls = []
    original_move_cursor = tools_module.move_cursor
    original_click_left = tools_module.click_left_click
    tools_module.move_cursor = lambda x, y, duration=0.2: calls.append(("move", x, y, duration))
    tools_module.click_left_click = lambda: calls.append(("left_click",))
    set_last_capture_context(
        width=1000,
        height=1000,
        logical_width=1000,
        logical_height=1000,
        offset_x=10,
        offset_y=20,
        scale_x=1.0,
        scale_y=1.0,
        mode="test",
    )
    try:
        tools_module.execute_tool_call(
            "click_target",
            {
                "target_description": "Save",
                "type_of_click": "left click",
                "ymin": 100,
                "xmin": 200,
                "ymax": 300,
                "xmax": 400,
            },
        )
    finally:
        tools_module.move_cursor = original_move_cursor
        tools_module.click_left_click = original_click_left

    assert calls == [("move", 310.0, 220.0, 0.2), ("left_click",)], calls


def test_execute_tool_call_uses_explicit_screen_frame_over_global_capture_state() -> None:
    from agents.cua_vision.screen_context import ScreenFrame

    calls = []
    original_move_cursor = tools_module.move_cursor
    original_click_left = tools_module.click_left_click
    tools_module.move_cursor = lambda x, y, duration=0.2: calls.append(("move", x, y, duration))
    tools_module.click_left_click = lambda: calls.append(("left_click",))

    set_last_capture_context(
        width=1000,
        height=1000,
        logical_width=1000,
        logical_height=1000,
        offset_x=1000,
        offset_y=1000,
        scale_x=1.0,
        scale_y=1.0,
        mode="polluted_global_state",
    )
    set_last_capture_image(Image.new("RGB", (1000, 1000), color="red"))

    model_frame = ScreenFrame(
        image=Image.new("RGB", (1000, 1000), color="blue"),
        context={
            "width": 1000,
            "height": 1000,
            "logical_width": 1000,
            "logical_height": 1000,
            "offset_x": 0,
            "offset_y": 0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "mode": "model_frame",
        },
    )

    try:
        tools_module.execute_tool_call(
            "click_target",
            {
                "target_description": "Save",
                "type_of_click": "left click",
                "ymin": 100,
                "xmin": 200,
                "ymax": 300,
                "xmax": 400,
            },
            screen_frame=model_frame,
        )
    finally:
        tools_module.move_cursor = original_move_cursor
        tools_module.click_left_click = original_click_left

    assert calls == [("move", 300.0, 200.0, 0.2), ("left_click",)], calls


async def test_pre_action_verification_does_not_retarget_click_target() -> None:
    calls = []
    original_move_cursor = tools_module.move_cursor
    original_click_left = tools_module.click_left_click
    original_capture_active_window = single_call_module.capture_active_window
    original_get_active_window_title = tools_module.get_active_window_title

    tools_module.move_cursor = lambda x, y, duration=0.2: calls.append(("move", x, y, duration))
    tools_module.click_left_click = lambda: calls.append(("left_click",))
    tools_module.get_active_window_title = lambda: "Editor - project"

    set_last_capture_context(
        width=1000,
        height=1000,
        logical_width=1000,
        logical_height=1000,
        offset_x=0,
        offset_y=0,
        scale_x=1.0,
        scale_y=1.0,
        mode="provided_full_screen",
    )
    set_last_capture_image(Image.new("RGB", (1000, 1000), color="blue"))

    def _capture_different_context():
        set_last_capture_context(
            width=1000,
            height=1000,
            logical_width=1000,
            logical_height=1000,
            offset_x=1000,
            offset_y=1000,
            scale_x=1.0,
            scale_y=1.0,
            mode="active_window_after_chat_restore",
        )
        set_last_capture_image(Image.new("RGB", (1000, 1000), color="red"))
        return Image.new("RGB", (1000, 1000), color="red")

    async def _noop_post_action_feedback(**_kwargs):
        return None

    async def _noop_wait_for_ui_settle():
        return None

    async def _noop_status(_text: str):
        return None

    engine = SingleCallVisionEngine(_DummyAgent())
    engine._set_status = _noop_status  # type: ignore[method-assign]
    engine._wait_for_ui_settle = _noop_wait_for_ui_settle  # type: ignore[method-assign]
    engine._handle_post_action_visual_feedback = _noop_post_action_feedback  # type: ignore[method-assign]
    single_call_module.capture_active_window = _capture_different_context
    try:
        await engine._handle_function_call(
            "Click Save",
            SimpleNamespace(
                name="click_target",
                args={
                    "target_description": "Save",
                    "type_of_click": "left click",
                    "ymin": 100,
                    "xmin": 200,
                    "ymax": 300,
                    "xmax": 400,
                },
            ),
        )
    finally:
        tools_module.move_cursor = original_move_cursor
        tools_module.click_left_click = original_click_left
        tools_module.get_active_window_title = original_get_active_window_title
        single_call_module.capture_active_window = original_capture_active_window

    assert calls == [("move", 300.0, 200.0, 0.2), ("left_click",)], calls


async def test_single_call_engine_passes_current_screen_frame_to_visual_tools() -> None:
    from agents.cua_vision.screen_context import ScreenFrame

    model_frame = ScreenFrame(
        image=Image.new("RGB", (1000, 1000), color="blue"),
        context={
            "width": 1000,
            "height": 1000,
            "logical_width": 1000,
            "logical_height": 1000,
            "offset_x": 0,
            "offset_y": 0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "mode": "model_frame",
        },
    )
    received = []
    original_execute_tool_call = single_call_module.execute_tool_call

    def _fake_execute_tool_call(name, args, *, screen_frame=None):
        received.append((name, dict(args or {}), screen_frame))

    async def _noop_post_action_feedback(**_kwargs):
        return None

    async def _noop_wait_for_ui_settle():
        return None

    async def _noop_status(_text: str):
        return None

    engine = SingleCallVisionEngine(_DummyAgent())
    engine._current_screen_frame = model_frame
    engine._set_status = _noop_status  # type: ignore[method-assign]
    engine._wait_for_ui_settle = _noop_wait_for_ui_settle  # type: ignore[method-assign]
    engine._capture_verification_snapshot = lambda: (None, None)  # type: ignore[method-assign]
    engine._handle_post_action_visual_feedback = _noop_post_action_feedback  # type: ignore[method-assign]
    single_call_module.execute_tool_call = _fake_execute_tool_call
    try:
        await engine._handle_function_call(
            "Click Save",
            SimpleNamespace(
                name="click_target",
                args={
                    "target_description": "Save",
                    "type_of_click": "left click",
                    "ymin": 100,
                    "xmin": 200,
                    "ymax": 300,
                    "xmax": 400,
                },
            ),
        )
    finally:
        single_call_module.execute_tool_call = original_execute_tool_call

    assert len(received) == 1, received
    assert received[0][0] == "click_target", received
    assert received[0][2] is model_frame, received


def test_press_key_for_duration_releases_key_when_sleep_fails() -> None:
    fake = _FakePyAutoGui()
    original_pyautogui = keyboard_module.pyautogui
    original_sleep = keyboard_module.time.sleep
    keyboard_module.pyautogui = fake

    def _raise_sleep(_seconds):
        raise RuntimeError("sleep interrupted")

    keyboard_module.time.sleep = _raise_sleep
    try:
        try:
            keyboard_module.press_key_for_duration("w", 0.1)
        except RuntimeError as exc:
            assert "sleep interrupted" in str(exc), exc
        else:
            raise AssertionError("Expected sleep failure")
    finally:
        keyboard_module.pyautogui = original_pyautogui
        keyboard_module.time.sleep = original_sleep

    assert fake.calls == [("keyDown", "w"), ("keyUp", "w")], fake.calls


def test_mouse_hold_and_release_use_supplied_coordinates() -> None:
    fake = _FakePyAutoGui()
    original_pyautogui = keyboard_module.pyautogui
    keyboard_module.pyautogui = fake
    try:
        keyboard_module.hold_down_left_click(12, 34)
        keyboard_module.release_left_click(56, 78)
    finally:
        keyboard_module.pyautogui = original_pyautogui

    assert fake.calls == [
        ("moveTo", {"x": 12.0, "y": 34.0, "duration": 0.0}),
        ("mouseDown", "left"),
        ("moveTo", {"x": 56.0, "y": 78.0, "duration": 0.0}),
        ("mouseUp", "left"),
    ], fake.calls


def test_hold_down_key_rejects_keys_outside_safe_hold_set() -> None:
    fake = _FakePyAutoGui()
    original_pyautogui = keyboard_module.pyautogui
    keyboard_module.pyautogui = fake
    try:
        try:
            keyboard_module.hold_down_key("shift")
        except ValueError as exc:
            assert "not allowed" in str(exc).lower(), exc
        else:
            raise AssertionError("Expected invalid held key to be rejected")
    finally:
        keyboard_module.pyautogui = original_pyautogui

    assert fake.calls == [], fake.calls


async def test_vision_run_stops_at_step_budget() -> None:
    function_call = SimpleNamespace(name="remember_information", args={"thing_to_remember": "x"})
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(function_call=function_call)
        ]))]
    )
    calls = {"count": 0}

    async def _fake_generate(_task):
        calls["count"] += 1
        if calls["count"] > 3:
            raise AssertionError("step budget was not enforced")
        return response

    async def _fake_handle(_task, _calls):
        return False

    engine = SingleCallVisionEngine(_DummyAgent())
    engine._max_steps = 2
    engine._max_duration_seconds = 60
    engine._generate_step_response = _fake_generate  # type: ignore[method-assign]
    engine._handle_function_calls = _fake_handle  # type: ignore[method-assign]
    engine._hide_statuses = lambda delay_ms=0: _noop()  # type: ignore[method-assign]
    original_sleep = single_call_module.asyncio.sleep
    single_call_module.asyncio.sleep = lambda _delay: _noop()
    try:
        try:
            await engine.run("keep acting")
        except RuntimeError as exc:
            assert "step budget" in str(exc).lower(), exc
        else:
            raise AssertionError("Expected step budget failure")
    finally:
        single_call_module.asyncio.sleep = original_sleep

    assert calls["count"] == 2, calls


async def test_external_screenshot_sharing_is_allowed_by_default_for_now() -> None:
    original_get_nvidia_api_key = single_call_module.get_nvidia_api_key
    original_get_openrouter_api_key = single_call_module.get_openrouter_api_key
    original_get_nvidia_models = single_call_module.get_nvidia_models
    original_call_openrouter_tool_sync = single_call_module.call_openrouter_tool_sync
    original_env = os.environ.pop("CUA_VISION_ALLOW_EXTERNAL_SCREENSHOTS", None)
    provider_calls = []

    single_call_module.get_nvidia_api_key = lambda: "nvidia-key"
    single_call_module.get_openrouter_api_key = lambda: ""
    single_call_module.get_nvidia_models = lambda _purpose: ["vision-model"]

    def _fake_call_openrouter_tool_sync(**kwargs):
        provider_calls.append(kwargs)
        return {
            "text": "",
            "tool_calls": [{"name": "task_is_complete", "arguments": {}}],
        }

    single_call_module.call_openrouter_tool_sync = _fake_call_openrouter_tool_sync
    try:
        engine = SingleCallVisionEngine(_DummyAgent())
        engine._set_status = lambda _text: _noop()  # type: ignore[method-assign]
        response = await engine._generate_provider_step_response(
            "look",
            Image.new("RGB", (4, 4), color="white"),
        )
    finally:
        single_call_module.get_nvidia_api_key = original_get_nvidia_api_key
        single_call_module.get_openrouter_api_key = original_get_openrouter_api_key
        single_call_module.get_nvidia_models = original_get_nvidia_models
        single_call_module.call_openrouter_tool_sync = original_call_openrouter_tool_sync
        if original_env is not None:
            os.environ["CUA_VISION_ALLOW_EXTERNAL_SCREENSHOTS"] = original_env

    assert len(provider_calls) == 1, provider_calls
    assert provider_calls[0]["image_data_url"].startswith("data:image/"), provider_calls[0]
    assert response.candidates[0].content.parts[0].function_call.name == "task_is_complete"


async def _noop():
    return None


async def run_checks() -> None:
    test_execute_tool_call_blocks_dangerous_hotkeys_before_os_input()
    test_execute_tool_call_blocks_oversized_text_before_typing()
    test_execute_tool_call_supplies_active_window_to_sensitive_policy()
    await test_vision_execute_passes_initial_screenshot_to_interaction_loop()
    test_click_target_moves_and_clicks_from_bbox_atomically()
    test_execute_tool_call_uses_explicit_screen_frame_over_global_capture_state()
    await test_pre_action_verification_does_not_retarget_click_target()
    await test_single_call_engine_passes_current_screen_frame_to_visual_tools()
    test_press_key_for_duration_releases_key_when_sleep_fails()
    test_mouse_hold_and_release_use_supplied_coordinates()
    test_hold_down_key_rejects_keys_outside_safe_hold_set()
    await test_vision_run_stops_at_step_budget()
    await test_external_screenshot_sharing_is_allowed_by_default_for_now()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_cua_vision_security_policy] All checks passed.")
