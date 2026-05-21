"""
Checks for typed routing contract validation.

Usage:
    python tests/test_routing_contracts.py
"""

import os
import sys
from typing import get_args, get_origin, get_type_hints

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.agent_step_execution_runtime as agent_step_execution_runtime
from models.contracts import RouteDecision, RoutedStepResult
import models.direct_response_policy as direct_response_policy
import models.orchestrator_planner as orchestrator_planner
import models.rapid_orchestrator_contracts as rapid_orchestrator_contracts
import models.rapid_step_payloads as rapid_step_payloads
import models.router_backend_types as router_backend_types
import models.router_runtime_contracts as router_runtime_contracts
import models.routing_decision_policy as routing_decision_policy
import models.routing_guardrails as routing_guardrails
import models.routing_prompt_state as routing_prompt_state
import models.routing_policy as routing_policy
import models.routing_question_policy as routing_question_policy
import models.routing_surface_policy as routing_surface_policy
import models.screen_context_policy as screen_context_policy
from models.orchestrator_contracts import OrchestratorTask
from models.routing_payload_parser import (
    BlockedStepSignature,
    DirectResponseArgsPayload,
    EmptyJsonObjectBoundary,
    MalformedJsonObjectBoundary,
    PlanTaskPayload,
    ParsedJsonObjectBoundary,
    RouteAgentName,
    RoutePayload,
    RoutingResult,
    ScreenContextPayload,
    parse_json_object_boundary_text,
)


def test_json_object_parse_boundary_contract_distinguishes_empty_and_malformed() -> None:
    empty = parse_json_object_boundary_text("")
    malformed = parse_json_object_boundary_text('{"agent": ')

    assert isinstance(empty, EmptyJsonObjectBoundary)
    assert empty.kind == "empty"
    assert isinstance(malformed, MalformedJsonObjectBoundary)
    assert malformed.kind == "malformed"
    assert [failure.stage for failure in malformed.failures] == ["full_text"]


def test_json_object_parse_boundary_preserves_salvage_metadata() -> None:
    parsed = parse_json_object_boundary_text(
        'Route this request: {"agent":"browser","task":"open https://example.com"}'
    )

    assert isinstance(parsed, ParsedJsonObjectBoundary)
    assert parsed.kind == "parsed"
    assert parsed.payload == {
        "agent": "browser",
        "task": "open https://example.com",
    }
    assert parsed.mode == "embedded_object"
    assert parsed.salvaged is True
    assert [failure.stage for failure in parsed.failures] == ["full_text"]


def test_screen_context_policy_helpers_keep_typed_payload_boundary() -> None:
    format_hints = get_type_hints(routing_policy._format_chain_state_for_prompt)
    choose_hints = get_type_hints(routing_policy._choose_actionable_agent)
    extracted_choose_hints = get_type_hints(routing_surface_policy.choose_actionable_agent)
    message_hints = get_type_hints(routing_policy._screen_context_message)

    assert get_origin(format_hints["chain_steps"]) is list
    assert get_args(format_hints["chain_steps"]) == (rapid_orchestrator_contracts.RapidAgentStepResult,)
    assert format_hints["latest_screen_context"] == ScreenContextPayload | None
    assert choose_hints["latest_screen_context"] == ScreenContextPayload | None
    assert extracted_choose_hints["latest_screen_context"] == ScreenContextPayload | None
    assert extracted_choose_hints["return"] == RouteAgentName
    assert message_hints["screen_context"] is ScreenContextPayload


def test_direct_response_policy_uses_typed_chain_step_contract() -> None:
    hints = get_type_hints(direct_response_policy.finalize_direct_response_text)

    assert get_args(hints["chain_steps"]) == (rapid_orchestrator_contracts.RapidAgentStepResult,)
    assert hints["user_prompt"] is str
    assert hints["text"] is object


def test_shared_routing_contract_aliases_are_reused_across_layers() -> None:
    normalize_hints = get_type_hints(routing_policy._normalize_router_decision_payload)
    extracted_normalize_hints = get_type_hints(routing_decision_policy.normalize_router_decision_payload)
    planner_hints = get_type_hints(orchestrator_planner.normalize_orchestration_plan_payload)
    chain_hints = get_type_hints(routing_prompt_state.format_chain_state_for_prompt)
    blocked_hints = get_type_hints(routing_prompt_state.format_blocked_step_signatures_for_prompt)
    route_hints = get_type_hints(RoutePayload)
    plan_task_hints = get_type_hints(PlanTaskPayload)
    orchestrator_task_hints = get_type_hints(OrchestratorTask)

    assert rapid_orchestrator_contracts.RapidRoutingResult == RoutingResult
    assert router_runtime_contracts.RouterNormalizedPayload == RoutingResult
    assert normalize_hints["return"] == RoutingResult
    assert extracted_normalize_hints["return"] == RoutingResult
    assert planner_hints["payload"] == RoutingResult
    assert DirectResponseArgsPayload == router_backend_types.JsonObject
    assert route_hints["agent"] == RouteAgentName
    assert get_origin(route_hints["direct_response_args"]) is dict
    assert route_hints["orchestrator_context"] is rapid_step_payloads.RapidTaskExecutionContextPayload
    assert plan_task_hints["direct_response_args"] == route_hints["direct_response_args"]
    assert orchestrator_task_hints["route"] == RoutePayload
    assert chain_hints["blocked_step_signatures"] == set[BlockedStepSignature] | None
    assert blocked_hints["blocked_step_signatures"] == set[BlockedStepSignature] | None


def test_extracted_prompt_and_screen_context_boundaries_keep_typed_contracts() -> None:
    prompt_hints = get_type_hints(routing_prompt_state.format_chain_state_for_prompt)
    screen_normalize_hints = get_type_hints(screen_context_policy.normalize_screen_context_payload)
    screen_message_hints = get_type_hints(screen_context_policy.screen_context_message)

    assert prompt_hints["latest_screen_context"] == ScreenContextPayload | None
    assert screen_normalize_hints["return"] is ScreenContextPayload
    assert screen_message_hints["screen_context"] is ScreenContextPayload


def test_extracted_question_policy_helpers_keep_bool_contracts() -> None:
    direct_hints = get_type_hints(routing_question_policy.is_direct_qa_request)
    visual_hints = get_type_hints(routing_question_policy.is_visual_explanation_request)
    web_hints = get_type_hints(routing_question_policy.is_web_qa_request)

    assert direct_hints["user_prompt"] is str
    assert direct_hints["return"] is bool
    assert visual_hints["user_prompt"] is str
    assert visual_hints["return"] is bool
    assert web_hints["user_prompt"] is str
    assert web_hints["return"] is bool


def test_agent_execution_runtime_uses_typed_json_safe_payload_contracts() -> None:
    payload_hints = get_type_hints(agent_step_execution_runtime.AgentExecutionPayload)
    critic_hints = get_type_hints(agent_step_execution_runtime.AgentExecutionOutcome.critic.fget)
    tool_call_hints = get_type_hints(agent_step_execution_runtime.AgentExecutionOutcome.tool_calls.fget)

    assert get_origin(payload_hints["critic"]) is dict
    assert get_args(payload_hints["critic"])[0] is str
    assert get_origin(critic_hints["return"]) is get_origin(router_backend_types.JsonObject | None)
    assert get_args(critic_hints["return"])[1] is type(None)
    assert tool_call_hints["return"] == list[rapid_step_payloads.RapidToolCallRecord] | None


def test_guardrail_contracts_preserve_typed_route_agent_selection() -> None:
    choose_hints = get_type_hints(routing_guardrails.apply_routing_guardrails)
    route_hints = get_type_hints(routing_guardrails.apply_routing_guardrails_route)

    assert choose_hints["routing_result"] == RoutePayload
    assert choose_hints["latest_screen_context"] == ScreenContextPayload | None
    assert route_hints["return"] == RoutePayload


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
        complete=False,
        tool_calls=[{"tool_name": "write_file", "status": "success"}],
    )
    assert step.as_dict()["agent"] == "browser"
    assert step.as_dict()["complete"] is False
    assert step.as_dict()["tool_calls"] == [{"tool_name": "write_file", "status": "success"}]

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
