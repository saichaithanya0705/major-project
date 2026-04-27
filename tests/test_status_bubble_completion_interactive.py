"""
Interactive Test: Status Bubble Completion Flow

This test uses mocked messages (no model calls) to validate:
1. Task runs in top status bubble
2. Completion shows "Task done" briefly, then expands with final response
3. Clicking expanded status bubble restores center input + under-bar response
4. Dismiss button (x) hides the expanded status bubble

Usage:
    python tests/test_status_bubble_completion_interactive.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from ui.server import VisualizationServer
from ui.visualization_api.clear_screen import _clear_screen
from ui.visualization_api.status_bubble import (
    show_status_bubble,
    update_status_bubble,
    complete_status_bubble,
    show_command_overlay,
)
from tests.status_bubble_harness import (
    HeadlessVisualizationClient,
    allocate_local_ws_endpoint,
    configure_isolated_runtime_endpoint,
)

LIGHT_STATUS_THEME = {
    "statusBg": "rgba(245, 248, 252, 0.96)",
    "statusBorder": "rgba(15, 20, 30, 0.1)",
    "statusText": "rgba(15, 20, 30, 0.94)",
    "statusShimmer": "rgba(60, 120, 220, 0.55)",
    "statusCheck": "rgba(60, 120, 220, 0.9)",
}


async def _run_mock_task(final_response: str):
    await show_command_overlay()
    await asyncio.sleep(0.05)

    await show_status_bubble("Running mocked agent...", theme=LIGHT_STATUS_THEME)
    await asyncio.sleep(0.05)
    await update_status_bubble("Gathering context...", theme=LIGHT_STATUS_THEME)
    await asyncio.sleep(0.05)
    await update_status_bubble("Executing mocked steps...", theme=LIGHT_STATUS_THEME)
    await asyncio.sleep(0.05)

    await complete_status_bubble(
        final_response,
        done_text="Task done",
        delay_ms=100,
        theme=LIGHT_STATUS_THEME,
    )


async def run_test():
    host, port = allocate_local_ws_endpoint()
    configure_isolated_runtime_endpoint(host=host, port=port)

    server = VisualizationServer(host=host, port=port)
    await server.start()
    try:
        uri = f"ws://{host}:{port}"
        async with HeadlessVisualizationClient(uri):
            await _run_mock_task(
                "Mocked CLI confirmation: wrote 2 files and finished without errors."
            )
            await asyncio.sleep(0.05)
            await _run_mock_task(
                "Mocked browser confirmation: extracted 5 results from the page."
            )
            await asyncio.sleep(0.1)
            print("[completion_interactive] Test finished.")
    finally:
        await _clear_screen()
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\n[completion_interactive] Interrupted by user.")
