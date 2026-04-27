"""
Test: Status Bubble - CUA Vision Agent

This test triggers the status bubble with simulated CUA Vision agent status updates.
Does NOT call the actual LLM - just demonstrates the status bubble UI flow.

Usage:
    python tests/test_status_bubble_cua_vision.py
"""

import asyncio
import os
import random
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.settings import get_screen_size
from ui.server import VisualizationServer
from ui.visualization_api.status_bubble import (
    show_status_bubble,
    update_status_bubble,
    hide_status_bubble,
)
from ui.visualization_api.cursor_status import (
    show_cursor_status,
    update_cursor_status,
    hide_cursor_status,
    set_cursor_status_position,
)
from tests.status_bubble_harness import (
    HeadlessVisualizationClient,
    allocate_local_ws_endpoint,
    configure_isolated_runtime_endpoint,
)


async def simulate_cua_vision_agent():
    """
    Simulates mouse movement with near-cursor thinking and status bubble updates.
    """
    screen_width, screen_height = get_screen_size()
    screen_width = int(screen_width or 1920)
    screen_height = int(screen_height or 1080)

    # Keep clicks comfortably away from screen edges.
    margin = 140
    min_x, max_x = margin, max(margin + 1, screen_width - margin)
    min_y, max_y = margin, max(margin + 1, screen_height - margin)

    points = [
        (random.randint(min_x, max_x), random.randint(min_y, max_y))
        for _ in range(3)
    ]

    cursor_messages = [
        "Searching for next button...",
        "Checking likely click target...",
        "Scanning visible controls...",
        "Finding the best match...",
        "Locating actionable element...",
    ]

    await show_status_bubble("Starting vision scan...")
    await show_cursor_status(random.choice(cursor_messages))

    for idx, (target_x, target_y) in enumerate(points, start=1):
        await update_status_bubble(f"Moving to point {idx}...")
        await set_cursor_status_position(target_x, target_y)
        next_cursor_msg = random.choice(cursor_messages)
        await update_cursor_status(next_cursor_msg)
        await asyncio.sleep(0.05)

    await update_status_bubble("Task complete")
    await asyncio.sleep(0.05)
    await hide_cursor_status()
    await hide_status_bubble(delay=50)


async def run_test():
    host, port = allocate_local_ws_endpoint()
    configure_isolated_runtime_endpoint(host=host, port=port)

    server = VisualizationServer(host=host, port=port)
    await server.start()
    try:
        uri = f"ws://{host}:{port}"
        async with HeadlessVisualizationClient(uri):
            await simulate_cua_vision_agent()
            await asyncio.sleep(0.1)
            print("[test_status_bubble_cua_vision] Test finished.")
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\n[test_status_bubble_cua_vision] Interrupted by user.")
