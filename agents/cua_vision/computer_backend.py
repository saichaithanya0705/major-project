"""
Computer backend boundary for CUA Vision.

The first backend deliberately wraps the existing screenshot and PyAutoGUI tool
path instead of introducing a backend package before multiple implementations
exist.
"""

from __future__ import annotations

import base64
import time
from io import BytesIO
from typing import Protocol, runtime_checkable

from agents.cua_vision.action_policy import normalize_hotkey_keys
from agents.cua_vision.contracts import (
    ActionResult,
    ActionType,
    ComputerAction,
    ScreenObservation,
    TargetKind,
)
from agents.cua_vision.keyboard import (
    click_double_left_click,
    click_left_click,
    click_right_click,
    move_cursor,
    pyautogui,
)
from agents.cua_vision.screen_context import capture_active_window_frame, get_active_window_title
from agents.cua_vision.tools import execute_tool_call


@runtime_checkable
class ComputerBackend(Protocol):
    def observe(self) -> ScreenObservation:
        ...

    def execute(self, action: ComputerAction) -> ActionResult:
        ...

    def get_active_window(self) -> str | None:
        ...

    def close(self) -> None:
        ...


class PyAutoGuiComputerBackend:
    """Adapter from typed CUA actions to the current PyAutoGUI implementation."""

    def __init__(self, accessibility_provider=None):
        self.accessibility_provider = accessibility_provider

    def observe(self) -> ScreenObservation:
        frame = capture_active_window_frame()
        accessibility_tree = None
        elements = ()
        capabilities: dict = {}
        if self.accessibility_provider is not None:
            snapshot = self.accessibility_provider.snapshot()
            accessibility_tree = snapshot.tree
            elements = snapshot.elements
            capabilities.update(snapshot.capabilities)
        return ScreenObservation(
            screenshot_png_base64=_image_to_png_base64(frame.image),
            active_window_title=get_active_window_title(),
            capture_context=frame.context_dict(),
            accessibility_tree=accessibility_tree,
            elements=elements,
            capabilities=capabilities,
        )

    def execute(self, action: ComputerAction) -> ActionResult:
        before = self.observe()
        try:
            self._execute_action(action)
        except Exception as exc:
            after, observe_error = self._safe_observe_after_error()
            message = str(exc)
            if observe_error:
                message = f"{message}; failed to observe after action: {observe_error}"
            return ActionResult(
                executed=False,
                message=message,
                before=before,
                after=after,
            )

        return ActionResult(
            executed=True,
            message=f"Executed {action.action_type.value}",
            before=before,
            after=self.observe(),
        )

    def get_active_window(self) -> str | None:
        return get_active_window_title()

    def close(self) -> None:
        return None

    def _safe_observe_after_error(self) -> tuple[ScreenObservation | None, str | None]:
        try:
            return self.observe(), None
        except Exception as exc:
            return None, str(exc)

    def _execute_action(self, action: ComputerAction) -> None:
        if action.action_type == ActionType.MOVE:
            self._execute_move(action)
        elif action.action_type in {
            ActionType.CLICK,
            ActionType.DOUBLE_CLICK,
            ActionType.RIGHT_CLICK,
        }:
            self._execute_click(action)
        elif action.action_type == ActionType.TYPE_TEXT:
            execute_tool_call(
                "type_string",
                {"string": action.text or "", **action.raw_args},
            )
        elif action.action_type == ActionType.HOTKEY:
            self._execute_hotkey(action)
        elif action.action_type == ActionType.KEYPRESS:
            self._execute_keypress(action)
        elif action.action_type == ActionType.SCROLL:
            pyautogui.scroll(int(action.scroll_delta or 0))
        elif action.action_type == ActionType.WAIT:
            time.sleep(float(action.duration_seconds or 0.0))
        elif action.action_type in {ActionType.COMPLETE, ActionType.ABORT}:
            return
        else:
            raise ValueError(f"Unsupported backend action: {action.action_type.value}")

    def _execute_move(self, action: ComputerAction) -> None:
        if action.target.kind == TargetKind.COORDINATE:
            move_cursor(action.target.x, action.target.y, duration=0.2)
            return
        if action.target.kind == TargetKind.BBOX:
            args = _bbox_args(action)
            execute_tool_call("go_to_element", args)
            return
        raise ValueError(f"Cannot move to ungrounded target: {action.target.kind.value}")

    def _execute_click(self, action: ComputerAction) -> None:
        if action.target.kind == TargetKind.COORDINATE:
            move_cursor(action.target.x, action.target.y, duration=0.2)
            self._click_current_position(action.action_type)
            return
        if action.target.kind == TargetKind.BBOX:
            args = _bbox_args(action)
            args["type_of_click"] = _action_type_to_click_type(action.action_type)
            execute_tool_call("click_target", args)
            return
        if action.target.kind == TargetKind.NONE:
            self._click_current_position(action.action_type)
            return
        raise ValueError(f"Cannot click ungrounded target: {action.target.kind.value}")

    def _click_current_position(self, action_type: ActionType) -> None:
        if action_type == ActionType.CLICK:
            click_left_click()
        elif action_type == ActionType.DOUBLE_CLICK:
            click_double_left_click()
        elif action_type == ActionType.RIGHT_CLICK:
            click_right_click()
        else:
            raise ValueError(f"Unsupported click action: {action_type.value}")

    def _execute_hotkey(self, action: ComputerAction) -> None:
        if not action.keys:
            raise ValueError("Hotkey actions require keys.")
        keys = normalize_hotkey_keys(action.keys)
        if len(keys) == 2 and keys[0] == "ctrl":
            execute_tool_call("press_ctrl_hotkey", {"key": keys[1]})
            return
        if len(keys) == 2 and keys[0] == "alt":
            execute_tool_call("press_alt_hotkey", {"key": keys[1]})
            return
        pyautogui.hotkey(*keys)

    def _execute_keypress(self, action: ComputerAction) -> None:
        if len(action.keys) != 1:
            raise ValueError("Keypress actions require exactly one key.")
        key = action.keys[0]
        if action.duration_seconds is not None:
            execute_tool_call(
                "press_key_for_duration",
                {"key": key, "seconds": action.duration_seconds},
            )
            return
        pyautogui.press(key)


def _bbox_args(action: ComputerAction) -> dict:
    if action.target.bbox is None:
        raise ValueError("Bbox action missing bbox.")
    ymin, xmin, ymax, xmax = action.target.bbox
    return {
        "ymin": ymin,
        "xmin": xmin,
        "ymax": ymax,
        "xmax": xmax,
        "target_description": action.target.description or "target",
    }


def _action_type_to_click_type(action_type: ActionType) -> str:
    if action_type == ActionType.CLICK:
        return "left click"
    if action_type == ActionType.DOUBLE_CLICK:
        return "double left click"
    if action_type == ActionType.RIGHT_CLICK:
        return "right click"
    raise ValueError(f"Unsupported click action: {action_type.value}")


def _image_to_png_base64(image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
