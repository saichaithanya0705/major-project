"""Prompt parsing helpers for routing-related prompts."""

from __future__ import annotations


_LATEST_REQUEST_MARKERS = (
    "# User's Latest Request:\n",
    "# User's Request:\n",
)


def _clean_prompt_text(value: object, *, max_len: int = 1800) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def extract_latest_request_from_router_prompt(prompt: str) -> str:
    for marker in _LATEST_REQUEST_MARKERS:
        if marker in prompt:
            tail = prompt.rsplit(marker, 1)[-1].strip()
            if tail:
                return tail
    return _clean_prompt_text(prompt, max_len=1800)


__all__ = ["extract_latest_request_from_router_prompt"]
