"""Direct-QA fast-path flow for the rapid orchestrator."""

from __future__ import annotations

import time
from typing import Sequence

from models.rapid_orchestrator_contracts import (
    RapidAgentStepResult,
    RapidDirectQaFlowDeps,
    RapidModel,
)


_STRUCTURAL_SUBFLOW_ERRORS = (
    AssertionError,
    AttributeError,
    KeyError,
    TypeError,
    ValueError,
)


def _raise_structural_subflow_error(exc: Exception) -> None:
    if isinstance(exc, _STRUCTURAL_SUBFLOW_ERRORS):
        raise exc


async def try_handle_direct_qa_request(
    *,
    model: RapidModel,
    user_prompt: str,
    request_id: str,
    deps: RapidDirectQaFlowDeps,
    chain_steps: Sequence[RapidAgentStepResult],
) -> bool:
    direct_started = time.monotonic()
    try:
        direct_answer = await deps.answer_direct_request(
            model=model,
            user_prompt=user_prompt,
            history_block=deps.format_rapid_history_for_prompt(),
        )
        direct_text = deps.finalize_direct_response_text(
            user_prompt=user_prompt,
            chain_steps=list(chain_steps),
            text=direct_answer,
        )
        deps.log_assistant_event(
            "router_decision",
            request_id=request_id,
            agent="direct",
            task=deps.clean_text(user_prompt, "", 420),
            duration_seconds=time.monotonic() - direct_started,
            metadata={"step_index": 0, "reason": "direct_qa_fast_path"},
        )
        tool = deps.router_tool_map.get("direct_response")
        if tool:
            tool(text=direct_text, source="rapid_response")
        deps.append_rapid_history("assistant", direct_text, "rapid")
        deps.log_assistant_event(
            "request_completed",
            request_id=request_id,
            agent="direct",
            task=deps.clean_text(user_prompt, "", 420),
            message=direct_text,
            success=True,
            duration_seconds=time.monotonic() - direct_started,
            metadata={"delegated_steps": 0, "fast_direct_qa": True},
        )
        return True
    except Exception as exc:
        _raise_structural_subflow_error(exc)
        error_text = deps.clean_text(str(exc), "Direct answer failed.", 420)
        deps.log_assistant_event(
            "direct_answer_failed",
            request_id=request_id,
            agent="direct",
            task=deps.clean_text(user_prompt, "", 420),
            message=error_text,
            error=str(exc),
            success=False,
            duration_seconds=time.monotonic() - direct_started,
        )
        return False
