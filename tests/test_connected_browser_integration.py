import asyncio
from types import SimpleNamespace

import pytest

from agents.browser.agent import BrowserAgent
from models.routing.routing_guardrails import apply_routing_guardrails


class Runner:
    def __init__(self):
        self.calls = []
        self.last_objective = ""
        self.last_progress = []
        self.awaiting_input = False
        self.state = "disconnected"
        self.gateway = SimpleNamespace(title="Chosen tab", url="https://example.org/private?secret=hidden")
        async def list_tabs(): return "0: Chosen tab — https://example.org/private"
        self.gateway.list_tabs = list_tabs

    async def execute(self, task):
        self.calls.append(task)
        return {"success": True, "complete": False, "error": None, "result": {"summary": "Need one field", "complete": False}}

    async def connect(self): self.state = "ready"; return "Chosen tab"
    async def disconnect(self): self.state = "disconnected"
    def request_stop(self): self.calls.append("stopped"); return True


async def test_extension_mode_runs_before_managed_fast_paths(monkeypatch):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    runner = Runner()
    monkeypatch.setattr(BrowserAgent, "_get_connected_runner", classmethod(lambda cls: runner), raising=False)
    result = await BrowserAgent("unused").execute("Open https://example.org")
    assert runner.calls == ["Open https://example.org"] and not result["complete"]


async def test_connection_failure_never_falls_back_to_a_managed_browser(monkeypatch):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    runner = Runner()
    async def fail(_): return {"success": False, "complete": False, "error": "Pairing needed"}
    runner.execute = fail
    monkeypatch.setattr(BrowserAgent, "_get_connected_runner", classmethod(lambda cls: runner), raising=False)
    result = await BrowserAgent("unused").execute("Search for documentation")
    assert not result["success"] and result["error"] == "Pairing needed"


async def test_control_commands_are_deterministic_and_status_hides_query(monkeypatch):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "managed")
    runner = Runner()
    monkeypatch.setattr(BrowserAgent, "_get_connected_runner", classmethod(lambda cls: runner), raising=False)
    monkeypatch.setattr(BrowserAgent, "_connected_runner", runner, raising=False)
    result = await BrowserAgent.handle_control_command("connect browser")
    assert result["success"] and runner.state == "ready"
    status = await BrowserAgent.handle_control_command("browser status")
    assert status["success"] and "0: Chosen tab" in str(status)
    assert "hidden" not in str(status)
    await BrowserAgent.handle_control_command("disconnect browser")
    assert runner.state == "disconnected"


async def test_required_submission_review_crosses_real_chat_websocket(monkeypatch):
    import json
    import websockets
    from core.confirmations import ConfirmationBroker
    from ui.server import VisualizationServer
    from ui.visualization_api import client as chat_client
    broker = ConfirmationBroker(timeout_seconds=5)
    async def answer(text, session_id=None): broker.answer(text)
    server = VisualizationServer(host="127.0.0.1", port=0, auth_token="fixture-auth", on_overlay_input=answer)
    sender = chat_client.VisualizationClient()
    monkeypatch.setattr(chat_client, "_client", sender)
    monkeypatch.setattr(chat_client, "get_host", lambda: "127.0.0.1")
    monkeypatch.setattr(chat_client, "get_auth_token", lambda: "fixture-auth")
    await server.start()
    port = server._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(chat_client, "get_port", lambda: port)
    pending = None
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/?token=fixture-auth", origin="file://") as ui:
            pending = asyncio.create_task(broker.request("submit the synthetic application", required=True))
            for _ in range(8):
                message = json.loads(await asyncio.wait_for(ui.recv(), 5))
                if message.get("command") == "confirmation_request": break
            assert message["command"] == "confirmation_request"
            assert "synthetic application" in message["text"] and not pending.done()
            await ui.send(json.dumps({"event":"overlay_input", "text":"yes"}))
            assert await asyncio.wait_for(pending, 5)
    finally:
        broker.cancel()
        if pending: await asyncio.gather(pending, return_exceptions=True)
        await sender.close()
        await server.stop()


@pytest.mark.parametrize("task", ["Fill this form in my browser", "Read the current tab and extract its headings"])
def test_connected_session_tasks_route_to_browser(monkeypatch, task):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    result = apply_routing_guardrails(user_prompt=task, routing_result={"agent": "cua_vision", "task": task}, latest_screen_context=None)
    assert result.route["agent"] == "browser"


@pytest.mark.parametrize("task", ["Maximize my browser window", "Open Chrome with my work profile",
    "Open Brave browser in a new window and search for cats", "Launch Comet", "Open a new Chrome window"])
def test_native_window_and_profile_requests_still_use_desktop_control(monkeypatch, task):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    result = apply_routing_guardrails(user_prompt=task, routing_result={"agent": "browser", "task": task}, latest_screen_context=None)
    assert result.route["agent"] == "cua_vision"


def test_resume_keeps_objective_but_not_old_refs(monkeypatch):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    runner = Runner()
    runner.last_objective = "Fill the application draft"
    runner.last_progress = ["Verified type on example.org: Name"]
    monkeypatch.setattr(BrowserAgent, "_connected_runner", runner, raising=False)
    task = BrowserAgent.resolve_resume_task("continue")
    assert "application draft" in task and "Verified type" in task


def test_resume_does_not_duplicate_router_expansion(monkeypatch):
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")
    runner = Runner()
    runner.last_objective = "Fill the application draft"
    runner.awaiting_input = True
    monkeypatch.setattr(BrowserAgent, "_connected_runner", runner, raising=False)
    expanded = BrowserAgent.resolve_resume_task("Use Demo as the name")
    assert BrowserAgent.resolve_resume_task(expanded) == expanded


async def test_chat_stop_is_handled_before_a_confirmation_answer(monkeypatch):
    import app
    ready = asyncio.Event()
    forever = asyncio.Event()
    handlers = {}
    calls = []
    class Server:
        def __init__(self, **kwargs): handlers.update(kwargs)
        async def start(self): ready.set()
        async def wait_for_client(self): pass
        async def wait_forever(self): await forever.wait()
    class Broker:
        def answer(self, text): calls.append(("answer", text)); return True
        def cancel(self): calls.append(("cancel", None))
    monkeypatch.setattr(app, "VisualizationServer", Server)
    monkeypatch.setattr(app, "CONFIRMATIONS", Broker())
    monkeypatch.setattr(app, "run_runtime_cleanup", lambda *_: None)
    monkeypatch.setattr(app, "set_host_and_port", lambda *_: ("127.0.0.1", 8765))
    monkeypatch.setattr(app, "ensure_auth_token", lambda *_: "test-token")
    monkeypatch.setattr(app, "set_screen_size", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app, "get_model_configs", lambda *_: ("test", "test"))
    monkeypatch.setattr(app, "preflight_router_configuration", lambda *_: None)
    monkeypatch.setattr(app, "maybe_launch_electron_ui", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app, "request_cua_vision_stop", lambda: None)
    monkeypatch.setattr(app, "reset_cua_vision_state", lambda: None)
    monkeypatch.setattr(app, "stop_all_actions", lambda: None)
    monkeypatch.setattr(BrowserAgent, "request_stop_all", classmethod(lambda cls: calls.append(("stop", None))))
    async def noop(*_args, **_kwargs): pass
    monkeypatch.setattr(app.CLIAgent, "stop_all_running_processes", noop)
    from ui.visualization_api import chat_response
    replies = []
    async def record_response(text, source="rapid_response"):
        replies.append({"text":text,"source":source})
    async def control(_cls, _text):
        return {"success":True,"result":{"summary":"Browser is ready."}}
    monkeypatch.setattr(chat_response, "send_chat_response", record_response)
    monkeypatch.setattr(BrowserAgent, "handle_control_command", classmethod(control))
    task = asyncio.create_task(app.main())
    try:
        await asyncio.wait_for(ready.wait(), 5)
        await handlers["on_overlay_input"]("stop")
        assert ("stop", None) in calls
        assert ("answer", "stop") not in calls
        await handlers["on_overlay_input"]("browser status")
        # Final control replies use the same visible chat channel as the main agent.
        # The renderer deliberately hides specialist status/trace sources.
        assert len(replies) == 2 and all(reply["source"] == "rapid_response" for reply in replies)
        assert replies[-1]["text"] == "Browser is ready."
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
