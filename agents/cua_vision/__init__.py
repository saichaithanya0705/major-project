"""
CUA Vision Agent - Desktop control via screen understanding + mouse/keyboard.

The package exports are resolved lazily to avoid import-time coupling with
optional desktop dependencies during lightweight module imports and tests.
"""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "LOOK_AT_SCREEN_PROMPT",
    "TOOL_CONFIG",
    "VISION_AGENT_SYSTEM_PROMPT",
    "VISION_TOOLS",
    "VISION_TOOL_MAP",
    "VisionAgent",
    "WATCH_SCREEN_PROMPT",
    "click_double_left_click",
    "click_left_click",
    "click_right_click",
    "crop_and_search",
    "find_and_click_element",
    "get_memory",
    "go_to_element",
    "look_at_screen_and_respond",
    "move_cursor",
    "press_alt_hotkey",
    "press_ctrl_hotkey",
    "remember_information",
    "reset_state",
    "start_interact_with_screen",
    "tts_speak",
    "type_string",
    "watch_screen_and_respond",
]

_AGENT_EXPORTS = {
    "VisionAgent",
    "start_interact_with_screen",
    "look_at_screen_and_respond",
    "watch_screen_and_respond",
}
_TOOL_EXPORTS = {
    "VISION_TOOLS",
    "VISION_TOOL_MAP",
    "TOOL_CONFIG",
    "reset_state",
    "get_memory",
    "remember_information",
    "find_and_click_element",
    "go_to_element",
    "crop_and_search",
}
_KEYBOARD_EXPORTS = {
    "move_cursor",
    "type_string",
    "press_ctrl_hotkey",
    "press_alt_hotkey",
    "click_left_click",
    "click_double_left_click",
    "click_right_click",
}
_PROMPT_EXPORTS = {
    "VISION_AGENT_SYSTEM_PROMPT",
    "LOOK_AT_SCREEN_PROMPT",
    "WATCH_SCREEN_PROMPT",
}

if TYPE_CHECKING:
    from agents.cua_vision.agent import (
        VisionAgent,
        look_at_screen_and_respond,
        start_interact_with_screen,
        watch_screen_and_respond,
    )
    from agents.cua_vision.keyboard import (
        click_double_left_click,
        click_left_click,
        click_right_click,
        move_cursor,
        press_alt_hotkey,
        press_ctrl_hotkey,
        type_string,
    )
    from agents.cua_vision.prompts import (
        LOOK_AT_SCREEN_PROMPT,
        VISION_AGENT_SYSTEM_PROMPT,
        WATCH_SCREEN_PROMPT,
    )
    from agents.cua_vision.tools import (
        TOOL_CONFIG,
        VISION_TOOL_MAP,
        VISION_TOOLS,
        crop_and_search,
        find_and_click_element,
        get_memory,
        go_to_element,
        remember_information,
        reset_state,
    )
    from integrations.audio import tts_speak


def __getattr__(name: str):
    if name in _AGENT_EXPORTS:
        return getattr(import_module("agents.cua_vision.agent"), name)
    if name in _TOOL_EXPORTS:
        return getattr(import_module("agents.cua_vision.tools"), name)
    if name in _KEYBOARD_EXPORTS:
        return getattr(import_module("agents.cua_vision.keyboard"), name)
    if name in _PROMPT_EXPORTS:
        return getattr(import_module("agents.cua_vision.prompts"), name)
    if name == "tts_speak":
        return getattr(import_module("integrations.audio"), name)
    raise AttributeError(f"module 'agents.cua_vision' has no attribute '{name}'")
