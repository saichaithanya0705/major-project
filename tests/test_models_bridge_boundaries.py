"""
Checks that models.models keeps its public bridge API while delegating cohesive
runtime concerns to named modules.
"""

import os
import sys
from typing import get_origin, get_type_hints

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
import models.browser_resume_route as browser_resume_route
import models.direct_answer_runtime as direct_answer_runtime
import models.jarvis_response_runtime as jarvis_response_runtime
import models.model_initialization as model_initialization
import models.openrouter_runtime as openrouter_runtime
import models.rapid_orchestrator_deps as rapid_orchestrator_deps
import models.request_agent_step_runtime as request_agent_step_runtime
import models.request_entrypoint as request_entrypoint
import models.router_provider_calls as router_provider_calls
import models.router_provider_policy as router_provider_policy
import models.router_execution_policy as router_execution_policy
import models.router_runtime as router_runtime
import models.router_runtime_contracts as router_runtime_contracts
import models.routing_policy as routing_policy
import models.screen_context_runtime as screen_context_runtime


def test_screenshot_public_api_is_extracted_from_models_bridge() -> None:
    assert model_module.store_screenshot.__module__ == "models.screenshot_store"
    assert model_module.get_stored_screenshot.__module__ == "models.screenshot_store"
    assert model_module.prepare_vision_screenshot.__module__ == "models.screenshot_store"


def test_models_bridge_does_not_reexport_browser_resume_helper() -> None:
    assert not hasattr(model_module, "_resume_interrupted_agent_route")
    assert browser_resume_route.build_browser_resume_route.__module__ == "models.browser_resume_route"


def test_preflight_public_api_is_extracted_from_models_bridge() -> None:
    assert model_module.preflight_router_configuration.__module__ == "models.router_preflight"


def test_model_initialization_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.initialize_gemini_model_runtime is model_initialization.initialize_gemini_model_runtime


def test_openrouter_bridge_methods_preserve_legacy_model_keyword() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.openrouter_api_key = ""
    model.openrouter_url = ""
    model.openrouter_site_url = ""
    model.openrouter_site_name = ""
    model.openrouter_timeout_seconds = 1
    model.openrouter_model = ""
    model.openrouter_vision_model = ""

    try:
        model._call_openrouter_text_sync(
            "system",
            "user",
            0.1,
            10,
            model="explicit-text-model",
        )
        raise AssertionError("Expected OpenRouter configuration failure.")
    except RuntimeError as exc:
        assert "OpenRouter fallback is not configured" in str(exc)

    try:
        model._call_openrouter_tool_sync(
            "system",
            "user",
            [],
            0.1,
            10,
            model="explicit-tool-model",
        )
        raise AssertionError("Expected OpenRouter configuration failure.")
    except RuntimeError as exc:
        assert "OpenRouter tool fallback is not configured" in str(exc)


def test_router_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.GeminiModel.route_request is router_runtime.route_request
    assert not hasattr(model_module.GeminiModel, "_router_wall_timeout_seconds")
    assert not hasattr(model_module.GeminiModel, "_call_router_provider_with_wall_timeout")


def test_router_runtime_uses_typed_request_scope_contracts() -> None:
    hints = get_type_hints(router_runtime.route_request)
    timeout_hints = get_type_hints(router_runtime.call_router_provider_with_wall_timeout)

    assert hints["model"] is router_runtime_contracts.RouterRuntimeModel
    assert hints["request_context"] == router_runtime_contracts.RouterRequestContext | None
    assert hints["return"] == router_runtime_contracts.RouterNormalizedPayload
    assert timeout_hints["model"] is router_runtime_contracts.RouterRuntimeModel
    assert timeout_hints["call"] is router_runtime_contracts.RouterProviderCall
    assert get_origin(timeout_hints["return"]) is dict
    assert router_runtime.RouterRequestContext is router_runtime_contracts.RouterRequestContext
    assert router_runtime.RouterProviderFailure is router_runtime_contracts.RouterProviderFailure
    assert not hasattr(router_runtime, "get_last_router_provider_failures")
    assert not hasattr(router_runtime, "clear_last_router_provider_failures")


def test_models_bridge_does_not_export_default_rapid_history_alias() -> None:
    assert not hasattr(model_module, "_RAPID_CONVERSATION_HISTORY")


def test_models_bridge_does_not_reexport_request_step_runner() -> None:
    assert not hasattr(model_module, "_run_routed_agent_step")
    assert request_agent_step_runtime.run_request_agent_step.__module__ == "models.request_agent_step_runtime"
    hints = get_type_hints(request_agent_step_runtime.run_request_agent_step)
    assert hints["routing_result"] == rapid_orchestrator_deps.RapidRouteResult
    assert hints["return"] == rapid_orchestrator_deps.RapidAgentStepResult


def test_router_provider_call_runtime_is_extracted_from_models_bridge() -> None:
    assert (
        model_module.GeminiModel._call_openrouter_router_sync
        is router_provider_calls.call_openrouter_router_sync
    )
    assert (
        model_module.GeminiModel._call_nvidia_router_sync
        is router_provider_calls.call_nvidia_router_sync
    )
    assert (
        model_module.GeminiModel._call_ollama_router_sync
        is router_provider_calls.call_ollama_router_sync
    )


def test_openrouter_fallback_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.GeminiModel._call_openrouter_text_sync.__module__ == "models.models"
    assert model_module.GeminiModel._call_openrouter_tool_sync.__module__ == "models.models"
    assert model_module.GeminiModel._try_openrouter_text_fallback is openrouter_runtime.try_openrouter_text_fallback
    assert model_module.GeminiModel._try_openrouter_tool_fallback is openrouter_runtime.try_openrouter_tool_fallback


def test_direct_answer_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.GeminiModel.answer_direct_request is direct_answer_runtime.answer_direct_request
    assert model_module.GeminiModel.answer_web_qa_request is direct_answer_runtime.answer_web_qa_request


def test_screen_context_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.GeminiModel.generate_screen_context is screen_context_runtime.generate_screen_context


def test_jarvis_response_runtime_is_extracted_from_models_bridge() -> None:
    assert model_module.GeminiModel.generate_jarvis_response is jarvis_response_runtime.generate_jarvis_response


def test_rapid_orchestrator_deps_builder_is_extracted_from_models_bridge() -> None:
    assert model_module.build_rapid_orchestrator_deps is rapid_orchestrator_deps.build_rapid_orchestrator_deps


def test_call_gemini_entrypoint_is_extracted_from_models_bridge() -> None:
    assert model_module.run_gemini_request is request_entrypoint.run_gemini_request


def test_models_bridge_does_not_reexport_routing_policy_internals() -> None:
    for name in (
        "_apply_routing_guardrails",
        "_router_provider_order",
        "_parse_json_object_from_text",
        "_is_execution_request",
        "_is_visual_explanation_request",
    ):
        assert not hasattr(model_module, name), name


class _RouterExecutionPolicyModel:
    router_provider = "openrouter"
    nvidia_api_key = "nvidia-key"
    nvidia_router_model = "nvidia-router"
    nvidia_url = "https://nvidia.example.invalid"
    nvidia_timeout_seconds = 1
    openrouter_api_key = "openrouter-key"
    openrouter_router_model = "openrouter-router"
    openrouter_url = "https://openrouter.example.invalid"
    openrouter_timeout_seconds = 2
    ollama_router_model = ""
    ollama_base_url = ""
    ollama_router_timeout_seconds = 90
    router_wall_timeout_grace_seconds = 0.5

    def _call_openrouter_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": prompt}

    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": prompt}

    def _call_ollama_router_sync(self, prompt: str):
        raise AssertionError("Ollama should not be enabled for this test.")


class _MissingOpenRouterExecutionPolicyModel(_RouterExecutionPolicyModel):
    _call_openrouter_router_sync = None


def test_router_execution_policy_is_testable_outside_route_request() -> None:
    model = _RouterExecutionPolicyModel()
    plan = router_execution_policy.build_router_provider_execution_plan(model)

    assert [entry.provider for entry in plan] == ["openrouter", "nvidia"]

    openrouter_entry, nvidia_entry = plan
    assert openrouter_entry.display_name == "OpenRouter"
    assert openrouter_entry.model_label == "openrouter-router (OpenRouter)"
    assert openrouter_entry.timeout_seconds == 2.5
    assert openrouter_entry.call is not None
    assert openrouter_entry.call.__self__ is model
    assert (
        openrouter_entry.call.__func__
        is _RouterExecutionPolicyModel._call_openrouter_router_sync
    )
    assert openrouter_entry.configuration_error is None

    assert nvidia_entry.display_name == "NVIDIA"
    assert nvidia_entry.model_label == "nvidia-router (NVIDIA)"
    assert nvidia_entry.timeout_seconds == 1.5
    assert nvidia_entry.call is not None
    assert nvidia_entry.call.__self__ is model
    assert nvidia_entry.call.__func__ is _RouterExecutionPolicyModel._call_nvidia_router_sync
    assert nvidia_entry.configuration_error is None


def test_router_execution_policy_surfaces_configuration_failures_without_route_request() -> None:
    plan = router_execution_policy.build_router_provider_execution_plan(
        _MissingOpenRouterExecutionPolicyModel()
    )

    assert [entry.provider for entry in plan] == ["openrouter", "nvidia"]
    assert plan[0].configuration_error is not None
    assert "_call_openrouter_router_sync" in str(plan[0].configuration_error)
    assert plan[0].call is None
    assert plan[1].configuration_error is None


def test_router_provider_policy_boundary_is_shared_between_routing_and_runtime() -> None:
    model = _RouterExecutionPolicyModel()

    assert routing_policy._router_provider_order is router_provider_policy.router_provider_order
    assert (
        router_execution_policy.router_provider_order(model)
        == router_provider_policy.router_provider_order_for_model(model)
    )
