import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.mcp_client import PlaywrightMcpClient, parse_mcp_text_response


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_parse_mcp_text_response_extracts_dict_text_blocks() -> None:
    response = {
        "content": [
            {"type": "text", "text": "alpha"},
            {"type": "image", "data": "ignored"},
            {"type": "text", "text": "beta"},
        ]
    }

    assert parse_mcp_text_response(response) == "alpha\nbeta"


def test_parse_mcp_text_response_extracts_sdk_object_text_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="one"),
            SimpleNamespace(type="resource", text="ignored"),
            SimpleNamespace(type="text"),
            SimpleNamespace(type="text", text="two"),
        ]
    )

    assert parse_mcp_text_response(response) == "one\ntwo"


def test_parse_mcp_text_response_returns_empty_for_missing_or_non_text() -> None:
    assert parse_mcp_text_response(None) == ""
    assert (
        parse_mcp_text_response({"content": [{"type": "image", "text": "nope"}]})
        == ""
    )
    assert parse_mcp_text_response(SimpleNamespace(content=[])) == ""
    assert parse_mcp_text_response("plain text is not an MCP result") == ""


def test_resolve_command_uses_local_playwright_mcp_binary() -> None:
    with tempfile.TemporaryDirectory() as root:
        project_root = Path(root)
        bin_dir = (
            project_root
            / "integrations"
            / "playwright_mcp"
            / "node_modules"
            / ".bin"
        )
        cmd_binary = bin_dir / "playwright-mcp.cmd"
        shell_binary = bin_dir / "playwright-mcp"
        _touch(cmd_binary)
        _touch(shell_binary)

        client = PlaywrightMcpClient(project_root)

        expected = cmd_binary if os.name == "nt" else shell_binary
        assert client.resolve_command() == expected
        assert "npx" not in str(client.resolve_command()).lower()
        assert client.is_installed()


def test_resolve_command_handles_missing_cmd_binary_by_platform() -> None:
    with tempfile.TemporaryDirectory() as root:
        project_root = Path(root)
        cmd_binary = (
            project_root
            / "integrations"
            / "playwright_mcp"
            / "node_modules"
            / ".bin"
            / "playwright-mcp.cmd"
        )
        shell_binary = (
            project_root
            / "integrations"
            / "playwright_mcp"
            / "node_modules"
            / ".bin"
            / "playwright-mcp"
        )
        _touch(shell_binary)

        client = PlaywrightMcpClient(project_root)

        if os.name == "nt":
            assert client.resolve_command() == cmd_binary
            assert not client.is_installed()
        else:
            assert client.resolve_command() == shell_binary
            assert client.is_installed()


async def _run_health_check_missing_install() -> None:
    with tempfile.TemporaryDirectory() as root:
        client = PlaywrightMcpClient(Path(root))

        assert await client.health_check() is False
        assert client._session is None
        assert client._exit_stack is None


def test_health_check_returns_false_when_local_binary_missing() -> None:
    asyncio.run(_run_health_check_missing_install())


class _FailingHealthClient(PlaywrightMcpClient):
    def __init__(self, project_root: Path, exit_stack: "_FakeExitStack") -> None:
        super().__init__(project_root)
        self._fake_exit_stack = exit_stack

    def is_installed(self) -> bool:
        return True

    async def _open_session(self, command: Path):
        del command
        return object(), self._fake_exit_stack

    async def _list_tools_for_session(self, session) -> list[object]:
        del session
        raise RuntimeError("list tools failed")


async def _run_health_check_closes_resources_after_list_tools_failure() -> None:
    exit_stack = _FakeExitStack()
    client = _FailingHealthClient(Path.cwd(), exit_stack)

    assert await client.health_check() is False
    assert exit_stack.close_count == 1
    assert client._session is None
    assert client._exit_stack is None


def test_health_check_closes_resources_after_list_tools_failure() -> None:
    asyncio.run(_run_health_check_closes_resources_after_list_tools_failure())


class _SuccessfulHealthClient(PlaywrightMcpClient):
    def __init__(self, project_root: Path, exit_stack: "_FakeExitStack") -> None:
        super().__init__(project_root)
        self._fake_exit_stack = exit_stack

    def is_installed(self) -> bool:
        return True

    async def _open_session(self, command: Path):
        del command
        return object(), self._fake_exit_stack

    async def _list_tools_for_session(self, session) -> list[object]:
        del session
        return [SimpleNamespace(name="browser_snapshot")]


async def _run_health_check_closes_resources_it_opens() -> None:
    exit_stack = _FakeExitStack()
    client = _SuccessfulHealthClient(Path.cwd(), exit_stack)

    assert await client.health_check() is True
    assert exit_stack.close_count == 1
    assert client._session is None
    assert client._exit_stack is None


def test_health_check_closes_resources_it_opens() -> None:
    asyncio.run(_run_health_check_closes_resources_it_opens())


class _MissingSnapshotHealthClient(_SuccessfulHealthClient):
    async def _list_tools_for_session(self, session) -> list[object]:
        del session
        return [SimpleNamespace(name="browser_click")]


async def _run_health_check_requires_browser_snapshot_tool() -> None:
    exit_stack = _FakeExitStack()
    client = _MissingSnapshotHealthClient(Path.cwd(), exit_stack)

    assert await client.health_check() is False
    assert exit_stack.close_count == 1
    assert client._session is None
    assert client._exit_stack is None


def test_health_check_requires_browser_snapshot_tool() -> None:
    asyncio.run(_run_health_check_requires_browser_snapshot_tool())


class _CancelledHealthClient(_SuccessfulHealthClient):
    async def _list_tools_for_session(self, session) -> list[object]:
        del session
        raise asyncio.CancelledError()


async def _run_health_check_closes_resources_on_cancellation() -> None:
    exit_stack = _FakeExitStack()
    client = _CancelledHealthClient(Path.cwd(), exit_stack)

    try:
        await client.health_check()
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("health_check should propagate cancellation")

    assert exit_stack.close_count == 1
    assert client._session is None
    assert client._exit_stack is None


def test_health_check_closes_resources_on_cancellation() -> None:
    asyncio.run(_run_health_check_closes_resources_on_cancellation())


class _ConcurrentConnectClient(PlaywrightMcpClient):
    def __init__(self, project_root: Path, exit_stack: "_FakeExitStack") -> None:
        super().__init__(project_root)
        self._fake_exit_stack = exit_stack
        self.open_count = 0

    async def _open_session(self, command: Path):
        del command
        self.open_count += 1
        await asyncio.sleep(0.01)
        return object(), self._fake_exit_stack


async def _run_connect_serializes_concurrent_openers() -> None:
    with tempfile.TemporaryDirectory() as root:
        project_root = Path(root)
        command = (
            project_root
            / "integrations"
            / "playwright_mcp"
            / "node_modules"
            / ".bin"
            / ("playwright-mcp.cmd" if os.name == "nt" else "playwright-mcp")
        )
        _touch(command)
        exit_stack = _FakeExitStack()
        client = _ConcurrentConnectClient(project_root, exit_stack)

        first, second = await asyncio.gather(client.connect(), client.connect())

        assert first is second
        assert client.open_count == 1
        await client.close()
        assert exit_stack.close_count == 1


def test_connect_serializes_concurrent_openers() -> None:
    asyncio.run(_run_connect_serializes_concurrent_openers())


class _RaceHealthClient(PlaywrightMcpClient):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.opened: list[tuple[object, _FakeExitStack]] = []
        self.health_listing_started = asyncio.Event()
        self.allow_health_listing = asyncio.Event()

    async def _open_session(self, command: Path):
        del command
        session = object()
        exit_stack = _FakeExitStack()
        self.opened.append((session, exit_stack))
        return session, exit_stack

    async def _list_tools_for_session(self, session) -> list[object]:
        if self.opened and session is self.opened[0][0]:
            self.health_listing_started.set()
            await self.allow_health_listing.wait()
        return [SimpleNamespace(name="browser_snapshot")]


async def _run_health_check_does_not_close_concurrent_connect_session() -> None:
    with tempfile.TemporaryDirectory() as root:
        project_root = Path(root)
        command = (
            project_root
            / "integrations"
            / "playwright_mcp"
            / "node_modules"
            / ".bin"
            / ("playwright-mcp.cmd" if os.name == "nt" else "playwright-mcp")
        )
        _touch(command)
        client = _RaceHealthClient(project_root)

        health_task = asyncio.create_task(client.health_check())
        await client.health_listing_started.wait()
        connect_task = asyncio.create_task(client.connect())
        await asyncio.sleep(0)
        client.allow_health_listing.set()

        assert await health_task is True
        shared_session = await connect_task
        assert client._session is shared_session
        assert len(client.opened) == 2
        health_stack = client.opened[0][1]
        shared_stack = client.opened[1][1]
        assert health_stack.close_count == 1
        assert shared_stack.close_count == 0

        await client.close()
        assert shared_stack.close_count == 1


def test_health_check_does_not_close_concurrent_connect_session() -> None:
    asyncio.run(_run_health_check_does_not_close_concurrent_connect_session())


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, object] | None = None):
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "tool result"}]}


async def _run_call_tool_parses_fake_session_response() -> None:
    client = PlaywrightMcpClient(Path.cwd())
    fake_session = _FakeSession()
    client._session = fake_session

    result = await client.call_tool("browser_snapshot", {"verbose": True})

    assert result == "tool result"
    assert fake_session.calls == [("browser_snapshot", {"verbose": True})]


def test_call_tool_parses_fake_session_response() -> None:
    asyncio.run(_run_call_tool_parses_fake_session_response())


class _FakeExitStack:
    def __init__(self) -> None:
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


async def _run_close_is_idempotent_and_clears_cached_resources() -> None:
    client = PlaywrightMcpClient(Path.cwd())
    exit_stack = _FakeExitStack()
    client._session = object()
    client._exit_stack = exit_stack

    await client.close()
    await client.close()

    assert exit_stack.close_count == 1
    assert client._session is None
    assert client._exit_stack is None


def test_close_is_idempotent_and_clears_cached_resources() -> None:
    asyncio.run(_run_close_is_idempotent_and_clears_cached_resources())


if __name__ == "__main__":
    test_parse_mcp_text_response_extracts_dict_text_blocks()
    test_parse_mcp_text_response_extracts_sdk_object_text_blocks()
    test_parse_mcp_text_response_returns_empty_for_missing_or_non_text()
    test_resolve_command_uses_local_playwright_mcp_binary()
    test_resolve_command_handles_missing_cmd_binary_by_platform()
    test_health_check_returns_false_when_local_binary_missing()
    test_health_check_closes_resources_after_list_tools_failure()
    test_health_check_closes_resources_it_opens()
    test_health_check_requires_browser_snapshot_tool()
    test_health_check_closes_resources_on_cancellation()
    test_connect_serializes_concurrent_openers()
    test_health_check_does_not_close_concurrent_connect_session()
    test_call_tool_parses_fake_session_response()
    test_close_is_idempotent_and_clears_cached_resources()
    print("PASS")
