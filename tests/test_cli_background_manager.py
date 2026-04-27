"""
Basic checks for CLIAgent managed background processes.

Usage:
    python tests/test_cli_background_manager.py
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.agent import CLIAgent
from agents.cua_cli.agent import CLIResponse


async def run_checks() -> None:
    agent = CLIAgent()

    # Ensure a clean slate for deterministic checks.
    await CLIAgent.stop_all_background_processes()

    task = (
        "Run this in background and keep it running on localhost: "
        "`sleep 30`"
    )
    result = await agent.execute(task, timeout=30)
    assert result.get("success"), result

    processes = CLIAgent.list_background_processes()
    assert processes, "Expected at least one managed background process"
    proc_id = processes[0]["id"]

    stopped = await CLIAgent.stop_background_process(proc_id)
    assert stopped, f"Failed to stop process {proc_id}"

    processes_after = CLIAgent.list_background_processes()
    assert not processes_after, f"Expected no managed processes, found: {processes_after}"

    inferred = CLIAgent._infer_server_launch_from_tool_calls([
        {
            "tool_name": "run_shell_command",
            "status": "success",
            "parameters": {"command": "cd ~/Desktop/demo-app && npm install && npm run dev"},
        }
    ])
    assert inferred is not None, "Expected inferred launch command from tool calls"
    assert inferred["command"] == "npm run dev", inferred
    expected_suffix = Path("Desktop") / "demo-app"
    assert Path(inferred["cwd"]).parts[-len(expected_suffix.parts):] == expected_suffix.parts, inferred
    assert CLIAgent._is_quick_server_launch_task("run npm start in ~/Desktop/demo-app")
    assert not CLIAgent._is_quick_server_launch_task(
        "Clone repo, run npm install, then npm start on localhost"
    )

    cli_task = (
        "By using the terminal create a new file in the d drive "
        "with name test.txt and write hello world"
    )
    cmd = agent._build_command(cli_task)
    include_dirs = [
        cmd[idx + 1]
        for idx, token in enumerate(cmd[:-1])
        if token == "--include-directories"
    ]
    if os.name == "nt" and Path(r"D:\\").exists():
        normalized_include_dirs = {
            os.path.normcase(os.path.normpath(path))
            for path in include_dirs
        }
        assert os.path.normcase(os.path.normpath(r"D:\\")) in normalized_include_dirs, include_dirs

    original_run_cli = CLIAgent._run_cli
    original_start_bg = CLIAgent._start_background_process

    async def _fake_run_cli_generic_error(self, task, timeout, status_callback=None):
        return CLIResponse(
            success=False,
            output="",
            error="[API Error: exception TypeError: fetch failed sending request]",
            tool_calls=[
                {
                    "tool_name": "write_file",
                    "tool_id": "write_file-failed",
                    "parameters": {"file_path": r"D:\test.txt", "content": "hello world"},
                    "result": 'Path not in workspace: Attempted path "D:\\test.txt"',
                    "status": "error",
                    "error": {
                        "type": "invalid_tool_params",
                        "message": 'Path not in workspace: Attempted path "D:\\test.txt"',
                    },
                }
            ],
        )

    CLIAgent._run_cli = _fake_run_cli_generic_error
    try:
        normalized_error = await agent.execute(cli_task, timeout=30)
        assert not normalized_error.get("success"), normalized_error
        assert "Path not in workspace" in str(normalized_error.get("error", "")), normalized_error
        assert "fetch failed" in str(normalized_error.get("error", "")).lower(), normalized_error
    finally:
        CLIAgent._run_cli = original_run_cli

    async def _fake_run_cli(self, task, timeout, status_callback=None):
        return CLIResponse(
            success=False,
            output="Server starting at http://127.0.0.1:3000",
            error="CLI task timed out after 120 seconds",
            tool_calls=[
                {
                    "tool_name": "run_shell_command",
                    "status": "success",
                    "parameters": {
                        "command": "cd ~/Desktop/demo-app && npm start",
                    },
                }
            ],
        )

    async def _fake_start_background_process(cls, command, env, working_dir, task):
        return {
            "success": True,
            "result": f"Started background process fake1234 | command: {command}",
            "error": None,
            "tool_calls": [
                {
                    "tool_name": "background_process_manager",
                    "tool_id": "fake1234",
                    "parameters": {"command": command},
                }
            ],
        }

    CLIAgent._run_cli = _fake_run_cli
    CLIAgent._start_background_process = classmethod(_fake_start_background_process)
    try:
        timeout_promoted = await agent.execute(
            "go into ~/Desktop/demo-app and run npm start",
            timeout=120,
        )
        assert timeout_promoted.get("success"), timeout_promoted
        result_text = str(timeout_promoted.get("result", ""))
        assert "Started background process" in result_text, timeout_promoted
    finally:
        CLIAgent._run_cli = original_run_cli
        CLIAgent._start_background_process = original_start_bg


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_cli_background_manager] All checks passed.")
