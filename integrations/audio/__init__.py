"""
Audio Integration - Text-to-Speech and Speech-to-Text capabilities.

Provides:
- tts_speak: Text-to-speech via ElevenLabs API
- stop_speaking: Stop current audio playback
- transcribe_audio_bytes: Speech-to-text for short voice command clips
"""
from integrations.audio.stt import transcribe_audio_bytes
from integrations.audio.tts import tts_speak, stop_speaking
