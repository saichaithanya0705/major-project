"""
Checks that LocalBrowserWatchdog delegates subprocess install waits to the shared runtime.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "agents", "browser"))

import browser_use.browser.watchdogs.local_browser_watchdog as watchdog_module
from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
from core.async_process_lifecycle import SubprocessOperationResult


class _FakeAsyncProcess:
    def __init__(self, pid: int = 7373) -> None:
        self.pid = pid
        self.returncode = 0
        self.kill_calls = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"install ok", b"")

    def kill(self) -> None:
        self.kill_calls += 1


def test_install_browser_uses_shared_subprocess_runtime(monkeypatch) -> None:
    async def _run() -> None:
        fake_process = _FakeAsyncProcess()
        captured: dict[str, object] = {}
        fake_self = SimpleNamespace(
            logger=SimpleNamespace(debug=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None),
            _find_installed_browser_path=lambda: "C:/chrome.exe",
        )

        async def _fake_create_subprocess_exec(*_args, **_kwargs):
            return fake_process

        async def _fake_await_subprocess_operation(**kwargs):
            operation = kwargs.get("operation")
            if hasattr(operation, "close"):
                operation.close()
            captured.update(kwargs)
            return SubprocessOperationResult(value=(b"install ok", b""), timed_out=False)

        monkeypatch.setattr(
            watchdog_module.asyncio,
            "create_subprocess_exec",
            _fake_create_subprocess_exec,
        )
        monkeypatch.setattr(
            watchdog_module,
            "await_subprocess_operation",
            _fake_await_subprocess_operation,
        )

        result = await LocalBrowserWatchdog._install_browser_with_playwright(fake_self)

        assert result == "C:/chrome.exe"
        assert captured["process"] is fake_process
        assert captured["timeout"] == 60.0
        assert captured["terminate"] == fake_process.kill
        assert captured["terminate_on_error"] is True

    asyncio.run(_run())
