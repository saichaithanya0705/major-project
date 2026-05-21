import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

import agents.cua_cli.agent as cli_agent_module
from agents.cua_cli.agent import CLIAgent, CLIResponse
from agents.cua_cli.response_runtime import (
    ResponseRuntimeDependencies,
    finalize_cli_response,
    normalize_cli_response,
)


@dataclass
class _FakeResponse:
    success: bool
    output: str
    error: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


def test_normalize_cli_response_uses_last_tool_error_as_primary_failure() -> None:
    response = _FakeResponse(
        success=True,
        output="",
        error="[API Error: fetch failed while sending request]",
        tool_calls=[
            {
                "tool_name": "write_file",
                "status": "error",
                "error": {"message": 'Tool "write_file" not found.'},
            }
        ],
    )

    normalized = normalize_cli_response(response)

    assert normalized is response
    assert normalized.success is False
    assert normalized.output == 'Tool "write_file" not found.'
    assert normalized.error == 'Tool "write_file" not found. | [API Error: fetch failed while sending request]'


def test_finalize_cli_response_promotes_server_launch_and_merges_tool_calls() -> None:
    async def _run() -> None:
        started: list[dict[str, Any]] = []

        async def _wait_for_any_port(*, ports: list[int], timeout_seconds: float) -> int | None:
            del ports, timeout_seconds
            return None

        async def _start_background_process(**kwargs: Any) -> dict[str, Any]:
            started.append(kwargs)
            return {
                "success": True,
                "result": "Started background process bg-123",
                "error": None,
                "tool_calls": [
                    {
                        "tool_name": "background_process_manager",
                        "tool_id": "bg-123",
                        "parameters": {"command": kwargs["command"]},
                    }
                ],
            }

        response = _FakeResponse(
            success=False,
            output="Booted dev server.",
            error="CLI task timed out after 3 seconds",
            tool_calls=[
                {
                    "tool_name": "run_shell_command",
                    "status": "success",
                    "parameters": {"command": "cd demo && npm run dev"},
                }
            ],
        )
        deps = ResponseRuntimeDependencies(
            infer_server_launch_from_tool_calls=lambda tool_calls: {
                "command": "npm run dev",
                "cwd": "D:/projects/major/project/demo",
            },
            extract_port_candidates=lambda text: [3000] if "dev server" in text.lower() else [],
            wait_for_any_port=_wait_for_any_port,
            start_background_process=_start_background_process,
            build_cli_env=lambda: {"GEMINI_API_KEY": "fake-key"},
            is_timeout_error_text=lambda text: "timed out" in str(text or "").lower(),
        )

        result = await finalize_cli_response("run the demo dev server", response, deps=deps)

        assert result["success"] is True, result
        assert "Booted dev server." in str(result["result"]), result
        assert "Started background process bg-123" in str(result["result"]), result
        assert len(result["tool_calls"]) == 2, result
        assert started == [
            {
                "command": "npm run dev",
                "env": {"GEMINI_API_KEY": "fake-key"},
                "working_dir": "D:/projects/major/project/demo",
                "task": "run the demo dev server",
            }
        ]

    asyncio.run(_run())


def test_finalize_cli_response_reports_unreachable_localhost_claim() -> None:
    async def _run() -> None:
        async def _wait_for_any_port(*, ports: list[int], timeout_seconds: float) -> int | None:
            del ports, timeout_seconds
            return None

        async def _unexpected_start_background_process(**kwargs: Any) -> dict[str, Any]:
            raise AssertionError(f"unexpected promotion: {kwargs}")

        response = _FakeResponse(
            success=True,
            output="Server is running on localhost:3000",
            error=None,
            tool_calls=None,
        )
        deps = ResponseRuntimeDependencies(
            infer_server_launch_from_tool_calls=lambda tool_calls: None,
            extract_port_candidates=lambda text: [3000] if "localhost:3000" in text else [],
            wait_for_any_port=_wait_for_any_port,
            start_background_process=_unexpected_start_background_process,
            build_cli_env=lambda: {},
            is_timeout_error_text=lambda text: "timed out" in str(text or "").lower(),
        )

        result = await finalize_cli_response("start the demo server", response, deps=deps)

        assert result["success"] is False, result
        assert "none of the claimed ports are reachable" in str(result["error"]), result
        assert result["result"] == "Server is running on localhost:3000", result

    asyncio.run(_run())


def test_execute_uses_response_runtime_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        agent = object.__new__(CLIAgent)
        captured: dict[str, Any] = {}
        response = CLIResponse(success=True, output="done", error=None, tool_calls=None)

        async def _none_management(task: str) -> None:
            del task
            return None

        async def _run_cli(*args: Any, **kwargs: Any) -> CLIResponse:
            del args, kwargs
            return response

        async def _fake_finalize_cli_response(task: str, cli_response: CLIResponse, *, deps: Any) -> dict[str, Any]:
            captured["task"] = task
            captured["response"] = cli_response
            captured["deps"] = deps
            return {"success": True, "result": "delegated", "error": None, "tool_calls": None}

        agent._maybe_handle_background_management_task = _none_management
        agent._extract_explicit_shell_command = lambda task: None
        agent._is_background_intent_task = lambda task, command: False
        agent._build_cli_env = lambda: {"K": "V"}
        agent._start_background_process = None
        agent._is_quick_server_launch_task = lambda task: False
        agent._prepare_cli_task = lambda task: task
        agent._run_cli = _run_cli

        monkeypatch.setattr(cli_agent_module, "extract_safe_direct_command", lambda task, explicit_command=None: None)
        monkeypatch.setattr(cli_agent_module, "finalize_cli_response", _fake_finalize_cli_response)

        result = await agent.execute("summarize the repo", timeout=7)

        assert result["result"] == "delegated", result
        assert captured["task"] == "summarize the repo"
        assert captured["response"] is response
        assert isinstance(captured["deps"], ResponseRuntimeDependencies)

    asyncio.run(_run())
