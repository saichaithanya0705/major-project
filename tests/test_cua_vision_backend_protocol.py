"""
Checks for the CUA Vision computer backend protocol.

Usage:
    python tests/test_cua_vision_backend_protocol.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.computer_backend import (  # noqa: E402
    ComputerBackend,
    PyAutoGuiComputerBackend,
)


def test_pyautogui_backend_satisfies_protocol() -> None:
    backend = PyAutoGuiComputerBackend()

    assert isinstance(backend, ComputerBackend)
    assert callable(backend.observe)
    assert callable(backend.execute)
    assert callable(backend.get_active_window)
    assert callable(backend.close)


def run_checks() -> None:
    test_pyautogui_backend_satisfies_protocol()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_backend_protocol] All checks passed.")

