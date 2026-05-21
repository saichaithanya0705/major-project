"""
Routing policy helpers for rapid-model orchestration.

This module is intentionally pure and side-effect light so routing behavior can
be tested and evolved independently from model/provider orchestration.
"""

from __future__ import annotations

from models.browser_resume_route import build_browser_resume_route
from models.routing_decision_policy import (
    normalize_router_decision_payload as _normalize_router_decision_payload,
)
from models.router_provider_policy import router_provider_order as _router_provider_order
from models.routing_surface_policy import (
    BROWSER_EXECUTION_MARKERS as _BROWSER_EXECUTION_MARKERS,
    BROWSER_SURFACE_MARKERS as _BROWSER_SURFACE_MARKERS,
    CLI_EXECUTION_MARKERS as _CLI_EXECUTION_MARKERS,
    DESKTOP_SURFACE_MARKERS as _DESKTOP_SURFACE_MARKERS,
    EXECUTION_INTENT_MARKERS as _EXECUTION_INTENT_MARKERS,
    SPECIFIC_BROWSER_CONTEXT_MARKERS as _SPECIFIC_BROWSER_CONTEXT_MARKERS,
    VISION_EXECUTION_MARKERS as _VISION_EXECUTION_MARKERS,
    WINDOW_MANAGEMENT_MARKERS as _WINDOW_MANAGEMENT_MARKERS,
    choose_actionable_agent as _choose_actionable_agent,
    is_execution_request as _is_execution_request,
    is_window_management_request as _is_window_management_request,
    requires_desktop_control_surface as _requires_desktop_control_surface,
)
from models.routing_question_policy import (
    VISUAL_EXPLAIN_MARKERS as _VISUAL_EXPLAIN_MARKERS,
    is_direct_qa_request as _is_direct_qa_request,
    is_visual_explanation_request as _is_visual_explanation_request,
    is_web_qa_request as _is_web_qa_request,
)
from models.routing_step_identity import (
    routing_signature as _routing_signature,
    routing_task_text as _routing_task_text,
)
from models.routing_prompt_state import (
    format_blocked_step_signatures_for_prompt as _format_blocked_step_signatures_for_prompt,
    format_chain_state_for_prompt as _format_chain_state_for_prompt,
)
from models.screen_context_policy import (
    normalize_screen_context_payload as _normalize_screen_context_payload,
    screen_context_message as _screen_context_message,
)
from models.routing_guardrails import (
    GuardrailApplication,
    apply_routing_guardrails as _apply_routing_guardrails_with_metadata,
    apply_routing_guardrails_route as _apply_routing_guardrails,
)
from models.routing_prompt_parser import extract_latest_request_from_router_prompt
from models.router_backend_types import JsonValue
from models.routing_payload_parser import (
    JsonObjectBoundary,
    JsonObject,
    RoutePayload,
    ScreenContextPayload,
    parse_json_object_boundary_text,
)
from models.text_normalization import (
    clean_text as _clean_text,
    format_direct_response_text as _format_direct_response_text,
)


def _parse_json_object_boundary_from_text(raw_text: str) -> JsonObjectBoundary:
    return parse_json_object_boundary_text(raw_text)


def _parse_json_object_from_text(raw_text: str) -> JsonObject:
    boundary = _parse_json_object_boundary_from_text(raw_text)
    if boundary.kind == "parsed":
        return boundary.payload
    return {}


def _extract_latest_request(prompt: str) -> str:
    return extract_latest_request_from_router_prompt(prompt)
