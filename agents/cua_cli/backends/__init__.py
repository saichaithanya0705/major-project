"""
Coding-agent CLI backends for CLIAgent.

Shell and desktop tasks run on the local backend (``JARVIS_CLI_BACKEND``,
default opencode). Coding tasks are delegated to the first installed backend in
``JARVIS_CODING_BACKENDS`` (default ``claude,codex,copilot,opencode``) unless
``JARVIS_CODING_DELEGATION=off``.
"""

from __future__ import annotations

import os
import re

from agents.cua_cli.backends.base import (
    BackendInvocation,
    BackendRequest,
    BackendUnavailableError,
    BackendUnsafeArgumentsError,
    CodingBackend,
    NormalizationState,
    looks_like_auth_failure,
)
from agents.cua_cli.backends.claude_code import ClaudeCodeBackend
from agents.cua_cli.backends.codex import CodexBackend
from agents.cua_cli.backends.copilot import CopilotBackend
from agents.cua_cli.backends.opencode import OpencodeBackend

BACKENDS: dict[str, type[CodingBackend]] = {
    OpencodeBackend.name: OpencodeBackend,
    ClaudeCodeBackend.name: ClaudeCodeBackend,
    CodexBackend.name: CodexBackend,
    CopilotBackend.name: CopilotBackend,
}

DEFAULT_LOCAL_BACKEND = OpencodeBackend.name
DEFAULT_CODING_BACKENDS = (
    ClaudeCodeBackend.name,
    CodexBackend.name,
    CopilotBackend.name,
    OpencodeBackend.name,
)

_CODING_TASK_PATTERNS = (
    r"\b(?:code|coding|codebase|source code|repo|repository|project)\b",
    r"\b(?:refactor|debug|bug|bugs|stack ?trace|traceback|exception|compile|compiler)\b",
    r"\b(?:implement|unit tests?|test suite|failing tests?|lint|linter|type ?check)\b",
    r"\b(?:function|class|method|module|api|endpoint|feature|pull request|commit)\b",
    r"\b(?:python|javascript|typescript|react|node\.?js|java|kotlin|rust|golang|c\+\+|c#|html|css|sql)\b",
    r"\.(?:py|js|jsx|ts|tsx|java|kt|rs|go|cpp|cc|c|h|cs|rb|php|swift|vue|svelte)\b",
)


def is_coding_task(task: str) -> bool:
    text = " ".join(str(task or "").split()).lower()
    return any(re.search(pattern, text) for pattern in _CODING_TASK_PATTERNS)


def _backend_names_from_env(name: str, default: tuple[str, ...]) -> list[str]:
    raw = os.getenv(name, "").strip()
    names = [part.strip().lower() for part in raw.split(",") if part.strip()] if raw else list(default)
    unknown = [entry for entry in names if entry not in BACKENDS]
    if unknown:
        raise ValueError(f"{name} names unknown backend(s): {', '.join(unknown)}. Known: {', '.join(BACKENDS)}")
    return names


def coding_delegation_enabled() -> bool:
    return os.getenv("JARVIS_CODING_DELEGATION", "auto").strip().lower() not in {"off", "0", "false", "no"}


def backend_chain_for_task(task: str) -> list[CodingBackend]:
    """Backends to try in order. Later entries are only used if earlier ones cannot start."""
    local = _backend_names_from_env("JARVIS_CLI_BACKEND", (DEFAULT_LOCAL_BACKEND,))[:1]
    if coding_delegation_enabled() and is_coding_task(task):
        names = _backend_names_from_env("JARVIS_CODING_BACKENDS", DEFAULT_CODING_BACKENDS)
    else:
        names = local
    return [BACKENDS[name]() for name in names]


__all__ = [
    "BACKENDS",
    "BackendInvocation",
    "BackendRequest",
    "BackendUnavailableError",
    "BackendUnsafeArgumentsError",
    "CodingBackend",
    "NormalizationState",
    "backend_chain_for_task",
    "coding_delegation_enabled",
    "is_coding_task",
    "looks_like_auth_failure",
]
