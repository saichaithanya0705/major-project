"""
Checks for the voice-command capture and transcription path.

Usage:
    python tests/test_voice_command_flow.py
"""

import asyncio
import base64
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from integrations.audio import stt as stt_module
from ui.server import VisualizationServer


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, message):
        self.sent.append(json.loads(message))


async def test_server_voice_transcription_success() -> None:
    observed = {}

    async def _fake_transcribe(audio_bytes, mime_type, filename):
        observed["audio_bytes"] = audio_bytes
        observed["mime_type"] = mime_type
        observed["filename"] = filename
        return "minimize the codex app"

    server = VisualizationServer(on_transcribe_audio=_fake_transcribe)
    websocket = _FakeWebSocket([
        json.dumps({
            "event": "transcribe_audio",
            "requestId": "voice_test_1",
            "mimeType": "audio/webm",
            "filename": "voice-command.webm",
            "audioBase64": base64.b64encode(b"voice bytes").decode("ascii"),
        })
    ])

    await server._handle_client(websocket)

    assert observed == {
        "audio_bytes": b"voice bytes",
        "mime_type": "audio/webm",
        "filename": "voice-command.webm",
    }, observed
    assert websocket.sent == [
        {
            "event": "voice_transcription_result",
            "requestId": "voice_test_1",
            "text": "minimize the codex app",
        }
    ], websocket.sent


async def test_server_voice_transcription_invalid_payload() -> None:
    server = VisualizationServer(on_transcribe_audio=lambda *_: "unused")
    websocket = _FakeWebSocket([
        json.dumps({
            "event": "transcribe_audio",
            "requestId": "voice_test_2",
            "mimeType": "audio/webm",
            "filename": "voice-command.webm",
            "audioBase64": "%%%not-base64%%%",
        })
    ])

    await server._handle_client(websocket)

    assert len(websocket.sent) == 1, websocket.sent
    payload = websocket.sent[0]
    assert payload["event"] == "voice_transcription_error", payload
    assert payload["requestId"] == "voice_test_2", payload
    assert "base64" in payload["error"].lower(), payload


def test_transcribe_audio_bytes_posts_expected_request() -> None:
    original_api_key = stt_module.ELEVENLABS_API_KEY
    original_api_base = stt_module.ELEVENLABS_API_BASE
    original_model_id = stt_module.ELEVENLABS_STT_MODEL_ID
    original_post = stt_module.requests.post
    captured = {}

    def _fake_post(url, headers=None, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["files"] = files
        captured["timeout"] = timeout
        return _FakeResponse(200, {"text": "  open settings  "})

    stt_module.ELEVENLABS_API_KEY = "test-key"
    stt_module.ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
    stt_module.ELEVENLABS_STT_MODEL_ID = "scribe_v2"
    stt_module.requests.post = _fake_post
    try:
        transcript = stt_module.transcribe_audio_bytes(
            b"voice-bytes",
            filename="voice-command.webm",
            mime_type="audio/webm",
        )
    finally:
        stt_module.ELEVENLABS_API_KEY = original_api_key
        stt_module.ELEVENLABS_API_BASE = original_api_base
        stt_module.ELEVENLABS_STT_MODEL_ID = original_model_id
        stt_module.requests.post = original_post

    assert transcript == "open settings", transcript
    assert captured["url"] == "https://api.elevenlabs.io/v1/speech-to-text", captured
    assert captured["headers"] == {"xi-api-key": "test-key"}, captured
    assert captured["data"]["model_id"] == "scribe_v2", captured
    assert captured["data"]["tag_audio_events"] == "false", captured
    assert captured["data"]["temperature"] == "0", captured
    assert captured["files"]["file"] == ("voice-command.webm", b"voice-bytes", "audio/webm"), captured
    assert captured["timeout"] == 45, captured


async def run_checks() -> None:
    await test_server_voice_transcription_success()
    await test_server_voice_transcription_invalid_payload()
    test_transcribe_audio_bytes_posts_expected_request()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_voice_command_flow] All checks passed.")
