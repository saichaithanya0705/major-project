"""
Speech-to-Text Integration - ElevenLabs API.

Provides short-form transcription for voice command capture in the chat UI.
"""
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_BASE = str(os.getenv("ELEVENLABS_API_BASE") or "https://api.elevenlabs.io").rstrip("/")
ELEVENLABS_API_KEY = str(os.getenv("ELEVENLABS_API_KEY") or "").strip()
ELEVENLABS_STT_MODEL_ID = str(os.getenv("ELEVENLABS_STT_MODEL_ID") or "scribe_v2").strip()


def _get_headers() -> dict[str, str]:
    return {
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

    try:
        response = requests.post(
            _get_stt_url(),
            headers=_get_headers(),
            data=data,
            files=files,
            timeout=45,
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"ElevenLabs STT request failed: {exc}") from exc

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
