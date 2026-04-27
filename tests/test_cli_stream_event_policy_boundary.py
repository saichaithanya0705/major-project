"""
Checks for extracted CLI stream-event policy helpers.

Usage:
    python tests/test_cli_stream_event_policy_boundary.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.stream_event_policy import (
    emit_terminal_stream_event,
    format_tool_status,
    safe_preview,
    status_from_stream_event,
)


async def run_checks() -> None:
    assert safe_preview("hello", 10) == "hello"
    assert safe_preview("x" * 20, 8).endswith("…")

    status = format_tool_status(
        tool_name="run_shell_command",
        parameters={"command": "echo hello"},
    )
    assert "Running shell command" in status, status

    tool_by_id: dict[str, str] = {}
    status = status_from_stream_event(
        event={"type": "tool_use", "tool_name": "write_file", "tool_id": "t1", "parameters": {"file_path": "a.py"}},
        tool_by_id=tool_by_id,
    )
    assert "Updating file" in str(status), status
    assert tool_by_id.get("t1") == "write_file", tool_by_id

    status = status_from_stream_event(
        event={"type": "tool_result", "tool_id": "t1", "status": "error", "error": {"message": "blocked"}},
        tool_by_id=tool_by_id,
    )
    assert "failed" in str(status).lower(), status

    emitted: list[dict] = []

    async def _emit_terminal_event(session_id: str, **payload):
        emitted.append({"session_id": session_id, **payload})

    shell_command_by_id: dict[str, str] = {}

    await emit_terminal_stream_event(
        session_id="s1",
        event={"type": "init"},
        tool_by_id={},
        shell_command_by_id=shell_command_by_id,
        emit_terminal_event=_emit_terminal_event,
        is_shell_tool_name=lambda name: name in {"run_shell_command", "shell", "bash"},
        stringify_terminal_value_fn=lambda value: "" if value is None else str(value),
    )
    assert emitted[-1]["kind"] == "session_started", emitted

    await emit_terminal_stream_event(
        session_id="s1",
        event={
            "type": "tool_use",
            "tool_name": "run_shell_command",
            "tool_id": "cmd1",
            "parameters": {"command": "echo hi"},
        },
        tool_by_id={"cmd1": "run_shell_command"},
        shell_command_by_id=shell_command_by_id,
        emit_terminal_event=_emit_terminal_event,
        is_shell_tool_name=lambda name: name in {"run_shell_command", "shell", "bash"},
        stringify_terminal_value_fn=lambda value: "" if value is None else str(value),
    )
    assert emitted[-1]["kind"] == "command_started", emitted
    assert shell_command_by_id.get("cmd1"), shell_command_by_id

    await emit_terminal_stream_event(
        session_id="s1",
        event={"type": "tool_result", "tool_id": "cmd1", "status": "success", "output": "ok"},
        tool_by_id={"cmd1": "run_shell_command"},
        shell_command_by_id=shell_command_by_id,
        emit_terminal_event=_emit_terminal_event,
        is_shell_tool_name=lambda name: name in {"run_shell_command", "shell", "bash"},
        stringify_terminal_value_fn=lambda value: "" if value is None else str(value),
    )
    assert emitted[-1]["kind"] == "command_output", emitted
    assert emitted[-1]["status"] == "success", emitted


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_cli_stream_event_policy_boundary] All checks passed.")
