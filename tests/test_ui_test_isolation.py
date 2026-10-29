"""The unit suite must never broadcast synthetic agent events into a live chat."""
import pytest
import os


def test_default_unit_browser_cannot_attach_an_inherited_user_profile():
    from agents.browser.connected_control import extension_mode
    assert not extension_mode()
    assert not os.getenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "")


async def test_default_test_ui_client_does_not_connect_to_a_running_app(monkeypatch):
    from ui.visualization_api import client as module
    connections=[]
    class Socket:
        async def send(self, _payload): pass
    async def connect(*args,**kwargs): connections.append(True); return Socket()
    monkeypatch.setattr(module.websockets,"connect",connect)
    client=await module.get_client()
    await client.send({"command":"chat_response","text":"TEST_ONLY_ISOLATION_PROBE"})
    assert not connections
