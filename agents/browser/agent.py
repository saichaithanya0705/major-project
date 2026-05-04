"""
Browser Agent - Web automation via browser-use.

Creates a fresh, headed browser window for each task and runs the browser-use agent.
"""

from __future__ import annotations

import asyncio
import atexit
import importlib.util
import os
import re
import sys
import tempfile
import shutil
from pathlib import Path
from urllib.parse import quote_plus
from typing import Any, Optional

from agents.browser.task_policy import (
    build_fallback_summary,
    extract_available_file_paths_from_task,
    extract_direct_url,
    has_browser_interaction_intent,
    is_current_tab_context_task,
    is_open_new_tab_task,
    must_avoid_search,
    should_close_after_task,
    should_extract_page_content,
    should_fallback_to_playwright,
    should_search_before_direct_navigation,
    should_reuse_existing_page,
    should_summarize_page_content,
    should_use_playwright_fast_path,
    steer_task_for_existing_page,
    task_to_search_query,
)
from models.openrouter_fallback import (
    get_openrouter_api_key,
    get_openrouter_base_url,
    get_openrouter_models,
    get_openrouter_site_name,
    get_openrouter_site_url,
    is_gemini_quota_error,
)

_RETAINED_BROWSER_HANDLES: list[dict[str, Any]] = []


class BrowserAgent:
    """
    Browser automation agent using browser-use.

    Starts a new, headed browser window per task and executes the agent loop.
    """
    _shared_backend: Optional[str] = None  # "browser_use" | "playwright" | None
    _shared_browser_use_session: Any = None
    _shared_browser_use_user_data_dir: Optional[str] = None
    _shared_playwright: Any = None
    _shared_playwright_browser: Any = None
    _shared_playwright_context: Any = None
    _shared_playwright_page: Any = None
    _shared_playwright_home: Optional[str] = None
    _shared_playwright_headless: bool = False
    _cleanup_registered: bool = False
    _browser_use_resolution_checked: bool = False
    _active_browser_use_agents: set[Any] = set()
    _browser_use_stop_requested: bool = False
    _interrupted_browser_use_state: Any = None
    _interrupted_browser_use_task: str = ""
    _interrupted_browser_use_summary: str = ""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._session = None
        self._register_cleanup_hook()

    @classmethod
    def _register_cleanup_hook(cls) -> None:
        if cls._cleanup_registered:
            return
        # Best-effort synchronous cleanup marker. OS process teardown will close
        # any remaining browser processes if async cleanup cannot run here.
        atexit.register(lambda: None)
        cls._cleanup_registered = True

    @staticmethod
    def _is_subpath(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _ensure_external_browser_use_resolution(cls) -> None:
        """
        Ensure runtime imports resolve to the installed third-party browser_use
        package and never to the vendored in-repo fork.
        """
        if cls._browser_use_resolution_checked:
            return

        spec = importlib.util.find_spec("browser_use")
        if spec is None or not spec.origin:
            raise RuntimeError(
                "browser_use is not installed. Install dependencies so BrowserAgent "
                "can use the canonical external browser_use package."
            )

        resolved_origin = Path(spec.origin).resolve()
        vendored_root = (Path(__file__).resolve().parent / "browser_use").resolve()
        if cls._is_subpath(resolved_origin, vendored_root):
            raise RuntimeError(
                "Refusing to import vendored browser_use from this repository. "
                "Use the installed browser_use dependency instead."
            )

        cls._browser_use_resolution_checked = True

    @classmethod
    def clear_stop_request(cls) -> None:
        cls._browser_use_stop_requested = False

    @classmethod
    def _register_active_browser_use_agent(cls, agent: Any) -> None:
        cls._active_browser_use_agents.add(agent)

    @classmethod
    def _unregister_active_browser_use_agent(cls, agent: Any) -> None:
        cls._active_browser_use_agents.discard(agent)

    @classmethod
    def request_stop_all(cls) -> int:
        cls._browser_use_stop_requested = True
        stopped = 0
        for agent in list(cls._active_browser_use_agents):
            stop = getattr(agent, "stop", None)
            if not callable(stop):
                continue
            try:
                stop()
                stopped += 1
            except Exception:
                pass
        return stopped

    @classmethod
    async def _should_stop_browser_use_agent(cls) -> bool:
        return cls._browser_use_stop_requested

    @staticmethod
    def _normalize_resume_text(value: str) -> str:
        return " ".join(str(value or "").split()).strip().lower()

    @classmethod
    def _is_resume_request(cls, task: str) -> bool:
        lowered = cls._normalize_resume_text(task)
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "continue",
                "resume",
                "keep going",
                "carry on",
                "pick up where",
                "where you left off",
                "from where you left",
            )
        )

    @classmethod
    def has_interrupted_work(cls) -> bool:
        return cls._interrupted_browser_use_state is not None and bool(
            cls._interrupted_browser_use_task.strip()
        )

    @classmethod
    def resolve_resume_task(cls, user_prompt: str) -> str | None:
        if not cls.has_interrupted_work() or not cls._is_resume_request(user_prompt):
            return None
        return cls._interrupted_browser_use_task

    @classmethod
    def _remember_interrupted_browser_use_agent(
        cls,
        agent: Any,
        *,
        task: str,
        summary: str = "",
    ) -> None:
        state = getattr(agent, "state", None)
        if state is None:
            return
        cls._interrupted_browser_use_state = state
        cls._interrupted_browser_use_task = str(task or "").strip()
        cls._interrupted_browser_use_summary = str(summary or "").strip()

    @classmethod
    def _clear_interrupted_browser_use_agent(cls, task: str = "") -> None:
        if task and cls._normalize_resume_text(task) != cls._normalize_resume_text(cls._interrupted_browser_use_task):
            return
        cls._interrupted_browser_use_state = None
        cls._interrupted_browser_use_task = ""
        cls._interrupted_browser_use_summary = ""

    @classmethod
    def _consume_resume_state_for_task(cls, task: str) -> Any:
        if not cls.has_interrupted_work():
            return None

        normalized_task = cls._normalize_resume_text(task)
        normalized_interrupted = cls._normalize_resume_text(cls._interrupted_browser_use_task)
        if normalized_task != normalized_interrupted and not cls._is_resume_request(task):
            return None

        state = cls._interrupted_browser_use_state
        for attr, value in (
            ("paused", False),
            ("stopped", False),
            ("follow_up_task", True),
        ):
            try:
                setattr(state, attr, value)
            except Exception:
                pass
        return state

    @classmethod
    async def _close_shared_resources(cls) -> None:
        if cls._shared_backend == "browser_use":
            session = cls._shared_browser_use_session
            if session is not None:
                try:
                    await session.kill()
                except Exception:
                    pass
            if cls._shared_browser_use_user_data_dir:
                try:
                    shutil.rmtree(cls._shared_browser_use_user_data_dir, ignore_errors=True)
                except Exception:
                    pass
            cls._shared_browser_use_session = None
            cls._shared_browser_use_user_data_dir = None

        elif cls._shared_backend == "playwright":
            context = cls._shared_playwright_context
            browser = cls._shared_playwright_browser
            playwright = cls._shared_playwright

            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass
            if cls._shared_playwright_home:
                try:
                    shutil.rmtree(cls._shared_playwright_home, ignore_errors=True)
                except Exception:
                    pass

            cls._shared_playwright = None
            cls._shared_playwright_browser = None
            cls._shared_playwright_context = None
            cls._shared_playwright_page = None
            cls._shared_playwright_home = None
            cls._shared_playwright_headless = False

        cls._shared_backend = None

    async def _get_or_create_browser_use_session(self):
        type(self)._ensure_external_browser_use_resolution()
        from browser_use.browser import BrowserProfile, BrowserSession

        cls = type(self)
        if cls._shared_backend == "playwright":
            raise RuntimeError("Shared browser backend is already Playwright.")

        if cls._shared_browser_use_session is not None:
            # Ensure existing reused session always stays alive across tasks.
            try:
                cls._shared_browser_use_session.browser_profile.keep_alive = True
            except Exception:
                pass
            return cls._shared_browser_use_session

        user_data_dir = tempfile.mkdtemp(prefix="jarvis-browser-use-")
        profile = BrowserProfile(
            headless=False,
            user_data_dir=user_data_dir,
            keep_alive=True,
        )
        session = BrowserSession(browser_profile=profile)
        cls._shared_backend = "browser_use"
        cls._shared_browser_use_session = session
        cls._shared_browser_use_user_data_dir = user_data_dir
        print("[Browser Agent] Created persistent browser-use session.")
        return session

    async def _get_or_create_playwright_page(self):
        from playwright.async_api import async_playwright

        cls = type(self)
        if cls._shared_backend == "browser_use":
            await cls._close_shared_resources()

        existing_page = cls._shared_playwright_page
        try:
            if existing_page is not None and not existing_page.is_closed():
                return existing_page, cls._shared_playwright_headless
        except Exception:
            cls._shared_playwright_page = None

        runtime_home = tempfile.mkdtemp(prefix="jarvis-playwright-home-")
        launch_env = dict(os.environ)
        launch_env["HOME"] = runtime_home

        playwright = await async_playwright().start()
        browser, used_headless = await self._launch_playwright_browser(playwright, launch_env)
        context = await browser.new_context()
        page = await context.new_page()

        cls._shared_backend = "playwright"
        cls._shared_playwright = playwright
        cls._shared_playwright_browser = browser
        cls._shared_playwright_context = context
        cls._shared_playwright_page = page
        cls._shared_playwright_home = runtime_home
        cls._shared_playwright_headless = used_headless
        print("[Browser Agent] Created persistent Playwright session.")
        return page, used_headless

    async def execute(self, task: str) -> dict[str, Any]:
        # Extract the direct URL from the ORIGINAL task before steering is applied,
        # so the steering preamble text doesn't produce false URL matches.
        original_direct_url = self._extract_direct_url(task)
        cls = type(self)
        # Only apply "stay on existing page" steering when there's already a
        # browser_use session that might have the target page open.  For fresh
        # sessions the LLM needs freedom to navigate to the correct URL on its own.
        # Note: only steer for browser_use sessions — playwright sessions are
        # navigation-only and will be closed below so the agent can use browser_use.
        if cls._shared_backend == "browser_use":
            task = self._steer_task_for_existing_page(task)
        # Keep browser sessions alive for the full process lifetime.
        close_when_done = False

        # Once a backend is chosen, keep using it so all browser actions stay in
        # the same persistent browser session.
        if cls._shared_backend == "browser_use":
            return await self._execute_with_browser_use(task, close_when_done=close_when_done)
        if cls._shared_backend == "playwright":
            return await self._execute_with_playwright(
                task,
                bootstrap_error="",
                close_when_done=close_when_done,
                pre_extracted_url=original_direct_url,
            )

        if self._should_use_playwright_fast_path(task):
            return await self._execute_with_playwright(
                task,
                bootstrap_error="deterministic_fast_path",
                close_when_done=close_when_done,
                pre_extracted_url=original_direct_url,
            )

        # Always try browser_use first — it can actually interact with pages.
        # Playwright fallback is a last resort for navigation-only tasks.
        try:
            result = await self._execute_with_browser_use(task, close_when_done=close_when_done)
            return result
        except Exception as exc:
            if not self._should_fallback_to_playwright(exc):
                return {"success": False, "result": None, "error": str(exc)}

            print(f"[Browser Agent][fallback] browser_use unavailable: {exc}")
            try:
                result = await self._execute_with_playwright(
                    task,
                    bootstrap_error=str(exc),
                    close_when_done=close_when_done,
                    pre_extracted_url=original_direct_url,
                )
                return result
            except Exception as fallback_exc:
                return {
                    "success": False,
                    "result": None,
                    "error": (
                        "Browser task failed in both browser_use and Playwright fallback. "
                        f"bootstrap_error={exc}; fallback_error={fallback_exc}"
                    ),
                }

    async def _execute_with_browser_use(self, task: str, close_when_done: bool) -> dict[str, Any]:
        type(self)._ensure_external_browser_use_resolution()
        from browser_use import Agent
        from browser_use.llm.google.chat import ChatGoogle

        session = await self._get_or_create_browser_use_session()
        self._session = session
        agent_task = type(self).resolve_resume_task(task) or task
        resume_state = type(self)._consume_resume_state_for_task(agent_task)
        if resume_state is not None:
            print("[Browser Agent] Resuming interrupted browser-use task.")

        available_file_paths = self._extract_available_file_paths_from_task(agent_task)
        if available_file_paths:
            print(f"[Browser Agent] available_file_paths: {available_file_paths}")

        async def run_with_llm(llm):
            agent = Agent(
                task=agent_task,
                llm=llm,
                browser_session=session,
                available_file_paths=available_file_paths,
                register_should_stop_callback=type(self)._should_stop_browser_use_agent,
                injected_agent_state=resume_state,
            )
            type(self)._register_active_browser_use_agent(agent)
            try:
                history = await agent.run()
            except asyncio.CancelledError:
                try:
                    agent.stop()
                except Exception:
                    pass
                type(self)._remember_interrupted_browser_use_agent(
                    agent,
                    task=agent_task,
                    summary="Browser task interrupted by user.",
                )
                raise
            finally:
                type(self)._unregister_active_browser_use_agent(agent)

            if type(self)._browser_use_stop_requested or getattr(agent.state, "stopped", False):
                type(self)._remember_interrupted_browser_use_agent(
                    agent,
                    task=agent_task,
                    summary="Browser task stopped by user.",
                )
                return {
                    "success": False,
                    "result": history,
                    "error": "Browser task stopped by user. Say 'continue' to resume it.",
                }

            type(self)._clear_interrupted_browser_use_agent(agent_task)
            if close_when_done:
                await type(self)._close_shared_resources()
            else:
                print("[Browser Agent] Reusing persistent browser window for future tasks.")
            return {"success": True, "result": history, "error": None}

        try:
            llm = ChatGoogle(model=self.model_name, api_key=os.getenv("GEMINI_API_KEY"))
            return await run_with_llm(llm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not is_gemini_quota_error(exc):
                return {"success": False, "result": None, "error": str(exc)}
            fallback_error = str(exc)
            for model_name in get_openrouter_models("browser"):
                try:
                    from browser_use.llm.openrouter.chat import ChatOpenRouter

                    print(f"[Browser Agent] Gemini quota hit; retrying via OpenRouter model {model_name}.")
                    llm = ChatOpenRouter(
                        model=model_name,
                        api_key=get_openrouter_api_key(),
                        http_referer=get_openrouter_site_url() or None,
                        base_url=get_openrouter_base_url(),
                        temperature=0,
                        default_headers={"X-Title": get_openrouter_site_name()},
                    )
                    return await run_with_llm(llm)
                except asyncio.CancelledError:
                    raise
                except Exception as fallback_exc:
                    fallback_error = str(fallback_exc)
                    print(f"[Browser Agent] OpenRouter fallback failed with {model_name}: {fallback_exc}")
            return {"success": False, "result": None, "error": fallback_error}
        finally:
            self._session = type(self)._shared_browser_use_session

    async def _execute_with_playwright(self, task: str, bootstrap_error: str, close_when_done: bool, pre_extracted_url: str | None = None) -> dict[str, Any]:
        # Use the pre-extracted URL (from original task) if available,
        # to avoid false matches from steering preamble text.
        direct_url = pre_extracted_url if pre_extracted_url is not None else self._extract_direct_url(task)
        avoid_search = self._must_avoid_search(task)
        prefer_search = self._should_search_before_direct_navigation(task)
        used_search = False
        page, used_headless = await self._get_or_create_playwright_page()
        action_mode = "direct_navigation"

        if self._is_open_new_tab_task(task):
            context = type(self)._shared_playwright_context
            if context is not None:
                page = await context.new_page()
                type(self)._shared_playwright_page = page
                action_mode = "new_tab"
            else:
                action_mode = "new_tab_current_context_unavailable"

        need_search_fallback = False

        if action_mode.startswith("new_tab"):
            pass
        elif direct_url and not prefer_search:
            await page.goto(direct_url, wait_until="domcontentloaded", timeout=30000)
            action_mode = "direct_navigation"
        elif avoid_search:
            relevant_page = await self._select_relevant_existing_page(task, page)
            if relevant_page is not None:
                page = relevant_page
                type(self)._shared_playwright_page = page
                action_mode = "current_tab_context"
            else:
                # No relevant page found; fall through to search
                need_search_fallback = True
        else:
            need_search_fallback = True

        if need_search_fallback:
            used_search = True
            search_query = self._task_to_search_query(task)
            search_url = f"https://duckduckgo.com/?q={quote_plus(search_query)}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await self._open_first_duckduckgo_result(page)
            action_mode = "search_fallback"

        await page.wait_for_timeout(1000)
        final_url = page.url
        title = await page.title()
        content_requested = self._should_extract_page_content(task)
        content_response = ""
        if content_requested:
            page_text = await self._extract_playwright_page_text(page)
            content_response = self._build_page_content_response(
                task=task,
                page_title=title,
                final_url=final_url,
                page_text=page_text,
            )
        complete = bool(content_response) if content_requested else not has_browser_interaction_intent(task)

        summary = content_response or self._build_fallback_summary(
            task=task,
            final_url=final_url,
            page_title=title,
            used_search=used_search,
            used_headless=used_headless,
            action_mode=action_mode,
        )
        if content_requested and not content_response:
            summary = f"{summary}; page content extraction did not return readable text."
        if not complete:
            if content_requested:
                summary = (
                    f"{summary}; additional browser content extraction is required "
                    "to finish the user's request."
                )
            else:
                summary = (
                    f"{summary}; interactive browser automation is still required "
                    "to finish the user's request."
                )

        if close_when_done:
            await type(self)._close_shared_resources()
        else:
            print("[Browser Agent] Reusing persistent browser window for future tasks.")

        return {
            "success": True,
            "result": {
                "summary": summary,
                "mode": "playwright_fallback",
                "task": task,
                "url": final_url,
                "title": title,
                "bootstrap_error": bootstrap_error,
                "complete": complete,
            },
            "error": None,
            "complete": complete,
        }

    async def _open_first_duckduckgo_result(self, page) -> None:
        selectors = [
            "a[data-testid='result-title-a']",
            "a.result__a",
        ]
        for selector in selectors:
            try:
                result = page.locator(selector).first
                await result.wait_for(state="visible", timeout=5000)
                await result.click()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                return
            except Exception:
                continue

    async def _launch_playwright_browser(self, playwright, launch_env: dict[str, str]):
        launch_args = ["--disable-crashpad", "--disable-crash-reporter"]
        errors: list[str] = []

        for headless in (False, True):
            try:
                browser = await playwright.chromium.launch(
                    headless=headless,
                    env=launch_env,
                    args=launch_args,
                )
                return browser, headless
            except Exception as exc:
                errors.append(f"bundled chromium headless={headless}: {exc}")

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
                    errors.append(f"channel {channel} headless={headless}: {exc}")

        for executable_path in self._known_browser_executables():
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
                    errors.append(f"executable {executable_path} headless={headless}: {exc}")

        raise RuntimeError(
            "Could not launch Playwright browser. "
            "Tried bundled Chromium, channels, and local executables. "
            "If needed, run: playwright install. "
            f"Launch errors: {' | '.join(errors[:6])}"
        )

    @staticmethod
    def _known_browser_executables() -> list[str]:
        if sys.platform.startswith("win"):
            candidates = [
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\Chromium\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Chromium\Application\chrome.exe",
                r"%LocalAppData%\Chromium\Application\chrome.exe",
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        else:
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/microsoft-edge",
                "/usr/bin/brave-browser",
                "/snap/bin/chromium",
            ]

        resolved: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            path = str(Path(os.path.expandvars(candidate)).expanduser())
            if path in seen:
                continue
            seen.add(path)
            if Path(path).exists():
                resolved.append(path)
        return resolved

    @staticmethod
    def _should_close_after_task(task: str) -> bool:
        return should_close_after_task(task)

    @staticmethod
    def _should_fallback_to_playwright(exc: Exception) -> bool:
        return should_fallback_to_playwright(exc)

    @staticmethod
    def _should_use_playwright_fast_path(task: str) -> bool:
        return should_use_playwright_fast_path(task)

    @staticmethod
    def _should_search_before_direct_navigation(task: str) -> bool:
        return should_search_before_direct_navigation(task)

    @staticmethod
    def _extract_direct_url(task: str) -> str | None:
        return extract_direct_url(task)

    @staticmethod
    def _extract_available_file_paths_from_task(task: str) -> list[str]:
        return extract_available_file_paths_from_task(task)

    @staticmethod
    def _is_open_new_tab_task(task: str) -> bool:
        return is_open_new_tab_task(task)

    @staticmethod
    def _is_current_tab_context_task(task: str) -> bool:
        return is_current_tab_context_task(task)

    @classmethod
    def _should_reuse_existing_page(cls, task: str) -> bool:
        del cls
        return should_reuse_existing_page(task)

    @classmethod
    def _steer_task_for_existing_page(cls, task: str) -> str:
        del cls
        return steer_task_for_existing_page(task)

    @classmethod
    def _must_avoid_search(cls, task: str) -> bool:
        del cls
        return must_avoid_search(task)

    @staticmethod
    def _should_extract_page_content(task: str) -> bool:
        return should_extract_page_content(task)

    @staticmethod
    def _should_summarize_page_content(task: str) -> bool:
        return should_summarize_page_content(task)

    @staticmethod
    def _clean_page_text(value: str) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        cleaned: list[str] = []
        previous_blank = False
        for line in lines:
            if not line:
                if cleaned and not previous_blank:
                    cleaned.append("")
                previous_blank = True
                continue
            cleaned.append(line)
            previous_blank = False
        return "\n".join(cleaned).strip()

    @staticmethod
    def _truncate_text(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= max_chars:
            return text
        clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
        return f"{clipped}..."

    @classmethod
    def _extractive_page_summary(cls, page_text: str) -> str:
        text = cls._clean_page_text(page_text)
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n+", text)
            if paragraph.strip()
        ]
        candidate = " ".join(paragraphs[:4]) if paragraphs else text
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", candidate)
            if sentence.strip()
        ]
        selected: list[str] = []
        for sentence in sentences:
            proposed = " ".join([*selected, sentence]).strip()
            if selected and len(proposed) > 1200:
                break
            selected.append(sentence)
            if len(selected) >= 5:
                break
        if selected:
            return cls._truncate_text(" ".join(selected), 1200)
        return cls._truncate_text(candidate, 1200)

    @classmethod
    def _build_page_content_response(
        cls,
        *,
        task: str,
        page_title: str,
        final_url: str,
        page_text: str,
    ) -> str:
        text = cls._clean_page_text(page_text)
        if not text:
            return ""

        title_text = page_title.strip() if isinstance(page_title, str) else ""
        source = title_text or final_url or "page"
        if final_url and final_url not in source:
            source = f"{source} ({final_url})"

        if cls._should_summarize_page_content(task):
            content = cls._extractive_page_summary(text)
            return f"Summary of {source}:\n{content}"

        content = cls._truncate_text(text, 1800)
        return f"Page content from {source}:\n{content}"

    @classmethod
    async def _extract_playwright_page_text(cls, page) -> str:
        script = """
() => {
  const selectors = [
    '#mw-content-text .mw-parser-output',
    'article',
    'main',
    '[role="main"]',
    'body'
  ];
  const root = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (!root) {
    return document.body ? document.body.innerText : '';
  }
  const clone = root.cloneNode(true);
  clone.querySelectorAll([
    'script',
    'style',
    'noscript',
    'nav',
    'header',
    'footer',
    'aside',
    'form',
    'table',
    'figure',
    'sup',
    '.mw-editsection',
    '.reference',
    '.reflist',
    '.navbox',
    '.infobox',
    '.sidebar'
  ].join(',')).forEach((element) => element.remove());
  const blocks = Array.from(clone.querySelectorAll('p, li'));
  const textBlocks = blocks
    .map((element) => (element.innerText || '').replace(/\\s+/g, ' ').trim())
    .filter((text) => text.length > 40);
  if (textBlocks.length > 0) {
    return textBlocks.join('\\n\\n');
  }
  return clone.innerText || '';
}
"""
        try:
            value = await page.evaluate(script)
        except Exception:
            return ""
        return cls._clean_page_text(str(value or ""))

    async def _select_relevant_existing_page(self, task: str, default_page):
        """Return a matching open page, or None if no relevant page is found."""
        lowered = task.lower()
        context = type(self)._shared_playwright_context
        if context is None:
            return None
        pages = list(getattr(context, "pages", []) or [])
        if not pages:
            return None

        if "scopegrade" in lowered:
            for candidate in pages:
                try:
                    title = (await candidate.title()).lower()
                    url = (candidate.url or "").lower()
                except Exception:
                    continue
                if "scopegrade" in title or "scopegrade" in url:
                    return candidate
                if "localhost" in url or "127.0.0.1" in url:
                    return candidate

        if "localhost" in lowered or "127.0.0.1" in lowered:
            for candidate in pages:
                url = (candidate.url or "").lower()
                if "localhost" in url or "127.0.0.1" in url:
                    return candidate

        return None

    @staticmethod
    def _task_to_search_query(task: str) -> str:
        return task_to_search_query(task)

    @staticmethod
    def _build_fallback_summary(
        task: str,
        final_url: str,
        page_title: str,
        used_search: bool,
        used_headless: bool,
        action_mode: str = "direct_navigation",
    ) -> str:
        return build_fallback_summary(
            task=task,
            final_url=final_url,
            page_title=page_title,
            used_search=used_search,
            used_headless=used_headless,
            action_mode=action_mode,
        )

    async def stop(self):
        await type(self)._close_shared_resources()

        for handle in list(_RETAINED_BROWSER_HANDLES):
            kind = handle.get("kind")
            try:
                if kind == "browser_use":
                    session = handle.get("session")
                    if session is not None:
                        await session.kill()
                elif kind == "playwright":
                    browser = handle.get("browser")
                    playwright = handle.get("playwright")
                    if browser is not None:
                        await browser.close()
                    if playwright is not None:
                        await playwright.stop()
            except Exception:
                pass

            user_data_dir = handle.get("user_data_dir")
            if user_data_dir:
                try:
                    shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass
            _RETAINED_BROWSER_HANDLES.remove(handle)

        if self._session is None:
            return
        try:
            await self._session.kill()
        finally:
            self._session = None
