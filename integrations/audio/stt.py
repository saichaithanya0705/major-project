"""
Speech-to-Text Integration - ElevenLabs API.

Provides short-form transcription for voice command capture in the chat UI.
"""
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()


def _get_env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or default).strip())
    except (TypeError, ValueError):
        return default


def _get_env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name) or default).strip())
    except (TypeError, ValueError):
        return default


ELEVENLABS_API_BASE = str(os.getenv("ELEVENLABS_API_BASE") or "https://api.elevenlabs.io").rstrip("/")
ELEVENLABS_API_KEY = str(os.getenv("ELEVENLABS_API_KEY") or "").strip()
ELEVENLABS_STT_MODEL_ID = str(os.getenv("ELEVENLABS_STT_MODEL_ID") or "scribe_v2").strip()
ELEVENLABS_STT_RETRIES = max(0, _get_env_int("ELEVENLABS_STT_RETRIES", 2))
ELEVENLABS_STT_CONNECT_TIMEOUT = max(1.0, _get_env_float("ELEVENLABS_STT_CONNECT_TIMEOUT", 10.0))
ELEVENLABS_STT_READ_TIMEOUT = max(1.0, _get_env_float("ELEVENLABS_STT_READ_TIMEOUT", 90.0))
ELEVENLABS_STT_USER_AGENT = "JARVIS/1.0 ElevenLabs-STT"


def _get_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": ELEVENLABS_STT_USER_AGENT,
        "xi-api-key": ELEVENLABS_API_KEY,
    }


def _get_stt_url() -> str:
    return f"{ELEVENLABS_API_BASE}/v1/speech-to-text"


def _extract_transcript_text(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return " ".join(text.split())

    transcripts = payload.get("transcripts")
    if isinstance(transcripts, list):
        merged = " ".join(
            str(item.get("text") or "").strip()
            for item in transcripts
            if isinstance(item, dict)
        ).strip()
        if merged:
            return " ".join(merged.split())

    raise RuntimeError("ElevenLabs returned no transcript text.")


def _is_retryable_request_error(exc: requests.exceptions.RequestException) -> bool:
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.Timeout,
        ),
    )


def _retry_delay_seconds(attempt: int) -> float:
    return min(0.75 * (2 ** max(0, attempt - 1)), 3.0)


def _post_stt_request(data: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> requests.Response:
    last_error: requests.exceptions.RequestException | None = None
    max_attempts = ELEVENLABS_STT_RETRIES + 1

    for attempt in range(1, max_attempts + 1):
        try:
            return requests.post(
                _get_stt_url(),
                headers=_get_headers(),
                data=data,
                files=files,
                timeout=(ELEVENLABS_STT_CONNECT_TIMEOUT, ELEVENLABS_STT_READ_TIMEOUT),
            )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable_request_error(exc):
                break
            time.sleep(_retry_delay_seconds(attempt))

    detail = str(last_error) if last_error else "unknown transport error"
    if len(detail) > 220:
        detail = f"{detail[:217].rstrip()}..."
    raise RuntimeError(
        "ElevenLabs STT request failed after "
        f"{max_attempts} attempt{'s' if max_attempts != 1 else ''}: {detail}"
    ) from last_error


def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    filename: str = "voice-command.webm",
    mime_type: str = "audio/webm",
) -> str:
    """Transcribe a recorded audio clip with ElevenLabs Speech-to-Text."""
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY is not configured.")
    if not audio_bytes:
        raise ValueError("Recorded audio was empty.")

    data = {
        "model_id": ELEVENLABS_STT_MODEL_ID,
        "tag_audio_events": "false",
        "temperature": "0",
    }
    files = {
        "file": (
            filename or "voice-command.webm",
            audio_bytes,
            mime_type or "application/octet-stream",
        ),
    }

    response = _post_stt_request(data, files)

    if response.status_code != 200:
        detail = response.text.strip()
        if len(detail) > 240:
            detail = f"{detail[:237].rstrip()}..."
        raise RuntimeError(
            f"ElevenLabs STT failed with status {response.status_code}: {detail or 'no response body'}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("ElevenLabs STT returned invalid JSON.") from exc

    return _extract_transcript_text(payload)
