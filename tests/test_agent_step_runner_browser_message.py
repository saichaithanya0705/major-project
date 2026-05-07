"""
Checks BrowserAgent structured page-context results surface as chat text.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.agent_step_runner import _browser_completion_message, _extract_browser_message


def test_browser_message_prefers_nested_page_context_summary() -> None:
    result = {
        "success": True,
        "result": {
            "page_context": {
                "summary": "Summary of Example Docs:\nInstall instructions explain setup."
            },
            "summary": "",
        },
    }

    assert _browser_completion_message(result) == (
        "Summary of Example Docs:\nInstall instructions explain setup."
    )


def test_extract_browser_message_reads_result_page_context() -> None:
    message = _extract_browser_message(
        {
            "result": {
                "page_context": {
                    "summary": "Nested result summary.",
                },
            },
        }
    )

    assert message == "Nested result summary."


def test_extract_browser_message_falls_back_to_page_context_content() -> None:
    message = _extract_browser_message(
        {
            "page_context": {
                "summary": "   ",
                "content": "Readable page content.",
            },
        }
    )

    assert message == "Readable page content."


if __name__ == "__main__":
    test_browser_message_prefers_nested_page_context_summary()
    test_extract_browser_message_reads_result_page_context()
    test_extract_browser_message_falls_back_to_page_context_content()
    print("[test_agent_step_runner_browser_message] All checks passed.")
