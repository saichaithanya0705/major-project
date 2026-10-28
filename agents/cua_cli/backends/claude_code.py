"""
Claude Code backend (``claude -p``), used for delegated coding tasks.

Uses the user's own Claude Code login. The prompt is read from stdin and
``--output-format stream-json --verbose`` yields one JSON event per line.
"""

from __future__ import annotations

from typing import Any

from agents.cua_cli.backends.base import (
    SHELL_TOOL_NAME,
    BackendRequest,
    CodingBackend,
    NormalizationState,
    message_event,
    result_event,
    tool_result_event,
    tool_use_event,
)
from agents.cua_cli.backends.safety_policy import denied_command_prefixes

ALLOWED_TOOLS = ("Bash", "Read", "Edit", "MultiEdit", "Write", "Glob", "Grep", "LS", "TodoWrite")

_TOOL_NAMES = {
    "Bash": SHELL_TOOL_NAME,
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Glob": "glob",
    "Grep": "grep",
}


def _tool_parameters(tool: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    if tool == "Bash":
        return {"command": raw_input.get("command", ""), "description": raw_input.get("description", "")}
    if tool in {"Read", "Write", "Edit", "MultiEdit"}:
        return {"file_path": raw_input.get("file_path") or ""}
    if tool in {"Glob", "Grep"}:
        return {"path": raw_input.get("path") or "", "query": raw_input.get("pattern") or ""}
    return dict(raw_input)


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return "" if content is None else str(content)


class ClaudeCodeBackend(CodingBackend):
    name = "claude"
    display_name = "Claude Code"
    executable_names = ("claude",)
    bin_env_var = "JARVIS_CLAUDE_BIN"
    model_env_var = "JARVIS_CLAUDE_MODEL"

    def build_args(self, request: BackendRequest) -> list[str]:
        if request.answer_only:
            args = ["-p", "--output-format", "stream-json", "--verbose", "--tools", "", "--strict-mcp-config"]
            model = request.model or self.default_model()
            return args + (["--model", model] if model else [])
        args = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            *ALLOWED_TOOLS,
            "--disallowedTools",
            *(f"Bash({prefix}:*)" for prefix in denied_command_prefixes(full_trust=request.full_trust)),
        ]
        for directory in request.workspace_dirs:
            if directory != request.cwd:
                args.extend(["--add-dir", directory])
        model = request.model or self.default_model()
        if model:
            args.extend(["--model", model])
        return args

    def normalize_event(self, raw: dict[str, Any], state: NormalizationState) -> list[dict[str, Any]]:
        event_type = raw.get("type")
        events: list[dict[str, Any]] = []

        if event_type == "system" and raw.get("subtype") == "init":
            state.started = True
            return [{"type": "init"}]

        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []

        if event_type == "assistant":
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and str(block.get("text") or "").strip():
                    events.append(message_event(str(block["text"]).strip()))
                elif block.get("type") == "tool_use":
                    tool = str(block.get("name") or "tool")
                    raw_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                    events.append(
                        tool_use_event(_TOOL_NAMES.get(tool, tool), str(block.get("id") or ""), _tool_parameters(tool, raw_input))
                    )
        elif event_type == "user":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    text = _tool_result_text(block.get("content"))
                    events.append(
                        tool_result_event(
                            str(block.get("tool_use_id") or ""),
                            success=not block.get("is_error"),
                            output=text,
                            error=text or None,
                        )
                    )
        elif event_type == "result":
            state.finished = True
            success = raw.get("subtype") == "success" and not raw.get("is_error")
            if not success:
                state.failed = True
            events.append(result_event(success=success, error=str(raw.get("result") or raw.get("subtype") or "")))
        return events
