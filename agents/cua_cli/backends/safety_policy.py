"""
Shell-command deny rules shared by every coding backend.

Rules are command prefixes. Each backend renders them in its own permission
syntax, and every backend's deny rules take precedence over its allow rules.
Scoped mode (the default) blocks destructive and publishing commands; full-trust
mode (``JARVIS_CLI_FULL_TRUST``) still blocks machine-level destruction.
"""

from __future__ import annotations

FULL_TRUST_DENIED_PREFIXES: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    "format",
    "diskpart",
    "dd",
    "shutdown",
    "reboot",
    "Stop-Computer",
    "Restart-Computer",
)

SCOPED_DENIED_PREFIXES: tuple[str, ...] = FULL_TRUST_DENIED_PREFIXES + (
    "rm -rf",
    "rm -fr",
    "rm -r",
    "rmdir /s",
    "rd /s",
    "del /s",
    "Remove-Item",
    "git push",
    "git reset --hard",
    "git clean",
    "git checkout --",
    "sudo",
    "reg delete",
)


def denied_command_prefixes(*, full_trust: bool) -> tuple[str, ...]:
    return FULL_TRUST_DENIED_PREFIXES if full_trust else SCOPED_DENIED_PREFIXES


def command_words(prefix: str) -> str:
    """The prefix without flags, e.g. ``git reset --hard`` -> ``git reset``."""
    words = [word for word in prefix.split() if not word.startswith(("-", "/"))]
    return " ".join(words[:2])
