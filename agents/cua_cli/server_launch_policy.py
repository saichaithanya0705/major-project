"""
Server-launch intent and command inference policy for CLIAgent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def extract_explicit_shell_command(task: str) -> str | None:
    if not task:
        return None

    backtick = re.search(r"`([^`]+)`", task, flags=re.DOTALL)
    if backtick:
        command = backtick.group(1).strip()
        return command if command else None

    prefixed = re.search(
        r"(?:^|\n)\s*command\s*:\s*(.+)$",
        task,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if prefixed:
        command = prefixed.group(1).strip()
        return command if command else None

    run_line = re.match(r"^\s*(?:run|start|launch)\s+(.+)$", task.strip(), flags=re.IGNORECASE)
    if run_line:
        candidate = run_line.group(1).strip()
        if any(
            token in candidate
            for token in ("npm ", "pnpm ", "yarn ", "python", "uvicorn", "node ", "flask")
        ):
            return candidate

    return None


def is_server_like_command(command: str) -> bool:
    c = command.lower()
    patterns = [
        r"\bnpm\s+run\s+(dev|start|serve)\b",
        r"\bnpm\s+(start|serve)\b",
        r"\bpnpm\s+(dev|start|serve)\b",
        r"\byarn\s+(dev|start|serve)\b",
        r"\bnext\s+dev\b",
        r"\bvite\b",
        r"\bwebpack-dev-server\b",
        r"\buvicorn\b",
        r"\bflask\s+run\b",
        r"\bpython(?:3)?\s+-m\s+http\.server\b",
        r"\bnode\s+.+\b(server|dev)\b",
        r"\bgunicorn\b",
    ]
    return any(re.search(p, c) for p in patterns)


def is_background_intent_task(task: str, command: str) -> bool:
    text = (task or "").lower()
    intent_markers = [
        "localhost",
        "port ",
        "dev server",
        "web server",
        "api server",
        "keep running",
        "background",
        "until i stop",
    ]
    return is_server_like_command(command) or any(marker in text for marker in intent_markers)


def is_server_intent_text(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    markers = [
        "localhost",
        "127.0.0.1",
        "local server",
        "dev server",
        "web server",
        "api server",
        "npm start",
        "npm run dev",
        "pnpm dev",
        "yarn dev",
        "uvicorn",
        "flask run",
    ]
    if any(marker in lowered for marker in markers):
        return True
    return is_server_like_command(lowered)


def is_quick_server_launch_task(text: str) -> bool:
    """
    True only when the request is primarily "start/run existing local server".
    False for multi-step setup tasks (clone/install/build/etc.) that need longer runtime.
    """
    lowered = (text or "").lower()
    if not lowered:
        return False

    setup_markers = [
        "clone",
        "git ",
        "install",
        "dependency",
        "dependencies",
        "setup",
        "set up",
        "bootstrap",
        "scaffold",
        "build",
        "compile",
        "create",
        "download",
        "npm ci",
        "pip install",
        "pnpm install",
        "yarn install",
    ]
    if any(marker in lowered for marker in setup_markers):
        return False

    return is_server_intent_text(lowered)


def extract_port_candidates(text: str) -> list[int]:
    ports = set()
    for m in re.finditer(r"(?:localhost|127\.0\.0\.1)\s*:\s*(\d{2,5})", text, flags=re.IGNORECASE):
        ports.add(int(m.group(1)))
    for m in re.finditer(r"\bport\s+(\d{2,5})\b", text, flags=re.IGNORECASE):
        ports.add(int(m.group(1)))
    for m in re.finditer(r"--port(?:=|\s+)(\d{2,5})", text, flags=re.IGNORECASE):
        ports.add(int(m.group(1)))
    return sorted(p for p in ports if 1 <= p <= 65535)


def resolve_shell_path(path_expr: str, base_dir: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(path_expr.strip().strip("'\"")))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate.resolve()
    return (base_dir / candidate).resolve()


def extract_server_subcommand(command: str) -> str:
    segments = [segment.strip() for segment in re.split(r"\s*&&\s*", command) if segment.strip()]
    for segment in reversed(segments):
        if is_server_like_command(segment):
            return segment
    return command.strip()


def extract_shell_command_from_tool_call(tool_call: dict[str, Any]) -> str | None:
    if not isinstance(tool_call, dict):
        return None
    tool_name = str(tool_call.get("tool_name") or "").strip().lower()
    if tool_name not in {"run_shell_command", "shell", "bash"}:
        return None
    params = tool_call.get("parameters")
    if not isinstance(params, dict):
        return None
    raw = params.get("command") or params.get("cmd") or params.get("script")
    if raw is None:
        return None
    command = str(raw).strip()
    return command or None


def infer_server_launch_from_tool_calls(
    tool_calls: list[dict[str, Any]] | None,
    initial_cwd: Path | None = None,
) -> dict[str, str] | None:
    if not tool_calls:
        return None

    current_dir = (initial_cwd or Path.cwd()).resolve()
    candidate: dict[str, str] | None = None

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        if tool_call.get("status") == "error":
            continue

        command = extract_shell_command_from_tool_call(tool_call)
        if not command:
            continue

        cd_chain = re.match(
            r"^\s*cd\s+([^;&|]+?)\s*&&\s*(.+)$",
            command,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if cd_chain:
            cd_target = cd_chain.group(1).strip()
            remaining = cd_chain.group(2).strip()
            try:
                current_dir = resolve_shell_path(cd_target, current_dir)
            except Exception:
                pass
            if is_server_like_command(remaining):
                candidate = {
                    "command": extract_server_subcommand(remaining),
                    "cwd": str(current_dir),
                }
            continue

        cd_only = re.match(r"^\s*cd\s+(.+?)\s*$", command, flags=re.IGNORECASE | re.DOTALL)
        if cd_only:
            try:
                current_dir = resolve_shell_path(cd_only.group(1), current_dir)
            except Exception:
                pass
            continue

        if is_server_like_command(command):
            candidate = {
                "command": extract_server_subcommand(command),
                "cwd": str(current_dir),
            }

    return candidate
