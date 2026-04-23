from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

_LOG_LOCK = Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_assistant_log_dir() -> Path:
    override = (os.getenv("JARVIS_LOG_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _project_root() / "logs"


def get_assistant_log_path() -> Path:
    log_dir = get_assistant_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "assistant_activity.jsonl"


def new_assistant_request_id() -> str:
    return uuid.uuid4().hex[:12]


def _coerce_text(value: Any, max_len: int = 4000) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def log_assistant_event(
    event_type: str,
    *,
    request_id: str,
    agent: str = "",
    task: str = "",
    message: str = "",
    error: str = "",
    success: Optional[bool] = None,
    duration_seconds: Optional[float] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": _coerce_text(event_type, max_len=120),
        "request_id": _coerce_text(request_id, max_len=120),
    }

    if agent:
        payload["agent"] = _coerce_text(agent, max_len=120)
    if task:
        payload["task"] = _coerce_text(task)
    if message:
        payload["message"] = _coerce_text(message)
    if error:
        payload["error"] = _coerce_text(error)
    if success is not None:
        payload["success"] = bool(success)
    if duration_seconds is not None:
        payload["duration_seconds"] = round(float(duration_seconds), 3)
    if metadata:
        payload["metadata"] = metadata

    log_path = get_assistant_log_path()
    line = json.dumps(payload, ensure_ascii=True)

    with _LOG_LOCK:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
