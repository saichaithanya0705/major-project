"""
Offline speech: faster-whisper for speech-to-text, Piper or the OS voice for text-to-speech.

- Whisper runs on the CPU by default (``JARVIS_WHISPER_DEVICE``) so it does not
  compete with the Ollama model for a small GPU. The model
  (``JARVIS_WHISPER_MODEL``, default ``base``) downloads once on first use.
- Piper needs a voice file (``JARVIS_PIPER_VOICE``, a ``.onnx`` from
  https://huggingface.co/rhasspy/piper-voices with its ``.onnx.json`` beside it).
- The OS voice needs nothing: Windows SAPI, macOS ``say``, or espeak on Linux.
  Text is passed on stdin or through an environment variable, never inside a
  shell command.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

_whisper_model: Any = None
_whisper_lock = threading.Lock()
_piper_voice: Any = None
_piper_lock = threading.Lock()

WINDOWS_SPEECH_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$voice.Speak($env:JARVIS_TTS_TEXT)"
)


def _whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Local speech-to-text needs faster-whisper: pip install faster-whisper") from exc
            _whisper_model = WhisperModel(
                os.getenv("JARVIS_WHISPER_MODEL", "base").strip() or "base",
                device=os.getenv("JARVIS_WHISPER_DEVICE", "cpu").strip() or "cpu",
                compute_type=os.getenv("JARVIS_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8",
            )
        return _whisper_model


def transcribe_locally(audio_bytes: bytes, *, filename: str = "voice-command.webm") -> str:
    suffix = Path(filename or "").suffix or ".webm"
    with tempfile.TemporaryDirectory(prefix="jarvis-stt-") as scratch:
        audio_path = Path(scratch) / f"clip{suffix}"
        audio_path.write_bytes(audio_bytes)
        segments, _info = _whisper().transcribe(
            str(audio_path),
            language=os.getenv("JARVIS_WHISPER_LANGUAGE", "").strip() or None,
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def piper_voice_path() -> Path | None:
    configured = os.getenv("JARVIS_PIPER_VOICE", "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser()
    return path if path.is_file() else None


def synthesize_with_piper(text: str, output_path: Path) -> Path:
    global _piper_voice
    voice_path = piper_voice_path()
    if voice_path is None:
        raise RuntimeError("JARVIS_PIPER_VOICE does not point to a Piper .onnx voice file.")
    with _piper_lock:
        if _piper_voice is None:
            try:
                from piper import PiperVoice
            except ImportError as exc:
                raise RuntimeError("Piper voices need piper-tts: pip install piper-tts") from exc
            _piper_voice = PiperVoice.load(str(voice_path))
        voice = _piper_voice
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return output_path


def system_speech_command() -> tuple[list[str], str] | None:
    """(argv, how text is passed: "env" or "stdin") for the OS speech engine, if any."""
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            return [powershell, "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SPEECH_SCRIPT], "env"
        return None
    if sys.platform == "darwin" and shutil.which("say"):
        return [shutil.which("say"), "-f", "-"], "stdin"
    for name in ("espeak-ng", "espeak"):
        path = shutil.which(name)
        if path:
            return [path, "--stdin"], "stdin"
    return None
