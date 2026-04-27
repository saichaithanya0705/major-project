"""
Test: Status Bubble - CUA CLI Agent

This test triggers the status bubble with simulated CUA CLI agent status updates.
Does NOT call the actual LLM - just demonstrates the status bubble UI flow.

Usage:
    python tests/test_status_bubble_cua_cli.py
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


async def simulate_cua_cli_agent():
    """
    Simulates the status updates a CUA CLI agent would produce.
    """
    status_messages = [
        "Opening terminal...",
        "Reading file structure...",
        "Executing: ls -la",
        "Processing output...",
        "Writing to config.json...",
        "Running npm install...",
        "Build successful",
        "Task complete",
    ]

    # Let server-side auto contrast decide the correct mode from the first frame.
    await show_status_bubble(status_messages[0])
    await asyncio.sleep(0.05)

    for msg in status_messages[1:]:
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
            print("[test_status_bubble_cua_cli] Headless client connected.")
            await simulate_cua_cli_agent()
            await asyncio.sleep(0.1)
            print("[test_status_bubble_cua_cli] Test finished.")
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\n[test_status_bubble_cua_cli] Interrupted by user.")
