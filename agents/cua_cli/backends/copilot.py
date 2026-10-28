"""
GitHub Copilot CLI backend (``copilot``), used for delegated coding tasks.

Uses the user's GitHub Copilot login. The prompt is read from stdin and
``--output-format json`` prints one event per line. ``--allow-all-tools`` is
required for non-interactive runs; ``--deny-tool`` rules take precedence.
Copilot shell rules match commands, not flags, so full-trust mode only denies
flag-free commands.
"""

from __future__ import annotations

import re
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
from agents.cua_cli.backends.safety_policy import command_words, denied_command_prefixes

_SHELL_TOOLS = {"bash", "powershell", "shell"}
_SHELL_ID_TRAILER = re.compile(r"\n?<shellId: [^>]*>\s*$")


def denied_shell_rules(*, full_trust: bool) -> list[str]:
    rules: list[str] = []
    for prefix in denied_command_prefixes(full_trust=full_trust):
        words = command_words(prefix)
        if full_trust and words != prefix:
            # Denying the bare command would block far more than the flagged form.
            continue
        rule = f"shell({words})"
        if words and rule not in rules:
            rules.append(rule)
    return rules


def _tool_parameters(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool in _SHELL_TOOLS:
        return {"command": arguments.get("command", ""), "description": arguments.get("description", "")}
    if tool in {"view", "create", "edit"}:
        return {"file_path": arguments.get("path") or ""}
    return dict(arguments)


class CopilotBackend(CodingBackend):
    name = "copilot"
    display_name = "GitHub Copilot CLI"
    executable_names = ("copilot",)
    bin_env_var = "JARVIS_COPILOT_BIN"
    model_env_var = "JARVIS_COPILOT_MODEL"

    def build_args(self, request: BackendRequest) -> list[str]:
        # Copilot otherwise starts its interactive UI even with piped stdin.
        # Keep the user's request on stdin; only this fixed instruction is in argv.
        args = ["--prompt", "Follow the user request provided on standard input.",
                "--output-format", "json", "--allow-all-tools"]
        if request.answer_only:
            # --available-tools= does not hide Copilot's tools, so deny the side-effecting ones.
            args.extend(["--deny-tool", "shell", "--deny-tool", "write"])
            model = request.model or self.default_model()
            return args + (["--model", model] if model else [])
        for rule in denied_shell_rules(full_trust=request.full_trust):
            args.extend(["--deny-tool", rule])
        for directory in request.workspace_dirs:
            if directory != request.cwd:
                args.extend(["--add-dir", directory])
        model = request.model or self.default_model()
        if model:
            args.extend(["--model", model])
        return args

    def normalize_event(self, raw: dict[str, Any], state: NormalizationState) -> list[dict[str, Any]]:
        if raw.get("ephemeral"):
            return []
        event_type = str(raw.get("type") or "")
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        events: list[dict[str, Any]] = []

        if not state.started and event_type in {"user.message", "assistant.turn_start"}:
            state.started = True
            events.append({"type": "init"})

        if event_type == "assistant.message":
            text = str(data.get("content") or "").strip()
            if text:
                events.append(message_event(text))
        elif event_type == "tool.execution_start":
            tool = str(data.get("toolName") or "tool")
            arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
            name = SHELL_TOOL_NAME if tool in _SHELL_TOOLS else {"view": "read_file", "create": "write_file"}.get(tool, tool)
            events.append(tool_use_event(name, str(data.get("toolCallId") or ""), _tool_parameters(tool, arguments)))
        elif event_type == "tool.execution_complete":
            result = data.get("result") if isinstance(data.get("result"), dict) else {}
            output = _SHELL_ID_TRAILER.sub("", str(result.get("content") or ""))
            error = data.get("error")
            error_text = str(error.get("message") if isinstance(error, dict) else error or "") or None
            events.append(
                tool_result_event(str(data.get("toolCallId") or ""), success=bool(data.get("success")), output=output, error=error_text)
            )
        elif event_type == "result":
            state.finished = True
            success = raw.get("exitCode") == 0
            if not success:
                state.failed = True
            events.append(result_event(success=success, error=f"Copilot exited with code {raw.get('exitCode')}"))
        elif event_type.endswith(".error") or event_type == "error":
            message = str(data.get("message") or raw.get("message") or "Copilot reported an error.")
            state.failed = True
            events.append({"type": "error", "message": message})
        return events
