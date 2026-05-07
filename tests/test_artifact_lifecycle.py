"""
Checks for generated artifact cleanup boundaries.

Usage:
    python tests/test_artifact_lifecycle.py
"""

import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from core.artifact_lifecycle import cleanup_runtime_artifacts


DAY_SECONDS = 24 * 60 * 60


def _touch_file(path: Path, *, mtime: float, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _touch_dir(path: Path, *, mtime: float) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    child = path / "payload.txt"
    child.write_text("generated", encoding="utf-8")
    os.utime(child, (mtime, mtime))
    os.utime(path, (mtime, mtime))
    return path


def test_cleanup_runtime_artifacts_removes_only_known_stale_temp_artifacts(tmp_path: Path) -> None:
    now = 2_000_000.0
    old = now - (3 * DAY_SECONDS)
    recent = now - (60 * 60)
    temp_root = tmp_path / "temp"
    project_root = tmp_path / "project"

    stale_browser_run = _touch_dir(temp_root / "browser_use_agent_abc_20260101", mtime=old)
    stale_browser_profile = _touch_dir(temp_root / "jarvis-browser-use-old", mtime=old)
    recent_browser_profile = _touch_dir(temp_root / "jarvis-browser-use-recent", mtime=recent)
    unrelated_user_dir = _touch_dir(temp_root / "user-downloads", mtime=old)

    stale_cli_log = _touch_file(temp_root / "jarvis_cli_bg_deadbeef.log", mtime=old)
    active_cli_log = _touch_file(temp_root / "jarvis_cli_bg_active.log", mtime=old)
    stale_debug = _touch_file(temp_root / "cua_vision_bbox_debug_20260506.png", mtime=old)
    stale_tts = _touch_file(temp_root / "jarvis" / "tts" / "old.mp3", mtime=old)

    stale_runtime = _touch_file(temp_root / "jarvis-runtime" / "old-project.json", mtime=now - (10 * DAY_SECONDS))
    recent_runtime = _touch_file(temp_root / "jarvis-runtime" / "recent-project.json", mtime=recent)

    report = cleanup_runtime_artifacts(
        project_root=project_root,
        temp_root=temp_root,
        now=now,
        active_background_logs=[active_cli_log],
    )

    assert not stale_browser_run.exists()
    assert not stale_browser_profile.exists()
    assert recent_browser_profile.exists()
    assert unrelated_user_dir.exists()
    assert not stale_cli_log.exists()
    assert active_cli_log.exists()
    assert not stale_debug.exists()
    assert not stale_tts.exists()
    assert not stale_runtime.exists()
    assert recent_runtime.exists()
    assert any("browser_use_agent_abc_20260101" in item for item in report.deleted)


def test_cleanup_runtime_artifacts_rotates_assistant_log_and_prunes_old_generated_logs(tmp_path: Path) -> None:
    now = 2_000_000.0
    old = now - (30 * DAY_SECONDS)
    recent = now - (60 * 60)
    project_root = tmp_path / "project"
    log_dir = project_root / "logs"
    temp_root = tmp_path / "temp"

    old_server_log = _touch_file(log_dir / "server-20250101.log", mtime=old)
    recent_ui_log = _touch_file(log_dir / "ui-20260506.log", mtime=recent)
    assistant_log = _touch_file(log_dir / "assistant_activity.jsonl", mtime=recent, content="x" * 128)

    cleanup_runtime_artifacts(
        project_root=project_root,
        temp_root=temp_root,
        now=now,
        assistant_log_max_bytes=64,
    )

    assert not old_server_log.exists()
    assert recent_ui_log.exists()
    assert assistant_log.exists()
    assert assistant_log.read_text(encoding="utf-8") == ""

    rotated_logs = list(log_dir.glob("assistant_activity-*.jsonl"))
    assert len(rotated_logs) == 1
    assert rotated_logs[0].read_text(encoding="utf-8") == "x" * 128


def run_checks() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        test_cleanup_runtime_artifacts_removes_only_known_stale_temp_artifacts(Path(tmpdir) / "case1")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_cleanup_runtime_artifacts_rotates_assistant_log_and_prunes_old_generated_logs(Path(tmpdir) / "case2")


if __name__ == "__main__":
    run_checks()
    print("[test_artifact_lifecycle] All checks passed.")
