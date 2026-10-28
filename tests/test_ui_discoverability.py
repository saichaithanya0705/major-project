"""Rendered UX regressions; requires Node.js, Playwright and its Chromium browser.

Playwright can be installed outside the repo and resolved through NODE_PATH.
UI_TEST_CHROMIUM_PATH can select an existing Chromium executable.
No model provider, live backend, or real user session data is used.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_input_window_discoverability_and_restoration() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for rendered UI tests")
    available = subprocess.run(
        [node, "-e", "require.resolve('playwright')"],
        cwd=ROOT_DIR,
        capture_output=True,
        check=False,
    )
    if available.returncode:
        pytest.skip("Playwright is required for rendered UI tests (supports NODE_PATH)")

    result = subprocess.run(
        [node, "--test", "tests/ui/input_window_ux.cjs"],
        cwd=ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
