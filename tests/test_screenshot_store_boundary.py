"""
Checks for routed vision screenshot notification boundaries.

Usage:
    python tests/test_screenshot_store_boundary.py
"""

import asyncio
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.screenshot_store as screenshot_store


class _FakeRapidState:
    def capture_fresh_screenshot(self):
        return "fresh-shot"


async def _fail_capture_started():
    raise RuntimeError("hide failed")


async def _fail_chat_restore():
    raise RuntimeError("restore failed")


async def _hang_notification():
    await asyncio.sleep(10)


class _SlowRapidState:
    def capture_fresh_screenshot(self):
        time.sleep(0.05)
        return "late-shot"


async def test_prepare_vision_screenshot_records_notification_failures() -> None:
    original_state = screenshot_store.RAPID_SESSION_STATE
    original_started = screenshot_store.send_vision_capture_started
    original_restore = screenshot_store.send_vision_chat_restore

    try:
        screenshot_store.RAPID_SESSION_STATE = _FakeRapidState()
        screenshot_store.send_vision_capture_started = _fail_capture_started
        screenshot_store.send_vision_chat_restore = _fail_chat_restore
        screenshot_store.clear_last_vision_capture_notification_failures()

        result = await screenshot_store.prepare_vision_screenshot(keep_chat_hidden=False)

        assert result == "fresh-shot"
        failures = screenshot_store.get_last_vision_capture_notification_failures()
        assert [failure.operation for failure in failures] == [
            "send_vision_capture_started",
            "send_vision_chat_restore",
        ]
        assert "hide failed" in str(failures[0].error)
        assert "restore failed" in str(failures[1].error)
    finally:
        screenshot_store.RAPID_SESSION_STATE = original_state
        screenshot_store.send_vision_capture_started = original_started
        screenshot_store.send_vision_chat_restore = original_restore
        screenshot_store.clear_last_vision_capture_notification_failures()


async def test_prepare_vision_screenshot_times_out_hung_notifications() -> None:
    original_state = screenshot_store.RAPID_SESSION_STATE
    original_started = screenshot_store.send_vision_capture_started
    original_restore = screenshot_store.send_vision_chat_restore

    try:
        screenshot_store.RAPID_SESSION_STATE = _FakeRapidState()
        screenshot_store.send_vision_capture_started = _hang_notification
        screenshot_store.send_vision_chat_restore = _hang_notification
        screenshot_store.clear_last_vision_capture_notification_failures()

        result = await screenshot_store.prepare_vision_screenshot(
            keep_chat_hidden=False,
            notification_timeout_seconds=0.001,
            settle_delay_seconds=0,
        )

        assert result == "fresh-shot"
        failures = screenshot_store.get_last_vision_capture_notification_failures()
        assert [failure.operation for failure in failures] == [
            "send_vision_capture_started",
            "send_vision_chat_restore",
        ]
        assert "timed out" in str(failures[0].error).lower()
        assert "timed out" in str(failures[1].error).lower()
    finally:
        screenshot_store.RAPID_SESSION_STATE = original_state
        screenshot_store.send_vision_capture_started = original_started
        screenshot_store.send_vision_chat_restore = original_restore
        screenshot_store.clear_last_vision_capture_notification_failures()


async def test_prepare_vision_screenshot_times_out_hung_capture_and_restores_chat() -> None:
    original_state = screenshot_store.RAPID_SESSION_STATE
    original_started = screenshot_store.send_vision_capture_started
    original_restore = screenshot_store.send_vision_chat_restore
    restore_calls = []

    async def _started():
        return None

    async def _restore():
        restore_calls.append("restore")

    try:
        screenshot_store.RAPID_SESSION_STATE = _SlowRapidState()
        screenshot_store.send_vision_capture_started = _started
        screenshot_store.send_vision_chat_restore = _restore
        screenshot_store.clear_last_vision_capture_notification_failures()

        try:
            await screenshot_store.prepare_vision_screenshot(
                keep_chat_hidden=False,
                capture_timeout_seconds=0.001,
                settle_delay_seconds=0,
            )
        except TimeoutError as exc:
            assert "screenshot capture timed out" in str(exc).lower()
        else:
            raise AssertionError("hung screenshot capture should time out")

        assert restore_calls == ["restore"]
        failures = screenshot_store.get_last_vision_capture_notification_failures()
        assert [failure.operation for failure in failures] == [
            "capture_fresh_screenshot",
        ]
    finally:
        screenshot_store.RAPID_SESSION_STATE = original_state
        screenshot_store.send_vision_capture_started = original_started
        screenshot_store.send_vision_chat_restore = original_restore
        screenshot_store.clear_last_vision_capture_notification_failures()


def run_checks() -> None:
    asyncio.run(test_prepare_vision_screenshot_records_notification_failures())
    asyncio.run(test_prepare_vision_screenshot_times_out_hung_notifications())
    asyncio.run(test_prepare_vision_screenshot_times_out_hung_capture_and_restores_chat())


if __name__ == "__main__":
    run_checks()
    print("[test_screenshot_store_boundary] All checks passed.")
