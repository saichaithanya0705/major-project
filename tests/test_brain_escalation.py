"""
Local-first brain: escalation order, self-escalation, explicit requests, and
answer-only CLI runs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.brain as brain  # noqa: E402
from agents.cua_cli.backends import BackendRequest  # noqa: E402
from agents.cua_cli.backends.claude_code import ClaudeCodeBackend  # noqa: E402
from agents.cua_cli.backends.codex import CodexBackend  # noqa: E402
from agents.cua_cli.backends.copilot import CopilotBackend  # noqa: E402
from agents.cua_cli.backends.runner import BackendAnswerError, run_backend_for_answer  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "coding_backends"


def _model(**overrides):
    values = dict(
        brain_primary="local",
        brain_escalation=("gemini", "codex"),
        brain_model="nemotron-3.5-bolt",
        brain_num_ctx=8192,
        brain_timeout_seconds=5,
        brain_cli_timeout_seconds=5,
        brain_self_escalate=True,
        jarvis_model="gemini-3-flash-preview",
        openrouter_model="",
        ollama_base_url="http://127.0.0.1:1",
        ollama_keep_alive="",
        client=object(),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class _Providers:
    """Scripted providers that record the system prompt each one received."""

    def __init__(self, **replies):
        self.replies = replies
        self.calls: list[tuple[str, str]] = []

    def table(self):
        def make(name):
            async def _reply(model, system, user, temperature, max_tokens, *, json_mode=False):
                del model, user, temperature, max_tokens, json_mode
                self.calls.append((name, system))
                reply = self.replies[name]
                if isinstance(reply, Exception):
                    raise reply
                return reply

            return _reply

        return {name: make(name) for name in ("local", "chatgpt", "gemini", "openrouter", "claude", "codex", "copilot")}


@pytest.fixture(autouse=True)
def _all_escalation_targets_configured(monkeypatch):
    monkeypatch.setattr(brain, "provider_configured", lambda model, name: name in model.brain_escalation or name == "local")


async def test_local_answer_is_used_when_it_succeeds() -> None:
    providers = _Providers(local="Paris.", gemini="unused", codex="unused")

    reply = await brain.generate_brain_reply(_model(), system="SYS", user="capital of France?", providers=providers.table())

    assert (reply.text, reply.provider, reply.escalated) == ("Paris.", "local", False)
    assert reply.label == "nemotron-3.5-bolt (local)"
    assert [name for name, _ in providers.calls] == ["local"]
    assert brain.ESCALATE_MARKER in providers.calls[0][1]


async def test_local_failure_escalates_in_configured_order() -> None:
    providers = _Providers(
        local=RuntimeError("model crashed"),
        gemini=brain.BrainProviderUnavailable("GEMINI_API_KEY is not set"),
        codex="42",
    )

    reply = await brain.generate_brain_reply(_model(), system="SYS", user="q", providers=providers.table())

    assert (reply.text, reply.provider, reply.escalated) == ("42", "codex", True)
    assert reply.label == "Codex CLI"
    assert [name for name, _ in providers.calls] == ["local", "gemini", "codex"]
    # Escalation targets never see the self-escalation instruction.
    assert all(brain.ESCALATE_MARKER not in system for name, system in providers.calls if name != "local")


async def test_local_model_can_ask_to_escalate() -> None:
    providers = _Providers(local="ESCALATE.", gemini="A careful answer.", codex="unused")

    reply = await brain.generate_brain_reply(_model(), system="SYS", user="prove it", providers=providers.table())

    assert (reply.provider, reply.text) == ("gemini", "A careful answer.")


async def test_explicit_strong_model_request_skips_local() -> None:
    providers = _Providers(local="unused", gemini="Deep answer.", codex="unused")

    reply = await brain.generate_brain_reply(
        _model(), system="SYS", user="q", force_escalation=True, providers=providers.table()
    )

    assert reply.provider == "gemini"
    assert [name for name, _ in providers.calls] == ["gemini"]


async def test_without_escalation_targets_local_answers_without_marker(monkeypatch) -> None:
    monkeypatch.setattr(brain, "provider_configured", lambda model, name: name == "local")
    providers = _Providers(local="Local answer.", gemini="unused", codex="unused")

    reply = await brain.generate_brain_reply(
        _model(), system="SYS", user="q", force_escalation=True, providers=providers.table()
    )

    assert reply.provider == "local"
    assert brain.ESCALATE_MARKER not in providers.calls[0][1]


async def test_all_providers_failing_reports_each_failure() -> None:
    providers = _Providers(local="", gemini=RuntimeError("503"), codex=brain.BrainProviderUnavailable("Codex CLI is not installed"))

    with pytest.raises(RuntimeError) as excinfo:
        await brain.generate_brain_reply(_model(), system="SYS", user="q", providers=providers.table())

    message = str(excinfo.value)
    assert "local: empty reply" in message
    assert "gemini: RuntimeError: 503" in message
    assert "codex: Codex CLI is not installed" in message


def test_wants_strong_model_phrases() -> None:
    for text in ("think harder about this", "please ask codex", "Use the stronger model", "ask ChatGPT what it thinks"):
        assert brain.wants_strong_model(text), text
    for text in ("what is the capital of France", "open my codex folder", "think about dinner"):
        assert not brain.wants_strong_model(text), text


async def test_local_reply_calls_ollama_chat_with_brain_settings() -> None:
    seen: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"message": {"role": "assistant", "content": "Hello from Bolt."}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        model = _model(ollama_base_url=f"http://127.0.0.1:{server.server_address[1]}", ollama_keep_alive="10m")
        text = await brain._local_reply(model, "SYS", "hi", 0.3, 256, json_mode=True)
    finally:
        server.shutdown()

    assert text == "Hello from Bolt."
    assert seen["path"] == "/api/chat"
    body = seen["body"]
    assert body["model"] == "nemotron-3.5-bolt"
    assert body["options"] == {"temperature": 0.3, "num_predict": 256, "num_ctx": 8192}
    assert body["keep_alive"] == "10m"
    assert body["format"] == "json"
    assert body["messages"][0] == {"role": "system", "content": "SYS"}


async def test_local_reply_reports_unreachable_ollama_as_unavailable() -> None:
    with pytest.raises(brain.BrainProviderUnavailable):
        await brain._local_reply(_model(), "SYS", "hi", 0.3, 64)


def test_answer_only_cli_runs_get_no_side_effecting_tools() -> None:
    request = BackendRequest(prompt="x", cwd="/tmp", workspace_dirs=("/tmp", "/home/u/project"), answer_only=True)

    claude = ClaudeCodeBackend().build_args(request)
    assert claude[claude.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in claude
    assert "--allowedTools" not in claude and "--add-dir" not in claude

    codex = CodexBackend().build_args(request)
    assert codex[codex.index("--sandbox") + 1] == "read-only"
    assert "--add-dir" not in codex and codex[-1] == "-"

    copilot = CopilotBackend().build_args(request)
    denied = [copilot[i + 1] for i, arg in enumerate(copilot) if arg == "--deny-tool"]
    assert denied == ["shell", "write"]
    assert "--add-dir" not in copilot


class _ReplayBackend(CodexBackend):
    def __init__(self, fixture: str) -> None:
        self._argv = [sys.executable, "-c", f"import sys; sys.stdin.read(); sys.stdout.write(open({str(FIXTURES / fixture)!r}).read())"]

    def resolve_executable(self):
        return self._argv

    def build_args(self, request):
        del request
        return []


async def test_run_backend_for_answer_returns_final_reply() -> None:
    answer = await run_backend_for_answer(
        _ReplayBackend("codex_success.jsonl"),
        BackendRequest(prompt="q", cwd=os.getcwd(), answer_only=True),
        timeout=20,
    )
    assert answer == "All done: hello."


async def test_run_backend_for_answer_rejects_empty_output(tmp_path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text('{"type":"thread.started","thread_id":"t"}\n{"type":"turn.completed","usage":{}}\n', encoding="utf-8")
    backend = _ReplayBackend("codex_success.jsonl")
    backend._argv = [sys.executable, "-c", f"import sys; sys.stdin.read(); sys.stdout.write(open({str(empty)!r}).read())"]

    with pytest.raises(BackendAnswerError):
        await run_backend_for_answer(backend, BackendRequest(prompt="q", cwd=os.getcwd(), answer_only=True), timeout=20)
