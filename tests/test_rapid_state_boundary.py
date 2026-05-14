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

    scoped_state = RapidSessionState(max_history=5)
    scoped_state.append_history(
        role="user",
        text="session alpha secret",
        source="user",
        cleaner=lambda value: value.strip(),
        session_id="chat-alpha",
    )
    scoped_state.append_history(
        role="user",
        text="session beta secret",
        source="user",
        cleaner=lambda value: value.strip(),
        session_id="chat-beta",
    )

    alpha_prompt = scoped_state.format_history_for_prompt(session_id="chat-alpha")
    beta_prompt = scoped_state.format_history_for_prompt(session_id="chat-beta")

    assert "session alpha secret" in alpha_prompt, alpha_prompt
    assert "session beta secret" not in alpha_prompt, alpha_prompt
    assert "session beta secret" in beta_prompt, beta_prompt
    assert "session alpha secret" not in beta_prompt, beta_prompt

    context_state = RapidSessionState(max_history=5)
    context_state.append_history(
        role="assistant",
        text="Substantive answer to preserve.",
        source="web_qa",
        cleaner=lambda value: value.strip(),
        session_id="chat-context",
    )
    context_state.append_history(
        role="assistant",
        text="The answer has been written to your desktop as context_dump.txt.",
        source="rapid",
        cleaner=lambda value: value.strip(),
        session_id="chat-context",
    )

    context = context_state.get_context("chat-context")
    assert context["last_assistant_message"] == "Substantive answer to preserve.", context

    enrichment_state = RapidSessionState(max_history=5)
    enrichment_state.record_assistant_context(
        role="assistant",
        text="Sourced answer that should only be copied for contextual requests.",
        source="web_qa",
        session_id="chat-enrichment",
    )

    non_contextual_write = {
        "agent": "cua_cli",
        "task": "write a README file on desktop",
    }
    non_contextual_result = enrichment_state.enrich_routing_result(
        non_contextual_write,
        user_prompt="write a README file on desktop",
        session_id="chat-enrichment",
    )
    assert non_contextual_result is non_contextual_write, non_contextual_result

    contextual_write = enrichment_state.enrich_routing_result(
        {"agent": "cua_cli", "task": "write it down in a file on desktop"},
        user_prompt="write it down in a file on desktop",
        session_id="chat-enrichment",
    )
    assert "Sourced answer that should only be copied" in contextual_write["task"], contextual_write

    artifact_state = RapidSessionState(max_history=5)
    artifact_state.record_step_context(
        {
            "success": True,
            "message": r"Read C:\Users\SAI\Desktop\notes.txt.",
            "tool_calls": [
                {
                    "tool_name": "read_file",
                    "parameters": {"file_path": r"C:\Users\SAI\Desktop\notes.txt"},
                    "status": "success",
                }
            ],
        },
        session_id="chat-artifact",
    )
    assert "last_file_path" not in artifact_state.get_context("chat-artifact")

    artifact_state.record_step_context(
        {
            "success": True,
            "message": r"The answer has been written to C:\Users\SAI\Desktop\context_dump.txt.",
            "tool_calls": [
                {
                    "tool_name": "write_file",
                    "parameters": {"file_path": r"C:\Users\SAI\Desktop\context_dump.txt"},
                    "status": "success",
                }
            ],
        },
        session_id="chat-artifact",
    )
    assert (
        artifact_state.get_context("chat-artifact")["last_file_path"]
        == r"C:\Users\SAI\Desktop\context_dump.txt"
    )

    artifact_state.append_history(
        role="user",
        text="give me the file name",
        source="user",
        cleaner=lambda value: value.strip(),
        session_id="chat-artifact",
    )
    artifact_prompt = artifact_state.format_history_for_prompt(session_id="chat-artifact")
    assert (
        r"C:\Users\SAI\Desktop\context_dump.txt" in artifact_prompt
    ), artifact_prompt

    contextual_open_from_vision = artifact_state.enrich_routing_result(
        {"agent": "cua_vision", "task": "open the file in vscode"},
        user_prompt="open the file in vscode",
        session_id="chat-artifact",
    )
    assert contextual_open_from_vision["agent"] == "cua_cli", contextual_open_from_vision
    assert (
        r"C:\Users\SAI\Desktop\context_dump.txt" in contextual_open_from_vision["task"]
    ), contextual_open_from_vision

    explicit_ui_action_stays_vision = artifact_state.enrich_routing_result(
        {"agent": "cua_vision", "task": "click the Extensions icon in VS Code"},
        user_prompt="click the Extensions icon in VS Code",
        session_id="chat-artifact",
    )
    assert explicit_ui_action_stays_vision["agent"] == "cua_vision", explicit_ui_action_stays_vision


if __name__ == "__main__":
    run_checks()
    print("[test_rapid_state_boundary] All checks passed.")
