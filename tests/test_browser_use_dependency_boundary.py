"""
Regression checks for BrowserAgent browser_use dependency boundary.

Usage:
    python tests/test_browser_use_dependency_boundary.py
"""

import importlib.util
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.browser_use_boundary import (
    BrowserUseBoundary,
    BrowserUseCleanupError,
    BrowserUseLifecycle,
    BrowserUsePackageNotInstalledError,
    BrowserUseSessionPolicy,
    BrowserUseToolPolicy,
    BrowserUseVendoredPackageError,
    BrowserUseSessionHandle,
)


class _FailingKillSession:
    async def kill(self):
        raise RuntimeError("session kill failed")


class _RecordingTools:
    def __init__(self, *, exclude_actions=None):
        self.exclude_actions = list(exclude_actions or [])


class _RecordingAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _RecordingBrowserProfile:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _RecordingBrowserSession:
    def __init__(self, *, browser_profile):
        self.browser_profile = browser_profile


class _RecordingBoundary(BrowserUseBoundary):
    def import_agent_class(self):
        return _RecordingAgent

    def import_tools_class(self):
        return _RecordingTools

    def import_browser_session_classes(self):
        return _RecordingBrowserProfile, _RecordingBrowserSession


def test_boundary_rejects_vendored_missing_and_accepts_external_package() -> None:
    run_checks()


def test_lifecycle_tracks_shared_browser_use_session_handle() -> None:
    lifecycle = BrowserUseLifecycle()
    handle = BrowserUseSessionHandle(
        session=object(),
        user_data_dir=r"C:\Temp\jarvis-browser-use-test",
    )

    lifecycle.remember_session(handle)

    assert lifecycle.session is handle.session
    assert lifecycle.user_data_dir == handle.user_data_dir

    released = lifecycle.detach_session()

    assert released == handle
    assert lifecycle.session is None
    assert lifecycle.user_data_dir is None


def test_boundary_raises_typed_cleanup_error_when_session_kill_fails() -> None:
    async def _run() -> None:
        boundary = BrowserUseBoundary()
        try:
            await boundary.cleanup_session(_FailingKillSession(), user_data_dir=None)
            raise AssertionError("Expected browser-use cleanup failure to be typed.")
        except BrowserUseCleanupError as exc:
            assert len(exc.failures) == 1, exc.failures
            failure = exc.failures[0]
            assert failure.operation == "session.kill", failure
            assert "session kill failed" in str(failure.error), failure

    asyncio.run(_run())


def test_boundary_create_agent_injects_first_party_tool_policy() -> None:
    boundary = _RecordingBoundary()
    agent = boundary.create_agent(
        task="summarize the page",
        llm=object(),
        browser_session=object(),
        available_file_paths=[],
        register_should_stop_callback=lambda *_args, **_kwargs: None,
        injected_agent_state=None,
        tool_policy=BrowserUseToolPolicy(),
    )

    tools = agent.kwargs["tools"]
    assert isinstance(tools, _RecordingTools)
    assert tools.exclude_actions == ["write_file", "replace_file"], tools.exclude_actions


def test_boundary_create_session_honors_first_party_session_policy() -> None:
    boundary = _RecordingBoundary()
    original_mkdtemp = tempfile.mkdtemp

    try:
        tempfile.mkdtemp = lambda prefix: rf"C:\Temp\{prefix}session"
        handle = boundary.create_session(
            session_policy=BrowserUseSessionPolicy(
                headless=True,
                keep_alive=False,
                temp_prefix="jarvis-browser-use-test-",
            )
        )
    finally:
        tempfile.mkdtemp = original_mkdtemp

    profile = handle.session.browser_profile
    assert profile.kwargs["headless"] is True, profile.kwargs
    assert profile.kwargs["keep_alive"] is False, profile.kwargs
    assert profile.kwargs["user_data_dir"] == r"C:\Temp\jarvis-browser-use-test-session", profile.kwargs
    assert handle.user_data_dir == r"C:\Temp\jarvis-browser-use-test-session", handle.user_data_dir


def run_checks() -> None:
    original_find_spec = importlib.util.find_spec
    vendored_root = (Path(ROOT_DIR) / "agents" / "browser" / "browser_use").resolve()
    boundary = BrowserUseBoundary(vendored_root=vendored_root)

    try:
        # Local vendored package resolution must be rejected.
        def _find_spec_local(name: str):
            if name == "browser_use":
                return SimpleNamespace(origin=str(vendored_root / "__init__.py"))
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_local
        try:
            boundary.ensure_external_package()
            raise AssertionError("Expected vendored browser_use resolution to be rejected.")
        except BrowserUseVendoredPackageError as exc:
            message = str(exc).lower()
            assert "vendored browser_use" in message, exc

        # Missing package resolution must be rejected.
        def _find_spec_missing(name: str):
            if name == "browser_use":
                return None
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_missing
        boundary.reset_resolution_cache()
        try:
            boundary.ensure_external_package()
            raise AssertionError("Expected missing browser_use resolution to be rejected.")
        except BrowserUsePackageNotInstalledError as exc:
            message = str(exc).lower()
            assert "browser_use is not installed" in message, exc

        # External (non-vendored) resolution should pass.
        def _find_spec_external(name: str):
            if name == "browser_use":
                return SimpleNamespace(origin=str(Path(ROOT_DIR) / ".venv" / "Lib" / "site-packages" / "browser_use" / "__init__.py"))
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_external
        boundary.reset_resolution_cache()
        boundary.ensure_external_package()
        assert boundary.resolution_checked is True
    finally:
        importlib.util.find_spec = original_find_spec


if __name__ == "__main__":
    run_checks()
    print("[test_browser_use_dependency_boundary] All checks passed.")
