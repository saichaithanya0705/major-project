"""
Rapid-response orchestration flow extracted from models.models.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional

from models.orchestrator_adapters import plan_from_route, route_from_task
from models.rapid_plan_orchestrator import execute_rapid_plan_payload, is_plan_payload
from models.rapid_completion_recovery_policy import (
    evaluate_incomplete_step_recovery,
)
from models.rapid_direct_answer_flow import try_handle_direct_qa_request
from models.rapid_orchestrator_outcomes import (
    RapidRequestOutcomeReporter,
    raise_structural_subflow_error,
)
from models.rapid_orchestrator_contracts import (
    RapidAgentStepResult,
    RapidAssistantLogger,
    RapidChainFormatter,
    RapidDirectAnswerer,
    RapidDirectQaPredicate,
    RapidDirectResponseFinalizer,
    RapidHistoryAppender,
    RapidHistoryFormatter,
    RapidModelFactory,
    RapidRepeatPredicate,
    RapidRoutingGuardrails,
    RapidRoutingResultEnricher,
    RapidRoutingSignature,
    RapidRoutingTaskText,
    RapidScreenContextMessage,
    RapidScreenshotGetter,
    RapidScreenshotPreparer,
    RapidStepContextRecorder,
    RapidStepRunner,
    RapidTextCleaner,
    RapidToolMap,
    RapidRouteResult,
)
from models.routing_payload_parser import BlockedStepSignature, ScreenContextPayload
from models.rapid_step_execution_runtime import execute_delegated_step


@dataclass(slots=True)
class RapidOrchestratorDeps:
    model_factory: RapidModelFactory
    append_rapid_history: RapidHistoryAppender
    format_rapid_history_for_prompt: RapidHistoryFormatter
    run_routed_agent_step: RapidStepRunner
    enrich_routing_result: RapidRoutingResultEnricher
    record_step_context: RapidStepContextRecorder
    get_stored_screenshot: RapidScreenshotGetter
    prepare_vision_screenshot: RapidScreenshotPreparer
    clean_text: RapidTextCleaner
    format_chain_state_for_prompt: RapidChainFormatter
    apply_routing_guardrails: RapidRoutingGuardrails
    routing_task_text: RapidRoutingTaskText
    routing_signature: RapidRoutingSignature
    user_requested_repeat: RapidRepeatPredicate
    finalize_direct_response_text: RapidDirectResponseFinalizer
    is_direct_qa_request: RapidDirectQaPredicate
    answer_direct_request: RapidDirectAnswerer
    screen_context_message: RapidScreenContextMessage
    router_tool_map: RapidToolMap
    log_assistant_event: RapidAssistantLogger
    rapid_response_system_prompt: str
    max_router_chain_steps: int
    repeated_step_limit: int

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

    chain_steps: list[RapidAgentStepResult] = []
    seen_step_signatures: dict[BlockedStepSignature, int] = {}
    blocked_step_signatures: set[BlockedStepSignature] = set()
    latest_screen_context: Optional[ScreenContextPayload] = None
    outcomes = RapidRequestOutcomeReporter(
        request_id=request_id,
        user_prompt=user_prompt,
        append_rapid_history=deps.append_rapid_history,
        clean_text=deps.clean_text,
        finalize_direct_response_text=deps.finalize_direct_response_text,
        log_assistant_event=deps.log_assistant_event,
        router_tool_map=deps.router_tool_map,
    )

    if deps.is_direct_qa_request(user_prompt):
        if await try_handle_direct_qa_request(
            model=model,
            user_prompt=user_prompt,
            request_id=request_id,
            deps=deps,
            chain_steps=chain_steps,
        ):
            return

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
            raise_structural_subflow_error(exc)
            error_text = deps.clean_text(str(exc), "Router failed.", 420)
            outcomes.fail_request(
                agent="router",
                message=f"Router failed: {error_text}",
                error=error_text,
                metadata={"step_index": step_index + 1},
            )
            return

        if not isinstance(routing_result, dict):
            outcomes.fail_request(
                agent="router",
                message="Router failed: invalid routing response shape.",
                error="Invalid routing response shape.",
                metadata={"step_index": step_index + 1},
            )
            return

        if is_plan_payload(routing_result):
            plan_result = await execute_rapid_plan_payload(
                routing_result=routing_result,
                user_prompt=user_prompt,
                model=model,
                jarvis_model=jarvis_model,
                request_id=request_id,
                deps=deps,
                step_index=step_index,
                latest_screen_context=latest_screen_context,
            )
            chain_steps.extend(plan_result.chain_steps)
            latest_screen_context = plan_result.latest_screen_context
            return

        routing_result = deps.apply_routing_guardrails(
            user_prompt=user_prompt,
            routing_result=routing_result,
            latest_screen_context=latest_screen_context,
        )
        routing_result = deps.enrich_routing_result(routing_result, user_prompt)
        recovery_decision = evaluate_incomplete_step_recovery(
            user_prompt=user_prompt,
            routing_result=routing_result,
            chain_steps=chain_steps,
            routing_task_text=deps.routing_task_text,
        )
        if recovery_decision is not None:
            incomplete_step = recovery_decision.incomplete_step
            recovery_route = recovery_decision.recovery_route
            if recovery_route:
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

        orchestration_plan = plan_from_route(user_prompt, routing_result, max_parallel=1)
        orchestration_task = orchestration_plan.tasks[0]
        routing_result = route_from_task(orchestration_task)

        deps.log_assistant_event(
            "router_decision",
            request_id=request_id,
            agent=str(routing_result.get("agent") or "direct"),
            task=deps.routing_task_text(routing_result),
            metadata={"step_index": step_index + 1},
        )

        if routing_result.get("agent") == "direct":
            direct_args = routing_result.get("direct_response_args")
            outcomes.complete_direct_response(
                response_text=routing_result.get("response_text"),
                chain_steps=chain_steps,
                agent="direct",
                direct_args=direct_args if isinstance(direct_args, dict) else None,
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

        print(
            f"[Router][Chain] Step {step_index + 1}/{deps.max_router_chain_steps}: "
            f"agent={routing_result.get('agent')} task={deps.routing_task_text(routing_result)}"
        )
        step_execution = await execute_delegated_step(
            model=model,
            routing_result=routing_result,
            user_prompt=user_prompt,
            jarvis_model=jarvis_model,
            request_id=request_id,
            deps=deps,
            chain_steps=chain_steps,
            orchestration_plan=orchestration_plan,
            orchestration_task=orchestration_task,
        )
        orchestration_plan = step_execution.orchestration_plan
        if step_execution.latest_screen_context is not None:
            latest_screen_context = step_execution.latest_screen_context
        if step_execution.disposition != "continue":
            return
        continue

    max_step_msg = (
        f"I stopped after {deps.max_router_chain_steps} delegated steps to avoid loops. "
        "If you want me to continue, ask for the next specific step."
    )
    outcomes.stop_request(
        message=max_step_msg,
        metadata={"reason": "max_router_chain_steps"},
    )
