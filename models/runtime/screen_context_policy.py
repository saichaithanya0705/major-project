"""Normalization and summary formatting for screen-context payloads."""

from __future__ import annotations

from models.router_backend_types import JsonValue
from models.routing_payload_parser import (
    JsonObject,
    ScreenContextPayload,
    is_route_agent_name,
)
from models.text_normalization import clean_text


def normalize_screen_context_payload(
    payload: JsonObject,
    user_request: str,
) -> ScreenContextPayload:
    recommended_agent = payload.get("recommended_agent")
    if not is_route_agent_name(recommended_agent):
        recommended_agent = ""

    recommended_task = clean_text(payload.get("recommended_task"), "", max_len=420)
    if not recommended_task:
        recommended_task = clean_text(user_request, "", max_len=420)

    normalized: ScreenContextPayload = {
        "summary": clean_text(payload.get("summary"), "", max_len=420),
        "repo_url": clean_text(payload.get("repo_url"), "", max_len=420),
        "local_url": clean_text(payload.get("local_url"), "", max_len=420),
        "recommended_agent": recommended_agent,
        "recommended_task": recommended_task,
        "hints": clean_text(payload.get("hints"), "", max_len=420),
    }

    return normalized


def screen_context_message(screen_context: ScreenContextPayload) -> str:
    summary = clean_text(screen_context.get("summary"), "Screen context captured.", max_len=260)
    repo_url = clean_text(screen_context.get("repo_url"), "", max_len=120)
    local_url = clean_text(screen_context.get("local_url"), "", max_len=120)
    recommended_agent = clean_text(screen_context.get("recommended_agent"), "", max_len=40)

    extras = []
    if repo_url:
        extras.append(f"repo={repo_url}")
    if local_url:
        extras.append(f"local={local_url}")
    if recommended_agent:
        extras.append(f"next={recommended_agent}")

    if extras:
        return f"{summary} ({', '.join(extras)})"
    return summary


__all__ = [
    "normalize_screen_context_payload",
    "screen_context_message",
]
