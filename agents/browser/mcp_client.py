from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Implementation


class McpToolError(RuntimeError):
    """The MCP server failed to execute an operation."""


@dataclass(frozen=True)
class McpToolResult:
    text: str
    is_error: bool = False
    structured: dict | None = None

    def require_success(self) -> "McpToolResult":
        if self.is_error or self.text.lstrip().startswith("### Error"):
            # Raw server errors may contain page contents or query strings.
            if "playwright extension not found" in self.text.lower():
                raise McpToolError("Install the official Playwright Extension in the Chrome profile you want to share, then connect again.")
            if "extension not connected" in self.text.lower():
                raise McpToolError("Open Chrome and complete the Playwright Extension connection prompt, then connect again.")
            raise McpToolError("Browser tool failed; inspect the selected tab and reconnect if needed.")
        return self


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


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
    def __init__(self, project_root: Path | None = None, *, extension: bool = False,
                 browser: str = "chrome", executable_path: str | None = None,
                 headless: bool = False, timeout: float = 45.0) -> None:
        if extension and browser not in {"chrome", "msedge"}:
            raise ValueError("Official extension mode supports chrome or msedge channels.")
        self.extension = extension
        self.browser = browser
        self.executable_path = executable_path
        self.headless = headless
        self.timeout = max(1.0, min(float(timeout), 120.0))
        self.project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._state_lock = asyncio.Lock()
        self._owner_lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._requests: asyncio.Queue = asyncio.Queue()
        self._closing = False

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

    def server_parameters(self, command: Path) -> StdioServerParameters:
        args = ["--image-responses", "omit", "--codegen", "none"]
        if self.extension:
            args.extend(["--extension", "--browser", self.browser])
        if self.executable_path:
            args.extend(["--executable-path", self.executable_path])
        if self.headless and not self.extension:
            args.extend(["--headless", "--isolated"])
        cli = self.integration_dir / "node_modules" / "@playwright" / "mcp" / "cli.js"
        executable = str(command)
        if os.name == "nt" and cli.is_file():
            executable = shutil.which("node") or "node"
            args.insert(0, str(cli))
        # Use the SDK's minimal inherited environment, plus optional pairing data.
        token = os.getenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "").strip()
        environment = {"PLAYWRIGHT_MCP_EXTENSION_TOKEN": token} if token else None
        return StdioServerParameters(command=executable, args=args,
            cwd=str(self.integration_dir if self.integration_dir.is_dir() else self.project_root),
            env=environment)

    async def _open_session(self, command: Path) -> tuple[ClientSession, AsyncExitStack]:
        exit_stack = AsyncExitStack()
        try:
            server = self.server_parameters(command)
            output = exit_stack.enter_context(tempfile.TemporaryDirectory(prefix="jarvis-browser-output-"))
            server.args.extend(["--output-dir", output])
            read_stream, write_stream = await exit_stack.enter_async_context(
                stdio_client(server)
            )
            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream, client_info=Implementation(name="JARVIS", version="1.0"))
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
        if self.extension or self._owner is not None:
            return await self._owned_request("tools", None)
        session = await self.connect()
        return await self._list_tools_for_session(session)

    async def _list_tools_for_session(self, session: ClientSession) -> list[Any]:
        result = await session.list_tools()
        tools = getattr(result, "tools", result)
        return list(tools or [])

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        if self.extension or self._owner is not None:
            return (await self.call_result(name, arguments)).require_success().text
        session = await self.connect()
        response = await session.call_tool(name, arguments)
        return parse_mcp_text_response(response)

    async def call_result(self, name: str, arguments: dict[str, Any] | None = None) -> McpToolResult:
        response = await self._owned_request("call", (name, arguments or {}))
        structured = _field(response, "structuredContent")
        return McpToolResult(parse_mcp_text_response(response), bool(_field(response, "isError", False)),
                             structured if isinstance(structured, dict) else None)

    async def tool_schemas(self) -> dict[str, dict]:
        tools = await self._owned_request("tools", None)
        return {self._tool_name(tool): _field(tool, "inputSchema", {}) for tool in tools}

    async def _owned_request(self, operation: str, value: Any) -> Any:
        async with self._owner_lock:
            if self._closing:
                raise McpToolError("Browser connection is closing.")
            if self._owner is None or self._owner.done():
                self._owner = asyncio.create_task(self._serve_requests(), name="jarvis-browser-mcp")
            future = asyncio.get_running_loop().create_future()
            self._requests.put_nowait((operation, value, future))
        try:
            return await asyncio.wait_for(future, timeout=self.timeout + 5)
        except asyncio.TimeoutError as exc:
            raise McpToolError("Browser connection timed out; outcome may be unknown. Reconnect before continuing.") from exc

    async def _serve_requests(self) -> None:
        # Opening and closing AnyIO's stdio scopes must happen in the SAME task.
        current = None
        try:
            while True:
                operation, value, current = await self._requests.get()
                if current.cancelled():
                    continue
                try:
                    async with asyncio.timeout(self.timeout):
                        session = await self.connect()
                        if current.cancelled():
                            continue
                        if operation == "tools":
                            result = await self._list_tools_for_session(session)
                        else:
                            name, arguments = value
                            result = await session.call_tool(name, arguments)
                    if not current.done():
                        current.set_result(result)
                except Exception as exc:
                    if not current.done():
                        current.set_exception(McpToolError(f"Browser transport failed ({type(exc).__name__}); reconnect or check extension setup."))
        finally:
            if current is not None and not current.done():
                current.cancel()
            while not self._requests.empty():
                _, _, pending = self._requests.get_nowait()
                if not pending.done():
                    pending.cancel()
            await self._close_session()

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
        if self.extension:
            try:
                return "browser_snapshot" in await self.tool_schemas()
            except Exception:
                return False
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
        async with self._owner_lock:
            self._closing = True
            owner = self._owner
            if owner is not None:
                owner.cancel()
        try:
            if owner is not None:
                await asyncio.gather(owner, return_exceptions=True)
            else:
                await self._close_session()
        finally:
            self._owner = None
            self._closing = False

    async def _close_session(self) -> None:
        async with self._state_lock:
            exit_stack = self._exit_stack
            self._session = None
            self._exit_stack = None
            if exit_stack is not None:
                await exit_stack.aclose()
