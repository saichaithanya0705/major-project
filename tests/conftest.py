from __future__ import annotations

import asyncio
import inspect
import pytest


@pytest.fixture(autouse=True)
def isolated_visualization_client(monkeypatch):
    """Unit fixtures must not publish agent events to a user's running chat.

    A real websocket integration test can explicitly install its owned client;
    ordinary code under test receives this per-test in-memory event sink.
    """
    from ui.visualization_api import client as module
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "managed")
    monkeypatch.setenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "")
    class Sink:
        def __init__(self): self.sent = []
        async def send(self, payload): self.sent.append(payload)
        async def close(self): pass
    sink = Sink()
    monkeypatch.setattr(module, "_client", sink)
    return sink


def pytest_pyfunc_call(pyfuncitem):
    test_function = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_function):
        return None

    fixture_args = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
    }
    asyncio.run(test_function(**fixture_args))
    return True
