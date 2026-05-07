from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DAY_SECONDS = 24 * 60 * 60

DEFAULT_TEMP_DIR_TTL_SECONDS = DAY_SECONDS
DEFAULT_BACKGROUND_LOG_TTL_SECONDS = DAY_SECONDS
DEFAULT_RUNTIME_STATE_TTL_SECONDS = 7 * DAY_SECONDS
DEFAULT_DEBUG_ARTIFACT_TTL_SECONDS = DAY_SECONDS
DEFAULT_LOG_TTL_SECONDS = 14 * DAY_SECONDS
DEFAULT_ASSISTANT_LOG_MAX_BYTES = 20 * 1024 * 1024


@dataclass
class CleanupReport:
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rotated: list[str] = field(default_factory=list)


def _resolve_path(path: str | os.PathLike[str] | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _path_key(path: str | os.PathLike[str] | Path) -> str:
    return os.path.normcase(os.path.normpath(str(_resolve_path(path))))


def _is_within(path: Path, root: Path) -> bool:
    path_key = _path_key(path)
    root_key = _path_key(root)
    try:
        return os.path.commonpath([path_key, root_key]) == root_key
    except ValueError:
        return False


def _is_older_than(path: Path, *, now: float, ttl_seconds: float) -> bool:
    try:
        age_seconds = now - path.stat().st_mtime
    except OSError:
        return False
    return age_seconds > ttl_seconds


def _delete_path(path: Path, *, root: Path, report: CleanupReport) -> None:
    resolved = _resolve_path(path)
    resolved_root = _resolve_path(root)
    if not _is_within(resolved, resolved_root):
        report.skipped.append(str(resolved))
        return

    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        report.deleted.append(str(resolved))
    except FileNotFoundError:
        pass
    except Exception as exc:
        report.errors.append(f"{resolved}: {type(exc).__name__}: {exc}")


def _cleanup_glob(
    *,
    root: Path,
    pattern: str,
    now: float,
    ttl_seconds: float,
    report: CleanupReport,
    directories: bool | None = None,
    active_paths: set[str] | None = None,
) -> None:
    if not root.exists() or not root.is_dir():
        return

    for path in root.glob(pattern):
        if directories is True and not path.is_dir():
            continue
        if directories is False and not path.is_file():
            continue

        if active_paths and _path_key(path) in active_paths:
            report.skipped.append(str(_resolve_path(path)))
            continue

        if _is_older_than(path, now=now, ttl_seconds=ttl_seconds):
            _delete_path(path, root=root, report=report)


def _remove_empty_dir(path: Path, *, root: Path, report: CleanupReport) -> None:
    if not path.exists() or not path.is_dir():
        return
    if not _is_within(path, root):
        report.skipped.append(str(_resolve_path(path)))
        return
    try:
        path.rmdir()
    except OSError:
        pass
    except Exception as exc:
        report.errors.append(f"{path}: {type(exc).__name__}: {exc}")


def _cleanup_temp_root(
    *,
    temp_root: Path,
    now: float,
    active_background_logs: set[str],
    report: CleanupReport,
    temp_dir_ttl_seconds: float,
    background_log_ttl_seconds: float,
    runtime_state_ttl_seconds: float,
    debug_artifact_ttl_seconds: float,
) -> None:
    if not temp_root.exists() or not temp_root.is_dir():
        return

    for pattern in (
        "browser_use_agent_*",
        "jarvis-browser-use-*",
        "jarvis-playwright-home-*",
        "browser-use-downloads-*",
    ):
        _cleanup_glob(
            root=temp_root,
            pattern=pattern,
            now=now,
            ttl_seconds=temp_dir_ttl_seconds,
            report=report,
            directories=True,
        )

    _cleanup_glob(
        root=temp_root,
        pattern="jarvis_cli_bg_*.log",
        now=now,
        ttl_seconds=background_log_ttl_seconds,
        report=report,
        directories=False,
        active_paths=active_background_logs,
    )
    _cleanup_glob(
        root=temp_root,
        pattern="jarvis_gemini_trusted_folders.json",
        now=now,
        ttl_seconds=runtime_state_ttl_seconds,
        report=report,
        directories=False,
    )
    _cleanup_glob(
        root=temp_root,
        pattern="cua_vision_bbox_debug_*.png",
        now=now,
        ttl_seconds=debug_artifact_ttl_seconds,
        report=report,
        directories=False,
    )
    _cleanup_glob(
        root=temp_root,
        pattern="cua_vision_bbox_debug_latest.png",
        now=now,
        ttl_seconds=debug_artifact_ttl_seconds,
        report=report,
        directories=False,
    )

    runtime_dir = temp_root / "jarvis-runtime"
    _cleanup_glob(
        root=runtime_dir,
        pattern="*.json",
        now=now,
        ttl_seconds=runtime_state_ttl_seconds,
        report=report,
        directories=False,
    )
    _remove_empty_dir(runtime_dir, root=temp_root, report=report)

    jarvis_temp = temp_root / "jarvis"
    for subdir, pattern in (
        ("tts", "*.mp3"),
        ("vision-artifact-images", "*.png"),
    ):
        generated_dir = jarvis_temp / subdir
        _cleanup_glob(
            root=generated_dir,
            pattern=pattern,
            now=now,
            ttl_seconds=debug_artifact_ttl_seconds,
            report=report,
            directories=False,
        )
        _remove_empty_dir(generated_dir, root=temp_root, report=report)
    _remove_empty_dir(jarvis_temp, root=temp_root, report=report)


def _rotate_assistant_log(
    assistant_log: Path,
    *,
    now: float,
    max_bytes: int,
    report: CleanupReport,
) -> None:
    if max_bytes <= 0 or not assistant_log.exists() or not assistant_log.is_file():
        return

    try:
        if assistant_log.stat().st_size <= max_bytes:
            return
    except OSError:
        return

    timestamp = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    rotated = assistant_log.with_name(f"assistant_activity-{timestamp}.jsonl")
    counter = 1
    while rotated.exists():
        rotated = assistant_log.with_name(f"assistant_activity-{timestamp}-{counter}.jsonl")
        counter += 1

    try:
        assistant_log.replace(rotated)
        assistant_log.touch()
        report.rotated.append(f"{assistant_log} -> {rotated}")
    except Exception as exc:
        report.errors.append(f"{assistant_log}: {type(exc).__name__}: {exc}")


def _cleanup_log_dir(
    *,
    log_dir: Path,
    now: float,
    log_ttl_seconds: float,
    assistant_log_max_bytes: int,
    report: CleanupReport,
) -> None:
    if not log_dir.exists() or not log_dir.is_dir():
        return

    for pattern in (
        "server-*.log",
        "ui-*.log",
        "electron-ui-*.log",
        "assistant_activity-*.jsonl",
    ):
        _cleanup_glob(
            root=log_dir,
            pattern=pattern,
            now=now,
            ttl_seconds=log_ttl_seconds,
            report=report,
            directories=False,
        )

    _rotate_assistant_log(
        log_dir / "assistant_activity.jsonl",
        now=now,
        max_bytes=assistant_log_max_bytes,
        report=report,
    )


def cleanup_runtime_artifacts(
    *,
    project_root: str | os.PathLike[str] | Path | None = None,
    temp_root: str | os.PathLike[str] | Path | None = None,
    log_dir: str | os.PathLike[str] | Path | None = None,
    active_background_logs: Iterable[str | os.PathLike[str] | Path] | None = None,
    now: float | None = None,
    temp_dir_ttl_seconds: float = DEFAULT_TEMP_DIR_TTL_SECONDS,
    background_log_ttl_seconds: float = DEFAULT_BACKGROUND_LOG_TTL_SECONDS,
    runtime_state_ttl_seconds: float = DEFAULT_RUNTIME_STATE_TTL_SECONDS,
    debug_artifact_ttl_seconds: float = DEFAULT_DEBUG_ARTIFACT_TTL_SECONDS,
    log_ttl_seconds: float = DEFAULT_LOG_TTL_SECONDS,
    assistant_log_max_bytes: int = DEFAULT_ASSISTANT_LOG_MAX_BYTES,
) -> CleanupReport:
    """
    Delete stale generated files from known runtime locations.

    This deliberately works from allowlisted directories and filename patterns.
    User-created files, downloads, and current chat session JSON are outside this
    cleanup surface.
    """
    report = CleanupReport()
    current_time = time.time() if now is None else float(now)
    active_logs = {_path_key(path) for path in (active_background_logs or [])}

    explicit_temp_root = temp_root is not None
    temp_roots = [_resolve_path(temp_root or tempfile.gettempdir())]
    if not explicit_temp_root:
        slash_tmp = Path("/tmp")
        if slash_tmp.exists() and _path_key(slash_tmp) != _path_key(temp_roots[0]):
            temp_roots.append(_resolve_path(slash_tmp))

    for root in temp_roots:
        _cleanup_temp_root(
            temp_root=root,
            now=current_time,
            active_background_logs=active_logs,
            report=report,
            temp_dir_ttl_seconds=temp_dir_ttl_seconds,
            background_log_ttl_seconds=background_log_ttl_seconds,
            runtime_state_ttl_seconds=runtime_state_ttl_seconds,
            debug_artifact_ttl_seconds=debug_artifact_ttl_seconds,
        )

    resolved_log_dir: Path | None = None
    if log_dir is not None:
        resolved_log_dir = _resolve_path(log_dir)
    elif project_root is not None:
        resolved_log_dir = _resolve_path(project_root) / "logs"

    if resolved_log_dir is not None:
        _cleanup_log_dir(
            log_dir=resolved_log_dir,
            now=current_time,
            log_ttl_seconds=log_ttl_seconds,
            assistant_log_max_bytes=assistant_log_max_bytes,
            report=report,
        )

    return report
