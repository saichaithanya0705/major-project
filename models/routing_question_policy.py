"""
Question-classification helpers for rapid routing decisions.
"""

from __future__ import annotations

from models.routing_intent_policy import (
    has_context_dependent_reference,
    is_direct_qa_request as classify_direct_qa_request,
    is_web_qa_request as classify_web_qa_request,
)
from models.routing_surface_policy import (
    BROWSER_EXECUTION_MARKERS,
    BROWSER_SURFACE_MARKERS,
    CLI_EXECUTION_MARKERS,
    is_execution_request,
    is_window_management_request,
)

VISUAL_EXPLAIN_MARKERS = (
    "analyze my screen",
    "analyse my screen",
    "analyze the screen",
    "analyse the screen",
    "analyze this screen",
    "analyse this screen",
    "analyze what's on my screen",
    "analyse what's on my screen",
    "look at my screen",
    "look at the screen",
    "look at this screen",
    "check my screen",
    "check the screen",
    "inspect my screen",
    "inspect the screen",
    "what do you see",
    "what do u see",
    "what's on my screen",
    "what is on my screen",
    "what am i looking at",
    "describe my screen",
    "describe what you see",
    "explain what you see",
    "explain my screen",
    "explain this screen",
    "tell me what you see",
    "can you see my screen",
)


def is_visual_explanation_request(user_prompt: str) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    if is_execution_request(lowered):
        return False
    if is_window_management_request(lowered):
        return False

    screen_analysis_terms = (
        "analyze",
        "analyse",
        "describe",
        "explain",
        "look at",
        "check",
        "inspect",
        "what",
        "what's",
        "what is",
        "tell me",
    )
    mentions_screen = "screen" in lowered or "what you see" in lowered
    if mentions_screen and any(term in lowered for term in screen_analysis_terms):
        return True

    if any(marker in lowered for marker in VISUAL_EXPLAIN_MARKERS):
        return True

    if lowered.startswith("what is this") or lowered.startswith("what's this"):
        return True
    if lowered.startswith("what is that") or lowered.startswith("what's that"):
        return True
    if "on my screen" in lowered and lowered.endswith("?"):
        return True
    return False


def is_direct_qa_request(user_prompt: str) -> bool:
    return classify_direct_qa_request(
        user_prompt,
        is_web_qa_request_predicate=is_web_qa_request,
        is_execution_request=is_execution_request,
        is_visual_explanation_request=is_visual_explanation_request,
        has_context_dependent_reference_predicate=has_context_dependent_reference,
        cli_execution_markers=CLI_EXECUTION_MARKERS,
        browser_surface_markers=BROWSER_SURFACE_MARKERS,
    )


def is_web_qa_request(user_prompt: str) -> bool:
    return classify_web_qa_request(
        user_prompt,
        is_visual_explanation_request=is_visual_explanation_request,
        has_context_dependent_reference_predicate=has_context_dependent_reference,
        cli_execution_markers=CLI_EXECUTION_MARKERS,
        browser_execution_markers=BROWSER_EXECUTION_MARKERS,
    )


__all__ = [
    "VISUAL_EXPLAIN_MARKERS",
    "is_direct_qa_request",
    "is_visual_explanation_request",
    "is_web_qa_request",
]
