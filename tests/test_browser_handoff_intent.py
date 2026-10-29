"""Regression tests for explicit browser-chat handoffs."""

from agents.browser.handoff_intent import parse_browser_handoff
from models.routing.routing_guardrails import apply_routing_guardrails


def test_explicit_handoff_extracts_a_safe_direct_url() -> None:
    intent = parse_browser_handoff(
        "  @Browser inspect https://example.test/form?step=one and leave it as a draft"
    )

    assert intent is not None
    assert intent.task == "inspect https://example.test/form?step=one and leave it as a draft"
    assert intent.direct_url == "https://example.test/form?step=one"
    assert intent.tab_policy == "owned_url"


def test_current_tab_language_prevents_owned_tab_creation() -> None:
    intent = parse_browser_handoff("@browser use the current tab at https://example.test/form")

    assert intent is not None
    assert intent.tab_policy == "current"


def test_marker_must_be_leading_and_have_an_objective() -> None:
    assert parse_browser_handoff("Explain what @browser means") is None
    assert parse_browser_handoff("@browser   ") is None


def test_explicit_handoff_overrides_an_ambiguous_router_reply(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_BROWSER_MODE", "extension")

    result = apply_routing_guardrails(
        user_prompt="@browser inspect https://example.test/form",
        routing_result={"agent": "direct", "response_text": "What would you like to do?"},
        latest_screen_context=None,
    )

    assert result.route == {"agent": "browser", "task": "inspect https://example.test/form"}
    assert result.rewrite_reason == "explicit_browser_handoff"
