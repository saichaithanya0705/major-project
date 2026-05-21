"""
Checks for app-owned process lifecycle boundaries.

Usage:
    python tests/test_app_process_lifecycle.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import app
from core import app_runtime_lifecycle
from core.process_lifecycle import ManagedProcessSpec, ProcessSupervisor


class _TimeoutProcess:
    pid = 4242

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self._poll_result = None

    def poll(self):
        return self._poll_result

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self._poll_result = -9

    def wait(self, timeout=None):
        if self._poll_result is None:
            raise TimeoutExpired(cmd="electron", timeout=timeout)
        return self._poll_result


def test_process_supervisor_force_kills_owned_process_tree_after_timeout() -> None:
    process = _TimeoutProcess()
    killed_trees: list[int] = []

    supervisor = ProcessSupervisor(
        popen_factory=lambda *_args, **_kwargs: process,
        process_tree_killer=lambda pid: killed_trees.append(pid),
        stop_timeout_seconds=0.01,
    )
    supervisor.start(
        ManagedProcessSpec(
            label="electron-ui",
            command=["npm", "run", "dev"],
            cwd=Path.cwd(),
        )
    )

    results = supervisor.stop_all()

    assert process.terminated is True
    assert killed_trees == [4242]
    assert results[0].label == "electron-ui"
    assert results[0].forced is True


def test_maybe_launch_electron_ui_registers_process_with_supervisor(tmp_path, monkeypatch) -> None:
    ui_root = tmp_path / "ui"
    electron_root = ui_root / "node_modules" / "electron" / "dist"
    electron_root.mkdir(parents=True)
    electron_binary = electron_root / ("electron.exe" if os.name == "nt" else "electron")
    electron_binary.write_text("binary", encoding="utf-8")

    captured: list[ManagedProcessSpec] = []

    class _Supervisor:
        def start(self, spec: ManagedProcessSpec):
            captured.append(spec)
            return SimpleNamespace(pid=5151)

    monkeypatch.setattr(app_runtime_lifecycle.shutil, "which", lambda _name: "npm.cmd")

    handle = app.maybe_launch_electron_ui(str(tmp_path), supervisor=_Supervisor())

    assert handle.pid == 5151
    assert captured
    assert captured[0].label == "electron-ui"
    assert captured[0].command == ["npm.cmd", "run", "dev"]
    assert captured[0].cwd == ui_root
    assert captured[0].env["JARVIS_ELECTRON_BINARY"] == str(electron_binary)


def test_run_runtime_cleanup_reports_operational_skip(monkeypatch) -> None:
    def _raise_cleanup(**_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(
        app_runtime_lifecycle,
        "cleanup_runtime_artifacts",
        _raise_cleanup,
    )

    outcome = app_runtime_lifecycle.run_runtime_cleanup(
        Path.cwd(),
        active_background_logs_provider=lambda: [],
    )

    assert outcome.skipped is True
    assert outcome.log_lines() == [
        "[Cleanup] Skipped runtime cleanup: OSError: permission denied"
    ]


def test_resolve_startup_screen_size_falls_back_to_configured_size_after_timeout() -> None:
    def _slow_capture() -> tuple[int, int]:
        time.sleep(0.05)
        return (2560, 1440)

    outcome = asyncio.run(
        app_runtime_lifecycle.resolve_startup_screen_size(
            "settings.json",
            capture_timeout_seconds=0.01,
            capture_screen_size=_slow_capture,
            configured_screen_size_reader=lambda _path: (1440, 900),
        )
    )

    assert outcome.source == "configured"
    assert (outcome.width, outcome.height) == (1440, 900)
    assert outcome.warning is not None
    assert "Timed out after" in outcome.warning


def test_execute_runtime_task_captures_failure() -> None:
    async def _fail() -> None:
        raise RuntimeError("boom")

    outcome = asyncio.run(app_runtime_lifecycle.execute_runtime_task(_fail))

    assert outcome.status == "failed"
    assert outcome.error == "RuntimeError: boom"


def run_checks() -> None:
    import tempfile

    test_process_supervisor_force_kills_owned_process_tree_after_timeout()
    with tempfile.TemporaryDirectory() as tmpdir:
        class _MonkeyPatch:
            def __init__(self) -> None:
                self._originals = []

            def setattr(self, target, name, value) -> None:
                self._originals.append((target, name, getattr(target, name)))
                setattr(target, name, value)

            def undo(self) -> None:
                for target, name, value in reversed(self._originals):
                    setattr(target, name, value)

        monkeypatch = _MonkeyPatch()
        try:
            test_maybe_launch_electron_ui_registers_process_with_supervisor(Path(tmpdir), monkeypatch)
        finally:
            monkeypatch.undo()
    class _RuntimeMonkeyPatch:
        def __init__(self) -> None:
            self._originals = []

        def setattr(self, target, name, value) -> None:
            self._originals.append((target, name, getattr(target, name)))
            setattr(target, name, value)

        def undo(self) -> None:
            for target, name, value in reversed(self._originals):
                setattr(target, name, value)

    runtime_monkeypatch = _RuntimeMonkeyPatch()
    try:
        test_run_runtime_cleanup_reports_operational_skip(runtime_monkeypatch)
    finally:
        runtime_monkeypatch.undo()
    test_resolve_startup_screen_size_falls_back_to_configured_size_after_timeout()
    test_execute_runtime_task_captures_failure()


if __name__ == "__main__":
    run_checks()
    print("[test_app_process_lifecycle] All checks passed.")
