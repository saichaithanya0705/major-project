"""Request-scoped delegated-step runtime for the public model bridge."""

from __future__ import annotations

from typing import Any

from models.agent_step_runner import run_routed_agent_step
from models.rapid_orchestrator_contracts import RapidAgentStepResult, RapidRouteResult
from models.screenshot_store import get_stored_screenshot, prepare_vision_screenshot


async def run_request_agent_step(
    model: Any,
    routing_result: RapidRouteResult,
    jarvis_model: str,
    request_id: str,
    prepare_vision_screenshot=None,
) -> RapidAgentStepResult:
    return await run_routed_agent_step(
        model=model,
        routing_result=routing_result,
        jarvis_model=jarvis_model,
        request_id=request_id,
        get_stored_screenshot=get_stored_screenshot,
        prepare_vision_screenshot=prepare_vision_screenshot or globals()["prepare_vision_screenshot"],
    )
