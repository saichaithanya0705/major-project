"""
Shared contract for coding-agent CLI backends used by CLIAgent.

Every backend turns a task into a subprocess invocation and translates the
CLI's own JSONL event stream into the normalized events the rest of
``agents.cua_cli`` already understands:

    {"type": "init"}
    {"type": "message", "role": "assistant", "content": str, "delta": False}
    {"type": "tool_use", "tool_name": str, "tool_id": str, "parameters": dict}
    {"type": "tool_result", "tool_id": str, "status": "success"|"error",
     "output": str, "error": str | None}
    {"type": "error", "message": str}
    {"type": "result", "status": "success"|"error", "error": str | None}

Shell tools are normalized to ``run_shell_command`` with a ``command``
parameter so server-launch inference and terminal transcripts keep working.
"""

from __future__ import annotations

import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SHELL_TOOL_NAME = "run_shell_command"

# Characters cmd.exe interprets even inside an argument list. A batch-file shim
# re-parses its arguments through cmd.exe, so these must never reach one.
_BATCH_METACHARACTERS = re.compile(r'[&|<>^%!"\r\n]')
_NPM_SHIM_TARGET = re.compile(r'"%~?dp0%?\\(?P<target>[^"]+)"\s+%\*')

_AUTH_FAILURE_PATTERNS = (
    r"\bnot (?:logged|signed) in\b",
    r"\b(?:please )?(?:log ?in|sign ?in|authenticate)\b",
    r"\bunauthori[sz]ed\b",
    r"\b401\b",
    r"\binvalid (?:api[ _-]?key|token|credentials)\b",
    r"\bmissing (?:api[ _-]?key|token|credentials)\b",
    r"\bno (?:api[ _-]?key|credentials) (?:found|configured)\b",
)


class BackendUnavailableError(RuntimeError):
    """Raised when a backend cannot be launched on this machine."""


class BackendUnsafeArgumentsError(RuntimeError):
    """Raised when arguments would be re-parsed unsafely by a Windows batch shim."""


@dataclass(frozen=True)
class BackendRequest:
    prompt: str
    cwd: str
    workspace_dirs: tuple[str, ...] = ()
    model: str | None = None
    full_trust: bool = False
    # Answer-only runs get no shell, file-writing, or MCP tools: the CLI is used as a strong model.
    answer_only: bool = False


@dataclass(frozen=True)
class BackendInvocation:
    argv: list[str]
    env: dict[str, str]
    cwd: str
    # Prompts travel on stdin so user text never becomes a command-line argument.
    stdin_text: str


@dataclass
class NormalizationState:
    """Per-run scratch space for event normalizers."""

    started: bool = False
    finished: bool = False
    failed: bool = False
    announced_tools: set[str] = field(default_factory=set)
    extra: dict[str, Any] = field(default_factory=dict)


def message_event(text: str) -> dict[str, Any]:
    return {"type": "message", "role": "assistant", "content": text, "delta": False}


def tool_use_event(tool_name: str, tool_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "tool_name": tool_name, "tool_id": tool_id, "parameters": parameters}


def tool_result_event(
    tool_id: str,
    *,
    success: bool,
    output: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_id": tool_id,
        "status": "success" if success else "error",
        "output": output,
        "error": None if success else (error or output or "Tool call failed."),
    }


def result_event(*, success: bool, error: str | None = None) -> dict[str, Any]:
    return {
        "type": "result",
        "status": "success" if success else "error",
        "error": None if success else (error or "Task failed"),
    }


def looks_like_auth_failure(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(re.search(pattern, lowered) for pattern in _AUTH_FAILURE_PATTERNS)


def unwrap_npm_cmd_shim(shim_path: str, *, node: str | None = None) -> list[str] | None:
    """
    Resolve an npm-generated ``.cmd`` shim to the program it launches.

    Running the target directly keeps cmd.exe out of the argument path.
    """
    try:
        text = Path(shim_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _NPM_SHIM_TARGET.search(text)
    if not match:
        return None
    target = Path(shim_path).parent.joinpath(*match.group("target").split("\\"))
    if not target.exists():
        return None
    if target.suffix.lower() == ".exe":
        return [str(target)]
    node = node or shutil.which("node")
    if not node:
        return None
    return [node, str(target)]


def ensure_safe_for_batch_shim(argv: list[str], *, windows: bool | None = None) -> None:
    if not (os.name == "nt" if windows is None else windows) or not argv:
        return
    if not argv[0].lower().endswith((".cmd", ".bat")):
        return
    unsafe = [arg for arg in argv[1:] if _BATCH_METACHARACTERS.search(arg)]
    if unsafe:
        raise BackendUnsafeArgumentsError(
            f"Refusing to pass {len(unsafe)} argument(s) with shell metacharacters through "
            f"the batch shim {argv[0]}. Install the native executable or set the backend's "
            "*_BIN environment variable to it."
        )


class CodingBackend(ABC):
    """A coding-agent CLI that CLIAgent can drive non-interactively."""

    name: str = ""
    display_name: str = ""
    executable_names: tuple[str, ...] = ()
    bin_env_var: str = ""
    model_env_var: str = ""

    def resolve_executable(self) -> list[str] | None:
        configured = os.getenv(self.bin_env_var, "").strip() if self.bin_env_var else ""
        candidates = [configured] if configured else list(self.executable_names)
        for candidate in candidates:
            resolved = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
            if not resolved:
                continue
            if os.name == "nt" and resolved.lower().endswith(".cmd"):
                unwrapped = unwrap_npm_cmd_shim(resolved)
                if unwrapped:
                    return unwrapped
            return [resolved]
        return None

    def is_available(self) -> bool:
        return self.resolve_executable() is not None

    def default_model(self) -> str | None:
        if not self.model_env_var:
            return None
        return os.getenv(self.model_env_var, "").strip() or None

    def invocation(self, request: BackendRequest) -> BackendInvocation:
        executable = self.resolve_executable()
        if not executable:
            raise BackendUnavailableError(
                f"{self.display_name} is not installed or not on PATH"
                + (f" (set {self.bin_env_var} to its path)" if self.bin_env_var else "")
                + "."
            )
        argv = executable + self.build_args(request)
        ensure_safe_for_batch_shim(argv)
        return BackendInvocation(
            argv=argv,
            env=self.build_env(request),
            cwd=request.cwd,
            stdin_text=request.prompt,
        )

    def build_env(self, request: BackendRequest) -> dict[str, str]:
        del request
        return os.environ.copy()

    @abstractmethod
    def build_args(self, request: BackendRequest) -> list[str]:
        """Arguments after the executable. Never include user prompt text."""

    @abstractmethod
    def normalize_event(self, raw: dict[str, Any], state: NormalizationState) -> list[dict[str, Any]]:
        """Translate one raw JSONL event into zero or more normalized events."""

    def finalize(self, state: NormalizationState, returncode: int, stderr: str) -> list[dict[str, Any]]:
        """Emit a closing result when the CLI did not report one itself."""
        if state.finished:
            return []
        state.finished = True
        if returncode == 0 and not state.failed:
            return [result_event(success=True)]
        detail = " ".join(str(stderr or "").split())[-600:]
        return [result_event(success=False, error=detail or f"{self.display_name} exited with code {returncode}")]
