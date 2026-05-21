"""Typed cleanup boundary for Playwright-owned browser resources."""

from __future__ import annotations

import inspect
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PlaywrightBoundaryError(RuntimeError):
    """Base class for Playwright lifecycle boundary failures."""


@dataclass(frozen=True)
class PlaywrightLifecycleFailure:
    operation: str
    error: BaseException
    subject: str = ""


def _format_failures(failures: tuple[PlaywrightLifecycleFailure, ...]) -> str:
    return "; ".join(
        f"{failure.operation}{f'[{failure.subject}]' if failure.subject else ''}: {failure.error}"
        for failure in failures
    )


class PlaywrightCleanupError(PlaywrightBoundaryError):
    def __init__(self, failures: tuple[PlaywrightLifecycleFailure, ...]):
        self.failures = failures
        super().__init__(f"Playwright cleanup failed: {_format_failures(failures)}")


class PlaywrightPageContextError(PlaywrightBoundaryError):
    """Raised when controller-owned page context extraction fails."""


class PlaywrightMcpSnapshotError(PlaywrightBoundaryError):
    """Raised when Playwright MCP snapshot capture fails."""


def is_subpath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class PlaywrightBoundary:
    def get_or_create_controller(self, state: "PlaywrightRuntimeState", factory: Any) -> Any:
        controller = state.controller
        if controller is None:
            controller = factory()
            state.controller = controller
        return controller

    def get_or_create_mcp_client(self, state: "PlaywrightRuntimeState", factory: Any) -> Any:
        client = state.mcp_client
        if client is None:
            client = factory()
            state.mcp_client = client
        return client

    def remember_runtime(
        self,
        state: "PlaywrightRuntimeState",
        *,
        playwright: Any,
        browser: Any,
        context: Any,
        page: Any,
        user_data_dir: str,
        headless: bool,
    ) -> None:
        state.playwright = playwright
        state.browser = browser
        state.context = context
        state.page = page
        state.user_data_dir = user_data_dir
        state.headless = headless

    def reuse_page(
        self,
        state: "PlaywrightRuntimeState",
    ) -> tuple[Any, bool] | None:
        page = state.page
        if page is None:
            return None

        is_closed = getattr(page, "is_closed", None)
        if not callable(is_closed):
            state.page = None
            return None

        try:
            if is_closed():
                state.page = None
                return None
        except Exception:
            state.page = None
            return None
        return page, state.headless

    async def close_resource(
        self,
        resource: Any,
        *,
        operation: str,
        method_name: str,
    ) -> tuple[PlaywrightLifecycleFailure, ...]:
        if resource is None:
            return ()

        close = getattr(resource, method_name, None)
        if not callable(close):
            return (
                PlaywrightLifecycleFailure(
                    operation=operation,
                    error=TypeError(f"resource has no callable {method_name}()."),
                    subject=type(resource).__name__,
                ),
            )

        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            return (
                PlaywrightLifecycleFailure(
                    operation=operation,
                    error=exc,
                    subject=type(resource).__name__,
                ),
            )
        return ()

    async def cleanup_resources(
        self,
        *,
        context: Any = None,
        browser: Any = None,
        playwright: Any = None,
        user_data_dir: str | None = None,
        expected_prefix: str = "jarvis-playwright-home-",
    ) -> tuple[PlaywrightLifecycleFailure, ...]:
        failures: list[PlaywrightLifecycleFailure] = []
        failures.extend(
            await self.close_resource(
                context,
                operation="context.close",
                method_name="close",
            )
        )
        failures.extend(
            await self.close_resource(
                browser,
                operation="browser.close",
                method_name="close",
            )
        )
        failures.extend(
            await self.close_resource(
                playwright,
                operation="playwright.stop",
                method_name="stop",
            )
        )
        if user_data_dir:
            failures.extend(
                self.cleanup_temp_dir(
                    user_data_dir,
                    expected_prefix=expected_prefix,
                )
        )
        return tuple(failures)

    async def cleanup_runtime(self, state: "PlaywrightRuntimeState") -> None:
        failures: list[PlaywrightLifecycleFailure] = []
        failures.extend(
            await self.close_resource(
                state.controller,
                operation="controller.close",
                method_name="close",
            )
        )
        state.controller = None
        failures.extend(
            await self.close_resource(
                state.mcp_client,
                operation="mcp_client.close",
                method_name="close",
            )
        )
        state.mcp_client = None
        failures.extend(
            await self.cleanup_resources(
                context=state.context,
                browser=state.browser,
                playwright=state.playwright,
                user_data_dir=state.user_data_dir,
            )
        )
        state.playwright = None
        state.browser = None
        state.context = None
        state.page = None
        state.user_data_dir = None
        state.headless = False
        state.last_cleanup_failures = tuple(failures)
        if failures:
            raise PlaywrightCleanupError(state.last_cleanup_failures)

    async def extract_page_context(
        self,
        controller: Any,
        *,
        task: str,
        pre_extracted_url: str | None,
    ) -> Any:
        try:
            if pre_extracted_url:
                return await controller.navigate_and_extract(pre_extracted_url)

            page, _used_headless = await controller.get_or_create_page()
            selected = await controller.select_relevant_existing_page(
                task,
                default_page=page,
            )
            return await controller.extract_context(selected or page)
        except Exception as exc:
            raise PlaywrightPageContextError(
                f"Playwright controller page context extraction failed: {exc}"
            ) from exc

    async def capture_mcp_snapshot(self, client: Any) -> str | None:
        try:
            healthy = await client.health_check()
        except Exception as exc:
            raise PlaywrightMcpSnapshotError(
                f"Playwright MCP health check failed: {exc}"
            ) from exc
        if not healthy:
            return None
        try:
            return await client.snapshot()
        except Exception as exc:
            raise PlaywrightMcpSnapshotError(
                f"Playwright MCP snapshot failed: {exc}"
            ) from exc

    def cleanup_temp_dir(
        self,
        path: str | Path,
        *,
        expected_prefix: str,
        temp_root: Path | None = None,
    ) -> tuple[PlaywrightLifecycleFailure, ...]:
        temp_root = (temp_root or Path(tempfile.gettempdir())).resolve()
        resolved_path = Path(path).resolve()
        failures: list[PlaywrightLifecycleFailure] = []

        if not is_subpath(resolved_path, temp_root):
            failures.append(
                PlaywrightLifecycleFailure(
                    operation="tempdir.guard",
                    error=ValueError(f"{resolved_path} is outside {temp_root}."),
                    subject=str(resolved_path),
                )
            )
        if not resolved_path.name.startswith(expected_prefix):
            failures.append(
                PlaywrightLifecycleFailure(
                    operation="tempdir.guard",
                    error=ValueError(
                        f"{resolved_path.name} does not start with {expected_prefix}."
                    ),
                    subject=str(resolved_path),
                )
            )
        if failures or not resolved_path.exists():
            return tuple(failures)

        try:
            shutil.rmtree(resolved_path, ignore_errors=False)
        except FileNotFoundError:
            return ()
        except Exception as exc:
            return (
                PlaywrightLifecycleFailure(
                    operation="tempdir.remove",
                    error=exc,
                    subject=str(resolved_path),
                ),
            )
        return ()


@dataclass
class PlaywrightRuntimeState:
    controller: Any = None
    mcp_client: Any = None
    playwright: Any = None
    browser: Any = None
    context: Any = None
    page: Any = None
    user_data_dir: str | None = None
    headless: bool = False
    last_cleanup_failures: tuple[PlaywrightLifecycleFailure, ...] = ()
