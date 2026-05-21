"""
Lightweight checks for BrowserAgent fallback helpers.

Usage:
    python tests/test_browser_agent_fallback.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.browser.agent as browser_agent_module
from agents.browser.agent import BrowserAgent
from agents.browser.browser_use_boundary import BrowserUseSessionPolicy, BrowserUseToolPolicy
from agents.browser.page_context import PageContext


class _FakePage:
    def __init__(self, url: str, title_text: str):
        self.url = url
        self._title_text = title_text
        self.body_text = ""
        self.goto_calls: list[str] = []

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        self.goto_calls.append(url)
        self.url = url

    async def wait_for_timeout(self, ms: int):
        return None

    async def title(self) -> str:
        return self._title_text

    async def evaluate(self, script: str):
        del script
        return self.body_text

    def is_closed(self) -> bool:
        return False


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages

    async def new_page(self):
        page = _FakePage("about:blank", "Blank")
        self.pages.append(page)
        return page


class _FakePlaywrightController:
    def __init__(self):
        self.navigate_calls: list[str] = []

    async def navigate_and_extract(self, url: str) -> PageContext:
        self.navigate_calls.append(url)
        return PageContext(
            title="Example Docs",
            url=url,
            headings=["Overview", "Usage"],
            text=(
                "Example Docs expected text explains the deterministic controller "
                "summary path. It avoids the browser-use fallback for page reading."
            ),
        )


class _FakePlaywrightMcpClient:
    snapshot_text = '- button "Submit" [ref=e12]\n- textbox "Search" [ref=e5]'

    def __init__(self):
        self.health_check_calls = 0
        self.snapshot_calls = 0
        self.close_calls = 0

    async def health_check(self) -> bool:
        self.health_check_calls += 1
        return True

    async def snapshot(self) -> str:
        self.snapshot_calls += 1
        return self.snapshot_text

    def close(self) -> None:
        self.close_calls += 1


class _FakeBrowserUseAgent:
    def __init__(self):
        self.state = SimpleNamespace(stopped=False)

    async def run(self):
        return {"summary": "browser-use completed"}


class _FakeBrowserUseBoundary:
    def __init__(self):
        self.create_session_calls = 0
        self.cleanup_calls: list[tuple[object, str | None]] = []
        self.keep_session_alive_calls = 0
        self.created_session = object()
        self.session_policies: list[BrowserUseSessionPolicy] = []
        self.tool_policies: list[BrowserUseToolPolicy] = []

    def import_google_llm_class(self):
        class _FakeChatGoogle:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        return _FakeChatGoogle

    def create_session(self, **kwargs):
        self.create_session_calls += 1
        self.session_policies.append(kwargs["session_policy"])
        return SimpleNamespace(
            session=self.created_session,
            user_data_dir=r"C:\Temp\jarvis-browser-use-session",
        )

    def keep_session_alive(self, session):
        self.keep_session_alive_calls += 1
        assert session is self.created_session

    async def cleanup_session(self, session, *, user_data_dir=None, expected_prefix="jarvis-browser-use-"):
        del expected_prefix
        self.cleanup_calls.append((session, user_data_dir))

    def create_agent(self, **kwargs):
        self.tool_policies.append(kwargs["tool_policy"])
        return _FakeBrowserUseAgent()


async def _run_backend_reuse_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_close = cls._close_shared_resources
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright

    calls: list[str] = []

    async def _fake_close_shared_resources(inner_cls):
        inner_cls._shared_backend = None

    async def _fake_execute_browser_use(task: str, close_when_done: bool):
        calls.append(f"browser_use:{task}")
        return {"success": True, "result": task, "error": None}

    async def _fake_execute_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        calls.append(f"playwright:{task}")
        return {"success": True, "result": task, "error": None}

    cls._close_shared_resources = classmethod(_fake_close_shared_resources)
    agent._execute_with_browser_use = _fake_execute_browser_use
    agent._execute_with_playwright = _fake_execute_playwright
    try:
        cls._shared_backend = "browser_use"
        result = await agent.execute("task-1")
        assert result["success"]
        assert calls[-1] == "browser_use:task-1", calls

        cls._shared_backend = "playwright"
        result = await agent.execute("task-2")
        assert result["success"]
        assert calls[-1] == "playwright:task-2", calls
    finally:
        cls._shared_backend = original_backend
        cls._close_shared_resources = original_close
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_playwright_fast_path_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright

    calls: list[str] = []

    async def _fake_execute_browser_use(task: str, close_when_done: bool):
        calls.append(f"browser_use:{task}")
        return {"success": True, "result": task, "error": None}

    async def _fake_execute_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        calls.append(f"playwright:{task}")
        return {"success": True, "result": task, "error": None}

    agent._execute_with_browser_use = _fake_execute_browser_use
    agent._execute_with_playwright = _fake_execute_playwright
    try:
        cls._shared_backend = None
        result = await agent.execute("open https://example.com")
        assert result["success"]
        assert calls[-1] == "playwright:open https://example.com", calls

        cls._shared_backend = None
        result = await agent.execute("open https://example.com and submit the form")
        assert result["success"]
        assert calls[-1] == "browser_use:open https://example.com and submit the form", calls
    finally:
        cls._shared_backend = original_backend
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_playwright_controller_direct_summary_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright

    controller = _FakePlaywrightController()

    async def _fail_browser_use(task: str, close_when_done: bool):
        del close_when_done
        raise AssertionError(f"browser_use should not handle page content task: {task}")

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright fallback should not handle page content task: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = controller
    agent._execute_with_browser_use = _fail_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("summarize https://example.com/docs")
        assert result["success"], result
        assert result["complete"] is True, result
        assert result["result"]["complete"] is True, result
        assert result["result"]["mode"] == "playwright_controller", result
        assert result["result"]["url"] == "https://example.com/docs", result
        assert result["result"]["title"] == "Example Docs", result
        assert result["result"]["headings"] == ["Overview", "Usage"], result
        summary = result["result"]["summary"]
        assert "Summary of Example Docs" in summary, summary
        assert "expected text explains the deterministic controller" in summary, summary
        assert controller.navigate_calls == ["https://example.com/docs"], controller.navigate_calls
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_playwright_controller_skips_query_summary_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _FailingController:
        async def navigate_and_extract(self, url: str):
            raise AssertionError(f"controller should not navigate for query summary: {url}")

        async def get_or_create_page(self):
            raise AssertionError("controller should not create a page for query summary")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use handled the query-style summary."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not be needed for query summary: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = _FailingController()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("fetch me the summary of world war 1 wikipedia page")
        assert result["success"], result
        assert result["complete"] is True, result
        assert calls == ["browser_use:fetch me the summary of world war 1 wikipedia page"], calls
        assert "Browser-use handled" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_playwright_controller_error_falls_back_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _FailingController:
        async def navigate_and_extract(self, url: str):
            calls.append(f"controller:{url}")
            raise RuntimeError("controller launch failed")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use recovered after controller failure."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not be needed after browser_use recovery: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = _FailingController()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("summarize https://example.com/docs")
        assert result["success"], result
        assert result["complete"] is True, result
        assert calls == [
            "controller:https://example.com/docs",
            "browser_use:summarize https://example.com/docs",
        ], calls
        assert "recovered after controller failure" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_controller_summary_failure_is_not_swallowed_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    original_formatter = browser_agent_module.format_page_context_response

    controller = _FakePlaywrightController()

    async def _unexpected_browser_use(task: str, close_when_done: bool):
        del task, close_when_done
        return {
            "success": True,
            "result": {"summary": "browser_use fallback should not run here."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del task, bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError("legacy Playwright fallback should not run for formatter failures")

    def _broken_formatter(task: str, context: PageContext) -> str:
        del task, context
        raise RuntimeError("controller summary formatting failed")

    cls._shared_backend = None
    cls._shared_playwright_controller = controller
    agent._execute_with_browser_use = _unexpected_browser_use
    agent._execute_with_playwright = _fail_playwright
    browser_agent_module.format_page_context_response = _broken_formatter
    try:
        try:
            await agent.execute("summarize https://example.com/docs")
            raise AssertionError("Expected formatter failure to surface past BrowserAgent shell.")
        except RuntimeError as exc:
            assert str(exc) == "controller summary formatting failed", exc
        assert controller.navigate_calls == ["https://example.com/docs"], controller.navigate_calls
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright
        browser_agent_module.format_page_context_response = original_formatter


async def _run_controller_current_page_does_not_override_active_backend_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _FailingController:
        async def get_or_create_page(self):
            raise AssertionError("controller should not read current page owned by browser_use")

        async def extract_context(self, page=None):
            raise AssertionError("controller should not extract current page owned by browser_use")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use kept ownership of the current page."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not be needed for browser_use current page: {task}")

    cls._shared_backend = "browser_use"
    cls._shared_playwright_controller = _FailingController()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("summarize the current page")
        assert result["success"], result
        assert result["complete"] is True, result
        assert len(calls) == 1 and calls[0].startswith("browser_use:"), calls
        assert "summarize the current page" in calls[0], calls
        assert "do not perform web search" in calls[0].lower(), calls
        assert "kept ownership" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_controller_current_page_requires_open_page_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _ClosedController:
        def has_open_page(self) -> bool:
            return False

        async def get_or_create_page(self):
            raise AssertionError("controller should not create a blank page for current-page reads")

        async def extract_context(self, page=None):
            raise AssertionError("controller should not extract without an open owned page")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use handled the current-page read."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not be needed for current-page read: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = _ClosedController()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("summarize the current page")
        assert result["success"], result
        assert result["complete"] is True, result
        assert calls == ["browser_use:summarize the current page"], calls
        assert "handled the current-page read" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_playwright_mcp_snapshot_route_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_mcp_client = getattr(cls, "_shared_playwright_mcp_client", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright

    fake_client = _FakePlaywrightMcpClient()
    browser_use_calls: list[str] = []

    async def _fail_browser_use(task: str, close_when_done: bool):
        del close_when_done
        browser_use_calls.append(task)
        raise AssertionError(f"browser_use should not handle MCP snapshot task: {task}")

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not handle MCP snapshot task: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = None
    cls._shared_playwright_mcp_client = fake_client
    agent._execute_with_browser_use = _fail_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("click the submit button based on the current page")
        assert result["success"], result
        assert result["complete"] is False, result
        assert result["result"]["complete"] is False, result
        assert result["result"]["mode"] == "playwright_mcp_snapshot", result
        assert result["result"]["task"] == "click the submit button based on the current page", result
        assert fake_client.health_check_calls == 1, fake_client.health_check_calls
        assert fake_client.snapshot_calls == 1, fake_client.snapshot_calls
        assert browser_use_calls == [], browser_use_calls
        summary = result["result"]["summary"]
        assert "Submit" in summary, summary
        assert result["result"]["snapshot"] == fake_client.snapshot_text, result

        await cls._close_shared_resources()
        assert fake_client.close_calls == 1, fake_client.close_calls
        assert getattr(cls, "_shared_playwright_mcp_client", None) is None
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        cls._shared_playwright_mcp_client = original_mcp_client
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_mcp_snapshot_skips_direct_url_interaction_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_mcp_client = getattr(cls, "_shared_playwright_mcp_client", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _FailingMcpClient:
        async def health_check(self) -> bool:
            raise AssertionError("MCP should not inspect direct URL interaction tasks")

        async def snapshot(self) -> str:
            raise AssertionError("MCP should not snapshot direct URL interaction tasks")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use handled the direct URL interaction."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not handle direct URL interaction: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = None
    cls._shared_playwright_mcp_client = _FailingMcpClient()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("open https://example.com and click the sign in button")
        assert result["success"], result
        assert result["complete"] is True, result
        assert calls == ["browser_use:open https://example.com and click the sign in button"], calls
        assert "direct URL interaction" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        cls._shared_playwright_mcp_client = original_mcp_client
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_mcp_snapshot_does_not_override_active_backend_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_mcp_client = getattr(cls, "_shared_playwright_mcp_client", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _FailingMcpClient:
        async def health_check(self) -> bool:
            raise AssertionError("MCP should not inspect a page owned by browser_use")

        async def snapshot(self) -> str:
            raise AssertionError("MCP should not snapshot a page owned by browser_use")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use handled the current-page interaction."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not handle browser_use-owned task: {task}")

    cls._shared_backend = "browser_use"
    cls._shared_playwright_mcp_client = _FailingMcpClient()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("click the submit button based on the current page")
        assert result["success"], result
        assert result["complete"] is True, result
        assert len(calls) == 1 and calls[0].startswith("browser_use:"), calls
        assert "click the submit button based on the current page" in calls[0], calls
        assert "handled the current-page interaction" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_mcp_client = original_mcp_client
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_mcp_snapshot_does_not_override_controller_page_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = getattr(cls, "_shared_playwright_controller", None)
    original_mcp_client = getattr(cls, "_shared_playwright_mcp_client", None)
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    class _ControllerOwner:
        pass

    class _FailingMcpClient:
        async def health_check(self) -> bool:
            raise AssertionError("MCP should not inspect a page owned by the controller")

        async def snapshot(self) -> str:
            raise AssertionError("MCP should not snapshot a page owned by the controller")

    async def _fake_browser_use(task: str, close_when_done: bool):
        del close_when_done
        calls.append(f"browser_use:{task}")
        return {
            "success": True,
            "result": {"summary": "Browser-use handled the controller-owned current-page task."},
            "error": None,
            "complete": True,
        }

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del bootstrap_error, close_when_done, pre_extracted_url
        raise AssertionError(f"legacy Playwright should not handle controller-owned task: {task}")

    cls._shared_backend = None
    cls._shared_playwright_controller = _ControllerOwner()
    cls._shared_playwright_mcp_client = _FailingMcpClient()
    agent._execute_with_browser_use = _fake_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("click the submit button based on the current page")
        assert result["success"], result
        assert result["complete"] is True, result
        assert len(calls) == 1 and calls[0].startswith("browser_use:"), calls
        assert "click the submit button based on the current page" in calls[0], calls
        assert "controller-owned current-page task" in result["result"]["summary"], result
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
        cls._shared_playwright_mcp_client = original_mcp_client
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_no_search_when_reusing_page_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_context = cls._shared_playwright_context
    original_page = cls._shared_playwright_page
    original_get_page = agent._get_or_create_playwright_page
    original_open_result = agent._open_first_duckduckgo_result

    page = _FakePage("http://localhost:3000/", "ScopeGrade")
    context = _FakeContext([page])

    async def _fake_get_or_create_playwright_page():
        return page, False

    async def _fail_if_search_used(_page):
        raise AssertionError("Search fallback should not execute for current-page tasks.")

    cls._shared_playwright_context = context
    cls._shared_playwright_page = page
    agent._get_or_create_playwright_page = _fake_get_or_create_playwright_page
    agent._open_first_duckduckgo_result = _fail_if_search_used
    try:
        result = await agent._execute_with_playwright(
            "On the currently open ScopeGrade page, upload ECE_131A_HW5.zip",
            bootstrap_error="",
            close_when_done=False,
        )
        assert result["success"], result
        summary = result["result"]["summary"]
        assert "current-tab context fallback" in summary.lower(), summary
        assert not any("duckduckgo.com" in url for url in page.goto_calls), page.goto_calls
    finally:
        cls._shared_playwright_context = original_context
        cls._shared_playwright_page = original_page
        agent._get_or_create_playwright_page = original_get_page
        agent._open_first_duckduckgo_result = original_open_result


async def _run_playwright_interaction_is_partial_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_context = cls._shared_playwright_context
    original_page = cls._shared_playwright_page
    original_get_page = agent._get_or_create_playwright_page

    page = _FakePage("about:blank", "ChatGPT")
    context = _FakeContext([page])

    async def _fake_get_or_create_playwright_page():
        return page, False

    cls._shared_playwright_context = context
    cls._shared_playwright_page = page
    agent._get_or_create_playwright_page = _fake_get_or_create_playwright_page
    try:
        result = await agent._execute_with_playwright(
            "goto chat.openai.com website and ask it for top 3 ml learning resources",
            bootstrap_error="browser_use unavailable",
            close_when_done=False,
        )
        assert result["success"], result
        assert result["complete"] is False, result
        assert result["result"]["complete"] is False, result
        assert "interactive browser automation is still required" in result["result"]["summary"], result
    finally:
        cls._shared_playwright_context = original_context
        cls._shared_playwright_page = original_page
        agent._get_or_create_playwright_page = original_get_page


async def _run_playwright_page_summary_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_context = cls._shared_playwright_context
    original_page = cls._shared_playwright_page
    original_get_page = agent._get_or_create_playwright_page
    original_open_result = agent._open_first_duckduckgo_result

    page = _FakePage("about:blank", "DuckDuckGo")
    page.body_text = (
        "World War I was a global conflict between two coalitions, the Allies and the Central Powers. "
        "Fighting took place throughout Europe, the Middle East, Africa, the Pacific, and parts of Asia. "
        "The war lasted from 1914 to 1918 and reshaped the political order of Europe."
    )
    context = _FakeContext([page])

    async def _fake_get_or_create_playwright_page():
        return page, False

    async def _fake_open_first_result(opened_page):
        opened_page.url = "https://en.wikipedia.org/wiki/World_War_I"
        opened_page._title_text = "World War I - Wikipedia"

    cls._shared_playwright_context = context
    cls._shared_playwright_page = page
    agent._get_or_create_playwright_page = _fake_get_or_create_playwright_page
    agent._open_first_duckduckgo_result = _fake_open_first_result
    try:
        result = await agent._execute_with_playwright(
            "fetch me the summary of world war 1 wikipedia page",
            bootstrap_error="browser_use unavailable",
            close_when_done=False,
        )
        assert result["success"], result
        assert result["complete"] is True, result
        summary = result["result"]["summary"]
        assert "World War I - Wikipedia" in summary, summary
        assert "global conflict between two coalitions" in summary, summary
        assert "Browser task completed via search fallback" not in summary, summary
    finally:
        cls._shared_playwright_context = original_context
        cls._shared_playwright_page = original_page
        agent._get_or_create_playwright_page = original_get_page
        agent._open_first_duckduckgo_result = original_open_result


async def _run_dependency_error_uses_shared_playwright_fallback_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright
    calls: list[str] = []

    async def _fail_browser_use(task: str, close_when_done: bool):
        del task, close_when_done
        raise ModuleNotFoundError("No module named 'browser_use'")

    async def _fake_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del close_when_done
        calls.append(f"playwright:{task}")
        calls.append(f"bootstrap:{bootstrap_error}")
        calls.append(f"url:{pre_extracted_url}")
        return {
            "success": True,
            "result": {"summary": "Playwright fallback recovered the task."},
            "error": None,
            "complete": True,
        }

    cls._shared_backend = None
    agent._execute_with_browser_use = _fail_browser_use
    agent._execute_with_playwright = _fake_playwright
    try:
        result = await agent.execute("open https://example.com and submit the form")
        assert result["success"], result
        assert calls[0] == "playwright:open https://example.com and submit the form", calls
        assert "No module named 'browser_use'" in calls[1], calls
        assert calls[2] == "url:https://example.com", calls
    finally:
        cls._shared_backend = original_backend
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_browser_use_and_playwright_dual_failure_message_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_execute_browser_use = agent._execute_with_browser_use
    original_execute_playwright = agent._execute_with_playwright

    async def _fail_browser_use(task: str, close_when_done: bool):
        del task, close_when_done
        raise ImportError("Failed to import BrowserSession")

    async def _fail_playwright(
        task: str,
        bootstrap_error: str,
        close_when_done: bool,
        pre_extracted_url: str | None = None,
    ):
        del task, bootstrap_error, close_when_done, pre_extracted_url
        raise RuntimeError("playwright launch failed")

    cls._shared_backend = None
    agent._execute_with_browser_use = _fail_browser_use
    agent._execute_with_playwright = _fail_playwright
    try:
        result = await agent.execute("open https://example.com and submit the form")
        assert result["success"] is False, result
        assert result["result"] is None, result
        error = result["error"]
        assert "Browser task failed in both browser_use and Playwright fallback." in error, error
        assert "bootstrap_error=Failed to import BrowserSession" in error, error
        assert "fallback_error=playwright launch failed" in error, error
    finally:
        cls._shared_backend = original_backend
        agent._execute_with_browser_use = original_execute_browser_use
        agent._execute_with_playwright = original_execute_playwright


async def _run_browser_use_tool_policy_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_boundary = cls._browser_use_boundary
    original_policy = cls._browser_use_tool_policy
    original_resolution = cls._ensure_external_browser_use_resolution
    original_get_session = agent._get_or_create_browser_use_session
    original_close = cls._close_shared_resources

    fake_boundary = _FakeBrowserUseBoundary()

    async def _fake_get_session():
        return object()

    async def _fake_close_shared_resources(inner_cls):
        del inner_cls
        return None

    cls._browser_use_boundary = fake_boundary
    cls._browser_use_tool_policy = BrowserUseToolPolicy()
    cls._ensure_external_browser_use_resolution = classmethod(lambda inner_cls: None)
    agent._get_or_create_browser_use_session = _fake_get_session
    cls._close_shared_resources = classmethod(_fake_close_shared_resources)
    try:
        result = await agent._execute_with_browser_use("open https://example.com", close_when_done=False)
        assert result["success"], result
        assert len(fake_boundary.tool_policies) == 1, fake_boundary.tool_policies
        assert fake_boundary.tool_policies[0].excluded_actions == (
            "write_file",
            "replace_file",
        ), fake_boundary.tool_policies[0]
    finally:
        cls._browser_use_boundary = original_boundary
        cls._browser_use_tool_policy = original_policy
        cls._ensure_external_browser_use_resolution = original_resolution
        agent._get_or_create_browser_use_session = original_get_session
        cls._close_shared_resources = original_close


async def _run_browser_use_session_policy_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_boundary = cls._browser_use_boundary
    original_policy = cls._browser_use_session_policy
    original_resolution = cls._ensure_external_browser_use_resolution
    original_backend = cls._shared_backend
    original_session = cls._shared_browser_use_session
    original_user_data_dir = cls._shared_browser_use_user_data_dir

    fake_boundary = _FakeBrowserUseBoundary()

    cls._browser_use_boundary = fake_boundary
    cls._browser_use_session_policy = BrowserUseSessionPolicy(
        headless=False,
        keep_alive=True,
        temp_prefix="jarvis-browser-use-test-",
    )
    cls._ensure_external_browser_use_resolution = classmethod(lambda inner_cls: None)
    cls._shared_backend = None
    cls._shared_browser_use_session = None
    cls._shared_browser_use_user_data_dir = None
    try:
        session = await agent._get_or_create_browser_use_session()
        reused_session = await agent._get_or_create_browser_use_session()
        assert reused_session is session
        assert session is cls._shared_browser_use_session
        assert cls._browser_use_lifecycle.session is session
        assert cls._browser_use_lifecycle.user_data_dir == r"C:\Temp\jarvis-browser-use-session"
        assert fake_boundary.create_session_calls == 1, fake_boundary.create_session_calls
        assert fake_boundary.keep_session_alive_calls == 1, fake_boundary.keep_session_alive_calls
        assert len(fake_boundary.session_policies) == 1, fake_boundary.session_policies
        assert fake_boundary.session_policies[0].temp_prefix == "jarvis-browser-use-test-"
        assert fake_boundary.session_policies[0].keep_alive is True
        assert fake_boundary.session_policies[0].headless is False
    finally:
        cls._browser_use_boundary = original_boundary
        cls._browser_use_session_policy = original_policy
        cls._ensure_external_browser_use_resolution = original_resolution
        cls._shared_backend = original_backend
        cls._shared_browser_use_session = original_session
        cls._shared_browser_use_user_data_dir = original_user_data_dir


async def _run_stop_skips_double_cleanup_for_shared_browser_use_session() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_boundary = cls._browser_use_boundary
    original_close = cls._close_shared_resources
    original_shared_session = cls._shared_browser_use_session

    fake_boundary = _FakeBrowserUseBoundary()
    shared_session = object()

    async def _fake_close_shared_resources(inner_cls):
        del inner_cls
        await fake_boundary.cleanup_session(shared_session, user_data_dir=r"C:\Temp\jarvis-browser-use-session")
        cls._shared_browser_use_session = None

    cls._browser_use_boundary = fake_boundary
    cls._close_shared_resources = classmethod(_fake_close_shared_resources)
    cls._shared_browser_use_session = shared_session
    agent._session = shared_session
    try:
        await agent.stop()
        assert fake_boundary.cleanup_calls == [
            (shared_session, r"C:\Temp\jarvis-browser-use-session")
        ], fake_boundary.cleanup_calls
        assert agent._session is None
    finally:
        cls._browser_use_boundary = original_boundary
        cls._close_shared_resources = original_close
        cls._shared_browser_use_session = original_shared_session


def run_checks() -> None:
    assert BrowserAgent._extract_direct_url("Go to https://slac.stanford.edu please") == "https://slac.stanford.edu"
    assert BrowserAgent._extract_direct_url("open stanford.edu") == "https://stanford.edu"
    assert BrowserAgent._extract_direct_url("open localhost 3000") == "http://localhost:3000"
    assert BrowserAgent._extract_direct_url("open localhost:3000") == "http://localhost:3000"
    assert BrowserAgent._extract_direct_url("search for Stanford SLAC website") is None

    assert BrowserAgent._should_fallback_to_playwright(ModuleNotFoundError("No module named 'x'"))
    assert BrowserAgent._should_fallback_to_playwright(ImportError("Failed to import BrowserSession"))
    assert not BrowserAgent._should_fallback_to_playwright(RuntimeError("Task execution failed after startup"))
    assert BrowserAgent._should_use_playwright_fast_path("open https://example.com")
    assert BrowserAgent._should_use_playwright_fast_path(
        "open google.com and search for free machine learning courses and open the starting point"
    )
    assert not BrowserAgent._should_use_playwright_fast_path("open https://example.com and submit the form")
    assert not BrowserAgent._should_use_playwright_fast_path(
        "goto chat.openai.com website and ask it for top 3 ml learning resources"
    )
    assert not BrowserAgent._should_use_playwright_fast_path(
        "open https://example.com and summarize the page"
    )

    q1 = BrowserAgent._task_to_search_query("Go to the Stanford SLAC website")
    q2 = BrowserAgent._task_to_search_query("Stanford Linear Accelerator Center")
    assert "Go to the Stanford SLAC website" == q1
    assert q2.endswith("official website")

    executables = BrowserAgent._known_browser_executables()
    assert isinstance(executables, list)

    assert not BrowserAgent._should_close_after_task("Open YouTube in the browser")
    assert BrowserAgent._should_close_after_task("Open YouTube and then close browser")
    assert not BrowserAgent._should_close_after_task("Open YouTube and keep open")
    assert BrowserAgent._is_open_new_tab_task("Open a new browser tab")
    assert BrowserAgent._is_current_tab_context_task("On the page that is currently open, upload this file")
    assert BrowserAgent._should_reuse_existing_page("Navigate to the ScopeGrade submission page and upload file")
    assert BrowserAgent._must_avoid_search("On the currently open page, upload this file")
    assert BrowserAgent._must_avoid_search("Open localhost 3000")
    assert not BrowserAgent._must_avoid_search("Open youtube.com")
    assert BrowserAgent._extract_available_file_paths_from_task("Open https://example.com") == []
    assert BrowserAgent._extract_available_file_paths_from_task('"https://example.com/file.pdf"') == []
    assert BrowserAgent._extract_available_file_paths_from_task(r"Upload C:\Users\SAI\Desktop\homework.zip")
    steered = BrowserAgent._steer_task_for_existing_page(
        "On the currently open ScopeGrade page, upload ECE_131A_HW5.zip"
    )
    assert "do not perform web search" in steered.lower()
    assert "currently open local-server page" in steered.lower()
    assert "hard constraint (local-site mode)" in steered.lower()
    assert "do not type the full task sentence" in steered.lower()
    plain = BrowserAgent._steer_task_for_existing_page("Open youtube.com")
    assert plain == "Open youtube.com"

    asyncio.run(_run_backend_reuse_check())
    asyncio.run(_run_playwright_fast_path_check())
    asyncio.run(_run_playwright_controller_direct_summary_check())
    asyncio.run(_run_playwright_controller_skips_query_summary_check())
    asyncio.run(_run_playwright_controller_error_falls_back_check())
    asyncio.run(_run_controller_summary_failure_is_not_swallowed_check())
    asyncio.run(_run_controller_current_page_does_not_override_active_backend_check())
    asyncio.run(_run_controller_current_page_requires_open_page_check())
    asyncio.run(_run_playwright_mcp_snapshot_route_check())
    asyncio.run(_run_mcp_snapshot_skips_direct_url_interaction_check())
    asyncio.run(_run_mcp_snapshot_does_not_override_active_backend_check())
    asyncio.run(_run_mcp_snapshot_does_not_override_controller_page_check())
    asyncio.run(_run_no_search_when_reusing_page_check())
    asyncio.run(_run_playwright_interaction_is_partial_check())
    asyncio.run(_run_playwright_page_summary_check())
    asyncio.run(_run_dependency_error_uses_shared_playwright_fallback_check())
    asyncio.run(_run_browser_use_and_playwright_dual_failure_message_check())
    asyncio.run(_run_browser_use_session_policy_check())
    asyncio.run(_run_stop_skips_double_cleanup_for_shared_browser_use_session())
    asyncio.run(_run_browser_use_tool_policy_check())


if __name__ == "__main__":
    run_checks()
    print("[test_browser_agent_fallback] All checks passed.")
