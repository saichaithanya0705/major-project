"""
Checks for assistant activity logging.

Usage:
    python tests/test_assistant_logging.py
"""

import json
import os
import sys
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.assistant_logging import get_assistant_log_path, log_assistant_event


def run_checks() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["JARVIS_LOG_DIR"] = tmpdir
        try:
            log_assistant_event(
                "request_started",
                request_id="req123",
                agent="browser",
                task="open example.com",
                message="Starting browser task",
                success=True,
                metadata={"step_index": 1},
            )
            log_assistant_event(
                "agent_step_failed",
                request_id="req123",
                agent="browser",
                task="open example.com",
                message="Browser task failed.",
                error="Timeout while loading page",
                success=False,
            )

            log_path = get_assistant_log_path()
            assert log_path.exists(), f"Expected log file at {log_path}"

            lines = log_path.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 2, lines

            first = json.loads(lines[0])
            second = json.loads(lines[1])

            assert first["event_type"] == "request_started", first
            assert first["request_id"] == "req123", first
            assert first["agent"] == "browser", first
            assert "timestamp" in first, first
            assert first["metadata"]["step_index"] == 1, first

            assert second["event_type"] == "agent_step_failed", second
            assert second["error"] == "Timeout while loading page", second
            assert second["success"] is False, second
        finally:
            os.environ.pop("JARVIS_LOG_DIR", None)


if __name__ == "__main__":
    run_checks()
    print("[test_assistant_logging] All checks passed.")
