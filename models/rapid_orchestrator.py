"""
Rapid-response orchestration flow extracted from models.models.
"""

from __future__ import annotations

import re
import time
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


@dataclass(slots=True)
class RapidOrchestratorDeps:
    model_factory: Callable[[str, str], Any]
    append_rapid_history: Callable[[str, str, str], None]
    format_rapid_history_for_prompt: Callable[[], str]
    run_routed_agent_step: Callable[..., Awaitable[dict[str, Any]]]
    get_stored_screenshot: Callable[[], Any]
    prepare_vision_screenshot: Callable[..., Awaitable[Any]]
    clean_text: Callable[[object, str, int | None], str]
    format_chain_state_for_prompt: Callable[..., str]
    apply_routing_guardrails: Callable[..., dict[str, Any]]
    routing_task_text: Callable[[dict[str, Any]], str]
    routing_signature: Callable[[dict[str, Any]], tuple[str, str]]
    user_requested_repeat: Callable[[str], bool]
    finalize_direct_response_text: Callable[..., str]
    is_direct_qa_request: Callable[[str], bool]
    answer_direct_request: Callable[..., Awaitable[str]]
    screen_context_message: Callable[[dict[str, Any]], str]
    router_tool_map: dict[str, Any]
    log_assistant_event: Callable[..., None]
    rapid_response_system_prompt: str
    max_router_chain_steps: int
    repeated_step_limit: int


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
    "readable": "read",
    "reading": "read",
    "repository": "repo",
    "repositories": "repo",
    "said": "content",
    "say": "content",
    "says": "content",
    "summaries": "summarize",
    "summarise": "summarize",
    "summarised": "summarize",
    "summarises": "summarize",
    "summarising": "summarize",
    "summary": "summarize",
    "titles": "title",
    "urls": "url",
    "webpage": "page",
    "webpages": "page",
    "website": "site",
    "websites": "site",
}


def _canonical_task_token(token: str) -> str:
    mapped = _TASK_TOKEN_SYNONYMS.get(token)
    if mapped:
        return mapped
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
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
    routing_result: dict[str, Any],
    step_result: dict[str, Any],
    routing_task_text: Callable[[dict[str, Any]], str],
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


def _step_marked_complete(step_result: dict[str, Any]) -> bool:
    return step_result.get("complete", True) is not False


def _latest_unresolved_incomplete_step(chain_steps: list[dict[str, Any]]) -> dict[str, Any] | None:
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
    incomplete_step: dict[str, Any],
) -> dict[str, Any] | None:
    agent = str(incomplete_step.get("agent") or "").strip().lower()
    if agent == "browser":
        return {
            "agent": "cua_vision",
            "task": (
                "Continue in the currently open browser window and finish the original "
                f"user request: {user_prompt}"
            ),
        }
    return None


def _route_repeats_incomplete_step(
    *,
    routing_result: dict[str, Any],
    incomplete_step: dict[str, Any],
    routing_task_text: Callable[[dict[str, Any]], str],
) -> bool:
    route_agent = str(routing_result.get("agent") or "").strip().lower()
    step_agent = str(incomplete_step.get("agent") or "").strip().lower()
    if route_agent != step_agent:
        return False
    return _normalized_task_text(routing_task_text(routing_result)) == _normalized_task_text(
        incomplete_step.get("task")
    )


def _should_finish_after_successful_agent_step(
    *,
    user_prompt: str,
    routing_result: dict[str, Any],
    step_result: dict[str, Any],
    chain_steps: list[dict[str, Any]],
    routing_task_text: Callable[[dict[str, Any]], str],
) -> bool:
    if not step_result.get("success"):
        return False
    if not _step_marked_complete(step_result):
        return False
    if len(chain_steps) != 1:
        return False

    agent = str(step_result.get("agent") or routing_result.get("agent") or "").strip().lower()
    if agent not in {"browser", "cua_cli", "cua_vision"}:
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


async def run_rapid_request(
    *,
    user_prompt: str,
    rapid_response_model: str,
    jarvis_model: str,
    request_id: str,
    deps: RapidOrchestratorDeps,
) -> None:
    model = deps.model_factory(
        jarvis_model=jarvis_model,
        rapid_response_model=rapid_response_model,
    )

    deps.append_rapid_history("user", user_prompt, "user")

    chain_steps: list[dict[str, Any]] = []
    seen_step_signatures: dict[tuple[str, str], int] = {}
    blocked_step_signatures: set[tuple[str, str]] = set()
    latest_screen_context: Optional[dict[str, Any]] = None

    if deps.is_direct_qa_request(user_prompt):
        direct_started = time.monotonic()
        try:
            direct_answer = await deps.answer_direct_request(
                model=model,
                user_prompt=user_prompt,
                history_block=deps.format_rapid_history_for_prompt(),
            )
            direct_text = deps.finalize_direct_response_text(
                user_prompt=user_prompt,
                chain_steps=chain_steps,
                text=deps.clean_text(direct_answer, "Rapid response provided.", None),
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
            return
        except Exception as exc:
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

    for step_index in range(deps.max_router_chain_steps):
        history_block = deps.format_rapid_history_for_prompt()
        chain_block = deps.format_chain_state_for_prompt(
            user_prompt=user_prompt,
            chain_steps=chain_steps,
            max_steps=deps.max_router_chain_steps,
            latest_screen_context=latest_screen_context,
            blocked_step_signatures=blocked_step_signatures,
        )
        rapid_prompt = (
            deps.rapid_response_system_prompt
            + history_block
            + chain_block
            + f"\n# User's Latest Request:\n{user_prompt}"
        )

        try:
            routing_result = await model.route_request(rapid_prompt)
        except Exception as exc:
            error_text = deps.clean_text(str(exc), "Router failed.", 420)
            router_error = f"Router failed: {error_text}"
            tool = deps.router_tool_map.get("direct_response")
            if tool:
                tool(text=router_error, source="rapid_response")
            deps.append_rapid_history("assistant", router_error, "rapid")
            deps.log_assistant_event(
                "request_failed",
                request_id=request_id,
                agent="router",
                task=deps.clean_text(user_prompt, "", 420),
                message=router_error,
                error=error_text,
                success=False,
                metadata={"step_index": step_index + 1},
            )
            return

        if not isinstance(routing_result, dict):
            router_error = "Router failed: invalid routing response shape."
            tool = deps.router_tool_map.get("direct_response")
            if tool:
                tool(text=router_error, source="rapid_response")
            deps.append_rapid_history("assistant", router_error, "rapid")
            deps.log_assistant_event(
                "request_failed",
                request_id=request_id,
                agent="router",
                task=deps.clean_text(user_prompt, "", 420),
                message=router_error,
                error="Invalid routing response shape.",
                success=False,
                metadata={"step_index": step_index + 1},
            )
            return

        routing_result = deps.apply_routing_guardrails(
            user_prompt=user_prompt,
            routing_result=routing_result,
            latest_screen_context=latest_screen_context,
        )
        incomplete_step = _latest_unresolved_incomplete_step(chain_steps)
        should_recover_from_incomplete = (
            incomplete_step is not None
            and (
                routing_result.get("agent") == "direct"
                or _route_repeats_incomplete_step(
                    routing_result=routing_result,
                    incomplete_step=incomplete_step,
                    routing_task_text=deps.routing_task_text,
                )
            )
        )
        if should_recover_from_incomplete and incomplete_step is not None:
            recovery_route = _recovery_route_for_incomplete_step(
                user_prompt=user_prompt,
                incomplete_step=incomplete_step,
            )
            if recovery_route is not None:
                guard_msg = (
                    "Router attempted to finish or repeat an incomplete delegated step. "
                    "Continuing with a different agent so the original request can be completed."
                )
                chain_steps.append(
                    {
                        "agent": "router_guard",
                        "task": deps.routing_task_text(routing_result),
                        "success": False,
                        "complete": False,
                        "message": guard_msg,
                        "source": "rapid",
                    }
                )
                deps.append_rapid_history("assistant", guard_msg, "rapid")
                deps.log_assistant_event(
                    "router_incomplete_guard",
                    request_id=request_id,
                    agent=str(recovery_route.get("agent") or ""),
                    task=deps.routing_task_text(recovery_route),
                    message=guard_msg,
                    success=False,
                    metadata={
                        "original_agent": str(incomplete_step.get("agent") or ""),
                        "original_task": deps.clean_text(incomplete_step.get("task"), "", 420),
                        "step_index": step_index + 1,
                    },
                )
                routing_result = recovery_route

        deps.log_assistant_event(
            "router_decision",
            request_id=request_id,
            agent=str(routing_result.get("agent") or "direct"),
            task=deps.routing_task_text(routing_result),
            metadata={"step_index": step_index + 1},
        )

        if routing_result.get("agent") == "direct":
            direct_args = routing_result.get("direct_response_args")
            if not isinstance(direct_args, dict):
                direct_args = {}
            raw_direct_text = direct_args.get("text") or routing_result.get("response_text")
            direct_text = deps.finalize_direct_response_text(
                user_prompt=user_prompt,
                chain_steps=chain_steps,
                text=deps.clean_text(raw_direct_text, "Rapid response provided.", None),
            )
            tool = deps.router_tool_map.get("direct_response")
            if tool:
                safe_args = dict(direct_args)
                safe_args.pop("text", None)
                tool(text=direct_text, source="rapid_response", **safe_args)
            deps.append_rapid_history("assistant", direct_text, "rapid")
            deps.log_assistant_event(
                "request_completed",
                request_id=request_id,
                agent="direct",
                task=deps.clean_text(user_prompt, "", 420),
                message=direct_text,
                success=True,
                metadata={"delegated_steps": len(chain_steps)},
            )
            return

        signature = deps.routing_signature(routing_result)
        if signature in blocked_step_signatures and not deps.user_requested_repeat(user_prompt):
            blocked_msg = (
                "Loop guard: the router chose a delegated step that was already blocked for repetition. "
                "Choosing a different next step or finishing directly is required."
            )
            chain_steps.append(
                {
                    "agent": "router_guard",
                    "task": deps.routing_task_text(routing_result),
                    "success": False,
                    "message": blocked_msg,
                    "source": "rapid",
                }
            )
            deps.append_rapid_history("assistant", blocked_msg, "rapid")
            deps.log_assistant_event(
                "router_loop_guard",
                request_id=request_id,
                agent=str(routing_result.get("agent") or ""),
                task=deps.routing_task_text(routing_result),
                message=blocked_msg,
                success=False,
                metadata={"reason": "blocked_repeated_step", "step_index": step_index + 1},
            )
            continue

        seen_step_signatures[signature] = seen_step_signatures.get(signature, 0) + 1
        if seen_step_signatures[signature] >= deps.repeated_step_limit and not deps.user_requested_repeat(user_prompt):
            blocked_step_signatures.add(signature)
            repeated_msg = (
                "Loop guard: I already delegated this exact next step multiple times, "
                "so I'm asking the router to choose a different next step or finish directly."
            )
            chain_steps.append(
                {
                    "agent": "router_guard",
                    "task": deps.routing_task_text(routing_result),
                    "success": False,
                    "message": repeated_msg,
                    "source": "rapid",
                }
            )
            deps.append_rapid_history("assistant", repeated_msg, "rapid")
            deps.log_assistant_event(
                "router_loop_guard",
                request_id=request_id,
                agent=str(routing_result.get("agent") or ""),
                task=deps.routing_task_text(routing_result),
                message=repeated_msg,
                success=False,
                metadata={"reason": "repeated_step_limit", "step_index": step_index + 1},
            )
            continue

        if routing_result.get("agent") == "screen_context":
            judge_task = routing_result.get("task") or user_prompt
            focus = routing_result.get("focus") or ""
            print(
                f"[Router][Chain] Step {step_index + 1}/{deps.max_router_chain_steps}: "
                f"agent=screen_context task={deps.clean_text(judge_task, '', 200)}"
            )
            screenshot = await deps.prepare_vision_screenshot(keep_chat_hidden=False)
            screen_context_started = time.monotonic()
            deps.log_assistant_event(
                "agent_step_started",
                request_id=request_id,
                agent="screen_context",
                task=deps.clean_text(judge_task, "", 420),
                metadata={"focus": deps.clean_text(focus, "", 220)},
            )
            try:
                latest_screen_context = await model.generate_screen_context(
                    user_request=judge_task,
                    image=screenshot,
                    focus=focus,
                )
                message = deps.screen_context_message(latest_screen_context)
                step_result = {
                    "agent": "screen_context",
                    "task": deps.clean_text(judge_task, "", 220),
                    "success": True,
                    "message": message,
                    "source": "screen_judge",
                }
                deps.log_assistant_event(
                    "agent_step_completed",
                    request_id=request_id,
                    agent="screen_context",
                    task=deps.clean_text(judge_task, "", 420),
                    message=message,
                    success=True,
                    duration_seconds=time.monotonic() - screen_context_started,
                    metadata=latest_screen_context,
                )
            except Exception as exc:
                step_result = {
                    "agent": "screen_context",
                    "task": deps.clean_text(judge_task, "", 220),
                    "success": False,
                    "message": deps.clean_text(str(exc), "Failed to collect screen context.", 420),
                    "source": "screen_judge",
                }
                deps.log_assistant_event(
                    "agent_step_failed",
                    request_id=request_id,
                    agent="screen_context",
                    task=deps.clean_text(judge_task, "", 420),
                    message=step_result["message"],
                    error=str(exc),
                    success=False,
                    duration_seconds=time.monotonic() - screen_context_started,
                    metadata={"traceback": traceback.format_exc()},
                )

            chain_steps.append(step_result)
            deps.append_rapid_history(
                "assistant",
                step_result.get("message", ""),
                step_result.get("source", "rapid"),
            )
            if not step_result.get("success"):
                failure_msg = (
                    f"Stopping chained execution because screen context failed: "
                    f"{step_result.get('message')}"
                )
                tool = deps.router_tool_map.get("direct_response")
                if tool:
                    tool(text=deps.clean_text(failure_msg, "Task failed.", 420), source="rapid_response")
                deps.append_rapid_history("assistant", failure_msg, "rapid")
                deps.log_assistant_event(
                    "request_failed",
                    request_id=request_id,
                    agent="screen_context",
                    task=deps.clean_text(judge_task, "", 420),
                    message=failure_msg,
                    error=step_result.get("message", ""),
                    success=False,
                )
                return
            continue

        print(
            f"[Router][Chain] Step {step_index + 1}/{deps.max_router_chain_steps}: "
            f"agent={routing_result.get('agent')} task={deps.routing_task_text(routing_result)}"
        )
        step_result = await deps.run_routed_agent_step(
            model=model,
            routing_result=routing_result,
            jarvis_model=jarvis_model,
            request_id=request_id,
            prepare_vision_screenshot=deps.prepare_vision_screenshot,
        )
        chain_steps.append(step_result)
        deps.append_rapid_history(
            "assistant",
            step_result.get("message", ""),
            step_result.get("source", "rapid"),
        )
        if _should_finish_after_successful_agent_step(
            user_prompt=user_prompt,
            routing_result=routing_result,
            step_result=step_result,
            chain_steps=chain_steps,
            routing_task_text=deps.routing_task_text,
        ):
            direct_text = deps.finalize_direct_response_text(
                user_prompt=user_prompt,
                chain_steps=chain_steps,
                text=deps.clean_text(step_result.get("message"), "Task completed.", None),
            )
            tool = deps.router_tool_map.get("direct_response")
            if tool:
                tool(text=direct_text, source="rapid_response")
            deps.append_rapid_history("assistant", direct_text, "rapid")
            deps.log_assistant_event(
                "request_completed",
                request_id=request_id,
                agent=str(step_result.get("agent") or routing_result.get("agent") or ""),
                task=deps.clean_text(user_prompt, "", 420),
                message=direct_text,
                success=True,
                metadata={
                    "delegated_steps": len(chain_steps),
                    "fast_finish": True,
                },
            )
            return
        if not step_result.get("success"):
            failure_msg = (
                f"Stopping chained execution because {step_result.get('agent')} failed: "
                f"{step_result.get('message')}"
            )
            tool = deps.router_tool_map.get("direct_response")
            if tool:
                tool(text=deps.clean_text(failure_msg, "Task failed.", 420), source="rapid_response")
            deps.append_rapid_history("assistant", failure_msg, "rapid")
            deps.log_assistant_event(
                "request_failed",
                request_id=request_id,
                agent=str(step_result.get("agent") or ""),
                task=deps.clean_text(step_result.get("task"), "", 420),
                message=failure_msg,
                error=step_result.get("message", ""),
                success=False,
            )
            return

    max_step_msg = (
        f"I stopped after {deps.max_router_chain_steps} delegated steps to avoid loops. "
        "If you want me to continue, ask for the next specific step."
    )
    tool = deps.router_tool_map.get("direct_response")
    if tool:
        tool(text=max_step_msg, source="rapid_response")
    deps.append_rapid_history("assistant", max_step_msg, "rapid")
    deps.log_assistant_event(
        "request_stopped",
        request_id=request_id,
        task=deps.clean_text(user_prompt, "", 420),
        message=max_step_msg,
        success=False,
        metadata={"reason": "max_router_chain_steps"},
    )
