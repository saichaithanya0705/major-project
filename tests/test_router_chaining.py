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
import models.openrouter_fallback as openrouter_fallback_module
import models.request_agent_step_runtime as request_agent_step_runtime
import models.router_backends as router_backends_module
import models.routing_policy as routing_policy


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
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("clone this repo and open locally", "rapid", "jarvis")
        assert executed_agents == ["cua_vision", "cua_cli", "browser"], executed_agents
        assert direct_messages, "Expected final direct response"
        assert direct_messages[-1] == "All done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_response_preserves_full_assistant_message() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_messages: list[str] = []
    long_message = " ".join(f"assistant-detail-{index}" for index in range(90))

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _FakeRouterModel.sequence = [
        {"agent": "direct", "response_text": long_message},
    ]

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "open localhost 3000 and explain the result in detail",
            "rapid",
            "jarvis",
        )
        assert direct_messages == [long_message], direct_messages[-1]
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


def test_router_normalization_preserves_full_direct_response() -> None:
    model = object.__new__(model_module.GeminiModel)
    long_message = (
        "## Normalized detail\n\n"
        + "\n".join(f"- normalized-detail-{index}" for index in range(5))
        + "\n\n"
        + "Closing paragraph."
    )

    route = model_module.GeminiModel._normalize_router_decision(
        model,
        {"agent": "direct", "response_text": long_message},
        "# User's Latest Request:\nTell me everything about elon musk.",
        provider_name="unit-test",
    )

    assert route == {"agent": "direct", "response_text": long_message}, route


def test_router_normalization_promotes_direct_response_text_from_kwargs() -> None:
    model = object.__new__(model_module.GeminiModel)

    route = model_module.GeminiModel._normalize_router_decision(
        model,
        {
            "agent": "direct",
            "direct_response_args": {"text": "All done", "variant": "compact"},
        },
        "# User's Latest Request:\nTell me the result.",
        provider_name="unit-test",
    )

    assert route == {
        "agent": "direct",
        "response_text": "All done",
        "direct_response_args": {"variant": "compact"},
    }, route


def test_router_normalization_accepts_web_qa_route() -> None:
    model = object.__new__(model_module.GeminiModel)

    route = model_module.GeminiModel._normalize_router_decision(
        model,
        {"agent": "web_qa", "task": "What is the latest news about SpaceX?"},
        "# User's Latest Request:\nWhat is the latest news about SpaceX?",
        provider_name="unit-test",
    )

    assert route == {
        "agent": "web_qa",
        "task": "What is the latest news about SpaceX?",
    }, route


def test_router_normalization_accepts_plan_payload() -> None:
    model = object.__new__(model_module.GeminiModel)

    route = model_module.GeminiModel._normalize_router_decision(
        model,
        {
            "tasks": [
                {"id": "research", "agent": "web_qa", "task": "Find release notes"},
                {
                    "id": "patch",
                    "agent": "cua_cli",
                    "task": "Update changelog",
                    "depends_on": ["research"],
                },
            ],
            "max_parallel": 2,
        },
        "# User's Latest Request:\nFind release notes and update changelog.",
        provider_name="unit-test",
    )

    assert route == {
        "tasks": [
            {
                "id": "research",
                "agent": "web_qa",
                "task": "Find release notes",
                "resources": ["web_qa"],
            },
            {
                "id": "patch",
                "agent": "cua_cli",
                "task": "Update changelog",
                "depends_on": ["research"],
                "resources": ["cli"],
            },
        ],
        "max_parallel": 2,
    }, route


async def test_web_qa_route_executes_agent_and_finishes() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_calls: list[dict[str, Any]] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", ""),
            "success": True,
            "message": "Sourced answer\n\nSources:\n- [Example](https://example.com)",
            "source": "web_qa",
        }

    def _fake_direct_response(**kwargs):
        direct_calls.append(dict(kwargs))

    _FakeRouterModel.sequence = [
        {"agent": "web_qa", "task": "What is the latest news about SpaceX?"},
    ]

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("What is the latest news about SpaceX?", "rapid", "jarvis")
        assert executed_agents == ["web_qa"], executed_agents
        assert direct_calls == [
            {
                "text": "Sourced answer\n\nSources:\n- [Example](https://example.com)",
                "source": "rapid_response",
            }
        ], direct_calls
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_response_promotes_text_out_of_direct_response_args() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_calls: list[dict[str, Any]] = []

    def _fake_direct_response(**kwargs):
        direct_calls.append(dict(kwargs))

    _FakeRouterModel.sequence = [
        {
            "agent": "direct",
            "direct_response_args": {"text": "All done", "variant": "compact"},
        },
    ]

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("finish this", "rapid", "jarvis")
        assert direct_calls == [
            {
                "text": "All done",
                "source": "rapid_response",
                "variant": "compact",
            }
        ], direct_calls
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_plan_payload_executes_multiple_tasks_then_finishes() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")
    original_log_event = model_module.log_assistant_event

    executed_routes: list[dict[str, Any]] = []
    direct_calls: list[dict[str, Any]] = []
    logged_events: list[dict[str, Any]] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        executed_routes.append(dict(routing_result))
        return {
            "agent": routing_result.get("agent", "unknown"),
            "task": routing_result.get("task", ""),
            "success": True,
            "complete": True,
            "message": f"{routing_result.get('agent')} completed {routing_result.get('task')}",
            "source": routing_result.get("agent", "rapid"),
        }

    def _fake_direct_response(**kwargs):
        direct_calls.append(dict(kwargs))

    def _fake_log_assistant_event(event_type, **kwargs):
        logged_events.append({"event_type": event_type, **kwargs})

    _FakeRouterModel.sequence = [
        {
            "tasks": [
                {"id": "research", "agent": "web_qa", "task": "research release notes"},
                {
                    "id": "patch",
                    "agent": "cua_cli",
                    "task": "update changelog",
                    "depends_on": ["research"],
                },
            ],
            "max_parallel": 2,
        }
    ]

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    model_module.log_assistant_event = _fake_log_assistant_event
    try:
        await model_module.call_gemini("research release notes and update changelog", "rapid", "jarvis")
        assert executed_routes[0] == {"agent": "web_qa", "task": "research release notes"}
        assert executed_routes[1]["agent"] == "cua_cli"
        assert executed_routes[1]["task"] == "update changelog"
        context = executed_routes[1]["orchestrator_context"]
        assert [outcome["task_id"] for outcome in context["dependency_outcomes"]] == ["research"]
        assert context["artifacts"] == ()
        assert direct_calls[-1] == {
            "text": "cua_cli completed update changelog",
            "source": "rapid_response",
        }
        completed_event = next(event for event in logged_events if event["event_type"] == "request_completed")
        metadata = completed_event["metadata"]
        assert metadata["orchestrated_plan"] is True
        assert [task["id"] for task in metadata["orchestration_plan"]["tasks"]] == ["research", "patch"]
        assert [event["event_type"] for event in metadata["orchestration_trace"]][-2:] == [
            "running",
            "completed",
        ]
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        model_module.log_assistant_event = original_log_event
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_repeated_step_loop_recovers_and_finishes() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("clone this repo and open locally", "rapid", "jarvis")
        assert executed_agents == ["cua_cli", "cua_cli"], executed_agents
        assert direct_messages, "Expected loop-recovery direct response"
        assert direct_messages[-1] == "done", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_single_full_agent_step_finishes_without_followup_router() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    class _CountingRouterModel(_FakeRouterModel):
        route_calls = 0

        async def route_request(self, prompt: str) -> dict[str, Any]:
            type(self).route_calls += 1
            return await super().route_request(prompt)

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "message": "Browser task completed quickly.",
            "source": "browser_use",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _CountingRouterModel.sequence = [
        {
            "agent": "browser",
            "task": "open google.com and search for free machine learning courses",
        },
        {"agent": "direct", "response_text": "This second route should not run."},
    ]
    _CountingRouterModel.route_calls = 0

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _CountingRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "open google.com and search for free machine learning courses",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["browser"], executed_agents
        assert _CountingRouterModel.route_calls == 1, _CountingRouterModel.route_calls
        assert direct_messages == ["Browser task completed quickly."], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_completed_browser_summary_finishes_when_router_rewrites_task() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    class _CountingRouterModel(_FakeRouterModel):
        route_calls = 0

        async def route_request(self, prompt: str) -> dict[str, Any]:
            type(self).route_calls += 1
            return await super().route_request(prompt)

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("task", routing_result.get("query", "")),
            "success": True,
            "complete": True,
            "message": "Example Domain is a small demonstration page used in documentation.",
            "source": "browser_use",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _CountingRouterModel.sequence = [
        {
            "agent": "browser",
            "task": "Open https://example.com, read the page content, and summarize the main finding.",
        },
        {"agent": "direct", "response_text": "This second route should not run."},
    ]
    _CountingRouterModel.route_calls = 0

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _CountingRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "summarize example.com",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["browser"], executed_agents
        assert _CountingRouterModel.route_calls == 1, _CountingRouterModel.route_calls
        assert direct_messages == [
            "Example Domain is a small demonstration page used in documentation."
        ], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


def test_completion_recovery_policy_recovers_repeated_incomplete_browser_step() -> None:
    import models.rapid_completion_recovery_policy as policy

    user_request = "goto chat.openai.com website and ask it for top 3 ml learning resources"
    decision = policy.evaluate_incomplete_step_recovery(
        user_prompt=user_request,
        routing_result={"agent": "browser", "task": user_request},
        chain_steps=[
            {
                "agent": "browser",
                "task": user_request,
                "success": True,
                "complete": False,
                "message": "Browser opened the site but interactive automation is still required.",
                "source": "browser_use",
            }
        ],
        routing_task_text=lambda route: str(route.get("task", "")),
    )

    assert decision is not None
    assert decision.incomplete_step["agent"] == "browser"
    assert decision.recovery_route == {
        "agent": "cua_vision",
        "task": (
            "Continue in the currently open browser window and finish the original "
            f"user request: {user_request}"
        ),
    }


def test_completion_recovery_policy_fast_finishes_when_route_covers_request() -> None:
    import models.rapid_completion_recovery_policy as policy

    routed_task = "Open https://example.com, read the page content, and summarize the main finding."
    assert policy.should_finish_after_successful_agent_step(
        user_prompt="summarize example.com",
        routing_result={"agent": "browser", "task": routed_task},
        step_result={
            "agent": "browser",
            "task": routed_task,
            "success": True,
            "complete": True,
            "message": "Example Domain is a small demonstration page used in documentation.",
            "source": "browser_use",
        },
        chain_steps=[
            {
                "agent": "browser",
                "task": routed_task,
                "success": True,
                "complete": True,
            }
        ],
        routing_task_text=lambda route: str(route.get("task", "")),
    )


async def test_partial_browser_step_continues_with_visual_agent_before_finishing() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []
    user_request = "goto chat.openai.com website and ask it for top 3 ml learning resources"

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        if agent == "browser":
            return {
                "agent": "browser",
                "task": routing_result.get("task", ""),
                "success": True,
                "complete": False,
                "message": (
                    "Browser fallback opened https://chat.openai.com, but interactive "
                    "browser automation is still required."
                ),
                "source": "browser_use",
            }
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
        {"agent": "browser", "task": user_request},
        {"agent": "browser", "task": user_request},
        {"agent": "direct", "response_text": "All done"},
    ]

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(user_request, "rapid", "jarvis")
        assert executed_agents == ["browser", "cua_vision"], executed_agents
        assert direct_messages == ["All done"], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _InvalidRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini("open localhost 3000", "rapid", "jarvis")
        history_entries = list(model_module.RAPID_SESSION_STATE.get_history())
        assert history_entries, "Expected rapid history entry after fallback"
        assert any("invalid routing response shape" in str(entry.get("text", "")).lower() for entry in history_entries), history_entries
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_response_repeat_artifact_is_sanitized() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
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
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_screen_context_then_actionable_agent() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")
    original_get_stored_screenshot = model_module.get_stored_screenshot
    original_prepare_vision_screenshot = model_module.prepare_vision_screenshot

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    async def _fake_prepare_vision_screenshot(*, keep_chat_hidden=False):
        return None

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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    model_module.get_stored_screenshot = lambda: None
    model_module.prepare_vision_screenshot = _fake_prepare_vision_screenshot
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
        request_agent_step_runtime.run_request_agent_step = original_run_step
        model_module.get_stored_screenshot = original_get_stored_screenshot
        model_module.prepare_vision_screenshot = original_prepare_vision_screenshot
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


def test_delegated_step_runtime_fast_finishes_completed_browser_step() -> None:
    from models.orchestrator_contracts import TaskStatus
    from models.orchestrator_adapters import plan_from_route
    from models.rapid_step_execution_runtime import execute_delegated_step

    direct_calls: list[dict[str, Any]] = []
    history_calls: list[tuple[str, str, str]] = []
    recorded_steps: list[dict[str, Any]] = []
    logged_events: list[dict[str, Any]] = []

    class _FakeDeps:
        router_tool_map = {
            "direct_response": lambda **kwargs: direct_calls.append(dict(kwargs)),
        }

        async def run_routed_agent_step(
            self,
            *,
            model,
            routing_result,
            jarvis_model,
            request_id=None,
            prepare_vision_screenshot=None,
        ):
            return {
                "agent": routing_result.get("agent", "unknown"),
                "task": routing_result.get("task", ""),
                "success": True,
                "complete": True,
                "message": "Example Domain is a small demonstration page used in documentation.",
                "source": "browser_use",
            }

        async def prepare_vision_screenshot(self, *, keep_chat_hidden=False):
            return None

        def record_step_context(self, step_result):
            recorded_steps.append(dict(step_result))

        def append_rapid_history(self, role, text, source):
            history_calls.append((role, text, source))

        def finalize_direct_response_text(self, *, user_prompt, chain_steps, text):
            return str(text or "")

        def clean_text(self, value, fallback, max_len):
            text = " ".join(str(value or "").split()).strip()
            if not text:
                text = fallback
            if max_len is not None:
                text = text[:max_len]
            return text

        def log_assistant_event(self, event_type, **kwargs):
            logged_events.append({"event_type": event_type, **kwargs})

        def routing_task_text(self, route):
            return str(route.get("task", route.get("query", "")))

        def screen_context_message(self, payload):
            return str(payload.get("summary", ""))

    user_prompt = "summarize example.com"
    route = {
        "agent": "browser",
        "task": "Open https://example.com, read the page content, and summarize the main finding.",
    }
    plan = plan_from_route(user_prompt, route, max_parallel=1)
    chain_steps: list[dict[str, Any]] = []

    result = asyncio.run(
        execute_delegated_step(
            model=object(),
            user_prompt=user_prompt,
            routing_result=route,
            orchestration_plan=plan,
            orchestration_task=plan.tasks[0],
            chain_steps=chain_steps,
            jarvis_model="jarvis",
            request_id="req-fast-finish",
            deps=_FakeDeps(),
        )
    )

    assert result.disposition == "fast_finish"
    assert result.latest_screen_context is None
    assert result.orchestration_plan.tasks[0].status is TaskStatus.COMPLETED
    assert chain_steps == [
        {
            "agent": "browser",
            "task": "Open https://example.com, read the page content, and summarize the main finding.",
            "success": True,
            "complete": True,
            "message": "Example Domain is a small demonstration page used in documentation.",
            "source": "browser_use",
        }
    ]
    assert recorded_steps == chain_steps
    assert direct_calls == [
        {
            "text": "Example Domain is a small demonstration page used in documentation.",
            "source": "rapid_response",
        }
    ]
    assert history_calls[-2:] == [
        (
            "assistant",
            "Example Domain is a small demonstration page used in documentation.",
            "browser_use",
        ),
        (
            "assistant",
            "Example Domain is a small demonstration page used in documentation.",
            "rapid",
        ),
    ]
    assert logged_events[-1]["event_type"] == "request_completed"
    assert logged_events[-1]["metadata"]["fast_finish"] is True


def test_delegated_step_runtime_fails_screen_context_and_stops() -> None:
    from models.orchestrator_contracts import TaskStatus
    from models.orchestrator_adapters import plan_from_route
    from models.rapid_step_execution_runtime import execute_delegated_step

    direct_calls: list[dict[str, Any]] = []
    history_calls: list[tuple[str, str, str]] = []
    recorded_steps: list[dict[str, Any]] = []
    logged_events: list[dict[str, Any]] = []

    class _FailingScreenContextModel:
        async def generate_screen_context(self, user_request: str, image=None, focus: str = "") -> dict[str, Any]:
            raise RuntimeError("screen context exploded")

    class _FakeDeps:
        router_tool_map = {
            "direct_response": lambda **kwargs: direct_calls.append(dict(kwargs)),
        }

        async def run_routed_agent_step(self, **kwargs):
            raise AssertionError("screen_context route should not call run_routed_agent_step")

        async def prepare_vision_screenshot(self, *, keep_chat_hidden=False):
            return None

        def record_step_context(self, step_result):
            recorded_steps.append(dict(step_result))

        def append_rapid_history(self, role, text, source):
            history_calls.append((role, text, source))

        def finalize_direct_response_text(self, *, user_prompt, chain_steps, text):
            return str(text or "")

        def clean_text(self, value, fallback, max_len):
            text = " ".join(str(value or "").split()).strip()
            if not text:
                text = fallback
            if max_len is not None:
                text = text[:max_len]
            return text

        def log_assistant_event(self, event_type, **kwargs):
            logged_events.append({"event_type": event_type, **kwargs})

        def routing_task_text(self, route):
            return str(route.get("task", route.get("query", "")))

        def screen_context_message(self, payload):
            return str(payload.get("summary", ""))

    user_prompt = "clone this repository for me and open it up on localhost"
    route = {
        "agent": "screen_context",
        "task": user_prompt,
        "focus": "extract github repo url",
    }
    plan = plan_from_route(user_prompt, route, max_parallel=1)
    chain_steps: list[dict[str, Any]] = []

    result = asyncio.run(
        execute_delegated_step(
            model=_FailingScreenContextModel(),
            user_prompt=user_prompt,
            routing_result=route,
            orchestration_plan=plan,
            orchestration_task=plan.tasks[0],
            chain_steps=chain_steps,
            jarvis_model="jarvis",
            request_id="req-screen-fail",
            deps=_FakeDeps(),
        )
    )

    assert result.disposition == "failed"
    assert result.latest_screen_context is None
    assert result.orchestration_plan.tasks[0].status is TaskStatus.FAILED
    assert chain_steps == [
        {
            "agent": "screen_context",
            "task": "clone this repository for me and open it up on localhost",
            "success": False,
            "message": "screen context exploded",
            "source": "screen_judge",
        }
    ]
    assert recorded_steps == []
    assert direct_calls == [
        {
            "text": (
                "Stopping chained execution because screen context failed: "
                "screen context exploded"
            ),
            "source": "rapid_response",
        }
    ]
    assert history_calls[-2:] == [
        ("assistant", "screen context exploded", "screen_judge"),
        (
            "assistant",
            "Stopping chained execution because screen context failed: screen context exploded",
            "rapid",
        ),
    ]
    assert logged_events[-1]["event_type"] == "request_failed"
    assert logged_events[-1]["agent"] == "screen_context"


async def test_visual_question_uses_router_then_jarvis() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    class _VisualRouterModel(_FakeRouterModel):
        route_calls = 0

        def __init__(self, jarvis_model: str, rapid_response_model: str):
            super().__init__(jarvis_model, rapid_response_model)

        async def route_request(self, prompt: str) -> dict[str, Any]:
            type(self).route_calls += 1
            return await super().route_request(prompt)

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        agent = routing_result.get("agent", "unknown")
        executed_agents.append(agent)
        return {
            "agent": agent,
            "task": routing_result.get("query", ""),
            "success": True,
            "message": "The screen analysis is complete.",
            "source": "jarvis",
        }

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    _VisualRouterModel.sequence = [
        {"agent": "jarvis", "query": "what do you see on my screen?"},
        {"agent": "direct", "response_text": "The screen analysis is complete."},
    ]
    _VisualRouterModel.route_calls = 0

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _VisualRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "what do you see on my screen?",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["jarvis"], executed_agents
        assert _VisualRouterModel.route_calls == 2, _VisualRouterModel.route_calls
        assert direct_messages == ["The screen analysis is complete."], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_execution_request_reroutes_jarvis_to_cli() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "clone this repo and run tests",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["cua_cli"], executed_agents
        assert direct_messages and direct_messages[-1] == "cua_cli step completed", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_execution_request_reroutes_jarvis_to_browser_when_url_task() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "open https://example.com and submit the form",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["browser"], executed_agents
        assert direct_messages and direct_messages[-1] == "browser step completed", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_window_management_request_reroutes_jarvis_to_cua_vision() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    executed_agents: list[str] = []
    direct_messages: list[str] = []

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
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

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FakeRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "Minimize the codex app on my screen",
            "rapid",
            "jarvis",
        )
        assert executed_agents == ["cua_vision"], executed_agents
        assert direct_messages and direct_messages[-1] == "cua_vision step completed", direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_call_gemini_uses_session_scoped_rapid_history() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    prompts: list[str] = []

    class _CapturingRouterModel:
        def __init__(self, jarvis_model: str, rapid_response_model: str):
            pass

        async def route_request(self, prompt: str) -> dict[str, Any]:
            prompts.append(prompt)
            return {"agent": "direct", "response_text": "done"}

    model_module.RAPID_SESSION_STATE.clear_history("chat-alpha")
    model_module.RAPID_SESSION_STATE.clear_history("chat-beta")
    model_module.GeminiModel = _CapturingRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = lambda **_kwargs: None
    try:
        await model_module.call_gemini("alpha-only memory", "rapid", "jarvis", session_id="chat-alpha")
        await model_module.call_gemini("beta asks a question", "rapid", "jarvis", session_id="chat-beta")
        await model_module.call_gemini("alpha follow-up", "rapid", "jarvis", session_id="chat-alpha")
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response

    assert len(prompts) == 3, prompts
    assert "alpha-only memory" not in prompts[1], prompts[1]
    assert "beta asks a question" not in prompts[2], prompts[2]
    assert "alpha-only memory" in prompts[2], prompts[2]


async def test_call_gemini_builds_deps_through_extracted_builder() -> None:
    original_builder = model_module.build_rapid_orchestrator_deps
    original_run_rapid_request = model_module.run_rapid_request

    sentinel_deps = object()
    captured: dict[str, Any] = {}

    def _fake_build_rapid_orchestrator_deps(**kwargs):
        captured.update(kwargs)
        return sentinel_deps

    async def _fake_run_rapid_request(
        *,
        user_prompt: str,
        rapid_response_model: str,
        jarvis_model: str,
        request_id: str,
        deps,
    ) -> None:
        assert user_prompt == "use extracted deps builder"
        assert rapid_response_model == "rapid"
        assert jarvis_model == "jarvis"
        assert isinstance(request_id, str) and request_id
        assert deps is sentinel_deps

    model_module.build_rapid_orchestrator_deps = _fake_build_rapid_orchestrator_deps
    model_module.run_rapid_request = _fake_run_rapid_request
    try:
        await model_module.call_gemini(
            "use extracted deps builder",
            "rapid",
            "jarvis",
            session_id="bridge-session",
        )
    finally:
        model_module.build_rapid_orchestrator_deps = original_builder
        model_module.run_rapid_request = original_run_rapid_request

    assert captured["rapid_session_id"] == "bridge-session"
    assert captured["model_factory"] is model_module.GeminiModel
    assert captured["run_routed_agent_step"] is request_agent_step_runtime.run_request_agent_step
    assert captured["get_stored_screenshot"] is model_module.get_stored_screenshot
    assert captured["prepare_vision_screenshot"] is model_module.prepare_vision_screenshot
    assert captured["log_assistant_event"] is model_module.log_assistant_event


async def test_contextual_file_followups_enrich_cli_tasks() -> None:
    original_model_cls = model_module.GeminiModel
    original_run_step = request_agent_step_runtime.run_request_agent_step
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    session_id = "contextual-file-followup"
    answer_text = "Bill Gates net worth is roughly $118 billion according to the sourced answer."
    created_path = r"C:\Users\SAI\Desktop\context_dump.txt"
    captured_tasks: list[str] = []
    captured_agents: list[str] = []

    class _QueueRouterModel:
        routes: list[dict[str, Any]] = []

        def __init__(self, jarvis_model: str, rapid_response_model: str):
            pass

        async def route_request(self, prompt: str) -> dict[str, Any]:
            if not type(self).routes:
                return {"agent": "direct", "response_text": "done"}
            return type(self).routes.pop(0)

    async def _fake_run_step(model, routing_result, jarvis_model, request_id=None, prepare_vision_screenshot=None):
        task = routing_result.get("task", routing_result.get("query", ""))
        captured_tasks.append(task)
        agent = routing_result.get("agent", "unknown")
        captured_agents.append(agent)
        if agent == "web_qa":
            return {
                "agent": "web_qa",
                "task": task,
                "success": True,
                "message": answer_text,
                "source": "web_qa",
            }
        if "write" in task.lower():
            return {
                "agent": "cua_cli",
                "task": task,
                "success": True,
                "message": f"The answer has been written to `{created_path}`.",
                "source": "cua_cli",
                "tool_calls": [
                    {
                        "tool_name": "write_file",
                        "parameters": {"file_path": created_path},
                        "status": "success",
                    }
                ],
            }
        return {
            "agent": "cua_cli",
            "task": task,
            "success": True,
            "message": "Opened the file in VS Code.",
            "source": "cua_cli",
        }

    model_module.RAPID_SESSION_STATE.clear_history(session_id)
    model_module.GeminiModel = _QueueRouterModel
    request_agent_step_runtime.run_request_agent_step = _fake_run_step
    model_module.ROUTER_TOOL_MAP["direct_response"] = lambda **_kwargs: None
    try:
        _QueueRouterModel.routes = [
            {"agent": "web_qa", "task": "what is the net worth of bill gates"},
        ]
        await model_module.call_gemini(
            "what is the net worth of bill gates",
            "rapid",
            "jarvis",
            session_id=session_id,
        )

        _QueueRouterModel.routes = [
            {"agent": "cua_cli", "task": "write it down in a file on desktop"},
        ]
        await model_module.call_gemini(
            "write it down in a file on desktop",
            "rapid",
            "jarvis",
            session_id=session_id,
        )

        _QueueRouterModel.routes = [
            {"agent": "cua_vision", "task": "open the file through vscode"},
        ]
        await model_module.call_gemini(
            "open the file through vscode",
            "rapid",
            "jarvis",
            session_id=session_id,
        )
    finally:
        model_module.GeminiModel = original_model_cls
        request_agent_step_runtime.run_request_agent_step = original_run_step
        model_module.RAPID_SESSION_STATE.clear_history(session_id)
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response

    assert len(captured_tasks) == 3, captured_tasks
    assert captured_agents == ["web_qa", "cua_cli", "cua_cli"], captured_agents
    assert answer_text in captured_tasks[1], captured_tasks[1]
    assert created_path in captured_tasks[2], captured_tasks[2]


async def test_direct_qa_bypasses_router_and_screenshot_capture() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")
    original_prepare_vision_screenshot = model_module.prepare_vision_screenshot

    direct_messages: list[str] = []

    class _DirectQAModel:
        route_calls = 0
        direct_calls = 0

        def __init__(self, jarvis_model: str, rapid_response_model: str):
            pass

        async def route_request(self, prompt: str) -> dict[str, Any]:
            type(self).route_calls += 1
            return {"agent": "screen_context", "task": "this should not run"}

        async def answer_direct_request(self, *, user_prompt: str, history_block: str = "") -> str:
            type(self).direct_calls += 1
            assert "Tell me everything about elon musk." in user_prompt
            assert "Tell me everything about elon musk." in history_block
            return "Elon Musk is an entrepreneur and business executive."

    async def _fail_prepare_screenshot(*, keep_chat_hidden=False):
        raise AssertionError("direct Q&A should not capture the screen")

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _DirectQAModel
    model_module.prepare_vision_screenshot = _fail_prepare_screenshot
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "Tell me everything about elon musk.",
            "rapid",
            "jarvis",
        )
        assert _DirectQAModel.direct_calls == 1, _DirectQAModel.direct_calls
        assert _DirectQAModel.route_calls == 0, _DirectQAModel.route_calls
        assert direct_messages == [
            "Elon Musk is an entrepreneur and business executive."
        ], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        model_module.prepare_vision_screenshot = original_prepare_vision_screenshot
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_qa_preserves_structured_response_formatting() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    rich_answer = (
        "## Elon Musk\n\n"
        "- Born June 28, 1971.\n"
        "- Co-founded Zip2 and X.com.\n\n"
        "| Company | Role |\n"
        "| --- | --- |\n"
        "| SpaceX | Founder |\n"
    )
    direct_messages: list[str] = []

    class _FormattedDirectQAModel:
        def __init__(self, jarvis_model: str, rapid_response_model: str):
            pass

        async def answer_direct_request(self, *, user_prompt: str, history_block: str = "") -> str:
            return rich_answer

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _FormattedDirectQAModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        await model_module.call_gemini(
            "Tell me everything about elon musk.",
            "rapid",
            "jarvis",
        )
        assert direct_messages == [rich_answer.strip()], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
        if original_direct_response is not None:
            model_module.ROUTER_TOOL_MAP["direct_response"] = original_direct_response


async def test_direct_qa_structural_error_is_not_swallowed() -> None:
    original_model_cls = model_module.GeminiModel

    class _BrokenDirectQAModel:
        def __init__(self, jarvis_model: str, rapid_response_model: str):
            pass

        async def answer_direct_request(self, *, user_prompt: str, history_block: str = "") -> str:
            raise AttributeError("direct qa wiring bug")

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _BrokenDirectQAModel
    try:
        try:
            await model_module.call_gemini(
                "Tell me everything about elon musk.",
                "rapid",
                "jarvis",
            )
            raise AssertionError("Expected structural direct-QA error to propagate.")
        except AttributeError as exc:
            assert str(exc) == "direct qa wiring bug", exc
    finally:
        model_module.GeminiModel = original_model_cls


async def test_router_structural_error_is_not_swallowed() -> None:
    original_model_cls = model_module.GeminiModel
    original_direct_response = model_module.ROUTER_TOOL_MAP.get("direct_response")

    direct_messages: list[str] = []

    class _BrokenRouterModel(_FakeRouterModel):
        async def route_request(self, prompt: str):
            raise ValueError("router configuration bug")

    def _fake_direct_response(**kwargs):
        direct_messages.append(str(kwargs.get("text", "")))

    model_module.RAPID_SESSION_STATE.clear_history()
    model_module.GeminiModel = _BrokenRouterModel
    model_module.ROUTER_TOOL_MAP["direct_response"] = _fake_direct_response
    try:
        try:
            await model_module.call_gemini("open localhost 3000", "rapid", "jarvis")
            raise AssertionError("Expected structural router error to propagate.")
        except ValueError as exc:
            assert str(exc) == "router configuration bug", exc
        assert direct_messages == [], direct_messages
    finally:
        model_module.GeminiModel = original_model_cls
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


def test_ollama_router_accepts_legacy_tool_call_text() -> None:
    model = object.__new__(model_module.GeminiModel)
    model.ollama_router_model = "router-model"
    model.ollama_router_num_predict = 800
    model.ollama_router_num_ctx = 4096
    model.ollama_router_think = False
    model.ollama_keep_alive = "10m"
    model.ollama_base_url = "http://127.0.0.1:11434"
    model.ollama_router_timeout_seconds = 90

    original_post = router_backends_module.requests.post

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {
                "message": {
                    "content": 'invoke_cua_cli(task="ping google.com from terminal")',
                },
            }

    def _fake_post(url, json, timeout):
        del url, json, timeout
        return _FakeResponse()

    router_backends_module.requests.post = _fake_post
    try:
        route = model._call_ollama_router_sync("ping google.com from terminal")
    finally:
        router_backends_module.requests.post = original_post

    assert route == {"agent": "cua_cli", "task": "ping google.com from terminal"}


def test_router_provider_order_uses_fallback_provider() -> None:
    assert routing_policy._router_provider_order(
        router_provider="openrouter",
        nvidia_enabled=True,
        openrouter_enabled=True,
        ollama_enabled=True,
    ) == ["openrouter", "nvidia", "ollama"]
    assert routing_policy._router_provider_order(
        router_provider="nvidia",
        nvidia_enabled=True,
        openrouter_enabled=True,
        ollama_enabled=True,
    ) == ["nvidia", "ollama"]
    assert routing_policy._router_provider_order(
        router_provider="ollama",
        nvidia_enabled=True,
        openrouter_enabled=True,
        ollama_enabled=True,
    ) == ["ollama", "nvidia", "openrouter"]


def test_openrouter_free_vision_defaults_prefer_gemma() -> None:
    originals = {
        key: os.environ.get(key)
        for key in (
            "OPENROUTER_VISION_MODEL",
            "OPENROUTER_JARVIS_MODEL",
            "OPENROUTER_BROWSER_MODEL",
            "OPENROUTER_MODEL",
            "OPENROUTER_FALLBACK_MODEL",
        )
    }
    try:
        for key in originals:
            os.environ[key] = ""
        models = openrouter_fallback_module.get_openrouter_models("vision")
        assert models[:5] == [
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
            "nvidia/nemotron-nano-12b-v2-vl:free",
            "openrouter/free",
        ], models

        os.environ["OPENROUTER_VISION_MODEL"] = "google/gemma-4-31b-it:free"
        pinned_models = openrouter_fallback_module.get_openrouter_models("vision")
        assert pinned_models[0] == "google/gemma-4-31b-it:free", pinned_models
        assert "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free" in pinned_models
        assert "openrouter/free" in pinned_models
    finally:
        for key, value in originals.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_openrouter_text_payload_supports_image_content() -> None:
    captured_payload: dict[str, Any] = {}
    original_post = router_backends_module.requests.post

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def _fake_post(url, headers, json, timeout):
        del url, headers, timeout
        captured_payload.update(json)
        return _FakeResponse()

    router_backends_module.requests.post = _fake_post
    try:
        text = router_backends_module.call_openrouter_text_sync(
            openrouter_api_key="key",
            openrouter_url="https://openrouter.example/chat/completions",
            openrouter_site_url="",
            openrouter_site_name="JARVIS",
            openrouter_timeout_seconds=10,
            model_name="google/gemma-4-31b-it:free",
            system_prompt="system",
            user_prompt="look",
            temperature=0.1,
            max_tokens=20,
            clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
            image_data_url="data:image/png;base64,abc",
        )
    finally:
        router_backends_module.requests.post = original_post

    assert text == "ok"
    content = captured_payload["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64,abc"


def test_nvidia_router_uses_direct_nvidia_endpoint() -> None:
    captured: dict[str, Any] = {}
    original_post = router_backends_module.requests.post

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": '{"agent":"cua_cli","task":"ping google.com"}'}}]}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["json"] = dict(json)
        captured["timeout"] = timeout
        return _FakeResponse()

    router_backends_module.requests.post = _fake_post
    try:
        route = router_backends_module.call_nvidia_router_sync(
            nvidia_api_key="nvidia-key",
            nvidia_url="https://integrate.api.nvidia.com/v1/chat/completions",
            nvidia_timeout_seconds=30,
            nvidia_router_model="qwen/qwen3.5-397b-a17b",
            nvidia_router_max_tokens=260,
            router_system_prompt="system",
            prompt="ping google.com",
            clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
            parse_json_object_from_text=routing_policy._parse_json_object_from_text,
        )
    finally:
        router_backends_module.requests.post = original_post

    assert route == {"agent": "cua_cli", "task": "ping google.com"}
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer nvidia-key"
    assert "HTTP-Referer" not in captured["headers"]
    assert captured["json"]["model"] == "qwen/qwen3.5-397b-a17b"
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_openrouter_tool_payload_parses_tool_calls() -> None:
    original_post = router_backends_module.requests.post

    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "go_to_element",
                                        "arguments": "{\"target_description\":\"button\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }

    def _fake_post(url, headers, json, timeout):
        del url, headers, json, timeout
        return _FakeResponse()

    router_backends_module.requests.post = _fake_post
    try:
        result = router_backends_module.call_openrouter_tool_sync(
            openrouter_api_key="key",
            openrouter_url="https://openrouter.example/chat/completions",
            openrouter_site_url="",
            openrouter_site_name="JARVIS",
            openrouter_timeout_seconds=10,
            model_name="google/gemma-4-31b-it:free",
            system_prompt="system",
            user_prompt="click",
            function_declarations=[
                {
                    "name": "go_to_element",
                    "description": "Move",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            temperature=0.1,
            max_tokens=20,
            clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
        )
    finally:
        router_backends_module.requests.post = original_post

    assert result == {
        "text": "",
        "tool_calls": [
            {
                "name": "go_to_element",
                "arguments": {"target_description": "button"},
            }
        ],
    }


async def test_openrouter_router_failure_falls_back_to_ollama() -> None:
    model = object.__new__(model_module.GeminiModel)
    model.router_provider = "openrouter"
    model.nvidia_api_key = ""
    model.nvidia_router_model = ""
    model.nvidia_url = ""
    model.openrouter_api_key = "bad-key"
    model.openrouter_router_model = "openrouter-router"
    model.openrouter_url = "https://openrouter.invalid"
    model.openrouter_timeout_seconds = 45
    model.ollama_router_model = "ollama-router"
    model.ollama_base_url = "http://127.0.0.1:11434"
    model.ollama_router_timeout_seconds = 90

    calls: list[str] = []

    def _failing_openrouter(prompt: str) -> dict[str, Any]:
        calls.append("openrouter")
        raise RuntimeError("OpenRouter HTTP 401: User not found")

    def _working_ollama(prompt: str) -> dict[str, Any]:
        calls.append("ollama")
        return {"agent": "direct", "response_text": "done"}

    async def _fake_set_model_name(name: str) -> None:
        return None

    original_set_model_name = model_module.set_model_name
    model._call_openrouter_router_sync = _failing_openrouter
    model._call_ollama_router_sync = _working_ollama
    model_module.set_model_name = _fake_set_model_name
    try:
        route = await model.route_request("# User's Latest Request:\nhello")
    finally:
        model_module.set_model_name = original_set_model_name

    assert calls == ["openrouter", "ollama"], calls
    assert route == {"agent": "direct", "response_text": "done"}, route


def test_window_management_is_execution_not_visual_explanation() -> None:
    prompt = "Minimize the codex app on my screen"
    route = routing_policy._apply_routing_guardrails(
        user_prompt=prompt,
        routing_result={"agent": "jarvis", "query": prompt},
        latest_screen_context=None,
    )

    assert routing_policy._is_execution_request(prompt) is True
    assert routing_policy._is_visual_explanation_request(prompt) is False
    assert route == {"agent": "cua_vision", "task": prompt}


async def run_checks() -> None:
    test_window_management_is_execution_not_visual_explanation()
    test_router_refusal_task_is_replaced_with_original_request()
    test_ollama_router_payload_disables_thinking()
    test_ollama_router_accepts_legacy_tool_call_text()
    test_router_provider_order_uses_fallback_provider()
    test_openrouter_free_vision_defaults_prefer_gemma()
    test_openrouter_text_payload_supports_image_content()
    test_nvidia_router_uses_direct_nvidia_endpoint()
    test_openrouter_tool_payload_parses_tool_calls()
    await test_openrouter_router_failure_falls_back_to_ollama()
    await test_chains_multiple_agents_then_finishes()
    await test_direct_response_preserves_full_assistant_message()
    test_router_normalization_preserves_full_direct_response()
    test_router_normalization_accepts_web_qa_route()
    await test_web_qa_route_executes_agent_and_finishes()
    await test_repeated_step_loop_recovers_and_finishes()
    await test_single_full_agent_step_finishes_without_followup_router()
    await test_completed_browser_summary_finishes_when_router_rewrites_task()
    await test_partial_browser_step_continues_with_visual_agent_before_finishing()
    await test_invalid_route_result_falls_back_to_direct()
    await test_direct_response_repeat_artifact_is_sanitized()
    await test_screen_context_then_actionable_agent()
    await test_visual_question_uses_router_then_jarvis()
    await test_execution_request_reroutes_jarvis_to_cli()
    await test_execution_request_reroutes_jarvis_to_browser_when_url_task()
    await test_window_management_request_reroutes_jarvis_to_cua_vision()
    await test_call_gemini_uses_session_scoped_rapid_history()
    await test_contextual_file_followups_enrich_cli_tasks()
    await test_direct_qa_bypasses_router_and_screenshot_capture()
    await test_direct_qa_preserves_structured_response_formatting()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_router_chaining] All checks passed.")
