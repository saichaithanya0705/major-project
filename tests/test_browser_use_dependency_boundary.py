"""
Regression checks for BrowserAgent browser_use dependency boundary.

Usage:
    python tests/test_browser_use_dependency_boundary.py
"""

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.agent import BrowserAgent


def run_checks() -> None:
    original_find_spec = importlib.util.find_spec
    original_checked_flag = BrowserAgent._browser_use_resolution_checked
    vendored_root = (Path(ROOT_DIR) / "agents" / "browser" / "browser_use").resolve()

    try:
        # Local vendored package resolution must be rejected.
        def _find_spec_local(name: str):
            if name == "browser_use":
                return SimpleNamespace(origin=str(vendored_root / "__init__.py"))
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_local
        BrowserAgent._browser_use_resolution_checked = False
        try:
            BrowserAgent._ensure_external_browser_use_resolution()
            raise AssertionError("Expected vendored browser_use resolution to be rejected.")
        except RuntimeError as exc:
            message = str(exc).lower()
            assert "vendored browser_use" in message, exc

        # Missing package resolution must be rejected.
        def _find_spec_missing(name: str):
            if name == "browser_use":
                return None
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_missing
        BrowserAgent._browser_use_resolution_checked = False
        try:
            BrowserAgent._ensure_external_browser_use_resolution()
            raise AssertionError("Expected missing browser_use resolution to be rejected.")
        except RuntimeError as exc:
            message = str(exc).lower()
            assert "browser_use is not installed" in message, exc

        # External (non-vendored) resolution should pass.
        def _find_spec_external(name: str):
            if name == "browser_use":
                return SimpleNamespace(origin=str(Path(ROOT_DIR) / ".venv" / "Lib" / "site-packages" / "browser_use" / "__init__.py"))
            return original_find_spec(name)

        importlib.util.find_spec = _find_spec_external
        BrowserAgent._browser_use_resolution_checked = False
        BrowserAgent._ensure_external_browser_use_resolution()
        assert BrowserAgent._browser_use_resolution_checked is True
    finally:
        importlib.util.find_spec = original_find_spec
        BrowserAgent._browser_use_resolution_checked = original_checked_flag


if __name__ == "__main__":
    run_checks()
    print("[test_browser_use_dependency_boundary] All checks passed.")
