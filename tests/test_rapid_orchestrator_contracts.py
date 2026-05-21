"""Checks typed contract usage across the rapid orchestrator runtime surface."""

import os
import sys
from typing import get_type_hints

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.rapid_orchestrator as rapid_orchestrator
import models.rapid_orchestrator_outcomes as rapid_outcomes
import models.rapid_orchestrator_contracts as rapid_contracts
import models.rapid_step_payloads as rapid_step_payloads
import models.screen_context_execution_runtime as screen_context_runtime
from models.routing_payload_parser import ScreenContextPayload


def test_rapid_orchestrator_deps_use_shared_contract_aliases() -> None:
    hints = get_type_hints(rapid_orchestrator.RapidOrchestratorDeps)

    assert hints["model_factory"] == rapid_contracts.RapidModelFactory
    assert hints["run_routed_agent_step"] == rapid_contracts.RapidStepRunner
    assert hints["enrich_routing_result"] == rapid_contracts.RapidRoutingResultEnricher
    assert hints["record_step_context"] == rapid_contracts.RapidStepContextRecorder
    assert hints["apply_routing_guardrails"] == rapid_contracts.RapidRoutingGuardrails
    assert hints["routing_task_text"] == rapid_contracts.RapidRoutingTaskText
    assert hints["routing_signature"] == rapid_contracts.RapidRoutingSignature
    assert hints["screen_context_message"] == rapid_contracts.RapidScreenContextMessage


def test_rapid_step_result_reuses_shared_payload_contracts() -> None:
    hints = get_type_hints(rapid_contracts.RapidAgentStepResult)

    assert hints["tool_calls"] == list[rapid_step_payloads.RapidToolCallRecord]
    assert hints["sources"] == list[rapid_step_payloads.RapidSourceRecord]
    assert hints["metadata"] == rapid_step_payloads.RapidStepMetadataPayload
    assert hints["artifacts"] == rapid_step_payloads.RapidStepArtifactCollection
    assert hints["orchestrator_context"] is rapid_step_payloads.RapidTaskExecutionContextPayload


def test_screen_context_runtime_reuses_rapid_step_and_screen_payload_contracts() -> None:
    hints = get_type_hints(screen_context_runtime.ScreenContextStepExecutionResult)
    model_hints = get_type_hints(screen_context_runtime.ScreenContextRuntimeModel.generate_screen_context)

    assert hints["step_result"] == rapid_contracts.RapidAgentStepResult
    assert hints["latest_screen_context"] == ScreenContextPayload | None
    assert model_hints["return"] is ScreenContextPayload


def test_rapid_request_outcome_reporter_finishes_direct_responses() -> None:
    direct_calls: list[dict[str, object]] = []
    history_calls: list[tuple[str, str, str]] = []
    logged_events: list[dict[str, object]] = []

    reporter = rapid_outcomes.RapidRequestOutcomeReporter(
        request_id="req-direct",
        user_prompt="open localhost 3000",
        append_rapid_history=lambda role, text, source: history_calls.append((role, text, source)),
        clean_text=lambda value, fallback, max_len: str(value or fallback),
        finalize_direct_response_text=lambda **kwargs: f"final::{kwargs['text']}",
        log_assistant_event=lambda event_type, **kwargs: logged_events.append(
            {"event_type": event_type, **kwargs}
        ),
        router_tool_map={
            "direct_response": lambda **kwargs: direct_calls.append(dict(kwargs)),
        },
    )

    reporter.complete_direct_response(
        agent="direct",
        response_text="All done",
        chain_steps=[],
        direct_args={"variant": "compact"},
        metadata={"delegated_steps": 0},
    )

    assert direct_calls == [
        {
            "text": "final::All done",
            "source": "rapid_response",
            "variant": "compact",
        }
    ]
    assert history_calls == [("assistant", "final::All done", "rapid")]
    assert logged_events == [
        {
            "event_type": "request_completed",
            "request_id": "req-direct",
            "agent": "direct",
            "task": "open localhost 3000",
            "message": "final::All done",
            "success": True,
            "metadata": {"delegated_steps": 0},
        }
    ]


def test_rapid_request_outcome_reporter_logs_failures_consistently() -> None:
    direct_calls: list[dict[str, object]] = []
    history_calls: list[tuple[str, str, str]] = []
    logged_events: list[dict[str, object]] = []

    reporter = rapid_outcomes.RapidRequestOutcomeReporter(
        request_id="req-failed",
        user_prompt="open localhost 3000",
        append_rapid_history=lambda role, text, source: history_calls.append((role, text, source)),
        clean_text=lambda value, fallback, max_len: str(value or fallback),
        finalize_direct_response_text=lambda **kwargs: str(kwargs["text"]),
        log_assistant_event=lambda event_type, **kwargs: logged_events.append(
            {"event_type": event_type, **kwargs}
        ),
        router_tool_map={
            "direct_response": lambda **kwargs: direct_calls.append(dict(kwargs)),
        },
    )

    reporter.fail_request(
        agent="router",
        message="Router failed: invalid routing response shape.",
        error="Invalid routing response shape.",
        metadata={"step_index": 1},
    )

    assert direct_calls == [
        {
            "text": "Router failed: invalid routing response shape.",
            "source": "rapid_response",
        }
    ]
    assert history_calls == [
        ("assistant", "Router failed: invalid routing response shape.", "rapid")
    ]
    assert logged_events == [
        {
            "event_type": "request_failed",
            "request_id": "req-failed",
            "agent": "router",
            "task": "open localhost 3000",
            "message": "Router failed: invalid routing response shape.",
            "error": "Invalid routing response shape.",
            "success": False,
            "metadata": {"step_index": 1},
        }
    ]
