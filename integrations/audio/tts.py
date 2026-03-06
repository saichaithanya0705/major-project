"""
Text-to-Speech Integration - ElevenLabs API.

Provides text-to-speech capabilities for verbal feedback to users.
"""
import os
import requests
import threading
import time
import logging

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

# Audio output file
AUDIO_FILE = "jarvis_audio.mp3"

# Audio player instance (global for stop functionality)
_audio_player = None

# Check if VLC python bindings and native runtime are available.
# On Windows, python-vlc may import successfully but still fail when libvlc.dll
# is missing. We treat any import/runtime exception as "VLC unavailable".
try:
    import vlc
    VLC_AVAILABLE = True
except Exception as exc:
    vlc = None
    VLC_AVAILABLE = False
    print(f"[TTS] VLC unavailable ({type(exc).__name__}: {exc}) - TTS will print to console only")


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


def _play_audio():
    """Internal function to play the audio file."""
    global _audio_player
    if not VLC_AVAILABLE:
        return

    _audio_player = vlc.MediaPlayer(AUDIO_FILE)
    _audio_player.play()
    # Wait for audio to finish
    time.sleep(_audio_player.get_length() / 1000 + 1)


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
            # Save the audio file
            with open(AUDIO_FILE, 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            # Play the audio in a separate thread
            if VLC_AVAILABLE:
                audio_thread = threading.Thread(target=_play_audio)
                audio_thread.start()
                audio_thread.join()
        else:
            print(f'[TTS] API call failed with status {response.status_code}')

    except requests.exceptions.RequestException as e:
        print(f'[TTS] Request failed: {e}')


def stop_speaking():
    """Stop the currently playing audio."""
    global _audio_player
    if _audio_player and VLC_AVAILABLE:
        _audio_player.stop()
        _audio_player = None
