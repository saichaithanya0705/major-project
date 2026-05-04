"""
Checks delegated-agent stop and resume lifecycle behavior.

Usage:
    python tests/test_agent_stop_resume.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.agent import BrowserAgent
import models.models as model_module


class _FakeBrowserUseAgent:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _FakeAgentState:
    def __init__(self):
        self.paused = True
        self.stopped = True
        self.follow_up_task = False


async def test_stop_request_reaches_registered_browser_use_agent() -> None:
    original_agents = set(BrowserAgent._active_browser_use_agents)
    original_stop_requested = BrowserAgent._browser_use_stop_requested
    try:
        BrowserAgent._active_browser_use_agents.clear()
        BrowserAgent.clear_stop_request()
        fake_agent = _FakeBrowserUseAgent()

        BrowserAgent._register_active_browser_use_agent(fake_agent)
        stopped = BrowserAgent.request_stop_all()

        assert stopped == 1, stopped
        assert fake_agent.stop_calls == 1, fake_agent.stop_calls
        assert await BrowserAgent._should_stop_browser_use_agent()
    finally:
        BrowserAgent._active_browser_use_agents = original_agents
        BrowserAgent._browser_use_stop_requested = original_stop_requested


async def test_interrupted_browser_use_state_can_be_resumed_without_losing_context() -> None:
    original_state = BrowserAgent._interrupted_browser_use_state
    original_task = BrowserAgent._interrupted_browser_use_task
    original_summary = BrowserAgent._interrupted_browser_use_summary
    try:
        state = _FakeAgentState()
        fake_agent = type("AgentWithState", (), {"state": state})()
        BrowserAgent._remember_interrupted_browser_use_agent(
            fake_agent,
            task="fill the application form",
            summary="Stopped after opening the form.",
        )

        assert BrowserAgent.has_interrupted_work()
        assert BrowserAgent.resolve_resume_task("continue") == "fill the application form"

        resumed_state = BrowserAgent._consume_resume_state_for_task("fill the application form")

        assert resumed_state is state
        assert resumed_state.paused is False
        assert resumed_state.stopped is False
        assert resumed_state.follow_up_task is True
    finally:
        BrowserAgent._interrupted_browser_use_state = original_state
        BrowserAgent._interrupted_browser_use_task = original_task
        BrowserAgent._interrupted_browser_use_summary = original_summary


async def test_router_routes_continue_to_interrupted_browser_work() -> None:
    original_state = BrowserAgent._interrupted_browser_use_state
    original_task = BrowserAgent._interrupted_browser_use_task
    original_summary = BrowserAgent._interrupted_browser_use_summary
    try:
        BrowserAgent._interrupted_browser_use_state = _FakeAgentState()
        BrowserAgent._interrupted_browser_use_task = "open the dashboard and finish setup"
        BrowserAgent._interrupted_browser_use_summary = "Stopped during browser setup."

        routed = model_module._resume_interrupted_agent_route("continue where you left off")

        assert routed == {
            "agent": "browser",
            "task": "open the dashboard and finish setup",
        }, routed
    finally:
        BrowserAgent._interrupted_browser_use_state = original_state
        BrowserAgent._interrupted_browser_use_task = original_task
        BrowserAgent._interrupted_browser_use_summary = original_summary


if __name__ == "__main__":
    asyncio.run(test_stop_request_reaches_registered_browser_use_agent())
    asyncio.run(test_interrupted_browser_use_state_can_be_resumed_without_losing_context())
    asyncio.run(test_router_routes_continue_to_interrupted_browser_work())
    print("[test_agent_stop_resume] All checks passed.")
