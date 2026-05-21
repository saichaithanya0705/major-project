import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.browser_resume_route as browser_resume_route
from models.routing_guardrails import apply_routing_guardrails
import models.routing_policy as routing_policy


def test_build_browser_resume_route_returns_browser_route() -> None:
    class _FakeBrowserAgent:
        @staticmethod
        def resolve_resume_task(user_prompt: str) -> str | None:
            assert user_prompt == "continue where you left off"
            return "finish checkout flow"

    route = browser_resume_route.build_browser_resume_route(
        "continue where you left off",
        browser_agent_loader=lambda: _FakeBrowserAgent,
    )

    assert route == {
        "agent": "browser",
        "task": "finish checkout flow",
    }
    assert browser_resume_route.get_last_browser_resume_route_failures() == ()


def test_build_browser_resume_route_records_loader_failure() -> None:
    browser_resume_route.clear_last_browser_resume_route_failures()

    def _failing_loader():
        raise RuntimeError("browser import exploded")

    route = browser_resume_route.build_browser_resume_route(
        "continue",
        browser_agent_loader=_failing_loader,
    )

    assert route is None
    failures = browser_resume_route.get_last_browser_resume_route_failures()
    assert len(failures) == 1
    failure = failures[0]
    assert failure.operation == "load_browser_agent"
    assert failure.user_prompt == "continue"
    assert "browser import exploded" in failure.message


def test_routing_guardrails_use_shared_browser_resume_route() -> None:
    original_build_browser_resume_route = routing_policy.build_browser_resume_route
    try:
        routing_policy.build_browser_resume_route = lambda _prompt: {
            "agent": "browser",
            "task": "resume current interrupted browser work",
        }

        guarded = routing_policy._apply_routing_guardrails(
            "continue where you left off",
            {"agent": "direct", "response_text": "ignored"},
            latest_screen_context=None,
        )
    finally:
        routing_policy.build_browser_resume_route = original_build_browser_resume_route

    assert guarded == {
        "agent": "browser",
        "task": "resume current interrupted browser work",
    }


def test_guardrail_helper_reports_resume_rewrite_provenance() -> None:
    guarded = apply_routing_guardrails(
        user_prompt="continue where you left off",
        routing_result={"agent": "direct", "response_text": "ignored"},
        latest_screen_context=None,
        build_browser_resume_route=lambda _prompt: {
            "agent": "browser",
            "task": "resume current interrupted browser work",
        },
    )

    assert guarded.route == {
        "agent": "browser",
        "task": "resume current interrupted browser work",
    }
    assert guarded.rewritten_from == {
        "agent": "direct",
        "response_text": "ignored",
    }
    assert guarded.rewrite_reason == "browser_resume"
