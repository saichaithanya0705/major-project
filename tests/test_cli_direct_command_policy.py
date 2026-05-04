"""
Checks for safe direct CLI command routing.

Usage:
    python tests/test_cli_direct_command_policy.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.agent import CLIAgent
from agents.cua_cli.direct_command_policy import extract_safe_direct_command


def test_extracts_safe_natural_language_ping() -> None:
    command = extract_safe_direct_command("ping the google.com through terminal")
    assert command is not None
    assert command.argv == ["ping", "google.com"], command
    assert command.display == "ping google.com", command


def test_rejects_mutating_or_compound_commands() -> None:
    assert extract_safe_direct_command("delete temp.txt from terminal") is None
    assert extract_safe_direct_command("ping google.com && del important.txt") is None
    assert extract_safe_direct_command("command: rm -rf .") is None


async def test_cli_agent_uses_direct_command_without_gemini_cli() -> None:
    agent = CLIAgent()
    calls = []

    async def _fake_run_direct_command(command, timeout, status_callback=None):
        del timeout, status_callback
        calls.append(command)
        return {
            "success": True,
            "result": "Pong",
            "error": None,
            "tool_calls": [
                {
                    "tool_name": "run_shell_command",
                    "parameters": {"command": command.display},
                    "status": "success",
                    "result": "Pong",
                }
            ],
        }

    agent._run_direct_command = _fake_run_direct_command
    result = await agent.execute("ping the google.com through terminal")

    assert result["success"] is True, result
    assert result["result"] == "Pong", result
    assert [call.argv for call in calls] == [["ping", "google.com"]], calls


async def run_checks() -> None:
    test_extracts_safe_natural_language_ping()
    test_rejects_mutating_or_compound_commands()
    await test_cli_agent_uses_direct_command_without_gemini_cli()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_cli_direct_command_policy] All checks passed.")
