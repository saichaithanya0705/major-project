"""Route task/signature helpers for delegated-step bookkeeping."""

from __future__ import annotations

from models.routing_payload_parser import (
    BlockedStepSignature,
    RouteAgentName,
    RoutePayload,
    is_route_agent_name,
)
from models.text_normalization import clean_text


def routing_task_text(routing_result: RoutePayload) -> str:
    return clean_text(
        routing_result.get("task") or routing_result.get("query") or "",
        "",
        max_len=220,
    )


def routing_signature(routing_result: RoutePayload) -> BlockedStepSignature:
    agent = routing_result.get("agent")
    normalized_agent: RouteAgentName = agent if is_route_agent_name(agent) else "direct"
    return (
        normalized_agent,
        routing_task_text(routing_result).strip().lower(),
    )


__all__ = [
    "routing_signature",
    "routing_task_text",
]
