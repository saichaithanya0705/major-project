from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class TavilyMcpConfigurationError(RuntimeError):
    pass


_PROJECT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_TAVILY_PLACEHOLDERS = {"", "YOUR_TAVILY_API_KEY"}


def _read_tavily_api_key_from_project_env() -> str:
    try:
        value = dotenv_values(_PROJECT_ENV_PATH).get("TAVILY_API_KEY", "")
    except Exception:
        return ""
    api_key = str(value or "").strip()
    return "" if api_key in _TAVILY_PLACEHOLDERS else api_key


def _content_item_text(item: Any) -> str:
    if isinstance(item, dict):
        item_type = item.get("type")
        text = item.get("text")
    else:
        item_type = getattr(item, "type", None)
        text = getattr(item, "text", None)
    if item_type == "text" and isinstance(text, str):
        return text
    return ""


def parse_mcp_text_response(response: Any) -> str:
    if response is None:
        return ""

    if isinstance(response, dict):
        content = response.get("content")
    else:
        content = getattr(response, "content", None)

    if content is None or isinstance(content, (str, bytes)):
        return ""

    try:
        items = list(content)
    except TypeError:
        return ""

    return "\n".join(text for text in (_content_item_text(item) for item in items) if text)


def _parse_json_payload(text: str) -> Any:
    candidates: list[str] = []
    stripped = (text or "").strip()
    if stripped:
        candidates.append(stripped)
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidates.append("\n".join(lines[1:-1]).strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start >= 0 and end > start:
            candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def parse_mcp_payload(response: Any) -> Any:
    if isinstance(response, dict):
        for key in ("structuredContent", "structured_content"):
            value = response.get(key)
            if value:
                return value
    else:
        for attr in ("structuredContent", "structured_content"):
            value = getattr(response, attr, None)
            if value:
                return value

    text = parse_mcp_text_response(response)
    parsed = _parse_json_payload(text)
    if parsed is not None:
        return parsed
    return {"raw_content": text} if text else {}


class TavilyMcpClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        command: str = "npx",
        args: list[str] | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = (api_key if api_key is not None else _read_tavily_api_key_from_project_env()).strip()
        self.command = command
        self.args = list(args) if args is not None else ["-y", "tavily-mcp@latest"]
        self.timeout_seconds = float(timeout_seconds)
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._state_lock = asyncio.Lock()
        self._search_tool_name = ""

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _open_session(self) -> tuple[ClientSession, AsyncExitStack]:
        if not self.is_configured():
            raise TavilyMcpConfigurationError(
                "Tavily web search is not configured. Set TAVILY_API_KEY to enable source-grounded web Q&A."
            )

        exit_stack = AsyncExitStack()
        try:
            env = dict(os.environ)
            env["TAVILY_API_KEY"] = self.api_key
            server = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=env,
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
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    session, exit_stack = await self._open_session()
            except BaseException:
                self._session = None
                self._exit_stack = None
                raise
            self._session = session
            self._exit_stack = exit_stack
            return session

    @staticmethod
    def _tool_name(tool: Any) -> str:
        if isinstance(tool, dict):
            value = tool.get("name")
        else:
            value = getattr(tool, "name", None)
        return str(value or "")

    async def _resolve_search_tool_name(self) -> str:
        if self._search_tool_name:
            return self._search_tool_name

        session = await self.connect()
        async with asyncio.timeout(self.timeout_seconds):
            result = await session.list_tools()
        tools = getattr(result, "tools", result)
        names = {self._tool_name(tool) for tool in list(tools or [])}
        for candidate in ("tavily_search", "tavily-search", "search"):
            if candidate in names:
                self._search_tool_name = candidate
                return candidate
        raise RuntimeError("Tavily MCP server did not expose a tavily_search tool.")

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        session = await self.connect()
        async with asyncio.timeout(self.timeout_seconds):
            response = await session.call_tool(name, arguments or {})
        return parse_mcp_payload(response)

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> Any:
        tool_name = await self._resolve_search_tool_name()
        return await self.call_tool(
            tool_name,
            {
                "query": query,
                "max_results": int(max_results),
                "search_depth": search_depth,
            },
        )

    async def close(self) -> None:
        async with self._state_lock:
            exit_stack = self._exit_stack
            self._session = None
            self._exit_stack = None
            if exit_stack is not None:
                await exit_stack.aclose()
