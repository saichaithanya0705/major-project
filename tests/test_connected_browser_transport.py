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


def test_text_error_without_flag_is_not_success():
    result = mcp_client.McpToolResult("### Error\nTarget is closed", False, None)
    with pytest.raises(mcp_client.McpToolError):
        result.require_success()
