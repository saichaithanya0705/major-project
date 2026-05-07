"""
Regression checks for CLIAgent trust-mode defaults.

Usage:
    python tests/test_cli_trust_policy.py
"""

import json
import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.agent import CLIAgent


_ENV_KEYS = (
    "GEMINI_API_KEY",
    "JARVIS_CLI_APPROVAL_MODE",
    "JARVIS_CLI_FULL_TRUST",
    "JARVIS_CLI_PERMISSIVE_POLICY",
    "GEMINI_SANDBOX",
)


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_checks() -> None:
    env_snapshot = {key: os.environ.get(key) for key in _ENV_KEYS}
    original_check_cli_built = CLIAgent._check_cli_built
    CLIAgent._check_cli_built = lambda self: None
    cli_path = str((Path(ROOT_DIR) / "agents" / "cua_cli" / "gemini-cli").resolve())
    try:
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["GEMINI_API_KEY"] = "fake-key"

        default_agent = CLIAgent(gemini_cli_path=cli_path)
        default_env = default_agent._build_cli_env()
        trusted_default = json.loads(Path(default_agent._trusted_folders_path).read_text(encoding="utf-8"))

        assert default_agent.approval_mode == "default", default_agent.approval_mode
        assert default_env.get("JARVIS_CLI_PERMISSIVE_POLICY") != "1", default_env
        assert default_env.get("GEMINI_SANDBOX") != "false", default_env
        assert str(Path.home().resolve()) not in trusted_default, trusted_default

        os.environ["JARVIS_CLI_FULL_TRUST"] = "1"
        full_trust_agent = CLIAgent(gemini_cli_path=cli_path)
        full_trust_env = full_trust_agent._build_cli_env()
        trusted_full = json.loads(Path(full_trust_agent._trusted_folders_path).read_text(encoding="utf-8"))

        assert full_trust_agent.approval_mode == "yolo", full_trust_agent.approval_mode
        assert full_trust_env["JARVIS_CLI_PERMISSIVE_POLICY"] == "1", full_trust_env
        assert full_trust_env["GEMINI_SANDBOX"] == "false", full_trust_env
        assert str(Path.home().resolve()) in trusted_full, trusted_full
    finally:
        CLIAgent._check_cli_built = original_check_cli_built
        _restore_env(env_snapshot)


if __name__ == "__main__":
    run_checks()
    print("[test_cli_trust_policy] All checks passed.")
