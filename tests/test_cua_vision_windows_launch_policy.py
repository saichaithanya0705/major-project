"""
Checks for Windows-first CUA vision app-launch guidance.

Usage:
    python tests/test_cua_vision_windows_launch_policy.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision import keyboard
from agents.cua_vision.prompts import VISION_AGENT_SYSTEM_PROMPT
from agents.cua_vision.single_call import SingleCallVisionEngine
from agents.cua_vision.tool_declarations import (
    VISION_DECLARED_TOOL_NAMES,
    press_alt_hotkey_declaration,
    press_ctrl_hotkey_declaration,
)
from agents.cua_vision.tools import VISION_TOOL_MAP


class _DummyAgent:
    retries = 0
    max_retries = 0


def run_checks() -> None:
    engine = SingleCallVisionEngine(_DummyAgent())
    step_prompt = engine._build_model_prompt(
        task="Open Notepad",
        active_window="Desktop",
        memory_text=[],
    )
    combined_prompt = f"{VISION_AGENT_SYSTEM_PROMPT}\n{step_prompt}"

    assert "Windows" in combined_prompt, combined_prompt
    assert "Google app" in combined_prompt, combined_prompt
    assert "Alt+Space" in combined_prompt, combined_prompt
    assert 'press_alt_hotkey(key="space"' in combined_prompt, combined_prompt
    assert "press_ctrl_hotkey" in combined_prompt, combined_prompt
    assert "open_windows_google_launcher" not in combined_prompt, combined_prompt
    assert "Command+Space" not in combined_prompt, combined_prompt
    assert "Spotlight" not in combined_prompt, combined_prompt
    assert "macOS" not in combined_prompt, combined_prompt

    assert "press_ctrl_hotkey" in VISION_DECLARED_TOOL_NAMES
    assert "press_alt_hotkey" in VISION_DECLARED_TOOL_NAMES
    assert "open_windows_google_launcher" not in VISION_DECLARED_TOOL_NAMES
    assert callable(VISION_TOOL_MAP["press_ctrl_hotkey"])
    assert callable(VISION_TOOL_MAP["press_alt_hotkey"])

    ctrl_description = press_ctrl_hotkey_declaration["description"]
    assert "Command" not in ctrl_description, ctrl_description
    assert "macOS" not in ctrl_description, ctrl_description
    assert "Control" in ctrl_description, ctrl_description

    alt_description = press_alt_hotkey_declaration["description"]
    assert "alt key" in alt_description.lower(), alt_description

    calls: list[tuple[str, ...]] = []

    class _FakePyAutoGui:
        def hotkey(self, *keys: str) -> None:
            calls.append(tuple(keys))

    original_pyautogui = keyboard.pyautogui
    keyboard.pyautogui = _FakePyAutoGui()
    try:
        keyboard.press_alt_hotkey("space")
        keyboard.press_ctrl_hotkey("l")
    finally:
        keyboard.pyautogui = original_pyautogui

    assert calls == [("alt", "space"), ("ctrl", "l")], calls


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_windows_launch_policy] All checks passed.")
