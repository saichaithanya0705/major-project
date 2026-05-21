"""Async subprocess lifecycle helpers shared across agent runtimes."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")
MaybeAwaitable = object | Awaitable[object]
TerminateProcess = Callable[[], MaybeAwaitable]
CleanupCallback = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class SubprocessOperationResult(Generic[T]):
    value: T | None
    timed_out: bool = False


async def _invoke_terminate_callback(terminate: TerminateProcess | None) -> None:
    if terminate is None:
        return
    try:
        result = terminate()
    except (OSError, ProcessLookupError):
        return
    if inspect.isawaitable(result):
        try:
            await result
        except (OSError, ProcessLookupError):
            return


async def _stop_subprocess(
    process: asyncio.subprocess.Process,
    *,
    terminate: TerminateProcess | None,
) -> None:
    if process.returncode is None:
        if terminate is None:
            try:
                process.kill()
            except (OSError, ProcessLookupError):
                pass
        else:
            await _invoke_terminate_callback(terminate)
    try:
        await process.wait()
    except Exception:
        pass


async def _run_cleanup(cleanup: CleanupCallback | None) -> None:
    if cleanup is not None:
        await cleanup()


async def await_subprocess_operation(
    *,
    process: asyncio.subprocess.Process,
    timeout: float,
    operation: Awaitable[T],
    cleanup: CleanupCallback | None = None,
    terminate: TerminateProcess | None = None,
    terminate_on_error: bool = False,
) -> SubprocessOperationResult[T]:
    try:
        value = await asyncio.wait_for(operation, timeout=timeout)
        return SubprocessOperationResult(value=value, timed_out=False)
    except asyncio.CancelledError:
        await _stop_subprocess(process, terminate=terminate)
        await _run_cleanup(cleanup)
        raise
    except asyncio.TimeoutError:
        await _stop_subprocess(process, terminate=terminate)
        await _run_cleanup(cleanup)
        return SubprocessOperationResult(value=None, timed_out=True)
    except Exception:
        if terminate_on_error:
            await _stop_subprocess(process, terminate=terminate)
            await _run_cleanup(cleanup)
        raise
