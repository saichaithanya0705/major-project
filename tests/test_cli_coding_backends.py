"""
Coding-agent CLI backends: event normalization, invocation safety, and selection.

Fixtures under tests/fixtures/coding_backends are real JSONL streams captured
from opencode 1.19.4, Claude Code 2.1.310, Codex CLI 0.164.0, and GitHub
Copilot CLI 1.0.103 driven by a scripted local model server.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_cli.agent as agent_module  # noqa: E402
from agents.cua_cli.agent import CLIAgent  # noqa: E402
from agents.cua_cli.backends import (  # noqa: E402
    BackendRequest,
    NormalizationState,
    backend_chain_for_task,
    is_coding_task,
)
from agents.cua_cli.backends.base import (  # noqa: E402
    BackendUnavailableError,
    BackendUnsafeArgumentsError,
    ensure_safe_for_batch_shim,
    unwrap_npm_cmd_shim,
)
from agents.cua_cli.backends.claude_code import ClaudeCodeBackend  # noqa: E402
from agents.cua_cli.backends.codex import CodexBackend, unwrap_shell_command  # noqa: E402
from agents.cua_cli.backends.copilot import CopilotBackend, denied_shell_rules  # noqa: E402
from agents.cua_cli.backends.opencode import OpencodeBackend, build_permission_policy  # noqa: E402
from agents.cua_cli.response_parser import parse_stream_json_response  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "coding_backends"
ALL_BACKENDS = (OpencodeBackend, ClaudeCodeBackend, CodexBackend, CopilotBackend)
HOSTILE_PROMPT = 'fix the bug & then "echo pwned" | del C:\\* > out.txt %PATH% ^ !x'


def _normalize_fixture(backend, name: str, returncode: int = 0) -> dict:
    state = NormalizationState()
    events = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        events.extend(backend.normalize_event(json.loads(line), state))
    events.extend(backend.finalize(state, returncode, ""))
    return parse_stream_json_response(
        stdout="\n".join(json.dumps(event) for event in events),
        stderr="",
        returncode=returncode,
    )


@pytest.mark.parametrize(
    ("backend_cls", "fixture", "expected_command", "expected_output"),
    [
        (OpencodeBackend, "opencode_success.jsonl", "echo hello-from-tool", "hello-from-tool\n"),
        (ClaudeCodeBackend, "claude_success.jsonl", "echo hello-from-claude", "hello-from-claude"),
        (CodexBackend, "codex_success.jsonl", "echo hello-from-codex", "hello-from-codex\n"),
        (CopilotBackend, "copilot_success.jsonl", "echo hello-from-copilot", "hello-from-copilot"),
    ],
)
def test_real_event_streams_normalize_to_shell_call_and_reply(
    backend_cls, fixture, expected_command, expected_output
) -> None:
    parsed = _normalize_fixture(backend_cls(), fixture)

    assert parsed["success"] is True, parsed
    assert parsed["output"] == "All done: hello.", parsed
    assert parsed["error"] is None, parsed
    [tool_call] = parsed["tool_calls"]
    assert tool_call["tool_name"] == "run_shell_command", tool_call
    assert tool_call["parameters"]["command"] == expected_command, tool_call
    assert tool_call["status"] == "success", tool_call
    assert tool_call["result"] == expected_output, tool_call


def test_opencode_denied_command_is_reported_as_a_failed_tool_call() -> None:
    parsed = _normalize_fixture(OpencodeBackend(), "opencode_denied.jsonl")

    assert parsed["success"] is False, parsed
    [tool_call] = parsed["tool_calls"]
    assert tool_call["parameters"]["command"] == "rm -rf ./zzz", tool_call
    assert tool_call["status"] == "error", tool_call
    assert "prevents you from using this specific tool call" in parsed["error"], parsed


def test_codex_non_fatal_warning_items_do_not_fail_the_run() -> None:
    state = NormalizationState()
    warning = {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message": "Model metadata missing"}}
    assert CodexBackend().normalize_event(warning, state) == []
    assert state.failed is False


def test_codex_turn_failure_is_a_failed_result() -> None:
    state = NormalizationState()
    events = CodexBackend().normalize_event({"type": "turn.failed", "error": {"message": "quota exceeded"}}, state)
    assert [event["type"] for event in events] == ["error", "result"], events
    assert events[-1] == {"type": "result", "status": "error", "error": "quota exceeded"}
    assert CodexBackend().finalize(state, 1, "") == []


def test_unwrap_shell_command_exposes_the_real_command() -> None:
    assert unwrap_shell_command("/bin/bash -lc 'npm run dev'") == "npm run dev"
    assert unwrap_shell_command("bash -c \"cd app && npm start\"") == "cd app && npm start"
    assert unwrap_shell_command("npm test") == "npm test"


def test_finalize_reports_exit_code_when_cli_sent_no_result() -> None:
    state = NormalizationState(started=True)
    [event] = OpencodeBackend().finalize(state, 2, "boom: model unreachable\n")
    assert event == {"type": "result", "status": "error", "error": "boom: model unreachable"}


@pytest.mark.parametrize("backend_cls", ALL_BACKENDS)
def test_prompt_travels_on_stdin_not_argv(backend_cls, monkeypatch) -> None:
    backend = backend_cls()
    monkeypatch.setattr(backend, "resolve_executable", lambda: [r"C:\npm\agent.cmd"])
    request = BackendRequest(
        prompt=HOSTILE_PROMPT,
        cwd="/work/project",
        workspace_dirs=("/work/project", "/work/other"),
        model="provider/model-1",
    )

    invocation = backend.invocation(request)

    assert invocation.stdin_text == HOSTILE_PROMPT
    assert all(HOSTILE_PROMPT not in arg for arg in invocation.argv), invocation.argv
    # The fixed arguments must stay safe even when launched through a batch shim.
    ensure_safe_for_batch_shim(invocation.argv, windows=True)


def test_batch_shim_guard_rejects_metacharacters_only_for_shims() -> None:
    with pytest.raises(BackendUnsafeArgumentsError):
        ensure_safe_for_batch_shim([r"C:\npm\opencode.cmd", "run", "a&b"], windows=True)
    ensure_safe_for_batch_shim([r"C:\tools\opencode.exe", "run", "a&b"], windows=True)
    ensure_safe_for_batch_shim([r"C:\npm\opencode.cmd", "run", "a&b"], windows=False)


def test_unwrap_npm_cmd_shim_resolves_script_and_native_targets(tmp_path: Path) -> None:
    script = tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    native = tmp_path / "node_modules" / "@openai" / "codex" / "codex.exe"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"MZ")

    script_shim = tmp_path / "opencode.cmd"
    script_shim.write_text(
        '@ECHO off\r\nendLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & '
        '"%_prog%"  "%dp0%\\node_modules\\opencode-ai\\bin\\opencode" %*\r\n',
        encoding="utf-8",
    )
    native_shim = tmp_path / "codex.cmd"
    native_shim.write_text('@ECHO off\r\n"%~dp0\\node_modules\\@openai\\codex\\codex.exe"   %*\r\n', encoding="utf-8")

    assert unwrap_npm_cmd_shim(str(script_shim), node="node.exe") == ["node.exe", str(script)]
    assert unwrap_npm_cmd_shim(str(native_shim)) == [str(native)]
    assert unwrap_npm_cmd_shim(str(tmp_path / "missing.cmd")) is None


def test_opencode_policy_denies_destructive_commands_and_external_dirs() -> None:
    scoped = build_permission_policy(full_trust=False)
    trusted = build_permission_policy(full_trust=True)

    assert scoped["bash"]["*"] == "allow"
    for pattern in ("git push*", "rm -rf*", "Remove-Item*", "git reset --hard*"):
        assert scoped["bash"][pattern] == "deny", pattern
    assert scoped["external_directory"] == "deny"
    assert "git push*" not in trusted["bash"]
    assert trusted["bash"]["mkfs*"] == "deny"
    assert trusted["external_directory"] == "allow"
    # Non-interactive runs auto-reject "ask", so the policy never relies on it.
    assert "ask" not in json.dumps(scoped)


def test_opencode_config_registers_local_ollama_model(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11500/")
    backend = OpencodeBackend()
    request = BackendRequest(prompt="x", cwd="/work", model="ollama/nemotron-3.5-bolt")

    config = json.loads(backend.build_env(request)["OPENCODE_CONFIG_CONTENT"])

    provider = config["provider"]["ollama"]
    assert provider["options"]["baseURL"] == "http://127.0.0.1:11500/v1"
    assert provider["models"]["nemotron-3.5-bolt"]["tool_call"] is True
    assert config["small_model"] == "ollama/nemotron-3.5-bolt"
    assert backend.build_args(request)[-2:] == ["--model", "ollama/nemotron-3.5-bolt"]

    cloud = json.loads(backend.build_env(BackendRequest(prompt="x", cwd="/w", model="openai/gpt-5"))["OPENCODE_CONFIG_CONTENT"])
    assert "provider" not in cloud


def test_opencode_fails_fast_when_ollama_is_down(monkeypatch) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    monkeypatch.setenv("OLLAMA_BASE_URL", f"http://127.0.0.1:{free_port}")
    backend = OpencodeBackend()
    monkeypatch.setattr(backend, "resolve_executable", lambda: ["/usr/bin/opencode"])

    with pytest.raises(BackendUnavailableError, match="ollama serve"):
        backend.invocation(BackendRequest(prompt="x", cwd="/w", model="ollama/nemotron-3.5-bolt"))
    # Cloud models do not depend on a local Ollama server.
    backend.invocation(BackendRequest(prompt="x", cwd="/w", model="openai/gpt-5"))


def test_claude_codex_copilot_safety_flags() -> None:
    scoped = BackendRequest(prompt="x", cwd="/w")
    trusted = BackendRequest(prompt="x", cwd="/w", full_trust=True)

    claude_args = ClaudeCodeBackend().build_args(scoped)
    assert "Bash(git push:*)" in claude_args and "Bash(rm -rf:*)" in claude_args
    assert "Bash(git push:*)" not in ClaudeCodeBackend().build_args(trusted)

    codex_scoped = CodexBackend().build_args(scoped)
    assert codex_scoped[-1] == "-"
    assert "workspace-write" in codex_scoped
    assert "sandbox_workspace_write.network_access=true" not in codex_scoped
    assert "sandbox_workspace_write.network_access=true" in CodexBackend().build_args(trusted)

    assert {"shell(git push)", "shell(rm)", "shell(Remove-Item)"} <= set(denied_shell_rules(full_trust=False))
    trusted_rules = denied_shell_rules(full_trust=True)
    assert "shell(mkfs)" in trusted_rules and "shell(rm)" not in trusted_rules


def test_coding_tasks_delegate_and_shell_tasks_stay_local(monkeypatch) -> None:
    for name in ("JARVIS_CLI_BACKEND", "JARVIS_CODING_BACKENDS", "JARVIS_CODING_DELEGATION"):
        monkeypatch.delenv(name, raising=False)

    assert is_coding_task("fix the failing unit tests in my Flask project")
    assert is_coding_task("refactor utils.py to remove duplication")
    assert not is_coding_task("create a folder named notes on the desktop")
    assert not is_coding_task("open notepad")

    coding = [backend.name for backend in backend_chain_for_task("fix the bug in app.py")]
    assert coding == ["claude", "codex", "copilot", "opencode"]
    assert [backend.name for backend in backend_chain_for_task("open notepad")] == ["opencode"]

    monkeypatch.setenv("JARVIS_CODING_BACKENDS", "codex, opencode")
    assert [backend.name for backend in backend_chain_for_task("fix the bug in app.py")] == ["codex", "opencode"]
    monkeypatch.setenv("JARVIS_CODING_DELEGATION", "off")
    assert [backend.name for backend in backend_chain_for_task("fix the bug in app.py")] == ["opencode"]
    monkeypatch.setenv("JARVIS_CLI_BACKEND", "nonsense")
    with pytest.raises(ValueError):
        backend_chain_for_task("open notepad")


_FAKE_CLI = r'''
import pathlib, sys
pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(), encoding="utf-8")
mode = sys.argv[2]
if mode == "auth":
    sys.stderr.write("Error: not logged in. Please run login first.\n")
    sys.exit(1)
if mode == "tool_then_fail":
    print('{"type":"tool_use","part":{"type":"tool","tool":"bash","callID":"c1","state":{"status":"completed","input":{"command":"echo hi"},"output":"hi"}}}')
    sys.stderr.write("Error: unauthorized\n")
    sys.exit(1)
sys.stdout.write(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
'''


class _ScriptedBackend(OpencodeBackend):
    """opencode's normalizer driven by a scripted stand-in executable."""

    def __init__(self, name: str, script: Path, prompt_file: Path, mode: str, available: bool = True) -> None:
        self.name = name
        self.display_name = name
        self._argv = [sys.executable, str(script), str(prompt_file), mode, str(FIXTURES / "opencode_success.jsonl")]
        self._available = available

    def resolve_executable(self):
        return self._argv if self._available else None

    def default_model(self) -> str:
        return "scripted/model"

    def build_args(self, request):
        del request
        return []


async def test_cli_agent_falls_through_unavailable_and_unauthenticated_backends(tmp_path, monkeypatch) -> None:
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    prompts = {name: tmp_path / f"{name}.prompt" for name in ("missing", "auth", "ok")}
    chain = [
        _ScriptedBackend("missing", script, prompts["missing"], "ok", available=False),
        _ScriptedBackend("auth", script, prompts["auth"], "auth"),
        _ScriptedBackend("ok", script, prompts["ok"], "ok"),
    ]
    monkeypatch.setattr(agent_module, "backend_chain_for_task", lambda task: chain)

    response = await CLIAgent()._run_cli("say hello & stay safe", timeout=30)

    assert response.success is True, response
    assert response.backend == "ok", response
    assert response.output == "All done: hello.", response
    assert response.tool_calls[0]["parameters"]["command"] == "echo hello-from-tool"
    assert not prompts["missing"].exists()
    assert prompts["auth"].read_text(encoding="utf-8") == "say hello & stay safe"
    assert prompts["ok"].read_text(encoding="utf-8") == "say hello & stay safe"


async def test_cli_agent_never_reruns_a_task_after_tools_executed(tmp_path, monkeypatch) -> None:
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    second_prompt = tmp_path / "second.prompt"
    chain = [
        _ScriptedBackend("first", script, tmp_path / "first.prompt", "tool_then_fail"),
        _ScriptedBackend("second", script, second_prompt, "ok"),
    ]
    monkeypatch.setattr(agent_module, "backend_chain_for_task", lambda task: chain)

    response = await CLIAgent()._run_cli("do it", timeout=30)

    assert response.success is False, response
    assert response.backend == "first", response
    assert response.tool_calls, response
    assert not second_prompt.exists()


async def test_cli_agent_reports_every_skipped_backend(monkeypatch, tmp_path) -> None:
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    chain = [_ScriptedBackend("missing", script, tmp_path / "p", "ok", available=False)]
    monkeypatch.setattr(agent_module, "backend_chain_for_task", lambda task: chain)

    response = await CLIAgent()._run_cli("do it", timeout=30)

    assert response.success is False
    assert response.error.startswith("No coding CLI could run this task."), response.error
    assert "missing is not installed" in response.error, response.error
