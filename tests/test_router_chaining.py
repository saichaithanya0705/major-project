"""
Checks for rapid-router multi-agent chaining behavior.

Usage:
    python3 tests/test_router_chaining.py
"""

import asyncio
import os
import sys
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
import models.router_backends as router_backends_module


class _FakeRouterModel:
    sequence: list[dict[str, Any]] = []
    screen_context_payload: dict[str, Any] = {}
    screen_context_calls: int = 0

    def __init__(self, jarvis_model: str, rapid_response_model: str):
        self._idx = 0

    async def route_request(self, prompt: str) -> dict[str, Any]:
        if self._idx >= len(self.sequence):
            return {"agent": "direct", "response_text": "done"}
        value = self.sequence[self._idx]
        self._idx += 1
        return value

    async def generate_screen_context(self, user_request: str, image=None, focus: str = "") -> dict[str, Any]:
        _FakeRouterModel.screen_context_calls += 1
        payload = dict(_FakeRouterModel.screen_context_payload)
        if "recommended_task" not in payload:
            payload["recommended_task"] = user_request
        if "summary" not in payload:
            payload["summary"] = "Screen context captured"
        if "recommended_agent" not in payload:
            payload["recommended_agent"] = "cua_cli"
        return payload


async def test_chains_multiple_agents_then_finishes() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "cua_vision", "task": "inspect screen for repo url"},
        {"agent": "cua_cli", "task": "clone repo locally"},
        {"agent": "browser", "task": "open localhost:3000"},
        {"agent": "direct", "response_text": "All done"},
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("clone this repo and open locally", "rapid", "jarvis")
        assert executed_agents == ["cua_vision", "cua_cli", "browser"], executed_agents
        assert direct_messages, "Expected final direct response"
        assert direct_messages[-1] == "All done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_repeated_step_loop_recovers_and_finishes() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "cua_cli", "task": "clone repo"},
        {"agent": "cua_cli", "task": "clone repo"},
        {"agent": "cua_cli", "task": "clone repo"},
        {"agent": "direct", "response_text": "done"},
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("clone this repo and open locally", "rapid", "jarvis")
        assert executed_agents == ["cua_cli", "cua_cli"], executed_agents
        assert direct_messages, "Expected loop-recovery direct response"
        assert direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_invalid_route_result_falls_back_to_direct() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_messages: list[str] = []

    class _InvalidRouterModel(_FakeRouterModel):
        async def route_request(self, prompt: str):
            return None

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _InvalidRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("open localhost 3000", "rapid", "jarvis")
        history_entries = list(model_module._RAPID_CONVERSATION_HISTORY)
        assert history_entries, "Expected rapid history entry after fallback"
        assert any("invalid routing response shape" in str(entry.get("text", "")).lower() for entry in history_entries), history_entries
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_response_repeat_artifact_is_sanitized() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "cua_cli", "task": "Create folder hw"},
        {"agent": "cua_cli", "task": "Move cs 173 hw into hw"},
        {
            "agent": "direct",
            "response_text": (
                "I see you're asking me to repeat the exact same task that was just completed "
                "in the history. Is there anything else I can help you with now?"
            ),
        },
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "create a folder hw on desktop and move cs 173 hw into it",
            "rapid",
            "jarvis",
        )
        assert direct_messages, "Expected sanitized final direct response"
        lowered = direct_messages[-1].lower()
        assert "repeat the exact same task" not in lowered, direct_messages[-1]
        assert lowered.startswith("task completed"), direct_messages[-1]
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_screen_context_then_actionable_agent() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")
    original_get_stored_screenshot = model_module.get_stored_screenshot

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "screen_context", "task": "clone this repository for me and open it up on localhost", "focus": "extract github repo url"},
        {"agent": "cua_cli", "task": "git clone <repo-url> && run locally"},
        {"agent": "direct", "response_text": "done"},
    ]
    _FakeRouterModel.screen_context_calls = 0
    _FakeRouterModel.screen_context_payload = {
        "summary": "GitHub repo page is visible.",
        "repo_url": "https://github.com/example/repo",
        "recommended_agent": "cua_cli",
        "recommended_task": "Clone the repo and start the local server.",
        "hints": "Repo URL visible in address bar.",
    }

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    model_module.get_stored_screenshot = lambda: None
    try:
        await model_module.call_gemini(
            "clone this repository for me and open it up on localhost",
            "rapid",
            "jarvis",
        )
        assert _FakeRouterModel.screen_context_calls == 1, _FakeRouterModel.screen_context_calls
        assert executed_agents == ["cua_cli"], executed_agents
        assert direct_messages, "Expected final direct response"
        assert direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        model_module.get_stored_screenshot = original_get_stored_screenshot
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_execution_request_reroutes_jarvis_to_cli() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "jarvis", "query": "clone this repo and run tests"},
        {"agent": "direct", "response_text": "done"},
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "clone this repo and run tests",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["cua_cli"], executed_agents
        assert direct_messages and direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_execution_request_reroutes_jarvis_to_browser_when_url_task() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "jarvis", "query": "open https://example.com and submit the form"},
        {"agent": "direct", "response_text": "done"},
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "open https://example.com and submit the form",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["browser"], executed_agents
        assert direct_messages and direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_window_management_request_reroutes_jarvis_to_cua_vision() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = model_module._run_routed_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": f"{agent} step completed",
            "source": "rapid",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "jarvis", "query": "Minimize the codex app on my screen"},
        {"agent": "direct", "response_text": "done"},
    ]

    model_module._RAPID_CONVERSATION_HISTORY.clear()
    model_module.GeminiModel = _FakeRouterModel
    model_module._run_routed_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "Minimize the codex app on my screen",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["cua_vision"], executed_agents
        assert direct_messages and direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module._run_routed_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


def test_router_refusal_task_is_replaced_with_original_request() -> None:
    model = object.__new__(model_module.GeminiModel)
    route = model_module.GeminiModel._normalize_router_decision(
        model,
        {
            "agent": "browser",
            "task": "I cannot open URLs directly as I am a text-based AI model.",
        },
        "# User's Latest Request:\nopen https://example.com",
        provider_name="Ollama",
    )
    assert route == {
        "agent": "browser",
        "task": "open https://example.com",
    }


def test_ollama_router_payload_disables_thinking() -> None:
    model = object.__new__(model_module.GeminiModel)
    model.ollama_router_model = "router-model"
    model.ollama_router_num_predict = 800
    model.ollama_router_num_ctx = 4096
    model.ollama_router_think = False
    model.ollama_keep_alive = "10m"
    model.ollama_base_url = "http://127.0.0.1:11434"
    model.ollama_router_timeout_seconds = 90

    captured_payload: dict[str, Any] = {}
    original_post = router_backends_module.requests.post

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "message": {
                    "content": '{"agent":"browser","task":"open https://example.com"}',
                },
            }

    def _fake_post(url, json, timeout):
        captured_payload.update(json)
        return _FakeResponse()

    router_backends_module.requests.post = _fake_post
    try:
        route = model._call_ollama_router_sync("open https://example.com")
    finally:
        router_backends_module.requests.post = original_post

    assert route == {"agent": "browser", "task": "open https://example.com"}
    assert captured_payload["think"] is False, captured_payload
    assert captured_payload["options"]["temperature"] == 0.0, captured_payload
    assert captured_payload["options"]["num_predict"] == 800, captured_payload


def test_deterministic_router_is_disabled_after_chain_progress() -> None:
    prompt = (
        "\n# Multi-Agent Chaining Mode\n"
        "Continue from prior delegated work. Choose the single best next tool call.\n"
        "Original request: clone this repo and open locally\n"
        "Completed delegated steps (1/6):\n"
        "1. agent=cua_cli success=True task=clone repo outcome=clone completed\n"
        "\n# User's Latest Request:\nclone this repo and open locally"
    )
    assert model_module._prompt_has_completed_delegated_steps(prompt) is True
    assert model_module._should_use_deterministic_router(prompt) is False


def test_window_management_is_execution_not_visual_explanation() -> None:
    prompt = "Minimize the codex app on my screen"
    route = model_module._deterministic_router_decision(
        f"# User's Latest Request:\n{prompt}"
    )

    assert model_module._is_execution_request(prompt) is True
    assert model_module._is_visual_explanation_request(prompt) is False
    assert route == {"agent": "cua_vision", "task": prompt}


async def run_checks() -> None:
    test_deterministic_router_is_disabled_after_chain_progress()
    test_window_management_is_execution_not_visual_explanation()
    test_router_refusal_task_is_replaced_with_original_request()
    test_ollama_router_payload_disables_thinking()
    await test_chains_multiple_agents_then_finishes()
    await test_repeated_step_loop_recovers_and_finishes()
    await test_invalid_route_result_falls_back_to_direct()
    await test_direct_response_repeat_artifact_is_sanitized()
    await test_screen_context_then_actionable_agent()
    await test_execution_request_reroutes_jarvis_to_cli()
    await test_execution_request_reroutes_jarvis_to_browser_when_url_task()
    await test_window_management_request_reroutes_jarvis_to_cua_vision()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_router_chaining] All checks passed.")
