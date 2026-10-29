"""Request entrypoint for the public `call_gemini()` bridge."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from models.rapid_orchestrator_contracts import RapidStepRunner
from models.shared.user_input_context import user_input_scope


class RapidSessionStateLike(Protocol):
    def normalize_session_id(self, session_id: str | None = None) -> str: ...


async def run_gemini_request(
    *,
    user_prompt: str,
    rapid_response_model: str,
    jarvis_model: str,
    session_id: str | None,
    new_request_id: Callable[[], str],
    log_assistant_event: Callable[..., None],
    clean_text: Callable[[object, str, int | None], str],
    rapid_session_state: RapidSessionStateLike,
    build_rapid_orchestrator_deps: Callable[..., Any],
    run_rapid_request: Callable[..., Awaitable[None]],
    model_factory: type[Any],
    run_routed_agent_step: RapidStepRunner,
    get_stored_screenshot: Callable[[], object],
    prepare_vision_screenshot: Callable[..., Awaitable[object]],
    max_router_chain_steps: int,
    repeated_step_limit: int,
    handle_local_command: Callable[[str], str | None] | None = None,
    send_local_reply: Callable[[str], Awaitable[None]] | None = None,
    build_memory_block: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    request_id = new_request_id()
    rapid_session_id = rapid_session_state.normalize_session_id(session_id)
    log_assistant_event(
        "request_started",
        request_id=request_id,
        task=clean_text(user_prompt, "", max_len=1200),
        metadata={
            "rapid_response_model": rapid_response_model,
            "jarvis_model": jarvis_model,
            "session_id": rapid_session_id,
        },
    )

    local_reply = handle_local_command(user_prompt) if handle_local_command else None
    if local_reply is not None:
        # Commands such as "remember that ..." are answered without a model.
        log_assistant_event(
            "request_completed",
            request_id=request_id,
            task=clean_text(user_prompt, "", max_len=1200),
            message=clean_text(local_reply, "", max_len=420),
            agent="local_command",
            success=True,
        )
        if send_local_reply is not None:
            await send_local_reply(local_reply)
        return request_id, rapid_session_id

    deps = build_rapid_orchestrator_deps(
        rapid_session_id=rapid_session_id,
        model_factory=model_factory,
        run_routed_agent_step=run_routed_agent_step,
        get_stored_screenshot=get_stored_screenshot,
        prepare_vision_screenshot=prepare_vision_screenshot,
        log_assistant_event=log_assistant_event,
        max_router_chain_steps=max_router_chain_steps,
        repeated_step_limit=repeated_step_limit,
        memory_block=build_memory_block(user_prompt) if build_memory_block else "",
    )
    with user_input_scope(user_prompt, rapid_session_id):
        await run_rapid_request(
            user_prompt=user_prompt,
            rapid_response_model=rapid_response_model,
            jarvis_model=jarvis_model,
            request_id=request_id,
            deps=deps,
        )
    return request_id, rapid_session_id
