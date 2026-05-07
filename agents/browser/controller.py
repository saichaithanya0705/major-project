from __future__ import annotations

import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.browser.page_context import MAIN_CONTENT_SCRIPT, PageContext, clean_page_text


_RUNTIME_HOME_PREFIX = "jarvis-playwright-home-"


class PlaywrightBrowserController:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._runtime_home: str | None = None
        self._used_headless = False

    async def get_or_create_page(self):
        if self._is_open_page(self._page):
            return self._page, self._used_headless

        page = self._find_last_open_page()
        if page is not None:
            self._page = page
            return page, self._used_headless

        if self._has_owned_resources():
            await self.close()

        from playwright.async_api import async_playwright

        self._runtime_home = tempfile.mkdtemp(prefix=_RUNTIME_HOME_PREFIX)
        launch_env = dict(os.environ)
        launch_env["HOME"] = self._runtime_home
        launch_env["USERPROFILE"] = self._runtime_home

        try:
            self._playwright = await async_playwright().start()
            self._browser, self._used_headless = await self._launch_browser(
                self._playwright,
                launch_env,
            )
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            return self._page, self._used_headless
        except Exception:
            await self.close()
            raise

    async def _launch_browser(self, playwright, launch_env: dict[str, str]):
        launch_args = ["--disable-crashpad", "--disable-crash-reporter"]
        launch_errors: list[str] = []

        for headless in (False, True):
            try:
                browser = await playwright.chromium.launch(
                    headless=headless,
                    env=launch_env,
                    args=launch_args,
                )
                return browser, headless
            except Exception as exc:
                launch_errors.append(f"bundled chromium headless={headless}: {exc}")

        for channel in ("chrome", "msedge"):
            for headless in (False, True):
                try:
                    browser = await playwright.chromium.launch(
                        channel=channel,
                        headless=headless,
                        env=launch_env,
                        args=launch_args,
                    )
                    return browser, headless
                except Exception as exc:
                    launch_errors.append(
                        f"channel {channel} headless={headless}: {exc}"
                    )

        for executable_path in self.known_browser_executables():
            for headless in (False, True):
                try:
                    browser = await playwright.chromium.launch(
                        executable_path=executable_path,
                        headless=headless,
                        env=launch_env,
                        args=launch_args,
                    )
                    return browser, headless
                except Exception as exc:
                    launch_errors.append(
                        f"executable {executable_path} headless={headless}: {exc}"
                    )

        preview = " | ".join(launch_errors[:8]) or "no browser candidates were tried"
        raise RuntimeError(
            "Could not launch Playwright browser. Tried bundled Chromium, "
            "Chrome/Edge channels, and local browser executables. "
            f"Launch errors: {preview}"
        )

    @staticmethod
    def known_browser_executables() -> list[str]:
        candidates: list[str]
        if sys.platform.startswith("win"):
            candidates = [
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                str(
                    Path.home()
                    / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                ),
                str(
                    Path.home()
                    / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
                ),
                str(
                    Path.home()
                    / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
                ),
            ]
        else:
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
                "/usr/bin/brave-browser",
                "/snap/bin/chromium",
            ]
            for command in (
                "google-chrome",
                "google-chrome-stable",
                "chromium",
                "chromium-browser",
                "microsoft-edge",
                "microsoft-edge-stable",
                "brave-browser",
            ):
                resolved = shutil.which(command)
                if resolved:
                    candidates.append(resolved)

        resolved_paths: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            expanded = os.path.expanduser(os.path.expandvars(candidate))
            normalized = os.path.normcase(os.path.abspath(expanded))
            if normalized in seen:
                continue
            seen.add(normalized)
            if os.path.exists(expanded):
                resolved_paths.append(expanded)
        return resolved_paths

    async def navigate_and_extract(self, url: str) -> PageContext:
        page, _used_headless = await self.get_or_create_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        return await self.extract_context(page)

    async def extract_context(self, page=None) -> PageContext:
        if page is None:
            page, _used_headless = await self.get_or_create_page()

        title = await self._safe_title(page)
        url = self._safe_url(page)
        payload: Any = {}
        try:
            evaluated = await page.evaluate(MAIN_CONTENT_SCRIPT)
            if isinstance(evaluated, dict):
                payload = evaluated
        except Exception:
            payload = {}

        headings = self._clean_headings(payload.get("headings"))
        text = clean_page_text(str(payload.get("text") or ""))
        return PageContext(title=title, url=url, headings=headings, text=text)

    async def select_relevant_existing_page(self, task: str, default_page=None):
        pages = self._open_pages()
        if not pages:
            return default_page if self._is_open_page(default_page) else None

        if self._is_local_task(task):
            for page in pages:
                if self._is_local_url(self._safe_url(page)):
                    return page

        if self._mentions_current_page(task):
            if self._is_open_page(default_page):
                return default_page
            if self._is_open_page(self._page):
                return self._page
            return pages[-1]

        if self._is_open_page(default_page):
            return default_page
        if self._is_open_page(self._page):
            return self._page
        return pages[-1]

    async def close(self) -> None:
        context = self._context
        browser = self._browser
        playwright = self._playwright
        runtime_home = self._runtime_home

        try:
            if context is not None:
                await self._safe_call(context, "close")
            if browser is not None:
                await self._safe_call(browser, "close")
            if playwright is not None:
                await self._safe_call(playwright, "stop")
        finally:
            self._remove_runtime_home(runtime_home)
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._runtime_home = None
            self._used_headless = False

    def _find_last_open_page(self):
        pages = self._open_pages()
        return pages[-1] if pages else None

    def has_open_page(self) -> bool:
        return self._is_open_page(self._page) or self._find_last_open_page() is not None

    def _open_pages(self) -> list[Any]:
        pages = getattr(self._context, "pages", None) or []
        return [page for page in pages if self._is_open_page(page)]

    @staticmethod
    def _is_open_page(page) -> bool:
        if page is None:
            return False
        try:
            is_closed = getattr(page, "is_closed", None)
            if callable(is_closed):
                return not bool(is_closed())
        except Exception:
            return False
        return True

    @staticmethod
    def _is_local_task(task: str) -> bool:
        lowered = " ".join(str(task or "").lower().split())
        markers = (
            "localhost",
            "127.0.0.1",
            "::1",
            "local app",
            "local page",
            "local site",
            "local server",
            "dev server",
            "development server",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _mentions_current_page(task: str) -> bool:
        lowered = " ".join(str(task or "").lower().split())
        markers = (
            "current page",
            "this page",
            "current tab",
            "active tab",
            "open page",
            "existing page",
            "already open",
            "page open",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _is_local_url(url: str) -> bool:
        try:
            hostname = urlparse(str(url or "")).hostname
        except Exception:
            return False
        return str(hostname or "").lower() in {
            "localhost",
            "127.0.0.1",
            "::1",
            "0.0.0.0",
        }

    def _has_owned_resources(self) -> bool:
        return any(
            resource is not None
            for resource in (
                self._playwright,
                self._browser,
                self._context,
                self._page,
                self._runtime_home,
            )
        )

    @staticmethod
    async def _safe_title(page) -> str:
        try:
            title = page.title()
            if inspect.isawaitable(title):
                title = await title
            return str(title or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _safe_url(page) -> str:
        try:
            return str(getattr(page, "url", "") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _clean_headings(value) -> list[str]:
        if not isinstance(value, list):
            return []
        headings: list[str] = []
        for heading in value:
            text = clean_page_text(str(heading or "")).replace("\n", " ").strip()
            if text:
                headings.append(text)
        return headings

    @staticmethod
    async def _safe_call(obj, method_name: str) -> None:
        method = getattr(obj, method_name, None)
        if not callable(method):
            return
        try:
            result = method()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

    @staticmethod
    def _remove_runtime_home(runtime_home: str | None) -> None:
        if not runtime_home:
            return

        try:
            runtime_path = Path(runtime_home).resolve()
            temp_root = Path(tempfile.gettempdir()).resolve()
            runtime_path.relative_to(temp_root)
        except Exception:
            return

        if runtime_path.name.startswith(_RUNTIME_HOME_PREFIX):
            shutil.rmtree(runtime_path, ignore_errors=True)
