"""
Checks for the router backend parsing seam.
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.contracts import RouteDecision
from models.router_backend_parsing import (
    normalize_tool_call,
    normalize_route_decision_payload,
    parse_router_response,
    parse_text_tool_calls,
)
from models.router_backend_types import NormalizedToolCall


def test_normalize_tool_call_returns_typed_contract() -> None:
    call = normalize_tool_call(
        {
            "function": {
                "name": "go_to_element",
                "arguments": '{"target_description":"search field","retry":2}',
            }
        },
        {"go_to_element"},
    )

    assert isinstance(call, NormalizedToolCall)
    assert call.as_dict() == {
        "name": "go_to_element",
        "arguments": {
            "target_description": "search field",
            "retry": 2,
        },
    }


def test_normalize_tool_call_rejects_non_object_arguments() -> None:
    call = normalize_tool_call(
        {
            "function": {
                "name": "go_to_element",
                "arguments": '["search field"]',
            }
        },
        {"go_to_element"},
    )

    assert call is None


def test_parse_text_tool_calls_returns_typed_results() -> None:
    parsed = parse_text_tool_calls(
        '{"tool_calls":[{"name":"go_to_element","arguments":{"target_description":"button"}}]}',
        {"go_to_element"},
    )

    assert len(parsed) == 1
    assert all(isinstance(item, NormalizedToolCall) for item in parsed)
    assert parsed[0].arguments["target_description"] == "button"


def test_parse_router_response_preserves_structured_json_for_runtime_normalization() -> None:
    route = parse_router_response(
        '{"agent":"direct","response_text":"done"}',
        lambda text: {"agent": "direct", "response_text": "done"} if text else {},
    )

    assert route == {"agent": "direct", "response_text": "done"}


def test_parse_router_response_preserves_unknown_agent_json_for_runtime_normalization_failure() -> None:
    route = parse_router_response(
        '{"agent":"banana","task":"do something"}',
        lambda text: {"agent": "banana", "task": "do something"} if text else {},
    )

    assert route == {"agent": "banana", "task": "do something"}


def test_normalize_route_decision_payload_uses_latest_request_for_refusals() -> None:
    route = normalize_route_decision_payload(
        {"agent": "browser", "task": "I can't help with that request."},
        latest_request="open https://example.com",
        clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
        format_direct_response_text=lambda value, fallback, max_len: str(value or fallback),
        looks_like_router_refusal=lambda text: text.startswith("I can't help"),
    )

    assert isinstance(route, RouteDecision)
    assert route.as_dict() == {"agent": "browser", "task": "open https://example.com"}


def test_normalize_route_decision_payload_applies_direct_fallback_text() -> None:
    route = normalize_route_decision_payload(
        {"agent": "direct"},
        latest_request="ignored",
        clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
        format_direct_response_text=lambda value, fallback, max_len: str(value or fallback),
        default_direct_response="Routing complete.",
    )

    assert isinstance(route, RouteDecision)
    assert route.as_dict() == {"agent": "direct", "response_text": "Routing complete."}


def test_normalize_route_decision_payload_promotes_direct_text_from_args() -> None:
    route = normalize_route_decision_payload(
        {
            "agent": "direct",
            "direct_response_args": {"text": "Routing complete.", "variant": "compact"},
        },
        latest_request="ignored",
        clean_text=lambda value, fallback, max_len: str(value or fallback)[:max_len],
        format_direct_response_text=lambda value, fallback, max_len: str(value or fallback),
        default_direct_response="unused",
    )

    assert isinstance(route, RouteDecision)
    assert route.as_dict() == {
        "agent": "direct",
        "response_text": "Routing complete.",
        "direct_response_args": {"variant": "compact"},
    }
