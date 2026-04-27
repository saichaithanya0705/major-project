"""
Checks for rapid-session state ownership boundary.

Usage:
    python tests/test_rapid_state_boundary.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.rapid_state import RapidSessionState


def run_checks() -> None:
    state = RapidSessionState(max_history=5)

    state.append_history(
        role="user",
        text="  hello  ",
        source="user",
        cleaner=lambda value: value.strip(),
    )
    state.append_history(
        role="assistant",
        text="step completed",
        source="cua_cli",
        cleaner=lambda value: value.strip(),
    )
    state.append_history(
        role="assistant",
        text="",
        source="rapid",
        cleaner=lambda value: value.strip(),
    )

    assert len(state.history) == 2, state.history
    prompt = state.format_history_for_prompt()
    assert "Conversation History (Rapid-Model Messages Only)" in prompt, prompt
    assert "User: hello" in prompt, prompt
    assert "Agent: step completed" in prompt, prompt


if __name__ == "__main__":
    run_checks()
    print("[test_rapid_state_boundary] All checks passed.")
