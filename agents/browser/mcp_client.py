from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def parse_mcp_text_response(response: Any) -> str:
    """Extract text content blocks from an MCP tool result."""
    if response is None:
        return ""

    if isinstance(response, dict):
        content = response.get("content")
    else:
        content = getattr(response, "content", None)

    if content is None or isinstance(content, (str, bytes)):
        return ""

    text_blocks: list[str] = []
    try:
        iterator = iter(content)
    except TypeError:
        return ""

    for item in iterator:
        if isinstance(item, dict):
            item_type = item.get("type")
            text = item.get("text")
        else:
            item_type = getattr(item, "type", None)
            text = getattr(item, "text", None)

        if item_type == "text" and isinstance(text, str):
            text_blocks.append(text)

    return "\n".join(text_blocks)


class PlaywrightMcpClient:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._state_lock = asyncio.Lock()

    @property
    def integration_dir(self) -> Path:
        return self.project_root / "integrations" / "playwright_mcp"

    def resolve_command(self) -> Path:
        bin_dir = self.integration_dir / "node_modules" / ".bin"
        cmd_binary = bin_dir / "playwright-mcp.cmd"
        shell_binary = bin_dir / "playwright-mcp"

        if os.name == "nt":
            return cmd_binary

        return shell_binary

    def is_installed(self) -> bool:
        return self.resolve_command().is_file()

    async def _open_session(self, command: Path) -> tuple[ClientSession, AsyncExitStack]:
        exit_stack = AsyncExitStack()
        try:
            cwd = self.integration_dir if self.integration_dir.is_dir() else self.project_root
            server = StdioServerParameters(
                command=str(command),
                args=[],
                cwd=str(cwd),
            )
            read_stream, write_stream = await exit_stack.enter_async_context(
                stdio_client(server)
            )
            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except BaseException:
            await exit_stack.aclose()
            raise

        return session, exit_stack

    async def connect(self) -> ClientSession:
        async with self._state_lock:
            if self._session is not None:
                return self._session

            command = self.resolve_command()
            if not command.is_file():
                raise FileNotFoundError(f"Local Playwright MCP binary not found: {command}")

            session, exit_stack = await self._open_session(command)
            self._exit_stack = exit_stack
            self._session = session
            return session

    async def list_tools(self) -> list[Any]:
        session = await self.connect()
        return await self._list_tools_for_session(session)

    async def _list_tools_for_session(self, session: ClientSession) -> list[Any]:
        result = await session.list_tools()
        tools = getattr(result, "tools", result)
        return list(tools or [])

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        session = await self.connect()
        response = await session.call_tool(name, arguments)
        return parse_mcp_text_response(response)

    async def snapshot(self) -> str:
        return await self.call_tool("browser_snapshot")

    @staticmethod
    def _tool_name(tool: Any) -> str:
        if isinstance(tool, dict):
            value = tool.get("name")
        else:
            value = getattr(tool, "name", None)
        return str(value or "")

    async def health_check(self) -> bool:
        if not self.is_installed():
            await self.close()
            return False

        exit_stack: AsyncExitStack | None = None
        async with self._state_lock:
            session = self._session
            if session is None:
                try:
                    session, exit_stack = await self._open_session(self.resolve_command())
                except Exception:
                    return False

        try:
            tools = await self._list_tools_for_session(session)
            return any(self._tool_name(tool) == "browser_snapshot" for tool in tools)
        except Exception:
            return False
        finally:
            if exit_stack is not None:
                await exit_stack.aclose()

    async def close(self) -> None:
        async with self._state_lock:
            exit_stack = self._exit_stack
            self._session = None
            self._exit_stack = None
            if exit_stack is not None:
                await exit_stack.aclose()
