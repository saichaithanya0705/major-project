"""
CUA CLI Agent - Desktop control and coding through coding-agent CLIs.

Drives a backend CLI (opencode locally; Claude Code, Codex CLI, or GitHub
Copilot CLI for delegated coding) to provide:
- Shell command execution
- File system operations
- Script execution and coding tasks
- CLI-based app control

The rapid response model invokes this agent for CLI tasks.
"""
from agents.cua_cli.agent import CLIAgent, CLIResponse, run_cli_task

__all__ = ["CLIAgent", "CLIResponse", "run_cli_task"]
