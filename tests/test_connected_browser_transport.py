"""Typed transport boundaries exercised without a browser or network."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.browser import mcp_client


def test_extension_launch_is_explicit_and_local():
    client = mcp_client.PlaywrightMcpClient(extension=True, browser="chrome")
    params = client.server_parameters(client.resolve_command())
    assert "--extension" in params.args
    assert params.args[params.args.index("--browser") + 1] == "chrome"
    assert "npx" not in params.command
    assert "--extension" not in mcp_client.PlaywrightMcpClient().server_parameters(Path("local")).args


@pytest.mark.parametrize("browser", ["firefox", "chrome --no-sandbox", "unknown"])
def test_unsupported_extension_channel_fails_before_launch(browser):
    with pytest.raises(ValueError):
        mcp_client.PlaywrightMcpClient(extension=True, browser=browser)


class Session:
    async def call_tool(self, name, arguments):
        return {"content": [{"type": "text", "text": "denied"}], "isError": True,
                "structuredContent": {"code": "denied"}}

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="browser_snapshot", inputSchema={"type": "object"})])


async def test_error_result_is_preserved():
    client = mcp_client.PlaywrightMcpClient()
    client._session = Session()
    try:
        result = await client.call_result("browser_snapshot", {})
        assert result.is_error and result.structured == {"code": "denied"}
        with pytest.raises(mcp_client.McpToolError):
            result.require_success()
    finally:
        await client.close()


async def test_schema_catalog_is_exposed():
    client = mcp_client.PlaywrightMcpClient()
    client._session = Session()
    try:
        assert await client.tool_schemas() == {"browser_snapshot": {"type": "object"}}
    finally:
        await client.close()


async def test_cross_task_calls_close_owner_cleanly(tmp_path):
    opened = []
    closed = []
    client = mcp_client.PlaywrightMcpClient(tmp_path)
    binary = client.resolve_command()
    binary.parent.mkdir(parents=True)
    binary.touch()

    class Stack:
        async def aclose(self):
            closed.append(asyncio.current_task())

    async def open_session(_command):
        opened.append(asyncio.current_task())
        return Session(), Stack()

    client._open_session = open_session
    await asyncio.gather(client.call_result("browser_snapshot"), client.tool_schemas())
    await asyncio.create_task(client.close())
    assert len(opened) == 1 and opened == closed
    assert client._session is None and client._exit_stack is None


async def test_cancelled_request_cannot_dispatch_after_connect():
    started, release = asyncio.Event(), asyncio.Event()
    dispatched = []
    class PendingSession(Session):
        async def call_tool(self, name, args): dispatched.append(name); return {}
    client = mcp_client.PlaywrightMcpClient()
    async def connect():
        started.set()
        await release.wait()
        return PendingSession()
    client.connect = connect
    task = asyncio.create_task(client.call_result("browser_click", {"target":"e1"}))
    try:
        await started.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        release.set()
        for _ in range(5): await asyncio.sleep(0)
        assert not dispatched
    finally: await client.close()


def test_text_error_without_flag_is_not_success():
    result = mcp_client.McpToolResult("### Error\nTarget is closed", False, None)
    with pytest.raises(mcp_client.McpToolError):
        result.require_success()


def test_extension_install_error_is_actionable_without_private_paths():
    result = mcp_client.McpToolResult('### Error\nPlaywright Extension not found in "C:/private-profile"', True)
    with pytest.raises(mcp_client.McpToolError, match="Install.*Playwright") as error:
        result.require_success()
    assert "private-profile" not in str(error.value)


async def test_owned_output_files_are_ephemeral(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    captured = []
    @asynccontextmanager
    async def stdio(params):
        captured.append(params)
        yield None, None
    class Context(Session):
        def __init__(self, *_, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def initialize(self): pass
    monkeypatch.setattr(mcp_client, "stdio_client", stdio)
    monkeypatch.setattr(mcp_client, "ClientSession", Context)
    client = mcp_client.PlaywrightMcpClient(tmp_path)
    command = client.resolve_command()
    command.parent.mkdir(parents=True)
    command.touch()
    try:
        await client.tool_schemas()
        args = captured[0].args
        assert "--output-dir" in args
        directory = Path(args[args.index("--output-dir") + 1])
        assert directory.is_dir()
        (directory / "private-snapshot.txt").write_text("private fixture")
    finally:
        await client.close()
    assert not directory.exists()
