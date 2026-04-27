"""
Test: Status Bubble - Browser Agent

This test triggers the status bubble with simulated Browser agent status updates.
Does NOT call the actual LLM - just demonstrates the status bubble UI flow.

Usage:
    python tests/test_status_bubble_browser.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from ui.server import VisualizationServer
from ui.visualization_api.status_bubble import (
    show_status_bubble,
    update_status_bubble,
    hide_status_bubble,
)
from tests.status_bubble_harness import (
    HeadlessVisualizationClient,
    allocate_local_ws_endpoint,
    configure_isolated_runtime_endpoint,
)


async def simulate_browser_agent():
    """
    Simulates the status updates a Browser agent would produce.
    """
    status_messages = [
        "Launching browser...",
        "Navigating to google.com...",
        "Page loaded successfully",
        "Locating search input...",
        "Typing search query...",
        "Clicking search button...",
        "Waiting for results...",
        "Extracting search results...",
        "Found 10 results",
        "Task complete",
    ]

    dark_theme = {
        "statusBg": "rgba(4, 5, 7, 0.96)",
        "statusBorder": "rgba(255, 255, 255, 0.06)",
        "statusText": "rgba(242, 245, 248, 0.96)",
        "statusShimmer": "rgba(160, 200, 255, 0.6)",
        "statusCheck": "rgba(130, 200, 130, 0.9)",
    }
    light_theme = {
        "statusBg": "rgba(245, 248, 252, 0.96)",
        "statusBorder": "rgba(15, 20, 30, 0.1)",
        "statusText": "rgba(15, 20, 30, 0.94)",
        "statusShimmer": "rgba(60, 120, 220, 0.55)",
        "statusCheck": "rgba(60, 120, 220, 0.9)",
    }

    await show_status_bubble(status_messages[0], theme=dark_theme)
    await asyncio.sleep(0.05)
    await update_status_bubble(status_messages[1], theme=light_theme)
    await asyncio.sleep(0.05)

    for msg in status_messages[2:]:
        await update_status_bubble(msg)
        await asyncio.sleep(0.05)

    # Hide after showing "Task complete" briefly
    await hide_status_bubble(delay=50)


async def run_test():
    host, port = allocate_local_ws_endpoint()
    configure_isolated_runtime_endpoint(host=host, port=port)

    server = VisualizationServer(host=host, port=port)
    await server.start()
    try:
        uri = f"ws://{host}:{port}"
        async with HeadlessVisualizationClient(uri):
            print("[test_status_bubble_browser] Headless client connected.")
            await simulate_browser_agent()
            await asyncio.sleep(0.1)
            print("[test_status_bubble_browser] Test finished.")
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\n[test_status_bubble_browser] Interrupted by user.")
