"""
OpenAI Codex CLI backend (``codex exec``), used for delegated coding tasks.

Runs on the user's own Codex login (ChatGPT sign-in or API key). ``codex exec -``
reads the prompt from stdin; ``--json`` prints one event per line. Codex has no
per-command deny list, so safety comes from its ``workspace-write`` sandbox,
with network access only in full-trust mode.
"""

from __future__ import annotations

import re
import shlex
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

_SHELL_WRAPPER = re.compile(r"^\S*(?:bash|sh|zsh)(?:\.exe)?\s+-l?c\s+(?P<script>.+)$", re.DOTALL)


def unwrap_shell_command(command: str) -> str:
    """``/bin/bash -lc 'npm test'`` -> ``npm test`` so command policies see the real command."""
    match = _SHELL_WRAPPER.match(command.strip())
    if not match:
        return command
    script = match.group("script").strip()
    try:
        parts = shlex.split(script)
    except ValueError:
        return script
    return parts[0] if len(parts) == 1 else script


class CodexBackend(CodingBackend):
    name = "codex"
    display_name = "Codex CLI"
    executable_names = ("codex",)
    bin_env_var = "JARVIS_CODEX_BIN"
    model_env_var = "JARVIS_CODEX_MODEL"

    def build_args(self, request: BackendRequest) -> list[str]:
        args = ["exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write"]
        if request.full_trust:
            args.extend(["-c", "sandbox_workspace_write.network_access=true"])
        for directory in request.workspace_dirs:
            if directory != request.cwd:
                args.extend(["--add-dir", directory])
        model = request.model or self.default_model()
        if model:
            args.extend(["--model", model])
        args.append("-")
        return args

    def normalize_event(self, raw: dict[str, Any], state: NormalizationState) -> list[dict[str, Any]]:
        event_type = raw.get("type")
        item = raw.get("item") if isinstance(raw.get("item"), dict) else {}
        item_type = item.get("type")
        item_id = str(item.get("id") or "")
        events: list[dict[str, Any]] = []

        if event_type == "thread.started":
            state.started = True
            return [{"type": "init"}]

        if event_type in {"item.started", "item.completed"} and item_type == "command_execution":
            if item_id not in state.announced_tools:
                state.announced_tools.add(item_id)
                command = unwrap_shell_command(str(item.get("command") or ""))
                events.append(tool_use_event(SHELL_TOOL_NAME, item_id, {"command": command}))
            if event_type == "item.completed":
                output = str(item.get("aggregated_output") or "")
                events.append(tool_result_event(item_id, success=item.get("exit_code") == 0, output=output))
        elif event_type == "item.completed" and item_type == "file_change":
            changes = item.get("changes") if isinstance(item.get("changes"), list) else []
            paths = ", ".join(str(change.get("path") or "") for change in changes if isinstance(change, dict))
            events.append(tool_use_event("write_file", item_id, {"file_path": paths}))
            events.append(tool_result_event(item_id, success=item.get("status") != "failed", output=paths))
        elif event_type == "item.completed" and item_type == "agent_message":
            text = str(item.get("text") or "").strip()
            if text:
                events.append(message_event(text))
        elif event_type == "turn.completed":
            state.finished = True
            events.append(result_event(success=True))
        elif event_type in {"turn.failed", "error"}:
            error = raw.get("error")
            message = str(error.get("message") if isinstance(error, dict) else raw.get("message") or error or "")
            state.failed = True
            state.finished = event_type == "turn.failed"
            events.append({"type": "error", "message": message or "Codex reported an error."})
            if state.finished:
                events.append(result_event(success=False, error=message))
        # Codex reports non-fatal warnings as ``item.completed`` items of type
        # "error"; they do not end the turn, so they are not surfaced as failures.
        return events
