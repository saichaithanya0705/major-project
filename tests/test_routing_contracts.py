"""
Checks for typed routing contract validation.

Usage:
    python tests/test_routing_contracts.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.contracts import RouteDecision, RoutedStepResult


def run_checks() -> None:
    direct = RouteDecision(agent="direct", response_text="done")
    assert direct.as_dict() == {"agent": "direct", "response_text": "done"}

    jarvis = RouteDecision(agent="jarvis", query="what is on my screen")
    assert jarvis.as_dict() == {"agent": "jarvis", "query": "what is on my screen"}

    browser = RouteDecision(agent="browser", task="open example.com")
    assert browser.as_dict() == {"agent": "browser", "task": "open example.com"}

    screen_context = RouteDecision(agent="screen_context", task="inspect", focus="repo url")
    assert screen_context.as_dict() == {"agent": "screen_context", "task": "inspect", "focus": "repo url"}

    step = RoutedStepResult(
        agent="browser",
        task="open page",
        success=True,
        message="done",
        source="browser_use",
    )
    assert step.as_dict()["agent"] == "browser"

    try:
        RouteDecision(agent="direct", response_text="   ")
        raise AssertionError("Expected direct route contract validation to fail.")
    except ValueError as exc:
        assert "response_text" in str(exc)

    try:
        RouteDecision(agent="browser", task="")
        raise AssertionError("Expected browser route contract validation to fail.")
    except ValueError as exc:
        assert "browser route decisions require task" in str(exc).lower()


if __name__ == "__main__":
    run_checks()
    print("[test_routing_contracts] All checks passed.")
