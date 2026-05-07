"""
Text-to-Speech Integration - ElevenLabs API.

Provides text-to-speech capabilities for verbal feedback to users.
"""
import os
import requests
import shutil
import subprocess
import sys
import tempfile
import threading
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from core.settings import get_tts_active_bool

logging.basicConfig(level=logging.ERROR)

load_dotenv()

# Configuration
CHUNK_SIZE = 1024
ELEVENLABS_API_BASE = str(os.getenv("ELEVENLABS_API_BASE") or "https://api.elevenlabs.io").rstrip("/")
ELEVENLABS_URL = str(os.getenv("ELEVENLABS_URL") or "").strip()
ELEVENLABS_API_KEY = str(os.getenv("ELEVENLABS_API_KEY") or "").strip()
ELEVENLABS_VOICE_ID = str(os.getenv("ELEVENLABS_VOICE_ID") or "JBFqnCBsd6RMkjVDRZzb").strip()
ELEVENLABS_MODEL_ID = str(os.getenv("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2").strip()
ELEVENLABS_OUTPUT_FORMAT = str(os.getenv("ELEVENLABS_OUTPUT_FORMAT") or "mp3_44100_128").strip()

# Audio output file. The default basename is resolved into the system temp
# directory so routine speech does not leave project-root artifacts behind.
DEFAULT_AUDIO_FILE = "jarvis_audio.mp3"
AUDIO_FILE = str(os.getenv("JARVIS_TTS_AUDIO_FILE") or DEFAULT_AUDIO_FILE)

# Audio playback subprocess (global for stop functionality)
_audio_process = None
_audio_process_lock = threading.Lock()


def _get_headers():
    """Get the API headers for ElevenLabs."""
    return {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }


def _get_tts_url() -> str:
    """
    Resolve TTS endpoint URL.

    Current ElevenLabs docs support API-key auth with voice-id path:
    POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
    """
    if ELEVENLABS_URL:
        return ELEVENLABS_URL

    if not ELEVENLABS_VOICE_ID:
        raise ValueError("ELEVENLABS_VOICE_ID is required when ELEVENLABS_URL is not set")

    return f"{ELEVENLABS_API_BASE}/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"


def _build_playback_command(audio_path: Path) -> list[str] | None:
    """Return an available command that can play the generated audio."""
    if os.name == "nt":
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return None

        script = r"""
param([string]$AudioPath)
Add-Type -AssemblyName PresentationCore
$resolved = (Resolve-Path -LiteralPath $AudioPath).Path
$player = New-Object System.Windows.Media.MediaPlayer
$player.Open([System.Uri]::new($resolved))
for ($i = 0; $i -lt 100 -and -not $player.NaturalDuration.HasTimeSpan; $i++) {
    Start-Sleep -Milliseconds 50
}
$player.Play()
if ($player.NaturalDuration.HasTimeSpan) {
    Start-Sleep -Milliseconds ([Math]::Ceiling($player.NaturalDuration.TimeSpan.TotalMilliseconds) + 250)
} else {
    Start-Sleep -Seconds 5
}
$player.Stop()
$player.Close()
"""
        return [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
            str(audio_path),
        ]

    if sys.platform == "darwin":
        afplay = shutil.which("afplay")
        if afplay:
            return [afplay, str(audio_path)]

    for command_name, extra_args in (
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
        ("mpg123", ["-q"]),
        ("mpv", ["--really-quiet", "--no-terminal"]),
    ):
        command = shutil.which(command_name)
        if command:
            return [command, *extra_args, str(audio_path)]

    return None


def _resolve_audio_output_path() -> Path:
    configured = Path(AUDIO_FILE)
    if str(AUDIO_FILE).strip() and configured != Path(DEFAULT_AUDIO_FILE):
        return configured.expanduser()

    output_dir = Path(tempfile.gettempdir()) / "jarvis" / "tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"jarvis_audio_{os.getpid()}_{int(time.time() * 1000)}.mp3"


def _play_audio(audio_path) -> bool:
    """Play a generated ElevenLabs audio file."""
    global _audio_process
    resolved_audio_path = Path(audio_path).resolve()
    command = _build_playback_command(resolved_audio_path)
    if not command:
        print(f"[TTS] Audio saved to {resolved_audio_path}, but no supported playback command was found")
        return False

    process = None
    played = False
    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            command,
            **popen_kwargs,
        )
        with _audio_process_lock:
            _audio_process = process
        process.wait()
        played = process.returncode == 0
    except OSError as e:
        print(f"[TTS] Audio playback failed: {e}")
    finally:
        if process is not None:
            with _audio_process_lock:
                if _audio_process is process:
                    _audio_process = None
    return played


def _preprocess_text(text: str) -> str:
    """Preprocess text to handle escape characters."""
    text = text.replace("\'", "'")
    text = text.replace("\\'", "\'")
    text = text.replace('\\\\', '\\')
    text = text.replace('\\n', '\n')
    text = text.replace('\\r', '\r')
    text = text.replace('\\t', '\t')
    text = text.replace('\\b', '\b')
    text = text.replace('\\f', '\f')
    return text


def tts_speak(text: str):
    """Verbally speak to the user using text-to-speech.

    Args:
        text: The text to be spoken to the user.
    """
    if not get_tts_active_bool()[0]:
        return

    text = _preprocess_text(text)
    print(f'[TTS] Speaking: {text}')

    # If ElevenLabs is not configured, just print
    if not ELEVENLABS_API_KEY:
        print("[TTS] ElevenLabs not configured - skipping audio")
        return

    # Prepare the API request
    data = {
        "text": text,
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }

    params = {}
    if ELEVENLABS_OUTPUT_FORMAT:
        params["output_format"] = ELEVENLABS_OUTPUT_FORMAT

    try:
        url = _get_tts_url()
    except ValueError as e:
        print(f"[TTS] Config error: {e}")
        return

    try:
        response = requests.post(
            url,
            json=data,
            params=params,
            headers=_get_headers(),
            stream=True,
            timeout=45
        )

        if response.status_code == 200:
            audio_path = _resolve_audio_output_path()
            audio_path.parent.mkdir(parents=True, exist_ok=True)

            # Save the audio file
            with open(audio_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            played = bool(_play_audio(audio_path))
            if played:
                try:
                    audio_path.unlink()
                except OSError:
                    pass
        else:
            print(f'[TTS] API call failed with status {response.status_code}')

    except requests.exceptions.RequestException as e:
        print(f'[TTS] Request failed: {e}')


def stop_speaking():
    """Stop the currently playing audio."""
    global _audio_process
    with _audio_process_lock:
        process = _audio_process
        _audio_process = None

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
