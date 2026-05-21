"""Checks extracted routing-policy helper boundaries."""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
import models.rapid_orchestrator_deps as rapid_orchestrator_deps
import models.routing_guardrails as routing_guardrails
import models.routing_question_policy as routing_question_policy
import models.router_runtime as router_runtime
import models.routing_decision_policy as routing_decision_policy
import models.routing_policy as routing_policy
import models.routing_prompt_state as routing_prompt_state
import models.routing_surface_policy as routing_surface_policy
import models.routing_step_identity as routing_step_identity
import models.screen_context_policy as screen_context_policy
import models.screen_context_runtime as screen_context_runtime


def test_routing_policy_prompt_helpers_are_extracted() -> None:
    assert (
        routing_policy._format_blocked_step_signatures_for_prompt
        is routing_prompt_state.format_blocked_step_signatures_for_prompt
    )
    assert (
        routing_policy._format_chain_state_for_prompt
        is routing_prompt_state.format_chain_state_for_prompt
    )


def test_routing_policy_screen_context_helpers_are_extracted() -> None:
    assert (
        routing_policy._normalize_screen_context_payload
        is screen_context_policy.normalize_screen_context_payload
    )
    assert routing_policy._screen_context_message is screen_context_policy.screen_context_message


def test_routing_policy_decision_normalization_helper_is_extracted() -> None:
    assert (
        routing_policy._normalize_router_decision_payload
        is routing_decision_policy.normalize_router_decision_payload
    )


def test_routing_policy_step_identity_helpers_are_extracted() -> None:
    assert routing_policy._routing_task_text is routing_step_identity.routing_task_text
    assert routing_policy._routing_signature is routing_step_identity.routing_signature


def test_routing_policy_surface_helpers_are_extracted() -> None:
    assert routing_policy._is_execution_request is routing_surface_policy.is_execution_request
    assert routing_policy._is_window_management_request is routing_surface_policy.is_window_management_request
    assert (
        routing_policy._requires_desktop_control_surface
        is routing_surface_policy.requires_desktop_control_surface
    )
    assert routing_policy._choose_actionable_agent is routing_surface_policy.choose_actionable_agent


def test_routing_policy_question_helpers_are_extracted() -> None:
    assert (
        routing_policy._is_visual_explanation_request
        is routing_question_policy.is_visual_explanation_request
    )
    assert routing_policy._is_direct_qa_request is routing_question_policy.is_direct_qa_request
    assert routing_policy._is_web_qa_request is routing_question_policy.is_web_qa_request


def test_routing_policy_guardrail_helpers_are_extracted() -> None:
    assert routing_policy._apply_routing_guardrails is routing_guardrails.apply_routing_guardrails_route
    assert (
        routing_policy._apply_routing_guardrails_with_metadata
        is routing_guardrails.apply_routing_guardrails
    )


def test_runtime_callers_use_extracted_prompt_and_screen_context_boundaries() -> None:
    assert (
        rapid_orchestrator_deps.format_chain_state_for_prompt
        is routing_prompt_state.format_chain_state_for_prompt
    )
    assert rapid_orchestrator_deps.screen_context_message is screen_context_policy.screen_context_message
    assert (
        screen_context_runtime._normalize_screen_context_payload
        is screen_context_policy.normalize_screen_context_payload
    )
    assert rapid_orchestrator_deps._routing_task_text is routing_step_identity.routing_task_text
    assert rapid_orchestrator_deps._routing_signature is routing_step_identity.routing_signature
    assert (
        router_runtime._normalize_router_decision_payload
        is routing_decision_policy.normalize_router_decision_payload
    )
    assert (
        model_module._normalize_router_decision_payload
        is routing_decision_policy.normalize_router_decision_payload
    )
    assert rapid_orchestrator_deps._is_direct_qa_request is routing_question_policy.is_direct_qa_request
    assert rapid_orchestrator_deps._apply_routing_guardrails is routing_guardrails.apply_routing_guardrails_route


def test_guardrail_defaults_use_extracted_surface_policy() -> None:
    (
        _build_browser_resume_route,
        _clean_text,
        choose_actionable_agent,
        is_execution_request,
        is_web_qa_request,
        requires_desktop_control_surface,
        _routing_task_text,
    ) = routing_guardrails._resolve_policy_helpers()

    assert choose_actionable_agent is routing_surface_policy.choose_actionable_agent
    assert is_execution_request is routing_surface_policy.is_execution_request
    assert is_web_qa_request is routing_question_policy.is_web_qa_request
    assert (
        requires_desktop_control_surface
        is routing_surface_policy.requires_desktop_control_surface
    )
