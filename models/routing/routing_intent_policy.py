"""
Intent and deictic classification helpers for routing policy decisions.
"""

from __future__ import annotations

import re
from core.local_inspection import is_local_machine_state_request
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
    "meaning of",
    "synonym for",
    "antonym for",
)
_SOURCE_GROUNDED_MARKERS = (
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
_DYNAMIC_WEB_SUBJECT_MARKERS = (
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
_DIRECT_CHAT_EXACT_MARKERS = (
    "bye",
    "goodbye",
    "good morning",
    "good night",
    "good afternoon",
    "good evening",
    "ok",
    "okay",
    "cool",
    "nice",
    "thanks",
    "thank you",
)
_DIRECT_CHAT_START_MARKERS = (
    "can we chat",
    "can we talk",
    "chat with me",
    "good morning",
    "good night",
    "good afternoon",
    "good evening",
    "how are you",
    "meaning of",
    "tell me a joke",
    "tell a joke",
    "thanks",
    "thank you",
    "what's up",
    "whats up",
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
_SOFTWARE_TOPIC_MARKERS = frozenset({"python", "node", "git", "npm", "pnpm", "yarn", "pip"})
_SOFTWARE_OPERATION_RE = re.compile(
    r"(?:^|\b(?:and|then)\s+)(?:(?:please|can you|could you|would you)\s+)*"
    r"(?:run|execute|install|uninstall|upgrade|clone|edit|fix|build|deploy|start|stop|delete|create|debug)\b"
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


def is_basic_time_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    return bool(
        re.match(
            r"^(?:what(?:'s| is)?\s+)?(?:the\s+)?(?:current\s+)?time\b",
            lowered,
        )
        or re.match(r"^time\s+(?:now|in|at|for)\b", lowered)
        or re.match(r"^(?:what(?:'s| is)?\s+)?(?:the\s+)?(?:current\s+)?date\b", lowered)
        or re.match(r"^date\s+(?:today|now|in|for)\b", lowered)
    )


def is_basic_weather_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    return bool(
        re.match(r"^(?:what(?:'s| is)?\s+)?(?:the\s+)?weather\b", lowered)
        or re.match(r"^forecast\b", lowered)
    )


def is_basic_direct_chat_request(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if lowered in _DIRECT_CHAT_EXACT_MARKERS:
        return True
    if any(lowered.startswith(marker) for marker in _DIRECT_CHAT_START_MARKERS):
        return True
    if is_basic_time_request(lowered) or is_basic_weather_request(lowered):
        return True
    return False


def _is_blocked_direct_intent(
    lowered: str,
    *,
    execution_predicate: TextPredicate,
    visual_predicate: TextPredicate,
    context_predicate: TextPredicate,
    cli_execution_markers: tuple[str, ...],
    browser_surface_markers: tuple[str, ...],
) -> bool:
    return (
        execution_predicate(lowered)
        or visual_predicate(lowered)
        or context_predicate(lowered)
        or matches_any_marker(lowered, cli_execution_markers)
        or matches_any_marker(lowered, browser_surface_markers)
    )


def has_context_dependent_reference(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return False
    if is_local_machine_state_request(lowered):
        return True
    if matches_any_marker(lowered, _CONTEXT_DEPENDENT_MARKERS):
        return True
    if not matches_any_marker(lowered, _BARE_DEICTIC_MARKERS):
        return False
    return matches_any_marker(lowered, _LOCAL_STATE_ANCHOR_MARKERS)


def is_direct_qa_request(
    user_prompt: str,
    *,
    is_source_grounded_qa_request_predicate: TextPredicate | None = None,
    is_execution_request: TextPredicate | None = None,
    is_visual_explanation_request: TextPredicate | None = None,
    has_context_dependent_reference_predicate: TextPredicate | None = None,
    cli_execution_markers: tuple[str, ...] = (),
    browser_surface_markers: tuple[str, ...] = (),
) -> bool:
    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    web_search_predicate = (
        is_source_grounded_qa_request_predicate
        or is_source_grounded_qa_request
    )
    execution_predicate = is_execution_request or (lambda _text: False)
    visual_predicate = is_visual_explanation_request or (lambda _text: False)
    context_predicate = has_context_dependent_reference_predicate or has_context_dependent_reference

    # Source classification already excludes local state and real automation;
    # domain names and software subjects must not block factual web Q&A.
    if web_search_predicate(lowered):
        return True

    if _is_blocked_direct_intent(
        lowered,
        execution_predicate=execution_predicate,
        visual_predicate=visual_predicate,
        context_predicate=context_predicate,
        cli_execution_markers=cli_execution_markers,
        browser_surface_markers=browser_surface_markers,
    ):
        return False

    if any(lowered.startswith(marker) for marker in _DIRECT_QA_START_MARKERS):
        return True
    if lowered in {"hi", "hello", "hey", "yo"}:
        return True
    if re.match(r"^(hi|hello|hey)\b", lowered):
        return True
    if " everything about " in f" {lowered} ":
        return True
    if re.match(r"^(who|what|why|how|when|where)\b", lowered):
        return True
    return False


def is_direct_chat_request(
    user_prompt: str,
    *,
    is_source_grounded_qa_request_predicate: TextPredicate | None = None,
    is_execution_request: TextPredicate | None = None,
    is_visual_explanation_request: TextPredicate | None = None,
    has_context_dependent_reference_predicate: TextPredicate | None = None,
    cli_execution_markers: tuple[str, ...] = (),
    browser_surface_markers: tuple[str, ...] = (),
) -> bool:
    if is_direct_qa_request(
        user_prompt,
        is_source_grounded_qa_request_predicate=is_source_grounded_qa_request_predicate,
        is_execution_request=is_execution_request,
        is_visual_explanation_request=is_visual_explanation_request,
        has_context_dependent_reference_predicate=has_context_dependent_reference_predicate,
        cli_execution_markers=cli_execution_markers,
        browser_surface_markers=browser_surface_markers,
    ):
        return True

    lowered = (user_prompt or "").lower().strip()
    if not lowered:
        return False

    execution_predicate = is_execution_request or (lambda _text: False)
    visual_predicate = is_visual_explanation_request or (lambda _text: False)
    context_predicate = has_context_dependent_reference_predicate or has_context_dependent_reference
    if _is_blocked_direct_intent(
        lowered,
        execution_predicate=execution_predicate,
        visual_predicate=visual_predicate,
        context_predicate=context_predicate,
        cli_execution_markers=cli_execution_markers,
        browser_surface_markers=browser_surface_markers,
    ):
        return False

    return is_basic_direct_chat_request(lowered)


def is_source_grounded_qa_request(
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
        local_state_markers = tuple(marker for marker in cli_execution_markers if marker not in _SOFTWARE_TOPIC_MARKERS)
        if (matches_any_marker(lowered, local_state_markers)
                or _SOFTWARE_OPERATION_RE.search(lowered)
                or not matches_any_marker(lowered, _SOURCE_GROUNDED_MARKERS)):
            return False

    if matches_any_marker(lowered, _SOURCE_GROUNDED_MARKERS):
        if not matches_any_marker(lowered, browser_execution_markers):
            return True
        return not matches_any_marker(lowered, _BROWSER_AUTOMATION_MARKERS)

    if is_basic_time_request(lowered) or is_basic_weather_request(lowered):
        return True

    if matches_any_marker(lowered, _DYNAMIC_WEB_SUBJECT_MARKERS):
        return bool(re.match(r"^(who|what|why|how|when|where|tell me|give me)\b", lowered))
    return False


__all__ = [
    "contains_phrase_or_word",
    "has_context_dependent_reference",
    "is_basic_direct_chat_request",
    "is_basic_time_request",
    "is_basic_weather_request",
    "is_direct_chat_request",
    "is_direct_qa_request",
    "is_source_grounded_qa_request",
    "matches_any_marker",
]
