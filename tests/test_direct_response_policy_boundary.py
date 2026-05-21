"""Checks the extracted direct-response policy and text-normalization seams."""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.agent_step_runner as agent_step_runner
import models.direct_answer_runtime as direct_answer_runtime
import models.direct_response_policy as direct_response_policy
import models.rapid_orchestrator_deps as rapid_orchestrator_deps
import models.routing_policy as routing_policy
import models.text_normalization as text_normalization


def test_routing_policy_text_helpers_are_extracted() -> None:
    assert routing_policy._clean_text is text_normalization.clean_text
    assert (
        routing_policy._format_direct_response_text
        is text_normalization.format_direct_response_text
    )
    assert not hasattr(routing_policy, "_finalize_direct_response_text")
    assert not hasattr(routing_policy, "_summarize_completed_steps")
    assert not hasattr(routing_policy, "_looks_like_repeat_artifact")
    assert not hasattr(routing_policy, "_user_requested_repeat")


def test_runtime_modules_import_text_normalization_boundary_directly() -> None:
    assert direct_answer_runtime._clean_text is text_normalization.clean_text
    assert (
        direct_answer_runtime._format_direct_response_text
        is text_normalization.format_direct_response_text
    )
    assert agent_step_runner._clean_text is text_normalization.clean_text
    assert (
        agent_step_runner._format_direct_response_text
        is text_normalization.format_direct_response_text
    )


def test_rapid_deps_builder_uses_direct_response_policy_boundary() -> None:
    assert rapid_orchestrator_deps.user_requested_repeat is direct_response_policy.user_requested_repeat
    assert (
        rapid_orchestrator_deps.finalize_direct_response_text
        is direct_response_policy.finalize_direct_response_text
    )
