"""
Regression checks for ElevenLabs TTS playback.

Usage:
    python tests/test_tts.py
"""

import os
import sys
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from integrations.audio import tts as tts_module


class _FakeAudioResponse:
    status_code = 200

    def iter_content(self, chunk_size):
        assert chunk_size == tts_module.CHUNK_SIZE
        yield b"audio-"
        yield b"bytes"


def test_tts_module_has_no_vlc_runtime_coupling() -> None:
    assert "vlc" not in tts_module.__dict__
    assert "VLC_AVAILABLE" not in tts_module.__dict__


def test_tts_speak_plays_elevenlabs_audio_without_vlc_gate() -> None:
    original_api_key = tts_module.ELEVENLABS_API_KEY
    original_api_base = tts_module.ELEVENLABS_API_BASE
    original_voice_id = tts_module.ELEVENLABS_VOICE_ID
    original_model_id = tts_module.ELEVENLABS_MODEL_ID
    original_output_format = tts_module.ELEVENLABS_OUTPUT_FORMAT
    original_audio_file = tts_module.AUDIO_FILE
    original_get_tts_active_bool = tts_module.get_tts_active_bool
    original_post = tts_module.requests.post
    original_play_audio = tts_module._play_audio
    missing = object()
    original_vlc_available = getattr(tts_module, "VLC_AVAILABLE", missing)
    captured = {}
    played = []

    def _fake_post(url, json=None, params=None, headers=None, stream=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["params"] = params
        captured["headers"] = headers
        captured["stream"] = stream
        captured["timeout"] = timeout
        return _FakeAudioResponse()

    def _fake_play_audio(audio_path):
        played.append(os.fspath(audio_path))

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "jarvis_audio.mp3")
        tts_module.ELEVENLABS_API_KEY = "test-key"
        tts_module.ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
        tts_module.ELEVENLABS_VOICE_ID = "voice-123"
        tts_module.ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
        tts_module.ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"
        tts_module.AUDIO_FILE = audio_path
        tts_module.get_tts_active_bool = lambda: (True,)
        tts_module.requests.post = _fake_post
        tts_module._play_audio = _fake_play_audio
        tts_module.VLC_AVAILABLE = False
        try:
            tts_module.tts_speak("Hello")
        finally:
            tts_module.ELEVENLABS_API_KEY = original_api_key
            tts_module.ELEVENLABS_API_BASE = original_api_base
            tts_module.ELEVENLABS_VOICE_ID = original_voice_id
            tts_module.ELEVENLABS_MODEL_ID = original_model_id
            tts_module.ELEVENLABS_OUTPUT_FORMAT = original_output_format
            tts_module.AUDIO_FILE = original_audio_file
            tts_module.get_tts_active_bool = original_get_tts_active_bool
            tts_module.requests.post = original_post
            tts_module._play_audio = original_play_audio
            if original_vlc_available is missing:
                delattr(tts_module, "VLC_AVAILABLE")
            else:
                tts_module.VLC_AVAILABLE = original_vlc_available

        with open(audio_path, "rb") as audio_file:
            assert audio_file.read() == b"audio-bytes"

    assert played == [audio_path], played
    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-123", captured
    assert captured["headers"]["xi-api-key"] == "test-key", captured
    assert captured["params"] == {"output_format": "mp3_44100_128"}, captured
    assert captured["stream"] is True, captured
    assert captured["timeout"] == 45, captured
    assert captured["json"]["text"] == "Hello", captured


def run_checks() -> None:
    test_tts_module_has_no_vlc_runtime_coupling()
    test_tts_speak_plays_elevenlabs_audio_without_vlc_gate()


if __name__ == "__main__":
    run_checks()
    print("[test_tts] All checks passed.")
