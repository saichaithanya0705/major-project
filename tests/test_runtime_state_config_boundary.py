"""
Regression checks for settings/runtime-state separation.

Usage:
    python tests/test_runtime_state_config_boundary.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.settings import (
    get_host,
    get_port,
    get_runtime_state_path,
    get_screen_size,
    get_viewport_size,
    set_host_and_port,
    set_runtime_host_and_port,
    set_screen_size,
    set_viewport_size,
)


def run_checks() -> None:
    original_runtime_state_path = os.environ.get("JARVIS_RUNTIME_STATE_PATH")
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-settings-test-") as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            runtime_state_path = Path(temp_dir) / "runtime_state.json"
            os.environ["JARVIS_RUNTIME_STATE_PATH"] = str(runtime_state_path)

            static_settings = {
                "host": "127.0.0.1",
                "port": 8765,
                "screen_width": 800,
                "screen_height": 600,
                "viewport_width": 100,
                "viewport_height": 120,
                "rapid_response_model": "rapid-model",
                "jarvis_model": "jarvis-model",
            }
            settings_path.write_text(json.dumps(static_settings, indent=2), encoding="utf-8")
            settings_snapshot = settings_path.read_text(encoding="utf-8")

            host, port = set_host_and_port(str(settings_path))
            assert host == "127.0.0.1"
            assert isinstance(port, int) and port > 0
            assert settings_path.read_text(encoding="utf-8") == settings_snapshot, "set_host_and_port mutated static settings file"
            explicit_host, explicit_port = set_runtime_host_and_port("127.0.0.1", 9999, str(settings_path))
            assert explicit_host == "127.0.0.1"
            assert explicit_port == 9999
            assert settings_path.read_text(encoding="utf-8") == settings_snapshot, "set_runtime_host_and_port mutated static settings file"

            set_screen_size(1337, 733, str(settings_path))
            set_viewport_size(500, 300, str(settings_path))
            assert settings_path.read_text(encoding="utf-8") == settings_snapshot, "screen/viewport writes mutated static settings file"

            runtime_payload = json.loads(runtime_state_path.read_text(encoding="utf-8"))
            assert runtime_payload["host"] == "127.0.0.1"
            assert runtime_payload["port"] == 9999
            assert runtime_payload["screen_width"] == 1337
            assert runtime_payload["screen_height"] == 733
            assert runtime_payload["viewport_width"] == 500
            assert runtime_payload["viewport_height"] == 300

            assert get_host(str(settings_path)) == "127.0.0.1"
            assert get_port(str(settings_path)) == 9999
            assert get_screen_size(str(settings_path)) == (1337, 733)
            assert get_viewport_size(str(settings_path)) == (500, 300)
            assert get_runtime_state_path(str(settings_path)) == str(runtime_state_path.resolve())

            runtime_state_path.unlink()
            assert get_host(str(settings_path)) == "127.0.0.1"
            assert get_port(str(settings_path)) == 8765
            assert get_screen_size(str(settings_path)) == (800, 600)
            assert get_viewport_size(str(settings_path)) == (100, 120)
    finally:
        if original_runtime_state_path is None:
            os.environ.pop("JARVIS_RUNTIME_STATE_PATH", None)
        else:
            os.environ["JARVIS_RUNTIME_STATE_PATH"] = original_runtime_state_path


if __name__ == "__main__":
    run_checks()
    print("[test_runtime_state_config_boundary] All checks passed.")
