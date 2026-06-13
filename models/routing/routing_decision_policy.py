"""Router-decision normalization helpers."""

from __future__ import annotations

from models.orchestrator_adapters import route_from_task
from models.orchestrator_planner import normalize_orchestration_plan_payload
from models.router_backend_parsing import normalize_route_decision_payload
from models.router_backend_types import JsonValue
from models.routing_payload_parser import (
    JsonObject,
    PlanDecisionPayload,
    PlanTaskPayload,
    RoutePayload,
    RoutingResult,
    is_route_agent_name,
    normalize_direct_response_route_payload,
)
from models.routing_prompt_parser import extract_latest_request_from_router_prompt
from models.text_normalization import clean_text, format_direct_response_text


def looks_like_router_refusal(text: str) -> bool:
    lowered = (text or "").lower()
    patterns = (
        "i cannot",
        "i can't",
        "i am unable",
        "i'm unable",
        "as a text-based",
        "as an ai",
        "i don't have the ability",
        "i do not have the ability",
        "guide you on how",
        "manually",
    )
    return any(pattern in lowered for pattern in patterns)


def normalize_plan_decision_payload(
    payload: JsonObject,
    latest_request: str,
) -> PlanDecisionPayload:
    plan = normalize_orchestration_plan_payload(latest_request, payload)
    tasks: list[PlanTaskPayload] = []
    for task in plan.tasks:
        route = route_from_task(task)
        task_payload: PlanTaskPayload = {
            "id": task.id,
            **route,
            "resources": [resource.value for resource in task.resources],
        }
        if task.depends_on:
            task_payload["depends_on"] = list(task.depends_on)
        if task.max_attempts != 1:
            task_payload["max_attempts"] = task.max_attempts
        tasks.append(task_payload)
    return {
        "tasks": tasks,
        "max_parallel": plan.max_parallel,
    }


def normalize_router_decision_payload(
    payload: JsonObject,
    prompt: str,
    *,
    provider_name: str,
) -> RoutingResult:
    latest_request = extract_latest_request_from_router_prompt(prompt)
    if "tasks" in payload:
        return normalize_plan_decision_payload(payload, latest_request)

    normalized = normalize_route_decision_payload(
        payload,
        latest_request=latest_request,
        clean_text=clean_text,
        format_direct_response_text=format_direct_response_text,
        looks_like_router_refusal=looks_like_router_refusal,
        default_direct_response="Routing complete.",
    )
    if normalized is None:
        agent = payload.get("agent")
        if not is_route_agent_name(agent):
            raise RuntimeError(f"{provider_name} router returned invalid agent '{agent}'.")
        raise RuntimeError(f"{provider_name} router returned invalid route payload.")
    route_payload: RoutePayload = normalized.as_dict()
    return normalize_direct_response_route_payload(
        route_payload,
        error_source=f"{provider_name} router direct route",
    )


__all__ = [
    "looks_like_router_refusal",
    "normalize_plan_decision_payload",
    "normalize_router_decision_payload",
]
