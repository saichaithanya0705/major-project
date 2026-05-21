"""
Checks for extracted CLI foreground runtime helpers.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_cli.agent as cli_agent_module
from agents.cua_cli.agent import CLIAgent
from agents.cua_cli.background_manager import (
    ForegroundOperationResult,
    await_foreground_process_operation,
)


class _FakeProcess:
    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self.wait_calls = 0
        self.returncode = None

    async def wait(self) -> int:
        self.wait_calls += 1
        if self.returncode is None:
            self.returncode = 0
        return 0

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = 0
        return (b"hello", b"")


def test_await_foreground_process_operation_returns_value_without_cleanup() -> None:
    async def _run() -> None:
        process = _FakeProcess()
        terminated: list[int] = []

        result = await await_foreground_process_operation(
            process=process,
            timeout=0.1,
            operation=asyncio.sleep(0, result="done"),
            terminate_process_tree=lambda meta: terminated.append(int(meta["pid"])),
        )

        assert result.value == "done", result
        assert result.timed_out is False, result
        assert terminated == [], terminated
        assert process.wait_calls == 0, process.wait_calls

    asyncio.run(_run())


def test_await_foreground_process_operation_times_out_and_runs_cleanup() -> None:
    async def _run() -> None:
        process = _FakeProcess()
        terminated: list[int] = []
        cleanup_calls: list[str] = []

        async def _cleanup() -> None:
            cleanup_calls.append("cleanup")

        result = await await_foreground_process_operation(
            process=process,
            timeout=0.01,
            operation=asyncio.sleep(0.05, result="late"),
            cleanup=_cleanup,
            terminate_process_tree=lambda meta: terminated.append(int(meta["pid"])),
        )

        assert result.value is None, result
        assert result.timed_out is True, result
        assert terminated == [4242], terminated
        assert cleanup_calls == ["cleanup"], cleanup_calls
        assert process.wait_calls == 1, process.wait_calls

    asyncio.run(_run())


def test_run_direct_command_uses_foreground_operation_boundary(monkeypatch) -> None:
    async def _run() -> None:
        agent = object.__new__(CLIAgent)
        fake_process = _FakeProcess(pid=5151)
        captured: dict[str, object] = {}
        unregistered: list[str] = []

        async def _fake_emit_terminal_event(*_args, **_kwargs) -> None:
            return None

        async def _fake_emit_status(*_args, **_kwargs) -> None:
            return None

        async def _fake_create_subprocess_exec(*_args, **_kwargs):
            return fake_process

        async def _fake_await_foreground_process_operation(**kwargs):
            operation = kwargs.get("operation")
            if hasattr(operation, "close"):
                operation.close()
            captured.update(kwargs)
            process = kwargs.get("process")
            if process is not None:
                process.returncode = 0
            return ForegroundOperationResult(value=(b"hello", b""), timed_out=False)

        agent._emit_terminal_event = _fake_emit_terminal_event
        agent._emit_status = _fake_emit_status
        agent._register_foreground_process = lambda session_id, process, task: {
            "id": session_id,
            "pid": process.pid,
            "task": task,
        }
        agent._unregister_foreground_process = lambda session_id: unregistered.append(session_id)
        agent._terminate_process_tree_sync = lambda _meta: None

        monkeypatch.setattr(
            cli_agent_module.asyncio,
            "create_subprocess_exec",
            _fake_create_subprocess_exec,
        )
        monkeypatch.setattr(
            cli_agent_module,
            "await_foreground_process_operation",
            _fake_await_foreground_process_operation,
        )

        result = await agent._run_direct_command(
            SimpleNamespace(argv=["echo", "hello"], display="echo hello"),
            timeout=5,
        )

        assert captured["process"] is fake_process
        assert captured["timeout"] == 5
        assert result["success"] is True, result
        assert result["result"] == "hello", result
        assert len(unregistered) == 1, unregistered

    asyncio.run(_run())


def test_run_command_uses_foreground_operation_boundary(monkeypatch) -> None:
    async def _run() -> None:
        agent = object.__new__(CLIAgent)
        fake_process = _FakeProcess(pid=6262)
        captured: dict[str, object] = {}

        async def _fake_create_subprocess_shell(*_args, **_kwargs):
            return fake_process

        async def _fake_await_foreground_process_operation(**kwargs):
            operation = kwargs.get("operation")
            if hasattr(operation, "close"):
                operation.close()
            captured.update(kwargs)
            return ForegroundOperationResult(value=(b"stdout", b"stderr"), timed_out=False)

        monkeypatch.setattr(
            cli_agent_module.asyncio,
            "create_subprocess_shell",
            _fake_create_subprocess_shell,
        )
        monkeypatch.setattr(
            cli_agent_module,
            "await_foreground_process_operation",
            _fake_await_foreground_process_operation,
        )

        stdout, stderr, returncode = await agent.run_command("echo hi", timeout=7)

        assert captured["process"] is fake_process
        assert captured["timeout"] == 7
        assert stdout == "stdout"
        assert stderr == "stderr"
        assert returncode == 0

    asyncio.run(_run())
