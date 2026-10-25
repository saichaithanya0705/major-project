"""
Long-term memory commands and recall; offline speech provider selection.
"""

from __future__ import annotations

import json
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import integrations.audio.local_voice as local_voice  # noqa: E402
import integrations.audio.stt as stt  # noqa: E402
import integrations.audio.tts as tts  # noqa: E402
from core.memory import MemoryStore, handle_memory_command, memory_prompt_block  # noqa: E402
from models.request_entrypoint import run_gemini_request  # noqa: E402


@pytest.fixture
def store(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite3")


# Memory ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "stored"),
    [
        ("remember that my name is Sai", "my name is Sai"),
        ("Remember: I prefer dark mode in every app.", "I prefer dark mode in every app"),
        ("Jarvis, remember my college is JNTU Hyderabad", "my college is JNTU Hyderabad"),
        ("please note that my laptop has 4 GB VRAM", "my laptop has 4 GB VRAM"),
    ],
)
def test_remember_commands_store_the_fact(text, stored, store) -> None:
    assert handle_memory_command(text, store) == f"Got it. I'll remember: {stored}"
    assert [memory.text for memory in store.all()] == [stored]


@pytest.mark.parametrize(
    "text",
    [
        "do you remember the movie Inception?",
        "remember when we fixed the router bug?",
        "what is the capital of France",
        "I can't remember my password",
        "make a presentation about memory",
    ],
)
def test_ordinary_requests_are_not_memory_commands(text, store) -> None:
    assert handle_memory_command(text, store) is None
    assert store.all() == []


def test_list_forget_and_clear(store) -> None:
    assert "not remembering anything yet" in handle_memory_command("what do you remember?", store)
    handle_memory_command("remember that my name is Sai", store)
    handle_memory_command("remember that my sister's birthday is 12 March", store)
    handle_memory_command("remember that my name is Sai", store)  # duplicate is ignored

    assert handle_memory_command("show my memories", store) == (
        "Here's what I remember:\n- my name is Sai\n- my sister's birthday is 12 March"
    )
    assert handle_memory_command("forget my sister's birthday", store) == "Forgotten:\n- my sister's birthday is 12 March"
    assert handle_memory_command("forget the moon landing", store) == "I couldn't find anything like that in my memory."
    assert handle_memory_command("forget everything you remember", store) == "Done. I forgot 1 thing."
    assert store.all() == []


def test_recall_ranks_relevant_memories_and_builds_prompt_block(store) -> None:
    for fact in ("my name is Sai", "I study at JNTU Hyderabad", "my laptop is an HP Pavilion with 4 GB VRAM", "I like filter coffee"):
        store.remember(fact)

    relevant = [memory.text for memory in store.relevant("what laptop do I have?")]
    assert relevant[0] == "my laptop is an HP Pavilion with 4 GB VRAM"
    assert store.relevant("hello") == []

    block = memory_prompt_block(store, "write my name in the email signature")
    assert block.startswith("\n# Things the user asked you to remember\n")
    assert "- my name is Sai" in block and "coffee" not in block
    assert memory_prompt_block(store, "open notepad") == ""


def test_memory_path_comes_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_MEMORY_PATH", str(tmp_path / "nested" / "mem.db"))
    MemoryStore().remember("x is y")
    assert (tmp_path / "nested" / "mem.db").exists()


async def test_request_entrypoint_answers_memory_commands_without_the_model() -> None:
    replies, deps_calls, events = [], [], []

    async def _send(text):
        replies.append(text)

    def _build_deps(**kwargs):
        deps_calls.append(kwargs)
        return "deps"

    async def _run(**kwargs):
        events.append("routed")

    common = dict(
        rapid_response_model="m", jarvis_model="j", session_id=None,
        new_request_id=lambda: "req-1",
        log_assistant_event=lambda *args, **kwargs: events.append(args[0]),
        clean_text=lambda value, fallback, max_len=None: str(value or fallback),
        rapid_session_state=SimpleNamespace(normalize_session_id=lambda session_id=None: "s"),
        build_rapid_orchestrator_deps=_build_deps, run_rapid_request=_run, model_factory=object,
        run_routed_agent_step=None, get_stored_screenshot=lambda: None, prepare_vision_screenshot=None,
        max_router_chain_steps=6, repeated_step_limit=3,
        handle_local_command=lambda text: "Got it." if text.startswith("remember") else None,
        send_local_reply=_send,
        build_memory_block=lambda text: f"<memories for {text}>",
    )

    await run_gemini_request(user_prompt="remember that I like tea", **common)
    assert replies == ["Got it."] and deps_calls == [] and "routed" not in events

    await run_gemini_request(user_prompt="what should I drink?", **common)
    assert deps_calls[0]["memory_block"] == "<memories for what should I drink?>"
    assert events[-1] == "routed"


# Speech-to-text ------------------------------------------------------------------------------


def test_stt_provider_selection(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_STT_PROVIDER", raising=False)
    monkeypatch.setattr(stt, "ELEVENLABS_API_KEY", "")
    assert stt.stt_provider() == "whisper"
    monkeypatch.setattr(stt, "ELEVENLABS_API_KEY", "key")
    assert stt.stt_provider() == "elevenlabs"
    monkeypatch.setenv("JARVIS_STT_PROVIDER", "whisper")
    assert stt.stt_provider() == "whisper"
    monkeypatch.setenv("JARVIS_STT_PROVIDER", "siri")
    with pytest.raises(ValueError):
        stt.stt_provider()


def test_local_whisper_transcribes_the_uploaded_clip(monkeypatch) -> None:
    seen = {}

    class _FakeWhisper:
        def transcribe(self, path, **kwargs):
            seen["suffix"] = Path(path).suffix
            seen["bytes"] = Path(path).read_bytes()
            seen["kwargs"] = kwargs
            return iter([SimpleNamespace(text=" open notepad "), SimpleNamespace(text="please ")]), None

    monkeypatch.setattr(local_voice, "_whisper_model", _FakeWhisper())
    monkeypatch.setenv("JARVIS_STT_PROVIDER", "whisper")
    monkeypatch.setenv("JARVIS_WHISPER_LANGUAGE", "en")

    assert stt.transcribe_audio_bytes(b"opus-bytes", filename="voice.webm") == "open notepad please"
    assert seen == {"suffix": ".webm", "bytes": b"opus-bytes", "kwargs": {"language": "en", "beam_size": 1, "vad_filter": True}}
    with pytest.raises(ValueError):
        stt.transcribe_audio_bytes(b"")


# Text-to-speech -------------------------------------------------------------------------------


def test_tts_provider_selection(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("JARVIS_TTS_PROVIDER", raising=False)
    monkeypatch.delenv("JARVIS_PIPER_VOICE", raising=False)
    monkeypatch.setattr(tts, "ELEVENLABS_API_KEY", "")
    assert tts.tts_provider() == "system"
    voice = tmp_path / "en_US-amy-medium.onnx"
    voice.write_bytes(b"onnx")
    monkeypatch.setenv("JARVIS_PIPER_VOICE", str(voice))
    assert tts.tts_provider() == "piper"
    monkeypatch.setattr(tts, "ELEVENLABS_API_KEY", "key")
    assert tts.tts_provider() == "elevenlabs"
    monkeypatch.setenv("JARVIS_TTS_PROVIDER", "off")
    assert tts.tts_provider() == "off"


def test_piper_writes_a_wav_with_the_loaded_voice(monkeypatch, tmp_path) -> None:
    voice_file = tmp_path / "voice.onnx"
    voice_file.write_bytes(b"onnx")
    monkeypatch.setenv("JARVIS_PIPER_VOICE", str(voice_file))

    class _FakeVoice:
        def synthesize_wav(self, text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\x00\x00" * len(text))

    monkeypatch.setattr(local_voice, "_piper_voice", _FakeVoice())
    out = local_voice.synthesize_with_piper("hello", tmp_path / "out" / "speech.wav")
    with wave.open(str(out)) as wav:
        assert (wav.getframerate(), wav.getnframes()) == (22050, 5)


@pytest.mark.parametrize("channel", ["stdin", "env"])
def test_system_voice_passes_text_without_a_shell(channel, monkeypatch, tmp_path) -> None:
    captured = tmp_path / "spoken.json"
    script = (
        "import json, os, sys; "
        f"json.dump({{'stdin': sys.stdin.read() if {channel == 'stdin'!r} else '', 'env': os.environ.get('JARVIS_TTS_TEXT', '')}}, "
        f"open({str(captured)!r}, 'w'))"
    )
    argv = [sys.executable, "-c", script]
    monkeypatch.setattr(tts, "system_speech_command", lambda: (argv, channel))
    text = 'Done & dusted; "rm -rf /" | $(whoami) %PATH%'

    tts._speak_with_system_voice(text)

    spoken = json.loads(captured.read_text())
    assert spoken[channel] == text
    assert tts._audio_process is None


def test_windows_system_voice_reads_text_from_the_environment() -> None:
    # The spoken text never becomes part of the PowerShell command itself.
    assert local_voice.WINDOWS_SPEECH_SCRIPT.endswith("$voice.Speak($env:JARVIS_TTS_TEXT)")
