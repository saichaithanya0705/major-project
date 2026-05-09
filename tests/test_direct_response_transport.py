"""
Checks for final assistant response transport.

Usage:
    python tests/test_direct_response_transport.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.jarvis import tools as jarvis_tools


def test_rapid_response_direct_reply_uses_chat_transport() -> None:
    original_dispatch_now = jarvis_tools._dispatch_now
    original_last_direct_response = jarvis_tools._LAST_DIRECT_RESPONSE
    original_waited_after_direct_response = jarvis_tools._WAITED_AFTER_DIRECT_RESPONSE
    dispatched = []

    def _fake_dispatch_now(coro):
        dispatched.append(coro)
        coro.close()

    jarvis_tools._dispatch_now = _fake_dispatch_now
    jarvis_tools._LAST_DIRECT_RESPONSE = None
    jarvis_tools._WAITED_AFTER_DIRECT_RESPONSE = True
    try:
        jarvis_tools.direct_response(
            "x" * 1600,
            source="rapid_response",
        )

        assert len(dispatched) == 1, dispatched
        assert dispatched[0].cr_code.co_name == "send_chat_response", dispatched[0]
        assert jarvis_tools._LAST_DIRECT_RESPONSE is None
        assert jarvis_tools._WAITED_AFTER_DIRECT_RESPONSE is True
    finally:
        jarvis_tools._dispatch_now = original_dispatch_now
        jarvis_tools._LAST_DIRECT_RESPONSE = original_last_direct_response
        jarvis_tools._WAITED_AFTER_DIRECT_RESPONSE = original_waited_after_direct_response


def run_checks() -> None:
    test_rapid_response_direct_reply_uses_chat_transport()


if __name__ == "__main__":
    run_checks()
    print("[test_direct_response_transport] All checks passed.")
