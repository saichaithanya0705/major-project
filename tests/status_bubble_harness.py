"""
Headless harness utilities for status-bubble visualization tests.
"""

from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

import websockets

from core.settings import set_runtime_host_and_port


def allocate_local_ws_endpoint(host: str = "127.0.0.1") -> tuple[str, int]:
    """Reserve a free local port for a short-lived websocket test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return host, int(sock.getsockname()[1])


def configure_isolated_runtime_endpoint(
    *,
    host: str,
    port: int,
    settings_path: str | None = None,
) -> str:
    """
    Point runtime-state reads/writes to a unique temp file for this process,
    then persist the requested websocket endpoint there.
    """
    runtime_dir = Path(tempfile.gettempdir()) / "jarvis-runtime-tests"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_state_path = runtime_dir / f"{uuid.uuid4().hex}.json"
    os.environ["JARVIS_RUNTIME_STATE_PATH"] = str(runtime_state_path)
    if settings_path is None:
        set_runtime_host_and_port(host, port)
    else:
        set_runtime_host_and_port(host, port, settings_path=settings_path)
    return str(runtime_state_path)


class HeadlessVisualizationClient:
    """
    Minimal websocket client that keeps the visualization server connection alive.

    It continuously drains inbound messages so server broadcasts never block.
    """

    def __init__(self, uri: str):
        self.uri = uri
        self._websocket = None
        self._recv_task = None

    async def __aenter__(self):
        self._websocket = await websockets.connect(self.uri, ping_interval=None)
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._recv_task is not None:
            self._recv_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._recv_task
            self._recv_task = None

        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None

    async def _recv_loop(self):
        try:
            async for _message in self._websocket:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            # Best effort only; tests care about sender-side behavior.
            pass
