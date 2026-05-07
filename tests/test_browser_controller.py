import asyncio
import os
import shutil
import sys
import tempfile
import types

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.browser.controller as controller_module
from agents.browser.controller import PlaywrightBrowserController
from agents.browser.page_context import PageContext


class _FakePage:
    def __init__(
        self,
        url: str = "about:blank",
        title: str = "Blank",
        payload=None,
    ) -> None:
        self.url = url
        self._title = title
        self.goto_calls: list[dict[str, object]] = []
        self.wait_calls: list[int] = []
        self.closed = False
        self.payload = payload or {
            "text": "Alpha paragraph explains the page. Beta paragraph adds detail.",
            "headings": ["Alpha", "Beta"],
        }

    async def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
    ):
        self.goto_calls.append(
            {"url": url, "wait_until": wait_until, "timeout": timeout}
        )
        self.url = url
        self._title = "Loaded"

    async def title(self) -> str:
        return self._title

    async def evaluate(self, script: str):
        assert "querySelector" in script
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    async def wait_for_timeout(self, ms: int):
        self.wait_calls.append(ms)

    def is_closed(self) -> bool:
        return self.closed


class _FakeContext:
    def __init__(self, pages: list[_FakePage] | None = None) -> None:
        self.pages = pages or []
        self.closed = False

    async def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class _Closeable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Stoppable:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakeBrowser(_Closeable):
    def __init__(self, context: _FakeContext) -> None:
        super().__init__()
        self._context = context

    async def new_context(self) -> _FakeContext:
        return self._context


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser, before_launch) -> None:
        self.browser = browser
        self.before_launch = before_launch
        self.launch_calls: list[dict[str, object]] = []

    async def launch(self, **kwargs):
        self.before_launch()
        self.launch_calls.append(kwargs)
        return self.browser


class _FakePlaywright(_Stoppable):
    def __init__(self, browser: _FakeBrowser, before_launch) -> None:
        super().__init__()
        self.chromium = _FakeChromium(browser, before_launch)


class _FakeAsyncPlaywrightStarter:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright
        self.started = False

    async def start(self) -> _FakePlaywright:
        self.started = True
        return self.playwright


async def _run_navigation_check() -> None:
    page = _FakePage("about:blank", "Blank")
    context = _FakeContext([page])
    controller = PlaywrightBrowserController()
    controller._page = page
    controller._context = context

    result = await controller.navigate_and_extract("https://example.com/docs")

    assert isinstance(result, PageContext)
    assert page.goto_calls == [
        {
            "url": "https://example.com/docs",
            "wait_until": "domcontentloaded",
            "timeout": 30000,
        }
    ]
    assert page.wait_calls == [1000]
    assert result.url == "https://example.com/docs"
    assert result.title == "Loaded"
    assert result.headings == ["Alpha", "Beta"]
    assert "Alpha paragraph" in result.text


async def _run_page_selection_check() -> None:
    default_page = _FakePage("https://example.com", "Remote")
    localhost_page = _FakePage("http://localhost:3000/dashboard", "Local")
    closed_page = _FakePage("http://127.0.0.1:5173", "Closed")
    closed_page.closed = True
    context = _FakeContext([default_page, localhost_page, closed_page])
    controller = PlaywrightBrowserController()
    controller._context = context
    controller._page = localhost_page

    selected = await controller.select_relevant_existing_page(
        "use the current page",
        default_page=default_page,
    )
    assert selected is default_page

    local_selected = await controller.select_relevant_existing_page(
        "summarize the local app",
        default_page=default_page,
    )
    assert local_selected is localhost_page


async def _run_has_open_page_check() -> None:
    open_page = _FakePage("https://example.com", "Remote")
    closed_page = _FakePage("https://closed.example", "Closed")
    closed_page.closed = True
    controller = PlaywrightBrowserController()

    assert not controller.has_open_page()

    controller._page = closed_page
    controller._context = _FakeContext([closed_page])
    assert not controller.has_open_page()

    controller._context = _FakeContext([closed_page, open_page])
    assert controller.has_open_page()


async def _run_local_url_check() -> None:
    assert PlaywrightBrowserController._is_local_url("http://localhost:3000")
    assert PlaywrightBrowserController._is_local_url("http://127.0.0.1:5173")
    assert PlaywrightBrowserController._is_local_url("http://[::1]:8000")
    assert PlaywrightBrowserController._is_local_url("http://0.0.0.0:9000")
    assert not PlaywrightBrowserController._is_local_url(
        "https://example.com/?next=http://localhost:3000"
    )
    assert not PlaywrightBrowserController._is_local_url(
        "https://localhost.example.com/dashboard"
    )


async def _run_extraction_fallback_check() -> None:
    controller = PlaywrightBrowserController()
    non_dict_page = _FakePage("https://example.com", "Example", payload=["bad"])
    non_dict_result = await controller.extract_context(non_dict_page)
    assert non_dict_result == PageContext(
        title="Example",
        url="https://example.com",
        headings=[],
        text="",
    )

    error_page = _FakePage(
        "https://example.com/failure",
        "Failure",
        payload=RuntimeError("evaluate failed"),
    )
    error_result = await controller.extract_context(error_page)
    assert error_result.title == "Failure"
    assert error_result.url == "https://example.com/failure"
    assert error_result.headings == []
    assert error_result.text == ""


async def _run_close_check() -> None:
    runtime_home = tempfile.mkdtemp(prefix="jarvis-playwright-home-")
    context = _FakeContext()
    browser = _Closeable()
    playwright = _Stoppable()
    controller = PlaywrightBrowserController()
    controller._runtime_home = runtime_home
    controller._context = context
    controller._browser = browser
    controller._playwright = playwright
    controller._page = _FakePage()
    controller._used_headless = True

    await controller.close()

    assert context.closed
    assert browser.closed
    assert playwright.stopped
    assert not os.path.exists(runtime_home)
    assert controller._playwright is None
    assert controller._browser is None
    assert controller._context is None
    assert controller._page is None
    assert controller._runtime_home is None
    assert controller._used_headless is False

    stray_dir = tempfile.mkdtemp(prefix="not-jarvis-owned-")
    try:
        controller._runtime_home = stray_dir
        await controller.close()
        assert os.path.isdir(stray_dir)
    finally:
        shutil.rmtree(stray_dir, ignore_errors=True)


async def _run_closed_page_relaunch_cleanup_check() -> None:
    old_runtime_home = tempfile.mkdtemp(prefix="jarvis-playwright-home-")
    old_closed_page = _FakePage("about:blank", "Old")
    old_closed_page.closed = True
    old_context = _FakeContext([old_closed_page])
    old_browser = _Closeable()
    old_playwright = _Stoppable()
    new_context = _FakeContext()
    new_browser = _FakeBrowser(new_context)

    def before_launch() -> None:
        assert old_context.closed
        assert old_browser.closed
        assert old_playwright.stopped
        assert not os.path.exists(old_runtime_home)

    new_playwright = _FakePlaywright(new_browser, before_launch)
    starter = _FakeAsyncPlaywrightStarter(new_playwright)

    fake_playwright_package = types.ModuleType("playwright")
    fake_async_api = types.ModuleType("playwright.async_api")
    fake_async_api.async_playwright = lambda: starter
    previous_playwright = sys.modules.get("playwright")
    previous_async_api = sys.modules.get("playwright.async_api")
    original_mkdtemp = controller_module.tempfile.mkdtemp
    sys.modules["playwright"] = fake_playwright_package
    sys.modules["playwright.async_api"] = fake_async_api

    def checked_mkdtemp(*args, **kwargs) -> str:
        assert old_context.closed
        assert old_browser.closed
        assert old_playwright.stopped
        assert not os.path.exists(old_runtime_home)
        return original_mkdtemp(*args, **kwargs)

    controller_module.tempfile.mkdtemp = checked_mkdtemp

    controller = PlaywrightBrowserController()
    controller._runtime_home = old_runtime_home
    controller._context = old_context
    controller._browser = old_browser
    controller._playwright = old_playwright
    controller._page = old_closed_page
    controller._used_headless = True

    try:
        page, used_headless = await controller.get_or_create_page()
    finally:
        controller_module.tempfile.mkdtemp = original_mkdtemp
        if previous_playwright is None:
            sys.modules.pop("playwright", None)
        else:
            sys.modules["playwright"] = previous_playwright
        if previous_async_api is None:
            sys.modules.pop("playwright.async_api", None)
        else:
            sys.modules["playwright.async_api"] = previous_async_api
        shutil.rmtree(old_runtime_home, ignore_errors=True)

    assert starter.started
    assert page is new_context.pages[0]
    assert used_headless is False
    assert controller._context is new_context
    assert controller._browser is new_browser
    assert controller._playwright is new_playwright
    assert controller._runtime_home != old_runtime_home
    assert os.path.exists(controller._runtime_home)
    await controller.close()


def test_controller_navigation_and_extraction() -> None:
    asyncio.run(_run_navigation_check())


def test_controller_existing_page_selection() -> None:
    asyncio.run(_run_page_selection_check())


def test_controller_reports_existing_open_page() -> None:
    asyncio.run(_run_has_open_page_check())


def test_controller_local_url_detection_uses_hostname_only() -> None:
    asyncio.run(_run_local_url_check())


def test_controller_extract_context_fallbacks() -> None:
    asyncio.run(_run_extraction_fallback_check())


def test_controller_close_resets_owned_resources() -> None:
    asyncio.run(_run_close_check())


def test_controller_relaunch_after_closed_page_cleans_old_resources() -> None:
    asyncio.run(_run_closed_page_relaunch_cleanup_check())


if __name__ == "__main__":
    test_controller_navigation_and_extraction()
    test_controller_existing_page_selection()
    test_controller_reports_existing_open_page()
    test_controller_local_url_detection_uses_hostname_only()
    test_controller_extract_context_fallbacks()
    test_controller_close_resets_owned_resources()
    test_controller_relaunch_after_closed_page_cleans_old_resources()
    print("PASS")
