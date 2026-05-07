"""
Security regression checks for the visualization websocket boundary.

Usage:
    python tests/test_ui_server_security.py
"""

import asyncio
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT_DIR))

from ui.server import VisualizationServer


class _FakeRequest:
    def __init__(self, path: str = "/", headers: dict[str, str] | None = None):
        self.path = path
        self.headers = headers or {}


class _FakeWebSocket:
    def __init__(
        self,
        messages,
        *,
        path: str = "/",
        headers: dict[str, str] | None = None,
    ):
        self._messages = list(messages)
        self.request = _FakeRequest(path, headers)
        self.sent = []
        self.closed = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def close(self, code=None, reason=None):
        self.closed = {"code": code, "reason": reason}


async def test_websocket_rejects_missing_auth_token() -> None:
    observed = []

    async def _fake_overlay_input(text, session_id=None):
        observed.append((text, session_id))

    server = VisualizationServer(
        auth_token="secret-token",
        on_overlay_input=_fake_overlay_input,
    )
    websocket = _FakeWebSocket([
        json.dumps({"event": "overlay_input", "text": "run the dangerous task"})
    ])

    await server._handle_client(websocket)

    assert observed == [], observed
    assert websocket.closed is not None, websocket.closed
    assert websocket.closed["code"] == 1008, websocket.closed


async def test_websocket_accepts_valid_auth_token_and_local_origin() -> None:
    observed = []

    async def _fake_overlay_input(text, session_id=None):
        observed.append((text, session_id))

    server = VisualizationServer(
        auth_token="secret-token",
        on_overlay_input=_fake_overlay_input,
    )
    websocket = _FakeWebSocket(
        [
            json.dumps({
                "event": "overlay_input",
                "text": "what is visible?",
                "sessionId": "chat-1",
            })
        ],
        path="/?token=secret-token",
        headers={"Origin": "file://"},
    )

    await server._handle_client(websocket)

    assert observed == [("what is visible?", "chat-1")], observed
    assert websocket.closed is None, websocket.closed


async def test_websocket_rejects_cross_origin_even_with_token() -> None:
    observed = []
    server = VisualizationServer(
        auth_token="secret-token",
        on_overlay_input=lambda text, session_id=None: observed.append(text),
    )
    websocket = _FakeWebSocket(
        [json.dumps({"event": "overlay_input", "text": "run it"})],
        path="/?token=secret-token",
        headers={"Origin": "https://evil.example"},
    )

    await server._handle_client(websocket)

    assert observed == [], observed
    assert websocket.closed is not None, websocket.closed
    assert websocket.closed["code"] == 1008, websocket.closed


async def test_overlay_input_is_size_limited() -> None:
    observed = []
    server = VisualizationServer(
        auth_token="secret-token",
        on_overlay_input=lambda text, session_id=None: observed.append(text),
    )
    websocket = _FakeWebSocket(
        [
            json.dumps({
                "event": "overlay_input",
                "text": "x" * (VisualizationServer.MAX_OVERLAY_INPUT_CHARS + 1),
            })
        ],
        path="/?token=secret-token",
    )

    await server._handle_client(websocket)

    assert observed == [], observed
    assert websocket.sent[-1]["event"] == "overlay_error", websocket.sent
    assert "too long" in websocket.sent[-1]["error"].lower(), websocket.sent


async def test_transcribe_audio_is_size_limited() -> None:
    observed = []
    server = VisualizationServer(
        auth_token="secret-token",
        on_transcribe_audio=lambda audio, *_args: observed.append(audio) or "unused",
    )
    oversized = b"x" * (VisualizationServer.MAX_AUDIO_BYTES + 1)
    websocket = _FakeWebSocket(
        [
            json.dumps({
                "event": "transcribe_audio",
                "requestId": "voice-1",
                "audioBase64": base64.b64encode(oversized).decode("ascii"),
            })
        ],
        path="/?token=secret-token",
    )

    await server._handle_client(websocket)

    assert observed == [], observed
    assert websocket.sent[-1]["event"] == "voice_transcription_error", websocket.sent
    assert "too large" in websocket.sent[-1]["error"].lower(), websocket.sent


def test_electron_server_config_returns_runtime_auth_token(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        return

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    runtime_path = project_root / "runtime-state.json"
    runtime_path.write_text(
        json.dumps({"host": "127.0.0.1", "port": 9911, "auth_token": "token-123"}),
        encoding="utf-8",
    )

    script = (
        "const path = require('path');\n"
        "const cfg = require(path.join(process.cwd(), 'ui', 'server_config.js'));\n"
        "const result = cfg.getServerConfig({ projectRoot: process.env.PROJECT_ROOT });\n"
        "process.stdout.write(JSON.stringify(result));"
    )
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root)
    env["JARVIS_RUNTIME_STATE_PATH"] = str(runtime_path)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {
        "host": "127.0.0.1",
        "port": 9911,
        "authToken": "token-123",
    }


async def run_checks() -> None:
    await test_websocket_rejects_missing_auth_token()
    await test_websocket_accepts_valid_auth_token_and_local_origin()
    await test_websocket_rejects_cross_origin_even_with_token()
    await test_overlay_input_is_size_limited()
    await test_transcribe_audio_is_size_limited()
    test_electron_server_config_returns_runtime_auth_token(Path(os.environ.get("TMP", ".")) / "ui-security-test")


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_ui_server_security] All checks passed.")
