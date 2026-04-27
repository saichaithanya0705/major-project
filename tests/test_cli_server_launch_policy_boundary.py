"""
Checks for extracted CLI server-launch policy helpers.

Usage:
    python tests/test_cli_server_launch_policy_boundary.py
"""

import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.server_launch_policy import (
    extract_explicit_shell_command,
    extract_port_candidates,
    extract_server_subcommand,
    infer_server_launch_from_tool_calls,
    is_background_intent_task,
    is_quick_server_launch_task,
    is_server_intent_text,
    is_server_like_command,
    resolve_shell_path,
)


def run_checks() -> None:
    assert extract_explicit_shell_command("Run this command: `npm run dev`") == "npm run dev"
    assert extract_explicit_shell_command("command: python -m http.server 3000") == "python -m http.server 3000"
    assert extract_explicit_shell_command("launch npm start") == "npm start"
    assert extract_explicit_shell_command("open youtube") is None

    assert is_server_like_command("npm run dev")
    assert is_server_like_command("uvicorn app:app --port 8000")
    assert not is_server_like_command("echo hello")

    assert is_server_intent_text("start localhost server on port 3000")
    assert not is_server_intent_text("create a README file")

    assert is_background_intent_task("keep this localhost server running", "echo hello")
    assert is_background_intent_task("run app", "npm run dev")
    assert not is_background_intent_task("write notes", "echo hello")

    assert is_quick_server_launch_task("run npm start on localhost")
    assert not is_quick_server_launch_task("clone repo and run npm install then npm start")

    ports = extract_port_candidates(
        "server at localhost:3000 and 127.0.0.1:8080 with --port 5000 and port 7000"
    )
    assert ports == [3000, 5000, 7000, 8080], ports

    sub = extract_server_subcommand("npm install && npm run dev")
    assert sub == "npm run dev", sub

    base = Path.cwd().resolve()
    resolved = resolve_shell_path("./demo-app", base)
    assert resolved == (base / "demo-app").resolve(), resolved

    inferred = infer_server_launch_from_tool_calls(
        [
            {
                "tool_name": "run_shell_command",
                "status": "success",
                "parameters": {"command": "cd ~/Desktop/demo-app && npm install && npm run dev"},
            }
        ]
    )
    assert inferred is not None, inferred
    assert inferred["command"] == "npm run dev", inferred
    assert inferred["cwd"], inferred


if __name__ == "__main__":
    run_checks()
    print("[test_cli_server_launch_policy_boundary] All checks passed.")
