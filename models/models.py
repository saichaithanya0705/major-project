"""
JARVIS Model Integration - Local router + Gemini vision agent logic.

This module handles:
- Screenshot capture and storage
- Two-tier model routing (provider-aware router -> specialized agents)
- Gemini/OpenRouter model configuration for screen tasks
"""
import asyncio
import os
import traceback
from typing import Any, Optional

from dotenv import load_dotenv

from core.assistant_logging import log_assistant_event, new_assistant_request_id
from models.function_calls import ROUTER_TOOL_MAP
from models.jarvis_response_runtime import generate_jarvis_response
from models.direct_answer_runtime import (
    answer_direct_request,
    answer_web_qa_request,
)
from models.model_initialization import initialize_gemini_model_runtime
from models.rapid_orchestrator import run_rapid_request
from models.rapid_orchestrator_deps import build_rapid_orchestrator_deps
from models.rapid_state import RAPID_SESSION_STATE
import models.request_agent_step_runtime as request_agent_step_runtime
from models.request_entrypoint import run_gemini_request
from models.router_runtime import route_request
from models.screen_context_runtime import generate_screen_context
from models.openrouter_runtime import (
    call_openrouter_text_sync as _call_openrouter_text_sync,
    call_openrouter_tool_sync as _call_openrouter_tool_sync,
    openrouter_enabled as _openrouter_enabled,
    openrouter_model_enabled as _openrouter_model_enabled,
    try_openrouter_text_fallback as _try_openrouter_text_fallback,
    try_openrouter_tool_fallback as _try_openrouter_tool_fallback,
)
from models.router_preflight import (
    preflight_router_configuration,
)
from models.router_provider_calls import (
    call_ollama_router_sync as _call_ollama_router_sync,
    call_nvidia_router_sync as _call_nvidia_router_sync,
    call_openrouter_router_sync as _call_openrouter_router_sync,
)
from models.routing_decision_policy import (
    normalize_router_decision_payload as _normalize_router_decision_payload,
)
from models.routing_prompt_parser import (
    extract_latest_request_from_router_prompt as _extract_latest_request,
)
from models.text_normalization import clean_text as _clean_text
from models.screenshot_store import (
    get_stored_screenshot,
    prepare_vision_screenshot,
    store_screenshot,
)

# Import JARVIS agent components
from agents.jarvis.tools import set_model_name

# Attempt to import Gemini libraries
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
    print('Google Gemini dependencies have not been installed')

load_dotenv()

__all__ = [
    "GeminiModel",
    "call_gemini",
    "preflight_router_configuration",
    "store_screenshot",
    "get_stored_screenshot",
    "prepare_vision_screenshot",
]


# ================================================================================
# RUNTIME BRIDGE STATE
# ================================================================================

_MAX_ROUTER_CHAIN_STEPS = 6
_REPEATED_STEP_LIMIT = 3


# ================================================================================
# MAIN ENTRY POINT
# ================================================================================

async def call_gemini(
    user_prompt: str,
    rapid_response_model: str,
    jarvis_model: str,
    session_id: str | None = None,
):
    try:
        request_id, _rapid_session_id = await run_gemini_request(
            user_prompt=user_prompt,
            rapid_response_model=rapid_response_model,
            jarvis_model=jarvis_model,
            session_id=session_id,
            new_request_id=new_assistant_request_id,
            log_assistant_event=log_assistant_event,
            clean_text=_clean_text,
            rapid_session_state=RAPID_SESSION_STATE,
            build_rapid_orchestrator_deps=build_rapid_orchestrator_deps,
            run_rapid_request=run_rapid_request,
            model_factory=GeminiModel,
            run_routed_agent_step=request_agent_step_runtime.run_request_agent_step,
            get_stored_screenshot=get_stored_screenshot,
            prepare_vision_screenshot=prepare_vision_screenshot,
            max_router_chain_steps=_MAX_ROUTER_CHAIN_STEPS,
            repeated_step_limit=_REPEATED_STEP_LIMIT,
        )
    except Exception as exc:
        log_assistant_event(
            "request_crashed",
            request_id=locals().get("request_id", "unknown"),
            task=_clean_text(user_prompt, "", max_len=420),
            message=_clean_text(str(exc), "Assistant request crashed.", max_len=420),
            error=str(exc),
            success=False,
            metadata={"traceback": traceback.format_exc()},
        )
        raise


# ================================================================================
# MODEL ORCHESTRATOR CLASS
# ================================================================================

class GeminiModel:
    """
    Model orchestrator with provider-aware routing and Gemini screen capabilities.

    Two-tier system:
    - Router model: OpenRouter or Ollama text model, no image, decides where to route requests
    - JARVIS model: Gemini with screenshot, for screen annotations and screen context

    Documentation Reference: https://github.com/googleapis/python-genai
    """

    def __init__(self, jarvis_model='gemini-3-flash-preview', rapid_response_model='qwen3.5:4b-q4_K_M'):
        if genai is None or types is None:
            raise RuntimeError(
                "Google Gemini dependencies are required to initialize GeminiModel. "
                "Install `google-genai` and its dependencies."
            )
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.jarvis_model = jarvis_model
        self.rapid_response_model = rapid_response_model
        initialize_gemini_model_runtime(
            self,
            rapid_response_model=self.rapid_response_model,
            types_module=types,
        )

    @staticmethod
    def _is_gemini_quota_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "429",
            "resource_exhausted",
            "quota",
            "rate limit",
            "rate_limit",
            "too many requests",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _is_gemini_temporary_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "503",
            "unavailable",
            "high demand",
            "temporarily unavailable",
            "overloaded",
            "deadline exceeded",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _extract_latest_request(prompt: str) -> str:
        return _extract_latest_request(prompt)

    _openrouter_model_enabled = _openrouter_model_enabled
    _openrouter_enabled = _openrouter_enabled

    def _call_openrouter_text_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        *,
        model: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        image_data_url: Optional[str] = None,
    ) -> str:
        return _call_openrouter_text_sync(
            self,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            model_name=model,
            response_format=response_format,
            image_data_url=image_data_url,
        )

    def _call_openrouter_tool_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        function_declarations: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        *,
        model: Optional[str] = None,
        image_data_url: Optional[str] = None,
    ) -> dict[str, Any]:
        return _call_openrouter_tool_sync(
            self,
            system_prompt,
            user_prompt,
            function_declarations,
            temperature,
            max_tokens,
            model_name=model,
            image_data_url=image_data_url,
        )

    _call_openrouter_router_sync = _call_openrouter_router_sync
    _call_nvidia_router_sync = _call_nvidia_router_sync

    _try_openrouter_text_fallback = _try_openrouter_text_fallback
    _try_openrouter_tool_fallback = _try_openrouter_tool_fallback

    _call_ollama_router_sync = _call_ollama_router_sync

    answer_direct_request = answer_direct_request
    answer_web_qa_request = answer_web_qa_request

    def _normalize_router_decision(
        self,
        payload: dict[str, Any],
        prompt: str,
        *,
        provider_name: str,
    ) -> dict[str, Any]:
        return _normalize_router_decision_payload(
            payload,
            prompt,
            provider_name=provider_name,
        )

    route_request = route_request

    generate_screen_context = generate_screen_context

    generate_jarvis_response = generate_jarvis_response
