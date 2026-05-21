"""
Browser Agent - Web automation via browser-use.

Creates a fresh, headed browser window for each task and runs the browser-use agent.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote_plus
from typing import Any, Optional

from agents.browser.controller import PlaywrightBrowserController
from agents.browser.browser_use_boundary import (
    BrowserUseBoundary,
    BrowserUseCleanupError,
    BrowserUseDependencyError,
    BrowserUseLifecycle,
    BrowserUseLifecycleError,
    BrowserUseLifecycleFailure,
    BrowserUseSessionPolicy,
    BrowserUseToolPolicy,
)
from agents.browser.mcp_client import PlaywrightMcpClient
from agents.browser.page_context import format_page_context_response
from agents.browser.playwright_boundary import (
    PlaywrightBoundary,
    PlaywrightCleanupError,
    PlaywrightMcpSnapshotError,
    PlaywrightPageContextError,
    PlaywrightLifecycleFailure,
    PlaywrightRuntimeState,
)
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
    should_use_mcp_snapshot,
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
    _shared_playwright_controller: Any = None
    _shared_playwright_mcp_client: Any = None
    _cleanup_registered: bool = False
    _browser_use_boundary: BrowserUseBoundary = BrowserUseBoundary()
    _browser_use_session_policy: BrowserUseSessionPolicy = BrowserUseSessionPolicy()
    _browser_use_tool_policy: BrowserUseToolPolicy = BrowserUseToolPolicy()
    _browser_use_lifecycle: BrowserUseLifecycle = BrowserUseLifecycle()
    _playwright_boundary: PlaywrightBoundary = PlaywrightBoundary()
    _playwright_runtime: PlaywrightRuntimeState = PlaywrightRuntimeState()
    _last_browser_use_stop_failures: tuple[BrowserUseLifecycleFailure, ...] = ()
    _last_browser_use_cleanup_failures: tuple[BrowserUseLifecycleFailure, ...] = ()
    _last_playwright_cleanup_failures: tuple[PlaywrightLifecycleFailure, ...] = ()
    # Legacy mirrors kept for existing private callers/tests while lifecycle
    # ownership lives in BrowserUseLifecycle.
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
        atexit.register(cls._cleanup_shared_temp_dirs_sync)
        cls._cleanup_registered = True

    @classmethod
    def _hydrate_browser_use_lifecycle_from_legacy_state(cls) -> BrowserUseLifecycle:
        lifecycle = cls._browser_use_lifecycle
        lifecycle.session = cls._shared_browser_use_session
        lifecycle.user_data_dir = cls._shared_browser_use_user_data_dir
        lifecycle.last_stop_failures = tuple(cls._last_browser_use_stop_failures)
        lifecycle.last_cleanup_failures = tuple(cls._last_browser_use_cleanup_failures)
        lifecycle.resolution_checked = bool(
            lifecycle.resolution_checked or cls._browser_use_resolution_checked
        )
        return lifecycle

    @classmethod
    def _sync_browser_use_legacy_state(cls) -> None:
        lifecycle = cls._browser_use_lifecycle
        cls._shared_browser_use_session = lifecycle.session
        cls._shared_browser_use_user_data_dir = lifecycle.user_data_dir
        cls._last_browser_use_stop_failures = tuple(lifecycle.last_stop_failures)
        cls._last_browser_use_cleanup_failures = tuple(lifecycle.last_cleanup_failures)
        cls._browser_use_resolution_checked = bool(
            lifecycle.resolution_checked or cls._browser_use_boundary.resolution_checked
        )
        cls._active_browser_use_agents = lifecycle.active_agents
        cls._browser_use_stop_requested = lifecycle.stop_requested
        interrupted = lifecycle.interrupted_work
        cls._interrupted_browser_use_state = interrupted.state if interrupted else None
        cls._interrupted_browser_use_task = interrupted.task if interrupted else ""
        cls._interrupted_browser_use_summary = interrupted.summary if interrupted else ""

    @classmethod
    def _hydrate_playwright_runtime_from_legacy_state(cls) -> PlaywrightRuntimeState:
        state = cls._playwright_runtime
        state.controller = cls._shared_playwright_controller
        state.mcp_client = cls._shared_playwright_mcp_client
        state.playwright = cls._shared_playwright
        state.browser = cls._shared_playwright_browser
        state.context = cls._shared_playwright_context
        state.page = cls._shared_playwright_page
        state.user_data_dir = cls._shared_playwright_home
        state.headless = cls._shared_playwright_headless
        state.last_cleanup_failures = tuple(cls._last_playwright_cleanup_failures)
        return state

    @classmethod
    def _sync_playwright_legacy_state(cls) -> None:
        state = cls._playwright_runtime
        cls._shared_playwright_controller = state.controller
        cls._shared_playwright_mcp_client = state.mcp_client
        cls._shared_playwright = state.playwright
        cls._shared_playwright_browser = state.browser
        cls._shared_playwright_context = state.context
        cls._shared_playwright_page = state.page
        cls._shared_playwright_home = state.user_data_dir
        cls._shared_playwright_headless = state.headless
        cls._last_playwright_cleanup_failures = tuple(state.last_cleanup_failures)

    @classmethod
    def _cleanup_shared_temp_dirs_sync(cls) -> None:
        lifecycle = cls._hydrate_browser_use_lifecycle_from_legacy_state()
        runtime = cls._hydrate_playwright_runtime_from_legacy_state()

        if lifecycle.user_data_dir:
            try:
                cls._browser_use_boundary.cleanup_temp_dir(
                    lifecycle.user_data_dir,
                    expected_prefix="jarvis-browser-use-",
                )
            except BrowserUseCleanupError:
                pass
            lifecycle.user_data_dir = None

        if runtime.user_data_dir:
            try:
                cls._playwright_boundary.cleanup_temp_dir(
                    runtime.user_data_dir,
                    expected_prefix="jarvis-playwright-home-",
                )
            except Exception:
                pass
            runtime.user_data_dir = None

        cls._sync_browser_use_legacy_state()
        cls._sync_playwright_legacy_state()

    @staticmethod
    def _is_subpath(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _ensure_external_browser_use_resolution(cls) -> None:
        lifecycle = cls._hydrate_browser_use_lifecycle_from_legacy_state()
        cls._browser_use_boundary.ensure_external_package()
        lifecycle.remember_resolution(cls._browser_use_boundary.resolution_checked)
        cls._sync_browser_use_legacy_state()

    @classmethod
    def clear_stop_request(cls) -> None:
        cls._browser_use_lifecycle.clear_stop_request()
        cls._browser_use_stop_requested = cls._browser_use_lifecycle.stop_requested

    @classmethod
    def _register_active_browser_use_agent(cls, agent: Any) -> None:
        cls._browser_use_lifecycle.register_active_agent(agent)
        cls._active_browser_use_agents = cls._browser_use_lifecycle.active_agents

    @classmethod
    def _unregister_active_browser_use_agent(cls, agent: Any) -> None:
        cls._browser_use_lifecycle.unregister_active_agent(agent)
        cls._active_browser_use_agents = cls._browser_use_lifecycle.active_agents

    @classmethod
    def request_stop_all(cls) -> int:
        result = cls._browser_use_lifecycle.request_stop_all()
        cls._last_browser_use_stop_failures = result.failures
        cls._active_browser_use_agents = cls._browser_use_lifecycle.active_agents
        cls._browser_use_stop_requested = cls._browser_use_lifecycle.stop_requested
        return result.stopped

    @classmethod
    async def _should_stop_browser_use_agent(cls) -> bool:
        should_stop = await cls._browser_use_lifecycle.should_stop_agent()
        cls._browser_use_stop_requested = cls._browser_use_lifecycle.stop_requested
        return should_stop

    @staticmethod
    def _normalize_resume_text(value: str) -> str:
        return BrowserUseLifecycle.normalize_resume_text(value)

    @classmethod
    def _is_resume_request(cls, task: str) -> bool:
        return cls._browser_use_lifecycle.is_resume_request(task)

    @classmethod
    def has_interrupted_work(cls) -> bool:
        return cls._browser_use_lifecycle.has_interrupted_work()

    @classmethod
    def resolve_resume_task(cls, user_prompt: str) -> str | None:
        return cls._browser_use_lifecycle.resolve_resume_task(user_prompt)

    @classmethod
    def _remember_interrupted_browser_use_agent(
        cls,
        agent: Any,
        *,
        task: str,
        summary: str = "",
    ) -> None:
        if not cls._browser_use_lifecycle.remember_interrupted_agent(
            agent,
            task=task,
            summary=summary,
        ):
            return
        interrupted = cls._browser_use_lifecycle.interrupted_work
        cls._interrupted_browser_use_state = interrupted.state if interrupted else None
        cls._interrupted_browser_use_task = interrupted.task if interrupted else ""
        cls._interrupted_browser_use_summary = interrupted.summary if interrupted else ""

    @classmethod
    def _clear_interrupted_browser_use_agent(cls, task: str = "") -> None:
        cls._browser_use_lifecycle.clear_interrupted_agent(task)
        interrupted = cls._browser_use_lifecycle.interrupted_work
        cls._interrupted_browser_use_state = interrupted.state if interrupted else None
        cls._interrupted_browser_use_task = interrupted.task if interrupted else ""
        cls._interrupted_browser_use_summary = interrupted.summary if interrupted else ""

    @classmethod
    def _consume_resume_state_for_task(cls, task: str) -> Any:
        return cls._browser_use_lifecycle.consume_resume_state_for_task(task)

    @classmethod
    async def _close_shared_resources(cls) -> None:
        playwright_failures: list[PlaywrightLifecycleFailure] = []
        browser_use_cleanup_error: BrowserUseCleanupError | None = None

        controller = cls._shared_playwright_controller
        cls._shared_playwright_controller = None
        if controller is not None:
            playwright_failures.extend(
                await cls._playwright_boundary.close_resource(
                    controller,
                    operation="controller.close",
                    method_name="close",
                )
            )

        mcp_client = cls._shared_playwright_mcp_client
        cls._shared_playwright_mcp_client = None
        if mcp_client is not None:
            playwright_failures.extend(
                await cls._playwright_boundary.close_resource(
                    mcp_client,
                    operation="mcp_client.close",
                    method_name="close",
                )
            )

        if cls._shared_backend == "browser_use":
            session = cls._shared_browser_use_session
            user_data_dir = cls._shared_browser_use_user_data_dir
            cls._shared_browser_use_session = None
            cls._shared_browser_use_user_data_dir = None
            try:
                await cls._browser_use_boundary.cleanup_session(
                    session,
                    user_data_dir=user_data_dir,
                )
                cls._last_browser_use_cleanup_failures = ()
            except BrowserUseCleanupError as exc:
                cls._last_browser_use_cleanup_failures = exc.failures
                browser_use_cleanup_error = exc

        elif cls._shared_backend == "playwright":
            context = cls._shared_playwright_context
            browser = cls._shared_playwright_browser
            playwright = cls._shared_playwright
            playwright_home = cls._shared_playwright_home
            playwright_failures.extend(
                await cls._playwright_boundary.cleanup_resources(
                    context=context,
                    browser=browser,
                    playwright=playwright,
                    user_data_dir=playwright_home,
                )
            )

            cls._shared_playwright = None
            cls._shared_playwright_browser = None
            cls._shared_playwright_context = None
            cls._shared_playwright_page = None
            cls._shared_playwright_home = None
            cls._shared_playwright_headless = False

        cls._shared_backend = None
        if playwright_failures:
            cls._last_playwright_cleanup_failures = tuple(playwright_failures)
            raise PlaywrightCleanupError(tuple(playwright_failures))
        cls._last_playwright_cleanup_failures = ()
        if browser_use_cleanup_error is not None:
            raise browser_use_cleanup_error

    @classmethod
    def _get_or_create_playwright_controller(cls) -> Any:
        if cls._shared_playwright_controller is None:
            cls._shared_playwright_controller = PlaywrightBrowserController()
        return cls._shared_playwright_controller

    @classmethod
    def _get_or_create_playwright_mcp_client(cls) -> PlaywrightMcpClient:
        client = cls._shared_playwright_mcp_client
        if client is None:
            client = PlaywrightMcpClient()
            cls._shared_playwright_mcp_client = client
        return client

    @classmethod
    def _should_use_controller_page_context(cls, task: str, direct_url: str | None) -> bool:
        if not should_extract_page_content(task):
            return False
        if has_browser_interaction_intent(task):
            return False
        if direct_url:
            return True
        if cls._shared_backend is not None:
            return False
        controller = cls._shared_playwright_controller
        if controller is None or not is_current_tab_context_task(task):
            return False
        has_open_page = getattr(controller, "has_open_page", None)
        if not callable(has_open_page):
            return False
        try:
            return bool(has_open_page())
        except Exception:
            return False

    async def _get_or_create_browser_use_session(self):
        type(self)._ensure_external_browser_use_resolution()

        cls = type(self)
        lifecycle = cls._hydrate_browser_use_lifecycle_from_legacy_state()
        if cls._shared_backend == "playwright":
            raise RuntimeError("Shared browser backend is already Playwright.")

        existing_session = lifecycle.reuse_session(cls._browser_use_boundary)
        if existing_session is not None:
            cls._sync_browser_use_legacy_state()
            return existing_session

        handle = cls._browser_use_boundary.create_session(
            session_policy=cls._browser_use_session_policy,
        )
        cls._shared_backend = "browser_use"
        session = lifecycle.remember_session(handle)
        cls._sync_browser_use_legacy_state()
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

        if cls._should_use_controller_page_context(task, original_direct_url):
            try:
                return await self._execute_with_controller_page_context(
                    task,
                    pre_extracted_url=original_direct_url,
                )
            except Exception as exc:
                print(f"[Browser Agent][controller] page context extraction failed: {exc}")

        if (
            cls._shared_backend is None
            and cls._shared_playwright_controller is None
            and self._should_use_mcp_snapshot(task)
        ):
            try:
                mcp_result = await self._execute_with_playwright_mcp_snapshot(task)
                if mcp_result.get("success"):
                    return mcp_result
            except Exception as exc:
                print(f"[Browser Agent][mcp] snapshot extraction failed: {exc}")

        # Once a backend is chosen, keep using it so all browser actions stay in
        # the same persistent browser session.
        if cls._shared_backend == "browser_use":
            try:
                return await self._execute_with_browser_use(task, close_when_done=close_when_done)
            except (BrowserUseDependencyError, BrowserUseLifecycleError) as exc:
                return {"success": False, "result": None, "error": str(exc)}
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
        except BrowserUseDependencyError as exc:
            return await self._execute_playwright_fallback_after_browser_use_failure(
                task,
                bootstrap_error=exc,
                close_when_done=close_when_done,
                pre_extracted_url=original_direct_url,
                log_prefix="[Browser Agent][fallback] browser_use dependency unavailable",
            )
        except BrowserUseLifecycleError as exc:
            return {"success": False, "result": None, "error": str(exc)}
        except Exception as exc:
            if not self._should_fallback_to_playwright(exc):
                return {"success": False, "result": None, "error": str(exc)}

            return await self._execute_playwright_fallback_after_browser_use_failure(
                task,
                bootstrap_error=exc,
                close_when_done=close_when_done,
                pre_extracted_url=original_direct_url,
                log_prefix="[Browser Agent][fallback] browser_use unavailable",
            )

    @staticmethod
    def _dual_backend_failure_message(
        bootstrap_error: Exception,
        fallback_error: Exception,
    ) -> str:
        return (
            "Browser task failed in both browser_use and Playwright fallback. "
            f"bootstrap_error={bootstrap_error}; fallback_error={fallback_error}"
        )

    async def _execute_playwright_fallback_after_browser_use_failure(
        self,
        task: str,
        *,
        bootstrap_error: Exception,
        close_when_done: bool,
        pre_extracted_url: str | None,
        log_prefix: str,
    ) -> dict[str, Any]:
        print(f"{log_prefix}: {bootstrap_error}")
        try:
            return await self._execute_with_playwright(
                task,
                bootstrap_error=str(bootstrap_error),
                close_when_done=close_when_done,
                pre_extracted_url=pre_extracted_url,
            )
        except Exception as fallback_exc:
            return {
                "success": False,
                "result": None,
                "error": self._dual_backend_failure_message(
                    bootstrap_error,
                    fallback_exc,
                ),
            }

    async def _execute_with_controller_page_context(
        self,
        task: str,
        *,
        pre_extracted_url: str | None,
    ) -> dict[str, Any]:
        controller = type(self)._get_or_create_playwright_controller()
        if pre_extracted_url:
            context = await controller.navigate_and_extract(pre_extracted_url)
        else:
            page, _used_headless = await controller.get_or_create_page()
            selected = await controller.select_relevant_existing_page(
                task,
                default_page=page,
            )
            context = await controller.extract_context(selected or page)

        summary = format_page_context_response(task, context)
        headings = list(getattr(context, "headings", []) or [])
        return {
            "success": True,
            "result": {
                "summary": summary,
                "mode": "playwright_controller",
                "task": task,
                "url": getattr(context, "url", ""),
                "title": getattr(context, "title", ""),
                "headings": headings,
                "complete": True,
            },
            "error": None,
            "complete": True,
        }

    async def _execute_with_playwright_mcp_snapshot(self, task: str) -> dict[str, Any]:
        client = type(self)._get_or_create_playwright_mcp_client()
        if not await client.health_check():
            return {
                "success": False,
                "result": None,
                "error": "Playwright MCP is unavailable.",
                "complete": False,
            }

        snapshot = await client.snapshot()
        summary = (
            "Playwright MCP captured the current page structure. "
            "Another browser action is needed to complete the task.\n\n"
            f"Snapshot:\n{snapshot}"
        )
        return {
            "success": True,
            "result": {
                "summary": summary,
                "mode": "playwright_mcp_snapshot",
                "task": task,
                "snapshot": snapshot,
                "complete": False,
            },
            "error": None,
            "complete": False,
        }

    async def _execute_with_browser_use(self, task: str, close_when_done: bool) -> dict[str, Any]:
        type(self)._ensure_external_browser_use_resolution()
        boundary = type(self)._browser_use_boundary
        ChatGoogle = boundary.import_google_llm_class()

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
            agent = boundary.create_agent(
                task=agent_task,
                llm=llm,
                browser_session=session,
                available_file_paths=available_file_paths,
                register_should_stop_callback=type(self)._should_stop_browser_use_agent,
                injected_agent_state=resume_state,
                tool_policy=type(self)._browser_use_tool_policy,
            )
            type(self)._register_active_browser_use_agent(agent)
            try:
                history = await agent.run()
            except asyncio.CancelledError:
                stop_result = type(self)._browser_use_lifecycle.stop_agent(agent)
                type(self)._last_browser_use_stop_failures = stop_result.failures
                type(self)._remember_interrupted_browser_use_agent(
                    agent,
                    task=agent_task,
                    summary="Browser task interrupted by user.",
                )
                raise
            finally:
                type(self)._unregister_active_browser_use_agent(agent)

            if type(self)._browser_use_lifecycle.stop_requested or getattr(agent.state, "stopped", False):
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
        except (BrowserUseDependencyError, BrowserUseLifecycleError):
            raise
        except Exception as exc:
            if not is_gemini_quota_error(exc):
                return {"success": False, "result": None, "error": str(exc)}
            fallback_error = str(exc)
            for model_name in get_openrouter_models("browser"):
                try:
                    ChatOpenRouter = boundary.import_openrouter_llm_class()

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
                except (BrowserUseDependencyError, BrowserUseLifecycleError):
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
    def _should_use_mcp_snapshot(task: str) -> bool:
        return should_use_mcp_snapshot(task)

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
        shared_browser_use_session = type(self)._shared_browser_use_session
        await type(self)._close_shared_resources()

        if self._session is shared_browser_use_session:
            self._session = None

        if self._session is None:
            return
        try:
            await type(self)._browser_use_boundary.cleanup_session(
                self._session,
                user_data_dir=None,
            )
        finally:
            self._session = None
