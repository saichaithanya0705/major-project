"""Process ownership helpers for app-started child processes."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any, Callable, Iterable, Mapping, Sequence


PopenFactory = Callable[..., Any]
ProcessTreeKiller = Callable[[int], None]


class ProcessLifecycleError(RuntimeError):
    """Base class for managed process lifecycle failures."""


class ProcessStartError(ProcessLifecycleError):
    """Raised when a managed process cannot be started."""


@dataclass(frozen=True)
class ManagedProcessSpec:
    label: str
    command: Sequence[str]
    cwd: str | os.PathLike[str]
    env: Mapping[str, str] | None = None
    creationflags: int = 0
    start_new_session: bool = False
    stop_timeout_seconds: float | None = None


@dataclass(frozen=True)
class ManagedProcessHandle:
    spec: ManagedProcessSpec
    process: Any
    started_at: float

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def pid(self) -> int:
        return int(self.process.pid)


@dataclass(frozen=True)
class ProcessStopResult:
    label: str
    pid: int
    returncode: int | None
    forced: bool
    error: str = ""


def _default_process_tree_killer(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


class ProcessSupervisor:
    """Tracks and stops child processes started by this app."""

    def __init__(
        self,
        *,
        popen_factory: PopenFactory = subprocess.Popen,
        process_tree_killer: ProcessTreeKiller = _default_process_tree_killer,
        stop_timeout_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._popen_factory = popen_factory
        self._process_tree_killer = process_tree_killer
        self._stop_timeout_seconds = stop_timeout_seconds
        self._monotonic = monotonic
        self._handles: dict[int, ManagedProcessHandle] = {}

    def start(self, spec: ManagedProcessSpec) -> ManagedProcessHandle:
        if not spec.command:
            raise ProcessStartError(f"{spec.label} has no command to start.")

        kwargs: dict[str, Any] = {
            "cwd": str(Path(spec.cwd)),
        }
        if spec.env is not None:
            kwargs["env"] = dict(spec.env)
        if os.name == "nt" and spec.creationflags:
            kwargs["creationflags"] = spec.creationflags
        if os.name != "nt" and spec.start_new_session:
            kwargs["start_new_session"] = True

        try:
            process = self._popen_factory(list(spec.command), **kwargs)
        except OSError as exc:
            raise ProcessStartError(f"Failed to start {spec.label}: {exc}") from exc

        pid = getattr(process, "pid", None)
        if pid is None:
            raise ProcessStartError(f"Failed to start {spec.label}: process has no pid.")

        handle = ManagedProcessHandle(
            spec=spec,
            process=process,
            started_at=self._monotonic(),
        )
        self._handles[int(pid)] = handle
        return handle

    def active_handles(self) -> list[ManagedProcessHandle]:
        return [handle for handle in self._handles.values() if handle.process.poll() is None]

    def stop_all(self) -> list[ProcessStopResult]:
        return [self.stop(handle) for handle in list(self._handles.values())]

    def stop(self, handle: ManagedProcessHandle) -> ProcessStopResult:
        process = handle.process
        pid = handle.pid
        timeout = handle.spec.stop_timeout_seconds or self._stop_timeout_seconds
        forced = False
        error = ""

        try:
            returncode = process.poll()
            if returncode is None:
                process.terminate()
                returncode = process.wait(timeout=timeout)
        except TimeoutExpired:
            forced = True
            returncode = self._force_stop(process, pid, timeout)
        except ProcessLookupError:
            returncode = process.poll()
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            returncode = process.poll()
        finally:
            self._handles.pop(pid, None)

        return ProcessStopResult(
            label=handle.label,
            pid=pid,
            returncode=returncode,
            forced=forced,
            error=error,
        )

    def _force_stop(self, process: Any, pid: int, timeout: float) -> int | None:
        try:
            self._process_tree_killer(pid)
        except (OSError, ProcessLookupError):
            pass

        try:
            return process.wait(timeout=timeout)
        except TimeoutExpired:
            process.kill()
            try:
                return process.wait(timeout=timeout)
            except TimeoutExpired:
                return process.poll()


def summarize_stop_results(results: Iterable[ProcessStopResult]) -> list[str]:
    messages: list[str] = []
    for result in results:
        if result.error:
            messages.append(
                f"{result.label} pid {result.pid} cleanup error: {result.error}"
            )
        elif result.forced:
            messages.append(f"{result.label} pid {result.pid} required forced cleanup.")
    return messages
