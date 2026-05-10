"""
Regression checks for CLIAgent non-interactive tool allowlists.

Usage:
    python tests/test_cli_tool_allowlist_policy.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.tool_allowlist_policy import allowed_tools_for_task


def run_checks() -> None:
    file_tools = allowed_tools_for_task("write it down in a file on desktop", "default")
    assert file_tools == ["write_file", "replace"], file_tools

    terminal_tools = allowed_tools_for_task(
        "By using the terminal create a desktop file named note.txt",
        "default",
    )
    assert "run_shell_command" in terminal_tools, terminal_tools

    clone_tools = allowed_tools_for_task("clone this repo and run tests", "default")
    assert "run_shell_command" in clone_tools, clone_tools

    move_tools = allowed_tools_for_task(
        "create a folder hw on desktop and move cs 173 hw into it",
        "default",
    )
    assert "run_shell_command" in move_tools, move_tools

    assert allowed_tools_for_task("write it down in a file", "plan") == []
    assert allowed_tools_for_task("write it down in a file", "yolo") == []


if __name__ == "__main__":
    run_checks()
    print("[test_cli_tool_allowlist_policy] All checks passed.")
