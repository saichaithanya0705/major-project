"""
Safe direct command routing for trivial CLI tasks.

This module intentionally recognizes only read-only, bounded commands. Anything
outside this narrow set stays on the Gemini CLI path where the agent can reason
about intent, tooling, and policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DirectCommand:
    argv: list[str]
    display: str
    timeout_seconds: int = 30


_HOST_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
_VERSION_COMMANDS = {"python", "node", "npm", "git"}


def _has_shell_control(text: str) -> bool:
    return bool(re.search(r"&&|\|\||[;|<>`$]", text or ""))


def _host(value: str) -> str:
    cleaned = str(value or "").strip().strip(".,);]}")
    if not re.fullmatch(_HOST_PATTERN, cleaned):
        return ""
    return cleaned


def _from_command_text(command: str) -> DirectCommand | None:
    text = " ".join(str(command or "").split()).strip()
    if not text or _has_shell_control(text):
        return None

    ping = re.fullmatch(
        rf"ping(?:\s+-n\s+(\d{{1,2}}))?\s+({_HOST_PATTERN})",
        text,
        flags=re.IGNORECASE,
    )
    if ping:
        count = ping.group(1)
        target = _host(ping.group(2))
        if not target:
            return None
        argv = ["ping"]
        if count:
            bounded_count = max(1, min(int(count), 10))
            argv.extend(["-n", str(bounded_count)])
        argv.append(target)
        return DirectCommand(argv=argv, display=" ".join(argv), timeout_seconds=25)

    ipconfig = re.fullmatch(r"ipconfig(?:\s+/all)?", text, flags=re.IGNORECASE)
    if ipconfig:
        argv = text.split()
        return DirectCommand(argv=argv, display=" ".join(argv), timeout_seconds=15)

    lookup = re.fullmatch(r"(nslookup|tracert)\s+(" + _HOST_PATTERN + r")", text, flags=re.IGNORECASE)
    if lookup:
        tool = lookup.group(1).lower()
        target = _host(lookup.group(2))
        if not target:
            return None
        return DirectCommand(argv=[tool, target], display=f"{tool} {target}", timeout_seconds=30)

    if re.fullmatch(r"(whoami|hostname)", text, flags=re.IGNORECASE):
        command_name = text.lower()
        return DirectCommand(argv=[command_name], display=command_name, timeout_seconds=10)

    version = re.fullmatch(r"(python|node|npm|git)\s+(--version|-v)", text, flags=re.IGNORECASE)
    if version:
        command_name = version.group(1).lower()
        flag = version.group(2)
        if command_name not in _VERSION_COMMANDS:
            return None
        return DirectCommand(argv=[command_name, flag], display=f"{command_name} {flag}", timeout_seconds=15)

    return None


def extract_safe_direct_command(task: str, explicit_command: str | None = None) -> DirectCommand | None:
    if explicit_command:
        return _from_command_text(explicit_command)

    text = " ".join(str(task or "").split()).strip()
    if not text or _has_shell_control(text):
        return None

    ping = re.search(
        rf"\bping\s+(?:the\s+)?(?P<host>{_HOST_PATTERN})\b",
        text,
        flags=re.IGNORECASE,
    )
    if ping:
        target = _host(ping.group("host"))
        if target:
            return DirectCommand(argv=["ping", target], display=f"ping {target}", timeout_seconds=25)

    for command_name in ("ipconfig", "whoami", "hostname"):
        if re.search(rf"\b{command_name}\b", text, flags=re.IGNORECASE):
            return DirectCommand(argv=[command_name], display=command_name, timeout_seconds=15)

    lookup = re.search(
        rf"\b(?P<tool>nslookup|tracert)\s+(?P<host>{_HOST_PATTERN})\b",
        text,
        flags=re.IGNORECASE,
    )
    if lookup:
        tool = lookup.group("tool").lower()
        target = _host(lookup.group("host"))
        if target:
            return DirectCommand(argv=[tool, target], display=f"{tool} {target}", timeout_seconds=30)

    return None
