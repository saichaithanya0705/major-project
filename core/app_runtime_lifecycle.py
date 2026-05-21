"""Owned runtime lifecycle helpers for app startup and overlay execution."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import ImageGrab

from core.artifact_lifecycle import CleanupReport, cleanup_runtime_artifacts
from core.process_lifecycle import (
    ManagedProcessHandle,
    ManagedProcessSpec,
    ProcessStartError,
    ProcessSupervisor,
)
from core.settings import get_screen_size

ActiveBackgroundLogsProvider = Callable[[], Sequence[str]]
ConfiguredScreenSizeReader = Callable[[str], tuple[int, int]]
RuntimeTask = Callable[[], Awaitable[object]]
ScreenCaptureSource = Literal["captured", "configured"]
RuntimeTaskStatus = Literal["completed", "cancelled", "failed"]


@dataclass(frozen=True, slots=True)
class RuntimeCleanupOutcome:
    report: CleanupReport | None = None
    skip_reason: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skip_reason is not None

    def log_lines(self) -> list[str]:
        if self.skip_reason:
            return [f"[Cleanup] Skipped runtime cleanup: {self.skip_reason}"]
        if self.report is None:
            return []

        lines: list[str] = []
        if self.report.deleted or self.report.rotated:
            lines.append(
                f"[Cleanup] Removed {len(self.report.deleted)} stale artifact(s); "
                f"rotated {len(self.report.rotated)} log file(s)."
            )
        if self.report.errors:
            lines.append(f"[Cleanup] {len(self.report.errors)} cleanup error(s) skipped.")
        return lines


@dataclass(frozen=True, slots=True)
class ElectronLaunchOutcome:
    handle: ManagedProcessHandle | None = None
    message: str | None = None

    @property
    def launched(self) -> bool:
        return self.handle is not None


@dataclass(frozen=True, slots=True)
class StartupScreenSizeOutcome:
    width: int
    height: int
    source: ScreenCaptureSource
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeTaskOutcome:
    status: RuntimeTaskStatus
    error: str | None = None


def run_runtime_cleanup(
    project_root: str | os.PathLike[str],
    *,
    active_background_logs_provider: ActiveBackgroundLogsProvider,
) -> RuntimeCleanupOutcome:
    try:
        report = cleanup_runtime_artifacts(
            project_root=Path(project_root),
            active_background_logs=active_background_logs_provider(),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return RuntimeCleanupOutcome(skip_reason=f"{type(exc).__name__}: {exc}")
    return RuntimeCleanupOutcome(report=report)


def launch_electron_ui(
    project_root: str,
    *,
    supervisor: ProcessSupervisor,
) -> ElectronLaunchOutcome:
    auto_launch = os.getenv("JARVIS_AUTO_LAUNCH_ELECTRON", "1").strip().lower()
    if auto_launch in {"0", "false", "no", "off"}:
        return ElectronLaunchOutcome()

    ui_root = os.path.join(project_root, "ui")
    if not os.path.isdir(ui_root):
        return ElectronLaunchOutcome(
            message=f"Electron auto-launch skipped (missing UI directory): {ui_root}"
        )

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    npm_path = shutil.which(npm_command) or shutil.which("npm")
    if not npm_path:
        return ElectronLaunchOutcome(message="Electron auto-launch skipped (npm not found on PATH).")

    env = os.environ.copy()
    electron_binary = os.path.join(
        ui_root,
        "node_modules",
        "electron",
        "dist",
        "electron.exe" if os.name == "nt" else "electron",
    )
    if os.path.exists(electron_binary):
        env.setdefault("JARVIS_ELECTRON_BINARY", electron_binary)

    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True

    try:
        handle = supervisor.start(
            ManagedProcessSpec(
                label="electron-ui",
                command=[npm_path, "run", "dev"],
                cwd=Path(ui_root),
                env=env,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        )
    except ProcessStartError as exc:
        return ElectronLaunchOutcome(message=f"Electron auto-launch failed: {exc}")

    return ElectronLaunchOutcome(handle=handle, message="Launching Electron UI...")


def _capture_screen_size() -> tuple[int, int]:
    return ImageGrab.grab().size


async def resolve_startup_screen_size(
    settings_path: str,
    *,
    capture_timeout_seconds: float = 2.0,
    capture_screen_size: Callable[[], tuple[int, int]] = _capture_screen_size,
    configured_screen_size_reader: ConfiguredScreenSizeReader = get_screen_size,
) -> StartupScreenSizeOutcome:
    try:
        width, height = await asyncio.wait_for(
            asyncio.to_thread(capture_screen_size),
            timeout=capture_timeout_seconds,
        )
        return StartupScreenSizeOutcome(
            width=int(width),
            height=int(height),
            source="captured",
        )
    except asyncio.TimeoutError:
        reason = f"Timed out after {capture_timeout_seconds:.1f}s"
    except (OSError, RuntimeError, NotImplementedError, ValueError) as exc:
        reason = f"{type(exc).__name__}: {exc}"

    width, height = configured_screen_size_reader(settings_path)
    return StartupScreenSizeOutcome(
        width=int(width),
        height=int(height),
        source="configured",
        warning=(
            f"Screen capture unavailable at startup ({reason}). "
            f"Using configured size {int(width)}x{int(height)}."
        ),
    )


async def execute_runtime_task(operation: RuntimeTask) -> RuntimeTaskOutcome:
    try:
        await operation()
        return RuntimeTaskOutcome(status="completed")
    except asyncio.CancelledError:
        return RuntimeTaskOutcome(status="cancelled")
    except Exception as exc:
        return RuntimeTaskOutcome(
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )


__all__ = [
    "ElectronLaunchOutcome",
    "RuntimeCleanupOutcome",
    "RuntimeTaskOutcome",
    "StartupScreenSizeOutcome",
    "execute_runtime_task",
    "launch_electron_ui",
    "resolve_startup_screen_size",
    "run_runtime_cleanup",
]
