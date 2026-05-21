"""Direct-response completion policy for rapid delegated flows."""

from __future__ import annotations

from collections.abc import Sequence

from models.rapid_orchestrator_contracts import RapidAgentStepResult
from models.text_normalization import clean_text, format_direct_response_text

_REPEAT_REQUEST_MARKERS = (
    "repeat",
    "again",
    "do it again",
    "rerun",
    "redo",
    "one more time",
)
_REPEAT_ARTIFACT_MARKERS = (
    "repeat the exact same task",
    "already completed",
    "already created",
    "already moved",
    "already done",
    "is there anything else i can help you with",
)


def user_requested_repeat(user_prompt: str) -> bool:
    lowered = (user_prompt or "").lower()
    return any(marker in lowered for marker in _REPEAT_REQUEST_MARKERS)


def looks_like_repeat_artifact(text: str) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in _REPEAT_ARTIFACT_MARKERS)


def summarize_completed_steps(chain_steps: Sequence[RapidAgentStepResult]) -> str:
    successful = [step for step in chain_steps if step.get("success")]
    if not successful:
        return "Task completed."

    messages: list[str] = []
    for step in successful:
        message = clean_text(step.get("message"), "", max_len=220)
        if message:
            messages.append(message)
    if not messages:
        return "Task completed."

    if len(messages) == 1:
        return f"Task completed: {messages[0]}"
    return f"Task completed: {messages[-2]} Then: {messages[-1]}"


def finalize_direct_response_text(
    *,
    user_prompt: str,
    chain_steps: Sequence[RapidAgentStepResult],
    text: object,
) -> str:
    cleaned = format_direct_response_text(text, "Task completed.", max_len=None)
    if not chain_steps:
        return cleaned
    if user_requested_repeat(user_prompt):
        return cleaned
    if looks_like_repeat_artifact(cleaned):
        return summarize_completed_steps(chain_steps)
    return cleaned


__all__ = [
    "finalize_direct_response_text",
    "looks_like_repeat_artifact",
    "summarize_completed_steps",
    "user_requested_repeat",
]
