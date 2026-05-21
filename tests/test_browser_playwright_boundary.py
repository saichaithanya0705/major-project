"""
Checks for BrowserAgent Playwright cleanup boundaries.

Usage:
    python tests/test_browser_playwright_boundary.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.agent import BrowserAgent
from agents.browser.playwright_boundary import (
    PlaywrightBoundary,
    PlaywrightCleanupError,
    PlaywrightMcpSnapshotError,
    PlaywrightPageContextError,
    PlaywrightRuntimeState,
)


class _FailingAsyncClose:
    async def close(self):
        raise RuntimeError("context close failed")


class _FailingController:
    async def navigate_and_extract(self, url: str):
        raise RuntimeError(f"controller launch failed for {url}")


class _FailingMcpClient:
    async def health_check(self) -> bool:
        return True

    async def snapshot(self) -> str:
        raise RuntimeError("snapshot capture failed")


async def test_close_shared_resources_surfaces_playwright_cleanup_failures() -> None:
    cls = BrowserAgent
    original_backend = cls._shared_backend
    original_context = cls._shared_playwright_context
    original_browser = cls._shared_playwright_browser
    original_playwright = cls._shared_playwright
    original_home = cls._shared_playwright_home
    original_failures = getattr(cls, "_last_playwright_cleanup_failures", ())

    try:
        cls._shared_backend = "playwright"
        cls._shared_playwright_context = _FailingAsyncClose()
        cls._shared_playwright_browser = None
        cls._shared_playwright = None
        cls._shared_playwright_home = None
        cls._last_playwright_cleanup_failures = ()

        try:
            await cls._close_shared_resources()
            raise AssertionError("Expected Playwright cleanup failure to be typed.")
        except PlaywrightCleanupError as exc:
            assert len(exc.failures) == 1, exc.failures
            assert exc.failures[0].operation == "context.close", exc.failures
            assert "context close failed" in str(exc.failures[0].error), exc.failures

        assert cls._shared_backend is None
        assert cls._shared_playwright_context is None
        assert len(cls._last_playwright_cleanup_failures) == 1
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_context = original_context
        cls._shared_playwright_browser = original_browser
        cls._shared_playwright = original_playwright
        cls._shared_playwright_home = original_home
        cls._last_playwright_cleanup_failures = original_failures


async def test_boundary_cleanup_runtime_clears_state_after_failure() -> None:
    boundary = PlaywrightBoundary()
    state = PlaywrightRuntimeState(context=_FailingAsyncClose())

    try:
        await boundary.cleanup_runtime(state)
        raise AssertionError("Expected typed Playwright cleanup failure.")
    except PlaywrightCleanupError as exc:
        assert len(exc.failures) == 1, exc.failures
        assert exc.failures[0].operation == "context.close", exc.failures
        assert "context close failed" in str(exc.failures[0].error), exc.failures

    assert state.context is None
    assert state.last_cleanup_failures
    assert state.last_cleanup_failures[0].operation == "context.close"


async def test_boundary_wraps_controller_failures_with_typed_error() -> None:
    boundary = PlaywrightBoundary()

    try:
        await boundary.extract_page_context(
            _FailingController(),
            task="summarize https://example.com/docs",
            pre_extracted_url="https://example.com/docs",
        )
        raise AssertionError("Expected typed controller boundary failure.")
    except PlaywrightPageContextError as exc:
        assert "controller launch failed" in str(exc), exc


async def test_boundary_wraps_mcp_snapshot_failures_with_typed_error() -> None:
    boundary = PlaywrightBoundary()

    try:
        await boundary.capture_mcp_snapshot(_FailingMcpClient())
        raise AssertionError("Expected typed MCP snapshot boundary failure.")
    except PlaywrightMcpSnapshotError as exc:
        assert "snapshot capture failed" in str(exc), exc


def run_checks() -> None:
    asyncio.run(test_close_shared_resources_surfaces_playwright_cleanup_failures())
    asyncio.run(test_boundary_cleanup_runtime_clears_state_after_failure())
    asyncio.run(test_boundary_wraps_controller_failures_with_typed_error())
    asyncio.run(test_boundary_wraps_mcp_snapshot_failures_with_typed_error())


if __name__ == "__main__":
    run_checks()
    print("[test_browser_playwright_boundary] All checks passed.")
