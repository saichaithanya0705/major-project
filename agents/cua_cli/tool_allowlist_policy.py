"""
Non-interactive tool allowlist policy for CLIAgent.
"""

from __future__ import annotations

import re

from agents.cua_cli.server_launch_policy import (
    extract_explicit_shell_command,
    is_server_intent_text,
)
from agents.cua_cli.workspace_policy import task_requests_terminal_execution

EDIT_TOOL_NAMES = ("write_file", "replace")
SHELL_TOOL_NAME = "run_shell_command"
_UNRESTRICTED_APPROVAL_MODES = {"plan", "yolo"}

_SHELL_INTENT_PATTERNS = (
    r"\bclone\b",
    r"\bgit\b",
    r"\binstall\b",
    r"\btest(?:s|ing)?\b",
    r"\bbuild\b",
    r"\bcompile\b",
    r"\bscript\b",
    r"\bcreate\s+(?:a\s+)?(?:new\s+)?folder\b",
    r"\bmake\s+(?:a\s+)?(?:new\s+)?(?:directory|folder)\b",
    r"\bmkdir\b",
    r"\bmove\b",
    r"\bcopy\b",
    r"\brename\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bopen\s+(?:app|application|file|folder|directory)\b",
)


def task_requires_shell_tool(task: str) -> bool:
    """
    Return true when a CLI task needs shell/process capability, not just edit tools.
    """
    text = " ".join(str(task or "").split()).lower()
    if not text:
        return False
    if task_requests_terminal_execution(text):
        return True
    if extract_explicit_shell_command(text):
        return True
    if is_server_intent_text(text):
        return True
    return any(re.search(pattern, text) for pattern in _SHELL_INTENT_PATTERNS)


def allowed_tools_for_task(task: str, approval_mode: str) -> list[str]:
    """
    Tools to pass via Gemini CLI --allowed-tools for scoped non-interactive runs.
    """
    mode = str(approval_mode or "").strip().lower()
    if mode in _UNRESTRICTED_APPROVAL_MODES:
        return []

    tools = list(EDIT_TOOL_NAMES)
    if task_requires_shell_tool(task):
        tools.append(SHELL_TOOL_NAME)
    return tools
