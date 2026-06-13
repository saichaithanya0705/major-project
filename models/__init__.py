"""
JARVIS Models - LLM integration and routing.

The package keeps imports lazy so lightweight consumers (for example, tests
that only need contracts/prompts) do not eagerly pull optional runtime deps.
"""

import sys
import types
from importlib import import_module
from typing import TYPE_CHECKING

class LazyModule(types.ModuleType):
    """
    A lazy module proxy that defers actual import until attribute access.
    This prevents circular import errors during early package bootstrapping.
    """
    def __init__(self, old_name, new_name):
        super().__init__(old_name)
        object.__setattr__(self, "_LazyModule__new_name", new_name)
        object.__setattr__(self, "_LazyModule__resolved_module", None)

    def _resolve(self):
        resolved = object.__getattribute__(self, "_LazyModule__resolved_module")
        if resolved is None:
            new_name = object.__getattribute__(self, "_LazyModule__new_name")
            resolved = import_module(new_name)
            object.__setattr__(self, "_LazyModule__resolved_module", resolved)
        return resolved

    def __getattribute__(self, name):
        if name in ("__name__", "__package__", "__loader__", "__spec__", "__path__", "__annotations__"):
            try:
                return object.__getattribute__(self, name)
            except AttributeError:
                pass
        if name in ("_resolve", "_LazyModule__new_name", "_LazyModule__resolved_module"):
            return object.__getattribute__(self, name)

        resolved = self._resolve()
        return getattr(resolved, name)

    def __setattr__(self, name, value):
        resolved = self._resolve()
        setattr(resolved, name, value)

    def __dir__(self):
        resolved = self._resolve()
        return dir(resolved)


# Map old module imports (models.xxx) to their new subfolders (models.category.xxx)
_MOVED_MODULES = {
    # Orchestrator
    "models.orchestrator_adapters": "models.orchestrator.orchestrator_adapters",
    "models.orchestrator_artifacts": "models.orchestrator.orchestrator_artifacts",
    "models.orchestrator_contracts": "models.orchestrator.orchestrator_contracts",
    "models.orchestrator_executor": "models.orchestrator.orchestrator_executor",
    "models.orchestrator_planner": "models.orchestrator.orchestrator_planner",
    "models.orchestrator_quality": "models.orchestrator.orchestrator_quality",
    "models.orchestrator_resources": "models.orchestrator.orchestrator_resources",
    "models.orchestrator_scheduler": "models.orchestrator.orchestrator_scheduler",
    "models.orchestrator_snapshots": "models.orchestrator.orchestrator_snapshots",
    "models.rapid_orchestrator": "models.orchestrator.rapid_orchestrator",
    "models.rapid_orchestrator_contracts": "models.orchestrator.rapid_orchestrator_contracts",
    "models.rapid_orchestrator_deps": "models.orchestrator.rapid_orchestrator_deps",
    "models.rapid_orchestrator_outcomes": "models.orchestrator.rapid_orchestrator_outcomes",
    "models.rapid_plan_orchestrator": "models.orchestrator.rapid_plan_orchestrator",

    # Routing
    "models.router_backend_parsing": "models.routing.router_backend_parsing",
    "models.router_backend_types": "models.routing.router_backend_types",
    "models.router_backends": "models.routing.router_backends",
    "models.router_execution_policy": "models.routing.router_execution_policy",
    "models.router_preflight": "models.routing.router_preflight",
    "models.router_provider_calls": "models.routing.router_provider_calls",
    "models.router_provider_config": "models.routing.router_provider_config",
    "models.router_provider_policy": "models.routing.router_provider_policy",
    "models.router_runtime": "models.routing.router_runtime",
    "models.router_runtime_contracts": "models.routing.router_runtime_contracts",
    "models.routing_decision_policy": "models.routing.routing_decision_policy",
    "models.routing_guardrails": "models.routing.routing_guardrails",
    "models.routing_intent_policy": "models.routing.routing_intent_policy",
    "models.routing_payload_parser": "models.routing.routing_payload_parser",
    "models.routing_policy": "models.routing.routing_policy",
    "models.routing_prompt_parser": "models.routing.routing_prompt_parser",
    "models.routing_prompt_state": "models.routing.routing_prompt_state",
    "models.routing_question_policy": "models.routing.routing_question_policy",
    "models.routing_step_identity": "models.routing.routing_step_identity",
    "models.routing_surface_policy": "models.routing.routing_surface_policy",
    "models.function_calls": "models.routing.function_calls",
    "models.prompts": "models.routing.prompts",

    # Runtime
    "models.agent_step_execution_runtime": "models.runtime.agent_step_execution_runtime",
    "models.agent_step_runner": "models.runtime.agent_step_runner",
    "models.browser_resume_route": "models.runtime.browser_resume_route",
    "models.direct_answer_runtime": "models.runtime.direct_answer_runtime",
    "models.direct_response_policy": "models.runtime.direct_response_policy",
    "models.jarvis_response_runtime": "models.runtime.jarvis_response_runtime",
    "models.request_agent_step_runtime": "models.runtime.request_agent_step_runtime",
    "models.request_entrypoint": "models.runtime.request_entrypoint",
    "models.runtime_config": "models.runtime.runtime_config",
    "models.screen_context_execution_runtime": "models.runtime.screen_context_execution_runtime",
    "models.screen_context_policy": "models.runtime.screen_context_policy",
    "models.screen_context_runtime": "models.runtime.screen_context_runtime",
    "models.rapid_completion_recovery_policy": "models.runtime.rapid_completion_recovery_policy",
    "models.rapid_direct_chat_flow": "models.runtime.rapid_direct_chat_flow",
    "models.rapid_direct_answer_flow": "models.runtime.rapid_direct_chat_flow",
    "models.rapid_state": "models.runtime.rapid_state",
    "models.rapid_step_execution_runtime": "models.runtime.rapid_step_execution_runtime",
    "models.rapid_step_payloads": "models.runtime.rapid_step_payloads",

    # Shared
    "models.contracts": "models.shared.contracts",
    "models.json_payload_coercion": "models.shared.json_payload_coercion",
    "models.model_initialization": "models.shared.model_initialization",
    "models.model_status": "models.shared.model_status",
    "models.openrouter_fallback": "models.shared.openrouter_fallback",
    "models.openrouter_runtime": "models.shared.openrouter_runtime",
    "models.screenshot_store": "models.shared.screenshot_store",
    "models.text_normalization": "models.shared.text_normalization",
    "models.output_file_artifacts": "models.shared.output_file_artifacts",
}

# Dynamic sys.modules registration using LazyModule proxies to keep legacy imports fully working
for old_name, new_name in _MOVED_MODULES.items():
    sys.modules[old_name] = LazyModule(old_name, new_name)

__all__ = [
    "GeminiModel",
    "RAPID_RESPONSE_SYSTEM_PROMPT",
    "RAPID_RESPONSE_TOOL_MAP",
    "RAPID_RESPONSE_TOOLS",
    "ROUTER_TOOL_MAP",
    "ROUTER_TOOLS",
    "TOOL_CONFIG",
    "call_gemini",
    "get_stored_screenshot",
    "store_screenshot",
]

_MODEL_EXPORTS = {
    "call_gemini",
    "store_screenshot",
    "get_stored_screenshot",
    "GeminiModel",
}
_FUNCTION_CALL_EXPORTS = {
    "ROUTER_TOOLS",
    "ROUTER_TOOL_MAP",
    "TOOL_CONFIG",
    "RAPID_RESPONSE_TOOLS",
    "RAPID_RESPONSE_TOOL_MAP",
}

if TYPE_CHECKING:
    from models.routing.function_calls import (
        RAPID_RESPONSE_TOOL_MAP,
        RAPID_RESPONSE_TOOLS,
        ROUTER_TOOL_MAP,
        ROUTER_TOOLS,
        TOOL_CONFIG,
    )
    from models.models import GeminiModel, call_gemini, get_stored_screenshot, store_screenshot
    from models.routing.prompts import RAPID_RESPONSE_SYSTEM_PROMPT


def __getattr__(name: str):
    if name in _MODEL_EXPORTS:
        return getattr(import_module("models.models"), name)
    if name in _FUNCTION_CALL_EXPORTS:
        return getattr(import_module("models.routing.function_calls"), name)
    if name == "RAPID_RESPONSE_SYSTEM_PROMPT":
        return getattr(import_module("models.routing.prompts"), name)
    raise AttributeError(f"module 'models' has no attribute '{name}'")
