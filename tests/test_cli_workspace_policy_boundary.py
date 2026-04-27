"""
Checks for extracted CLI workspace-policy helpers.

Usage:
    python tests/test_cli_workspace_policy_boundary.py
"""

import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.workspace_policy import (
    compute_workspace_dirs,
    dedupe_workspace_dirs,
    extract_drive_roots_from_task,
    extract_path_candidates_from_task,
    nearest_existing_workspace_scope,
    task_requests_terminal_execution,
    workspace_dirs_for_task,
)


def run_checks() -> None:
    dirs = compute_workspace_dirs()
    assert isinstance(dirs, list), dirs
    assert dirs, dirs

    assert task_requests_terminal_execution("Run this in powershell")
    assert not task_requests_terminal_execution("Open browser and click submit")

    drives = extract_drive_roots_from_task("Create a file in D drive and E drive")
    assert isinstance(drives, list), drives
    assert len(drives) == len(set(drives)), drives

    candidates = extract_path_candidates_from_task(
        r'Upload "C:\Users\SAI\Desktop\hw.zip" and also ~/projects/demo/file.txt'
    )
    assert any("hw.zip" in c for c in candidates), candidates
    assert any("file.txt" in c for c in candidates), candidates

    current_file = Path(__file__).resolve()
    scope = nearest_existing_workspace_scope(str(current_file))
    assert scope is not None, scope
    assert Path(scope).exists(), scope

    deduped = dedupe_workspace_dirs([str(Path.cwd()), str(Path.cwd()), str(Path.home())])
    assert len(deduped) <= 2, deduped

    scoped = workspace_dirs_for_task(
        base_workspace_dirs=[str(Path.cwd().resolve())],
        task=f'Please read "{current_file}"',
    )
    normalized_scoped = {os.path.normcase(os.path.normpath(p)) for p in scoped}
    assert os.path.normcase(os.path.normpath(str(Path.cwd().resolve()))) in normalized_scoped, scoped


if __name__ == "__main__":
    run_checks()
    print("[test_cli_workspace_policy_boundary] All checks passed.")
