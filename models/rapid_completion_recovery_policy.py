"""Pure completion and recovery policy for the rapid orchestrator."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


RoutingTaskText = Callable[[Mapping[str, Any]], str]


@dataclass(frozen=True, slots=True)
class IncompleteStepRecoveryDecision:
    incomplete_step: Mapping[str, Any]
    recovery_route: dict[str, str]


def _normalized_task_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip().lower()


_TASK_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TASK_TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "can",
        "could",
        "com",
        "current",
        "do",
        "does",
        "for",
        "from",
        "http",
        "https",
        "i",
        "in",
        "is",
        "it",
        "its",
        "just",
        "main",
        "me",
        "my",
        "of",
        "on",
        "or",
        "please",
        "should",
        "that",
        "the",
        "this",
        "to",
        "using",
        "was",
        "were",
        "what",
        "whats",
        "will",
        "with",
        "would",
        "www",
        "you",
    }
)
_TASK_TOKEN_SYNONYMS = {
    "analysed": "analyze",
    "analyses": "analyze",
    "analysing": "analyze",
    "analysis": "analyze",
    "analyse": "analyze",
    "extract": "read",
    "extracted": "read",
    "extracting": "read",
    "fetch": "read",
    "fetched": "read",
    "fetching": "read",
    "findings": "finding",
    "headings": "heading",
    "locally": "local",
    "opened": "open",
    "opening": "open",
    "reads": "read",
    "reading": "read",
    "searched": "search",
    "searching": "search",
    "summaries": "summary",
    "summarized": "summary",
    "summarize": "summary",
    "summarizing": "summary",
    "summary": "summary",
    "updates": "update",
    "updating": "update",
    "visited": "open",
    "visiting": "open",
    "webpage": "page",
    "website": "site",
}


def _canonical_task_token(token: str) -> str:
    mapped = _TASK_TOKEN_SYNONYMS.get(token)
    if mapped:
        return mapped
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _meaningful_task_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    for raw_token in _TASK_TOKEN_RE.findall(_normalized_task_text(value)):
        token = _canonical_task_token(raw_token)
        if len(token) < 2 or token in _TASK_TOKEN_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _routed_task_covers_user_request(
    *,
    user_prompt: str,
    routing_result: Mapping[str, Any],
    step_result: Mapping[str, Any],
    routing_task_text: RoutingTaskText,
) -> bool:
    requested_tokens = _meaningful_task_tokens(user_prompt)
    if not requested_tokens:
        return False

    candidate_tokens = set()
    candidate_tokens.update(_meaningful_task_tokens(routing_task_text(routing_result)))
    candidate_tokens.update(_meaningful_task_tokens(step_result.get("task")))
    if not candidate_tokens:
        return False

    return requested_tokens.issubset(candidate_tokens)


def _step_marked_complete(step_result: Mapping[str, Any]) -> bool:
    return step_result.get("complete", True) is not False


def find_latest_unresolved_incomplete_step(
    chain_steps: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for step in reversed(chain_steps):
        if str(step.get("agent") or "").strip().lower() == "router_guard":
            continue
        if step.get("success") and _step_marked_complete(step):
            return None
        if step.get("success") and not _step_marked_complete(step):
            return step
    return None


def _recovery_route_for_incomplete_step(
    *,
    user_prompt: str,
    incomplete_step: Mapping[str, Any],
) -> dict[str, str] | None:
    agent = str(incomplete_step.get("agent") or "").strip().lower()
    if agent == "browser":
        return {
            "agent": "cua_vision",
            "task": (
                "Continue in the currently open browser window and finish the original "
                f"user request: {user_prompt}"
            ),
        }
    if agent == "cua_vision":
        reason = str(
            incomplete_step.get("message")
            or _critic_reason(incomplete_step)
            or "The previous computer-use step did not produce goal-state evidence."
        ).strip()
        return {
            "agent": "screen_context",
            "task": (
                "Observe the current screen after the previous computer-use attempt. "
                f"Original user request: {user_prompt}. "
                f"Previous CUA result: {reason}"
            ),
            "focus": (
                "concrete goal-state evidence, visible app/page, current input focus, "
                "whether the requested message/action is actually complete, and the next safest agent"
            ),
        }
    return None


def _critic_reason(incomplete_step: Mapping[str, Any]) -> str:
    critic = incomplete_step.get("critic")
    if not isinstance(critic, Mapping):
        return ""
    return str(critic.get("reason") or "").strip()


def _route_repeats_incomplete_step(
    *,
    routing_result: Mapping[str, Any],
    incomplete_step: Mapping[str, Any],
    routing_task_text: RoutingTaskText,
) -> bool:
    route_agent = str(routing_result.get("agent") or "").strip().lower()
    step_agent = str(incomplete_step.get("agent") or "").strip().lower()
    if route_agent != step_agent:
        return False
    return _normalized_task_text(routing_task_text(routing_result)) == _normalized_task_text(
        incomplete_step.get("task")
    )


def evaluate_incomplete_step_recovery(
    *,
    user_prompt: str,
    routing_result: Mapping[str, Any],
    chain_steps: Sequence[Mapping[str, Any]],
    routing_task_text: RoutingTaskText,
) -> IncompleteStepRecoveryDecision | None:
    incomplete_step = find_latest_unresolved_incomplete_step(chain_steps)
    if incomplete_step is None:
        return None

    if routing_result.get("agent") != "direct" and not _route_repeats_incomplete_step(
        routing_result=routing_result,
        incomplete_step=incomplete_step,
        routing_task_text=routing_task_text,
    ):
        return None

    recovery_route = _recovery_route_for_incomplete_step(
        user_prompt=user_prompt,
        incomplete_step=incomplete_step,
    )
    if recovery_route is None:
        return None

    return IncompleteStepRecoveryDecision(
        incomplete_step=incomplete_step,
        recovery_route=recovery_route,
    )


def should_finish_after_successful_agent_step(
    *,
    user_prompt: str,
    routing_result: Mapping[str, Any],
    step_result: Mapping[str, Any],
    chain_steps: Sequence[Mapping[str, Any]],
    routing_task_text: RoutingTaskText,
) -> bool:
    if not step_result.get("success"):
        return False
    if not _step_marked_complete(step_result):
        return False
    if len(chain_steps) != 1:
        return False

    agent = str(step_result.get("agent") or routing_result.get("agent") or "").strip().lower()
    if agent not in {"browser", "cua_cli", "cua_vision", "web_qa"}:
        return False

    requested = _normalized_task_text(user_prompt)
    if not requested:
        return False

    routed_task = _normalized_task_text(routing_task_text(routing_result))
    completed_task = _normalized_task_text(step_result.get("task"))
    if requested in {routed_task, completed_task}:
        return True
    return _routed_task_covers_user_request(
        user_prompt=user_prompt,
        routing_result=routing_result,
        step_result=step_result,
        routing_task_text=routing_task_text,
    )
