"""
Intent and deictic classification helpers for routing policy decisions.
"""

from __future__ import annotations

import re
from typing import Callable

TextPredicate = Callable[[str], bool]

_DIRECT_QA_START_MARKERS = (
    "tell me about",
    "tell me everything about",
    "who is",
    "who was",
    "what is",
    "what are",
    "what was",
    "explain",
    "define",
    "describe",
    "why is",
    "why are",
    "how does",
    "how do",
    "give me an overview of",
    "give me a summary of",
)
_WEB_QA_MARKERS = (
    "as of today",
    "as of now",
    "current",
    "currently",
    "latest",
    "live",
    "newest",
    "news",
    "recent",
    "recently",
    "today",
    "up to date",
    "up-to-date",
    "with citations",
    "with sources",
    "cite sources",
    "citation",
    "citations",
    "source-grounded",
    "sources",
    "web search",
    "search the web",
    "look up",
)
_WEB_QA_DYNAMIC_SUBJECT_MARKERS = (
    "ceo",
    "company",
    "companies",
    "court",
    "election",
    "law",
    "laws",
    "legal",
    "net worth",
    "politics",
    "president",
    "price",
    "prices",
    "regulation",
    "rules",
    "schedule",
    "score",
    "sports",
    "stock",
    "weather",
)
_CONTEXT_DEPENDENT_MARKERS = (
    "my screen",
    "the screen",
    "this screen",
    "on screen",
    "on my screen",
    "what you see",
    "currently open",
    "current page",
    "current tab",
    "this page",
    "this tab",
    "this repo",
    "this repository",
    "this file",
    "this folder",
    "this project",
    "this app",
    "this window",
    "that repo",
    "that url",
    "that page",
)
_BARE_DEICTIC_MARKERS = (
    "this",
    "that",
    "these",
    "those",
    "visible",
    "here",
)
_LOCAL_STATE_ANCHOR_MARKERS = (
    "screen",
    "page",
    "tab",
    "repo",
    "repository",
    "file",
    "folder",
    "project",
    "app",
    "window",
    "url",
)
_BROWSER_AUTOMATION_MARKERS = (
    "click",
    "fill",
    "submit",
    "open",
    "go to",
    "login",
    "log in",
    "sign in",
    "type",
)


def contains_phrase_or_word(text: str, marker: str) -> bool:
    if " " in marker:
        return marker in text
    return bool(re.search(rf"\b{re.escape(marker)}\b", text))


def matches_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False
    return any(contains_phrase_or_word(lowered, marker) for marker in markers)


def has_context_dependent_reference(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if matches_any_marker(lowered, _CONTEXT_DEPENDENT_MARKERS):
        return True
    if not matches_any_marker(lowered, _BARE_DEICTIC_MARKERS):
        return False
    return matches_any_marker(lowered, _LOCAL_STATE_ANCHOR_MARKERS)


def is_direct_qa_request(
    user_prompt: str,
    *,
    is_web_qa_request_predicate: TextPredicate | None = None,
    is_execution_request: TextPredicate | None = None,
    is_visual_explanation_request: TextPredicate | None = None,
    has_context_dependent_reference_predicate: TextPredicate | None = None,
    cli_execution_markers: tuple[str, ...] = (),
    browser_surface_markers: tuple[str, ...] = (),
) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    web_qa_predicate = is_web_qa_request_predicate or is_web_qa_request
    execution_predicate = is_execution_request or (lambda _text: False)
    visual_predicate = is_visual_explanation_request or (lambda _text: False)
    context_predicate = has_context_dependent_reference_predicate or has_context_dependent_reference

    if web_qa_predicate(lowered):
        return False
    if execution_predicate(lowered):
        return False
    if visual_predicate(lowered):
        return False
    if context_predicate(lowered):
        return False
    if matches_any_marker(lowered, cli_execution_markers):
        return False
    if matches_any_marker(lowered, browser_surface_markers):
        return False

    if any(lowered.startswith(marker) for marker in _DIRECT_QA_START_MARKERS):
        return True
    if " everything about " in f" {lowered} ":
        return True
    if re.match(r"^(who|what|why|how|when|where)\b", lowered):
        return True
    return False


def is_web_qa_request(
    user_prompt: str,
    *,
    is_visual_explanation_request: TextPredicate | None = None,
    has_context_dependent_reference_predicate: TextPredicate | None = None,
    cli_execution_markers: tuple[str, ...] = (),
    browser_execution_markers: tuple[str, ...] = (),
) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    visual_predicate = is_visual_explanation_request or (lambda _text: False)
    context_predicate = has_context_dependent_reference_predicate or has_context_dependent_reference

    if visual_predicate(lowered):
        return False
    if context_predicate(lowered):
        return False
    if matches_any_marker(lowered, cli_execution_markers):
        return False

    if matches_any_marker(lowered, _WEB_QA_MARKERS):
        if not matches_any_marker(lowered, browser_execution_markers):
            return True
        return not matches_any_marker(lowered, _BROWSER_AUTOMATION_MARKERS)

    if matches_any_marker(lowered, _WEB_QA_DYNAMIC_SUBJECT_MARKERS):
        return bool(re.match(r"^(who|what|why|how|when|where|tell me|give me)\b", lowered))
    return False


__all__ = [
    "contains_phrase_or_word",
    "has_context_dependent_reference",
    "is_direct_qa_request",
    "is_web_qa_request",
    "matches_any_marker",
]
