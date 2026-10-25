"""
opencode backend (https://opencode.ai), the default local CLI agent.

Runs ``opencode run --format json`` with the prompt on stdin. Jarvis passes its
model and permission policy through ``OPENCODE_CONFIG_CONTENT``, which takes
precedence over global and project ``opencode.json`` files, so a project config
cannot loosen the deny rules. Permission rules that resolve to "ask" are
auto-rejected in non-interactive runs, so the policy only uses allow/deny.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.cua_cli.backends.base import (
    SHELL_TOOL_NAME,
    BackendInvocation,
    BackendRequest,
    BackendUnavailableError,
    CodingBackend,
    NormalizationState,
    message_event,
    result_event,
    tool_result_event,
    tool_use_event,
)
from agents.cua_cli.backends.safety_policy import denied_command_prefixes

DEFAULT_OPENCODE_MODEL = "ollama/nemotron-3.5-bolt"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
# setup.sh / setup.ps1 install the opencode version these normalizers were verified against here.
PINNED_INSTALL_BIN_DIR = Path(__file__).resolve().parents[3] / "integrations" / "opencode" / "node_modules" / ".bin"

_TOOL_NAMES = {
    "bash": SHELL_TOOL_NAME,
    "read": "read_file",
    "write": "write_file",
    "edit": "edit",
    "glob": "glob",
    "grep": "grep",
}


def _tool_parameters(tool: str, raw_input: dict[str, Any]) -> dict[str, Any]:
    if tool == "bash":
        return {"command": raw_input.get("command", ""), "description": raw_input.get("description", "")}
    if tool in {"read", "write", "edit"}:
        return {"file_path": raw_input.get("filePath") or raw_input.get("file_path") or ""}
    if tool in {"glob", "grep"}:
        return {"path": raw_input.get("path") or "", "query": raw_input.get("pattern") or ""}
    return dict(raw_input)


def ollama_base_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def ollama_is_reachable(base_url: str, timeout: float = 1.5) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_permission_policy(*, full_trust: bool) -> dict[str, Any]:
    bash_rules: dict[str, str] = {"*": "allow"}
    for prefix in denied_command_prefixes(full_trust=full_trust):
        bash_rules[f"{prefix}*"] = "deny"
    return {
        "edit": "allow",
        "bash": bash_rules,
        "webfetch": "allow",
        # Scoped mode keeps file tools inside the task's working directory.
        "external_directory": "allow" if full_trust else "deny",
    }


class OpencodeBackend(CodingBackend):
    name = "opencode"
    display_name = "opencode"
    executable_names = ("opencode",)
    bin_env_var = "JARVIS_OPENCODE_BIN"
    model_env_var = "JARVIS_OPENCODE_MODEL"

    def resolve_executable(self) -> list[str] | None:
        if not os.getenv(self.bin_env_var, "").strip():
            pinned = PINNED_INSTALL_BIN_DIR / ("opencode.cmd" if os.name == "nt" else "opencode")
            if pinned.exists():
                self.executable_names = (str(pinned),) + type(self).executable_names
        return super().resolve_executable()

    def default_model(self) -> str:
        return super().default_model() or DEFAULT_OPENCODE_MODEL

    def invocation(self, request: BackendRequest) -> BackendInvocation:
        model = request.model or self.default_model()
        # opencode retries an unreachable model until the task times out, so fail fast instead.
        if model.startswith("ollama/") and not ollama_is_reachable(ollama_base_url()):
            raise BackendUnavailableError(
                f"Ollama is not reachable at {ollama_base_url()}. Start it with `ollama serve` "
                f"and pull the model with `ollama pull {model.split('/', 1)[1]}`."
            )
        return super().invocation(request)

    def build_args(self, request: BackendRequest) -> list[str]:
        return ["run", "--format", "json", "--model", request.model or self.default_model()]

    def build_config(self, request: BackendRequest) -> dict[str, Any]:
        model = request.model or self.default_model()
        config: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "share": "disabled",
            "permission": build_permission_policy(full_trust=request.full_trust),
        }
        provider_id, _, model_id = model.partition("/")
        if provider_id == "ollama" and model_id:
            config["provider"] = {
                "ollama": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Ollama (local)",
                    "options": {"baseURL": f"{ollama_base_url()}/v1"},
                    "models": {model_id: {"name": model_id, "tool_call": True}},
                }
            }
            config["small_model"] = model
        return config

    def build_env(self, request: BackendRequest) -> dict[str, str]:
        env = super().build_env(request)
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(self.build_config(request))
        return env

    def normalize_event(self, raw: dict[str, Any], state: NormalizationState) -> list[dict[str, Any]]:
        event_type = raw.get("type")
        part = raw.get("part") if isinstance(raw.get("part"), dict) else {}
        events: list[dict[str, Any]] = []

        if not state.started:
            state.started = True
            events.append({"type": "init"})

        if event_type == "text":
            text = str(part.get("text") or "").strip()
            if text:
                events.append(message_event(text))
        elif event_type == "tool_use":
            tool = str(part.get("tool") or "tool")
            tool_id = str(part.get("callID") or part.get("id") or "")
            call_state = part.get("state") if isinstance(part.get("state"), dict) else {}
            raw_input = call_state.get("input") if isinstance(call_state.get("input"), dict) else {}
            events.append(tool_use_event(_TOOL_NAMES.get(tool, tool), tool_id, _tool_parameters(tool, raw_input)))
            status = str(call_state.get("status") or "")
            if status in {"completed", "error"}:
                events.append(
                    tool_result_event(
                        tool_id,
                        success=status == "completed",
                        output=str(call_state.get("output") or ""),
                        error=str(call_state.get("error") or "") or None,
                    )
                )
        elif event_type == "error":
            error = raw.get("error")
            message = ""
            if isinstance(error, dict):
                data = error.get("data") if isinstance(error.get("data"), dict) else {}
                message = str(data.get("message") or error.get("message") or error.get("name") or "")
            elif error:
                message = str(error)
            state.failed = True
            events.append({"type": "error", "message": message or "opencode reported an error."})
            events.append(result_event(success=False, error=message or "opencode reported an error."))
            state.finished = True
        return events
