"""
Checks for the first CUA Vision PyAutoGUI backend adapter.

Usage:
    python tests/test_cua_vision_pyautogui_backend.py
"""

import os
import sys

from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.computer_backend as backend_module  # noqa: E402
from agents.cua_vision.computer_backend import PyAutoGuiComputerBackend  # noqa: E402
from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402


class _FakeFrame:
    image = Image.new("RGB", (2, 2), color="white")

    def context_dict(self):
        return {
            "width": 2,
            "height": 2,
            "logical_width": 2,
            "logical_height": 2,
            "offset_x": 0,
            "offset_y": 0,
            "scale_x": 1.0,
            "scale_y": 1.0,
            "mode": "test",
        }


class _FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def press(self, key):
        self.calls.append(("press", key))

    def scroll(self, delta):
        self.calls.append(("scroll", delta))


def _install_observe_fakes():
    original_capture = backend_module.capture_active_window_frame
    original_title = backend_module.get_active_window_title
    backend_module.capture_active_window_frame = lambda: _FakeFrame()
    backend_module.get_active_window_title = lambda: "Test Window"
    return original_capture, original_title


def _restore_observe_fakes(original_capture, original_title):
    backend_module.capture_active_window_frame = original_capture
    backend_module.get_active_window_title = original_title


def test_observe_returns_typed_screen_observation() -> None:
    original_capture, original_title = _install_observe_fakes()
    try:
        observation = PyAutoGuiComputerBackend().observe()
    finally:
        _restore_observe_fakes(original_capture, original_title)

    assert observation.screenshot_png_base64
    assert observation.active_window_title == "Test Window"
    assert observation.capture_context["mode"] == "test"


def test_observe_preserves_screenshot_when_accessibility_provider_fails() -> None:
    class _FailingAccessibilityProvider:
        def snapshot(self):
            raise RuntimeError("uia bridge failed")

    original_capture, original_title = _install_observe_fakes()
    try:
        observation = PyAutoGuiComputerBackend(
            accessibility_provider=_FailingAccessibilityProvider()
        ).observe()
    finally:
        _restore_observe_fakes(original_capture, original_title)

    assert observation.screenshot_png_base64
    assert observation.capabilities["accessibility"] == "unavailable"
    assert "uia bridge failed" in observation.capabilities["reason"]


def test_execute_coordinate_click_returns_action_result() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_move = backend_module.move_cursor
    original_click = backend_module.click_left_click
    calls = []
    backend_module.move_cursor = lambda x, y, duration=0.2: calls.append(("move", x, y, duration))
    backend_module.click_left_click = lambda: calls.append(("click",))
    action = ComputerAction(
        action_type=ActionType.CLICK,
        target=TargetRef(TargetKind.COORDINATE, x=10, y=20),
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.move_cursor = original_move
        backend_module.click_left_click = original_click

    assert result.executed is True, result
    assert result.before is not None
    assert result.after is not None
    assert calls == [("move", 10, 20, 0.2), ("click",)], calls


def test_execute_returns_failure_when_pre_observation_fails() -> None:
    original_capture = backend_module.capture_active_window_frame
    original_move = backend_module.move_cursor
    calls = []
    backend_module.capture_active_window_frame = lambda: (_ for _ in ()).throw(RuntimeError("capture failed"))
    backend_module.move_cursor = lambda x, y, duration=0.2: calls.append(("move", x, y, duration))
    action = ComputerAction(
        action_type=ActionType.MOVE,
        target=TargetRef(TargetKind.COORDINATE, x=10, y=20),
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        backend_module.capture_active_window_frame = original_capture
        backend_module.move_cursor = original_move

    assert result.executed is False
    assert "Failed to observe before action" in result.message
    assert result.before is None
    assert result.after is None
    assert calls == []


def test_execute_bbox_click_uses_existing_click_target_tool() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_execute = backend_module.execute_tool_call
    calls = []
    backend_module.execute_tool_call = lambda name, args: calls.append((name, dict(args)))
    action = ComputerAction(
        action_type=ActionType.RIGHT_CLICK,
        target=TargetRef(
            TargetKind.BBOX,
            bbox=(1, 2, 3, 4),
            description="Row menu",
        ),
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.execute_tool_call = original_execute

    assert result.executed is True, result
    assert calls == [
        (
            "click_target",
            {
                "ymin": 1,
                "xmin": 2,
                "ymax": 3,
                "xmax": 4,
                "target_description": "Row menu",
                "type_of_click": "right click",
            },
        )
    ], calls


def test_execute_type_text_uses_existing_tool_policy_boundary() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_execute = backend_module.execute_tool_call
    calls = []
    backend_module.execute_tool_call = lambda name, args: calls.append((name, dict(args)))
    action = ComputerAction(
        action_type=ActionType.TYPE_TEXT,
        text="hello",
        raw_args={"submit": True},
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.execute_tool_call = original_execute

    assert result.executed is True, result
    assert calls == [("type_string", {"string": "hello", "submit": True})], calls


def test_execute_type_text_contract_overrides_stale_raw_string() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_execute = backend_module.execute_tool_call
    calls = []
    backend_module.execute_tool_call = lambda name, args: calls.append((name, dict(args)))
    action = ComputerAction(
        action_type=ActionType.TYPE_TEXT,
        text="safe typed value",
        raw_args={"string": "stale raw value", "submit": True},
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.execute_tool_call = original_execute

    assert result.executed is True, result
    assert calls == [("type_string", {"submit": True, "string": "safe typed value"})], calls


def test_execute_ungrounded_description_target_returns_failure_result() -> None:
    original_capture, original_title = _install_observe_fakes()
    action = ComputerAction(
        action_type=ActionType.CLICK,
        target=TargetRef(TargetKind.DESCRIPTION, description="Save button"),
    )
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)

    assert result.executed is False
    assert "ungrounded" in result.message
    assert result.before is not None
    assert result.after is not None


def test_execute_generic_hotkey_falls_back_to_pyautogui() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_pyautogui = backend_module.pyautogui
    fake = _FakePyAutoGui()
    backend_module.pyautogui = fake
    action = ComputerAction(action_type=ActionType.HOTKEY, keys=("shift", "f4"))
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.pyautogui = original_pyautogui

    assert result.executed is True, result
    assert fake.calls == [("hotkey", ("shift", "f4"))], fake.calls


def test_execute_generic_hotkey_uses_policy_boundary() -> None:
    original_capture, original_title = _install_observe_fakes()
    action = ComputerAction(action_type=ActionType.HOTKEY, keys=("ctrl", "w"))
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)

    assert result.executed is False
    assert "blocked" in result.message.lower(), result


def test_execute_keypress_uses_pyautogui_press() -> None:
    original_capture, original_title = _install_observe_fakes()
    original_pyautogui = backend_module.pyautogui
    fake = _FakePyAutoGui()
    backend_module.pyautogui = fake
    action = ComputerAction(action_type=ActionType.KEYPRESS, keys=("enter",))
    try:
        result = PyAutoGuiComputerBackend().execute(action)
    finally:
        _restore_observe_fakes(original_capture, original_title)
        backend_module.pyautogui = original_pyautogui

    assert result.executed is True, result
    assert fake.calls == [("press", "enter")], fake.calls


def run_checks() -> None:
    test_observe_returns_typed_screen_observation()
    test_observe_preserves_screenshot_when_accessibility_provider_fails()
    test_execute_coordinate_click_returns_action_result()
    test_execute_returns_failure_when_pre_observation_fails()
    test_execute_bbox_click_uses_existing_click_target_tool()
    test_execute_type_text_uses_existing_tool_policy_boundary()
    test_execute_type_text_contract_overrides_stale_raw_string()
    test_execute_ungrounded_description_target_returns_failure_result()
    test_execute_generic_hotkey_falls_back_to_pyautogui()
    test_execute_generic_hotkey_uses_policy_boundary()
    test_execute_keypress_uses_pyautogui_press()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_pyautogui_backend] All checks passed.")
