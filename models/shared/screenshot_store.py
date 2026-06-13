"""
Screenshot capture helpers for routed vision workflows.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from models.rapid_state import RAPID_SESSION_STATE
from ui.visualization_api.chat_visibility import (
    send_vision_capture_started,
    send_vision_chat_restore,
)


@dataclass(frozen=True)
class VisionCaptureNotificationFailure:
    operation: str
    error: BaseException


_LAST_VISION_CAPTURE_NOTIFICATION_FAILURES: tuple[VisionCaptureNotificationFailure, ...] = ()
DEFAULT_VISION_CAPTURE_NOTIFICATION_TIMEOUT_SECONDS = 2.0
DEFAULT_VISION_SCREENSHOT_CAPTURE_TIMEOUT_SECONDS = 8.0
DEFAULT_VISION_CAPTURE_SETTLE_DELAY_SECONDS = 0.25


def get_last_vision_capture_notification_failures() -> tuple[VisionCaptureNotificationFailure, ...]:
    return _LAST_VISION_CAPTURE_NOTIFICATION_FAILURES


def clear_last_vision_capture_notification_failures() -> None:
    global _LAST_VISION_CAPTURE_NOTIFICATION_FAILURES
    _LAST_VISION_CAPTURE_NOTIFICATION_FAILURES = ()


def store_screenshot():
    """Capture and store a screenshot before the overlay appears."""
    screenshot = RAPID_SESSION_STATE.capture_screenshot()
    print("Screenshot captured (before overlay)")
    return screenshot


def get_stored_screenshot():
    """Get the stored screenshot and clear it, or capture a new one if none is stored."""
    return RAPID_SESSION_STATE.consume_or_capture_screenshot()


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _resolve_timeout(
    explicit_seconds: float | None,
    *,
    env_name: str,
    default_seconds: float,
    minimum: float,
    maximum: float,
) -> float:
    if explicit_seconds is not None:
        return max(minimum, min(maximum, float(explicit_seconds)))
    return _env_float(env_name, default_seconds, minimum=minimum, maximum=maximum)


def _timeout_error(operation: str, timeout_seconds: float) -> TimeoutError:
    return TimeoutError(f"{operation} timed out after {timeout_seconds:.3g}s")


async def _await_with_timeout(
    operation: str,
    awaitable: Awaitable[object],
    timeout_seconds: float,
) -> object:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise _timeout_error(operation, timeout_seconds) from exc


async def _send_capture_notification(
    *,
    operation: str,
    sender: Callable[[], Awaitable[object]],
    timeout_seconds: float,
    failures: list[VisionCaptureNotificationFailure],
) -> None:
    try:
        await _await_with_timeout(operation, sender(), timeout_seconds)
    except Exception as exc:
        failures.append(
            VisionCaptureNotificationFailure(
                operation=operation,
                error=exc,
            )
        )
        print(f"[VisionCapture] {operation} skipped: {exc}")


async def _capture_fresh_screenshot(timeout_seconds: float):
    return await _await_with_timeout(
        "screenshot capture",
        asyncio.to_thread(RAPID_SESSION_STATE.capture_fresh_screenshot),
        timeout_seconds,
    )


async def prepare_vision_screenshot(
    *,
    keep_chat_hidden: bool = False,
    notification_timeout_seconds: float | None = None,
    capture_timeout_seconds: float | None = None,
    settle_delay_seconds: float | None = None,
):
    """Hide the chat window before taking a fresh screenshot for vision agents."""
    global _LAST_VISION_CAPTURE_NOTIFICATION_FAILURES
    notification_failures: list[VisionCaptureNotificationFailure] = []
    notification_timeout = _resolve_timeout(
        notification_timeout_seconds,
        env_name="VISION_CAPTURE_NOTIFICATION_TIMEOUT_SECONDS",
        default_seconds=DEFAULT_VISION_CAPTURE_NOTIFICATION_TIMEOUT_SECONDS,
        minimum=0.001,
        maximum=30.0,
    )
    capture_timeout = _resolve_timeout(
        capture_timeout_seconds,
        env_name="VISION_SCREENSHOT_CAPTURE_TIMEOUT_SECONDS",
        default_seconds=DEFAULT_VISION_SCREENSHOT_CAPTURE_TIMEOUT_SECONDS,
        minimum=0.001,
        maximum=60.0,
    )
    settle_delay = (
        DEFAULT_VISION_CAPTURE_SETTLE_DELAY_SECONDS
        if settle_delay_seconds is None
        else max(0.0, float(settle_delay_seconds))
    )
    screenshot = None
    capture_error: Exception | None = None

    try:
        await _send_capture_notification(
            operation="send_vision_capture_started",
            sender=send_vision_capture_started,
            timeout_seconds=notification_timeout,
            failures=notification_failures,
        )

        if settle_delay > 0:
            await asyncio.sleep(settle_delay)

        try:
            screenshot = await _capture_fresh_screenshot(capture_timeout)
        except Exception as exc:
            capture_error = exc
            notification_failures.append(
                VisionCaptureNotificationFailure(
                    operation="capture_fresh_screenshot",
                    error=exc,
                )
            )
            print(f"[VisionCapture] Screenshot capture failed: {exc}")
    finally:
        if not keep_chat_hidden:
            await _send_capture_notification(
                operation="send_vision_chat_restore",
                sender=send_vision_chat_restore,
                timeout_seconds=notification_timeout,
                failures=notification_failures,
            )
        _LAST_VISION_CAPTURE_NOTIFICATION_FAILURES = tuple(notification_failures)

    if capture_error is not None:
        raise capture_error

    return screenshot


__all__ = [
    "DEFAULT_VISION_CAPTURE_NOTIFICATION_TIMEOUT_SECONDS",
    "DEFAULT_VISION_CAPTURE_SETTLE_DELAY_SECONDS",
    "DEFAULT_VISION_SCREENSHOT_CAPTURE_TIMEOUT_SECONDS",
    "VisionCaptureNotificationFailure",
    "clear_last_vision_capture_notification_failures",
    "get_last_vision_capture_notification_failures",
    "get_stored_screenshot",
    "prepare_vision_screenshot",
    "store_screenshot",
]
