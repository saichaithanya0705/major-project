"""
Workspace-scoping policy helpers for CLIAgent tasks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def compute_workspace_dirs() -> list[str]:
    """
    Include common directories so workspace-scoped tools (ls/glob/read/write)
    can operate beyond the gemini-cli subfolder.
    """
    paths = [
        str(Path.cwd().resolve()),
        str(Path.home().resolve()),
        str((Path.home() / "Desktop").resolve()),
        "/tmp",
    ]
    deduped: list[str] = []
    for path in paths:
        if path not in deduped and Path(path).exists():
            deduped.append(path)
    return deduped


def task_requests_terminal_execution(task: str) -> bool:
    lowered = (task or "").lower()
    markers = (
        "terminal",
        "shell",
        "powershell",
        "pwsh",
        "bash",
        "cmd",
        "command prompt",
    )
    return any(marker in lowered for marker in markers)


def extract_drive_roots_from_task(task: str) -> list[str]:
    roots: list[str] = []
    for match in re.finditer(r"\b([a-zA-Z])\s*(?::)?\s*drive\b", task or "", flags=re.IGNORECASE):
        root = f"{match.group(1).upper()}:\\"
        if Path(root).exists() and root not in roots:
            roots.append(root)
    return roots


def extract_path_candidates_from_task(task: str) -> list[str]:
    if not task:
        return []

    candidates: list[str] = []

    for pattern in (r"`([^`]+)`", r"'([^']+)'", r'"([^"]+)"'):
        for match in re.finditer(pattern, task, flags=re.DOTALL):
            candidate = match.group(1).strip()
            if candidate and any(token in candidate for token in ("\\", "/", ":")):
                candidates.append(candidate)

    path_scan_text = re.sub(r"https?://[^\s,;]+", " ", task, flags=re.IGNORECASE)
    raw_matches = re.findall(
        r"(?<!\w)(~\/[^\s,;]+|\/[^\s,;]+|[A-Za-z]:\\[^\n\r\t]+|\\\\[^\n\r\t]+)",
        path_scan_text,
    )
    for raw in raw_matches:
        candidate = str(raw).strip().strip(".,;:()[]{}'\"`")
        if candidate:
            candidates.append(candidate)

    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def nearest_existing_workspace_scope(path_expr: str) -> str | None:
    if not path_expr:
        return None

    expanded = os.path.expandvars(os.path.expanduser(path_expr.strip().strip("'\"`")))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path.cwd().resolve() / candidate

    probe = candidate
    while True:
        if probe.exists():
            directory = probe if probe.is_dir() else probe.parent
            try:
                return str(directory.resolve())
            except Exception:
                return str(directory)

        parent = probe.parent
        if parent == probe:
            return None
        probe = parent


def dedupe_workspace_dirs(paths: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        try:
            normalized = str(Path(raw).resolve())
        except Exception:
            normalized = os.path.abspath(raw)
        key = os.path.normcase(os.path.normpath(normalized))
        if key in seen or not Path(normalized).exists():
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def workspace_dirs_for_task(base_workspace_dirs: list[str], task: str) -> list[str]:
    scoped_paths: list[str] = list(base_workspace_dirs)
    scoped_paths.extend(extract_drive_roots_from_task(task))

    for candidate in extract_path_candidates_from_task(task):
        scope = nearest_existing_workspace_scope(candidate)
        if scope:
            scoped_paths.append(scope)

    return dedupe_workspace_dirs(scoped_paths)
