"""Dependency assembly for the rapid orchestrator runtime."""

from __future__ import annotations

from typing import Any

from models.direct_response_policy import finalize_direct_response_text
from models.direct_response_policy import user_requested_repeat
from models.function_calls import ROUTER_TOOL_MAP
from models.prompts import RAPID_RESPONSE_SYSTEM_PROMPT
from models.rapid_orchestrator_contracts import (
    RapidAgentStepResult,
    RapidModelFactory,
    RapidRouteResult,
    RapidRoutingResultEnricher,
    RapidScreenshotGetter,
    RapidScreenshotPreparer,
    RapidStepRunner,
    RapidAssistantLogger,
)
from models.rapid_orchestrator import RapidOrchestratorDeps
from models.rapid_state import RAPID_SESSION_STATE, RapidSessionState
from models.routing_prompt_state import format_chain_state_for_prompt
from models.routing_step_identity import (
    routing_signature as _routing_signature,
    routing_task_text as _routing_task_text,
)
from models.routing_guardrails import apply_routing_guardrails_route as _apply_routing_guardrails
from models.routing_question_policy import is_direct_qa_request as _is_direct_qa_request
from models.screen_context_policy import screen_context_message
from models.text_normalization import clean_text


async def answer_direct_request_via_model(
    *,
    model: Any,
    user_prompt: str,
    history_block: str = "",
) -> str:
    return await model.answer_direct_request(
        user_prompt=user_prompt,
        history_block=history_block,
    )


def build_rapid_orchestrator_deps(
    *,
    rapid_session_id: str,
    model_factory: RapidModelFactory,
    run_routed_agent_step: RapidStepRunner,
    get_stored_screenshot: RapidScreenshotGetter,
    prepare_vision_screenshot: RapidScreenshotPreparer,
    log_assistant_event: RapidAssistantLogger,
    rapid_session_state: RapidSessionState = RAPID_SESSION_STATE,
    max_router_chain_steps: int = 6,
    repeated_step_limit: int = 3,
) -> RapidOrchestratorDeps:
    def append_session_history(role: str, text: str, source: str) -> None:
        rapid_session_state.append_history(
            role=role,
            text=text,
            source=source,
            cleaner=lambda value: clean_text(value, "", max_len=600),
            session_id=rapid_session_id,
        )

    def format_session_history_for_prompt() -> str:
        return rapid_session_state.format_history_for_prompt(session_id=rapid_session_id)

    def enrich_session_routing_result(
        routing_result: RapidRouteResult,
        user_prompt_text: str,
    ) -> RapidRouteResult:
        return rapid_session_state.enrich_routing_result(
            routing_result,
            user_prompt=user_prompt_text,
            session_id=rapid_session_id,
        )

    def record_session_step_context(step_result: RapidAgentStepResult) -> None:
        rapid_session_state.record_step_context(
            step_result,
            session_id=rapid_session_id,
        )

    return RapidOrchestratorDeps(
        model_factory=model_factory,
        append_rapid_history=append_session_history,
        format_rapid_history_for_prompt=format_session_history_for_prompt,
        run_routed_agent_step=run_routed_agent_step,
        enrich_routing_result=enrich_session_routing_result,
        record_step_context=record_session_step_context,
        get_stored_screenshot=get_stored_screenshot,
        prepare_vision_screenshot=prepare_vision_screenshot,
        clean_text=lambda value, fallback, max_len: clean_text(
            value,
            fallback,
            max_len=max_len,
        ),
        format_chain_state_for_prompt=format_chain_state_for_prompt,
        apply_routing_guardrails=_apply_routing_guardrails,
        routing_task_text=_routing_task_text,
        routing_signature=_routing_signature,
        user_requested_repeat=user_requested_repeat,
        finalize_direct_response_text=finalize_direct_response_text,
        is_direct_qa_request=_is_direct_qa_request,
        answer_direct_request=answer_direct_request_via_model,
        screen_context_message=screen_context_message,
        router_tool_map=ROUTER_TOOL_MAP,
        log_assistant_event=log_assistant_event,
        rapid_response_system_prompt=RAPID_RESPONSE_SYSTEM_PROMPT,
        max_router_chain_steps=max_router_chain_steps,
        repeated_step_limit=repeated_step_limit,
    )
