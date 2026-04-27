"""
Stream-event status and terminal transcript policy for CLIAgent.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


def safe_preview(value: object, max_len: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def format_tool_status(
    *,
    tool_name: str,
    parameters: dict[str, Any],
    safe_preview_fn: Callable[[object, int], str] = safe_preview,
) -> str:
    name = (tool_name or "tool").strip()
    friendly = name.replace("_", " ")

    if name in {"run_shell_command", "shell", "bash"}:
        command = safe_preview_fn(
            parameters.get("command") or parameters.get("cmd") or parameters.get("script"),
            120,
        )
        return f"Running shell command: {command}" if command else "Running shell command..."

    if name in {"read_file", "cat"}:
        path = safe_preview_fn(parameters.get("file_path") or parameters.get("path"), 96)
        if path:
            return f"Reading file: {path}"
        return "Reading files..."

    if name in {"write_file", "edit"}:
        path = safe_preview_fn(parameters.get("file_path") or parameters.get("path"), 96)
        if path:
            return f"Updating file: {path}"
        return "Updating files..."

    if name in {"ls", "glob", "grep", "ripgrep"}:
        path = safe_preview_fn(parameters.get("path") or parameters.get("query"), 96)
        if path:
            return f"{friendly.title()}: {path}"
        return f"{friendly.title()}..."

    return f"Using {friendly}..."


def status_from_stream_event(
    *,
    event: dict[str, Any],
    tool_by_id: dict[str, str],
    safe_preview_fn: Callable[[object, int], str] = safe_preview,
    format_tool_status_fn: Callable[..., str] = format_tool_status,
) -> str | None:
    event_type = event.get("type")
    if not event_type:
        return None

    if event_type == "init":
        return "CLI session started..."

    if event_type == "tool_use":
        tool_name = str(event.get("tool_name") or "tool")
        tool_id = event.get("tool_id")
        if isinstance(tool_id, str) and tool_id:
            tool_by_id[tool_id] = tool_name
        params = event.get("parameters")
        if not isinstance(params, dict):
            params = {}
        return format_tool_status_fn(
            tool_name=tool_name,
            parameters=params,
            safe_preview_fn=safe_preview_fn,
        )

    if event_type == "tool_result":
        tool_id = event.get("tool_id")
        tool_name = tool_by_id.get(str(tool_id), "tool")
        if event.get("status") == "error":
            err = event.get("error")
            if isinstance(err, dict):
                err_msg = safe_preview_fn(err.get("message"), 72)
            else:
                err_msg = safe_preview_fn(err, 72)
            if err_msg:
                return f"{tool_name.replace('_', ' ').title()} failed: {err_msg}"
            return f"{tool_name.replace('_', ' ').title()} failed."
        return f"Finished {tool_name.replace('_', ' ')}."

    if event_type == "error":
        msg = safe_preview_fn(event.get("message"), 96)
        if msg:
            return f"CLI error: {msg}"
        return "CLI error."

    if event_type == "result":
        if event.get("status") == "success":
            return "Finalizing CLI response..."
        err = event.get("error")
        if isinstance(err, dict):
            err_msg = safe_preview_fn(err.get("message"), 80)
        else:
            err_msg = safe_preview_fn(err, 80)
        if err_msg:
            return f"CLI task failed: {err_msg}"
        return "CLI task failed."

    return None


async def emit_terminal_stream_event(
    *,
    session_id: str,
    event: dict[str, Any],
    tool_by_id: dict[str, str],
    shell_command_by_id: dict[str, str],
    emit_terminal_event: Callable[..., Awaitable[None]],
    is_shell_tool_name: Callable[[str], bool],
    safe_preview_fn: Callable[[object, int], str] = safe_preview,
    stringify_terminal_value_fn: Callable[[Any], str],
) -> None:
    event_type = event.get("type")
    if event_type == "init":
        await emit_terminal_event(
            session_id,
            kind="session_started",
            text="CLI session started.",
            status="running",
        )
        return

    if event_type == "tool_use":
        tool_name = str(event.get("tool_name") or "tool")
        tool_id = str(event.get("tool_id") or "")
        if not is_shell_tool_name(tool_name):
            return
        params = event.get("parameters")
        if not isinstance(params, dict):
            params = {}
        command = safe_preview_fn(
            params.get("command") or params.get("cmd") or params.get("script"),
            400,
        )
        if tool_id and command:
            shell_command_by_id[tool_id] = command
        await emit_terminal_event(
            session_id,
            kind="command_started",
            shell_command=command,
            text=command or "Running shell command...",
            status="running",
        )
        return

    if event_type == "tool_result":
        tool_id = str(event.get("tool_id") or "")
        tool_name = tool_by_id.get(tool_id, "tool")
        if not is_shell_tool_name(tool_name):
            return
        command = shell_command_by_id.get(tool_id, "")
        output_text = stringify_terminal_value_fn(event.get("output"))
        error_text = stringify_terminal_value_fn(event.get("error"))
        if event.get("status") == "error":
            await emit_terminal_event(
                session_id,
                kind="command_output",
                shell_command=command,
                text=error_text or "Shell command failed without captured stderr.",
                status="error",
            )
            return

        await emit_terminal_event(
            session_id,
            kind="command_output",
            shell_command=command,
            text=output_text or "(command completed with no output)",
            status="success",
        )
        return

    if event_type == "error":
        await emit_terminal_event(
            session_id,
            kind="session_error",
            text=safe_preview_fn(event.get("message"), 240) or "CLI session failed.",
            status="error",
        )
        return

    if event_type == "result":
        status = "success" if event.get("status") == "success" else "error"
        error = event.get("error")
        if isinstance(error, dict):
            result_text = safe_preview_fn(error.get("message"), 240)
        else:
            result_text = safe_preview_fn(error, 240)
        await emit_terminal_event(
            session_id,
            kind="session_finished" if status == "success" else "session_error",
            text=result_text or ("CLI session finished." if status == "success" else "CLI session failed."),
            status=status,
        )
