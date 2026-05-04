"""
JARVIS Model Integration - Local router + Gemini vision agent logic.

This module handles:
- Screenshot capture and storage
- Two-tier model routing (provider-aware router -> specialized agents)
- Gemini/OpenRouter model configuration for screen tasks
"""
import asyncio
import json
import os
import time
import traceback
from typing import Any, Optional

from PIL import Image
from dotenv import load_dotenv

from core.assistant_logging import log_assistant_event, new_assistant_request_id
from models.agent_step_runner import run_routed_agent_step
from models.function_calls import ROUTER_TOOL_MAP, TOOL_CONFIG
from models.prompts import RAPID_RESPONSE_SYSTEM_PROMPT, OLLAMA_ROUTER_SYSTEM_PROMPT
from models.rapid_state import RAPID_SESSION_STATE
from models.rapid_orchestrator import RapidOrchestratorDeps, run_rapid_request
from models.router_backends import (
    call_ollama_router_sync,
    call_openrouter_router_sync,
    call_openrouter_text_sync,
    call_openrouter_tool_sync,
    validate_ollama_router_model_sync,
)
from models.openrouter_fallback import (
    get_openrouter_models,
    image_to_data_url,
    openrouter_tool_result_to_genai_response,
)
from models.runtime_config import build_model_runtime_config
from models.routing_policy import (
    _apply_routing_guardrails,
    _choose_actionable_agent,
    _clean_text,
    _extract_latest_request,
    _finalize_direct_response_text,
    _format_chain_state_for_prompt,
    _is_execution_request,
    _is_visual_explanation_request,
    _normalize_router_decision_payload,
    _normalize_screen_context_payload,
    _parse_json_object_from_text,
    _router_provider_order,
    _routing_signature,
    _routing_task_text,
    _screen_context_message,
    _user_requested_repeat,
)

# Import JARVIS agent components
from agents.jarvis.tools import JARVIS_TOOLS, JARVIS_TOOL_MAP, set_model_name
from agents.jarvis.tool_declarations import JARVIS_FUNCTION_DECLARATIONS

# Attempt to import Gemini libraries
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
    print('Google Gemini dependencies have not been installed')

load_dotenv()


# ================================================================================
# SCREENSHOT STORAGE (captured before overlay appears)
# ================================================================================

_RAPID_CONVERSATION_HISTORY = RAPID_SESSION_STATE.history
_MAX_ROUTER_CHAIN_STEPS = 6
_REPEATED_STEP_LIMIT = 3
_DEFAULT_OPENROUTER_ROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
_DEFAULT_OPENROUTER_FALLBACK_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"


def _looks_like_openrouter_model_name(model_name: str) -> bool:
    cleaned = (model_name or "").strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith("openrouter:"):
        return True
    return "/" in cleaned or cleaned.endswith(":free")


def _extract_openrouter_model_name(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if cleaned.lower().startswith("openrouter:"):
        return cleaned.split(":", 1)[1].strip()
    return cleaned


def preflight_router_configuration(rapid_response_model: str) -> Optional[str]:
    runtime_config = build_model_runtime_config(
        rapid_response_model,
        default_openrouter_router_model=_DEFAULT_OPENROUTER_ROUTER_MODEL,
        default_openrouter_fallback_model=_DEFAULT_OPENROUTER_FALLBACK_MODEL,
        looks_like_openrouter_model_name=_looks_like_openrouter_model_name,
        extract_openrouter_model_name=_extract_openrouter_model_name,
    )
    provider_order = _router_provider_order(
        router_provider=runtime_config.router_provider,
        openrouter_enabled=bool(runtime_config.openrouter_api_key and runtime_config.openrouter_router_model),
        ollama_enabled=bool(runtime_config.ollama_router_model and runtime_config.ollama_base_url),
    )
    if not provider_order:
        return (
            "Router provider is not configured. Set OPENROUTER_API_KEY for OpenRouter "
            "or configure an Ollama router model."
        )
    if provider_order[0] == "ollama":
        return validate_ollama_router_model_sync(
            ollama_base_url=runtime_config.ollama_base_url,
            ollama_router_model=runtime_config.ollama_router_model,
            timeout_seconds=min(runtime_config.ollama_router_timeout_seconds, 3),
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
        )
    if provider_order[0] == "openrouter" and not runtime_config.openrouter_api_key:
        return "OpenRouter router provider is selected but OPENROUTER_API_KEY is not set."
    return None


def _resume_interrupted_agent_route(user_prompt: str) -> Optional[dict[str, str]]:
    try:
        from agents.browser.agent import BrowserAgent
    except Exception:
        return None

    browser_task = BrowserAgent.resolve_resume_task(user_prompt)
    if browser_task:
        return {
            "agent": "browser",
            "task": browser_task,
        }
    return None

def store_screenshot():
    """Capture and store a screenshot (called before overlay appears)."""
    screenshot = RAPID_SESSION_STATE.capture_screenshot()
    print("Screenshot captured (before overlay)")
    return screenshot


def get_stored_screenshot():
    """Get the stored screenshot and clear it, or capture a new one if none stored."""
    return RAPID_SESSION_STATE.consume_or_capture_screenshot()


def _append_rapid_history(role: str, text: str, source: str) -> None:
    RAPID_SESSION_STATE.append_history(
        role=role,
        text=text,
        source=source,
        cleaner=lambda value: _clean_text(value, "", max_len=600),
    )


def _format_rapid_history_for_prompt() -> str:
    return RAPID_SESSION_STATE.format_history_for_prompt()


async def _run_routed_agent_step(
    model: "GeminiModel",
    routing_result: dict[str, Any],
    jarvis_model: str,
    request_id: str,
) -> dict[str, Any]:
    return await run_routed_agent_step(
        model=model,
        routing_result=routing_result,
        jarvis_model=jarvis_model,
        request_id=request_id,
        get_stored_screenshot=get_stored_screenshot,
    )


# ================================================================================
# MAIN ENTRY POINT
# ================================================================================

async def call_gemini(user_prompt: str, rapid_response_model: str, jarvis_model: str):
    """
    Main entry point - uses two-tier model system:
    1. Rapid response model (router) decides how to handle the request
    2. Routes to appropriate agent: JARVIS, Browser, or Desktop
    """
    request_id = new_assistant_request_id()
    log_assistant_event(
        "request_started",
        request_id=request_id,
        task=_clean_text(user_prompt, "", max_len=1200),
        metadata={
            "rapid_response_model": rapid_response_model,
            "jarvis_model": jarvis_model,
        },
    )

    try:
        deps = RapidOrchestratorDeps(
            model_factory=GeminiModel,
            append_rapid_history=_append_rapid_history,
            format_rapid_history_for_prompt=_format_rapid_history_for_prompt,
            run_routed_agent_step=_run_routed_agent_step,
            get_stored_screenshot=get_stored_screenshot,
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
            format_chain_state_for_prompt=_format_chain_state_for_prompt,
            apply_routing_guardrails=_apply_routing_guardrails,
            routing_task_text=_routing_task_text,
            routing_signature=_routing_signature,
            user_requested_repeat=_user_requested_repeat,
            finalize_direct_response_text=_finalize_direct_response_text,
            screen_context_message=_screen_context_message,
            router_tool_map=ROUTER_TOOL_MAP,
            log_assistant_event=log_assistant_event,
            rapid_response_system_prompt=RAPID_RESPONSE_SYSTEM_PROMPT,
            max_router_chain_steps=_MAX_ROUTER_CHAIN_STEPS,
            repeated_step_limit=_REPEATED_STEP_LIMIT,
        )
        await run_rapid_request(
            user_prompt=user_prompt,
            rapid_response_model=rapid_response_model,
            jarvis_model=jarvis_model,
            request_id=request_id,
            deps=deps,
        )
    except Exception as exc:
        log_assistant_event(
            "request_crashed",
            request_id=request_id,
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
        self.screen_judge_model = "gemini-3-flash-preview"
        runtime_config = build_model_runtime_config(
            self.rapid_response_model,
            default_openrouter_router_model=_DEFAULT_OPENROUTER_ROUTER_MODEL,
            default_openrouter_fallback_model=_DEFAULT_OPENROUTER_FALLBACK_MODEL,
            looks_like_openrouter_model_name=_looks_like_openrouter_model_name,
            extract_openrouter_model_name=_extract_openrouter_model_name,
        )
        self.jarvis_thinking_budget = runtime_config.jarvis_thinking_budget
        self.openrouter_api_key = runtime_config.openrouter_api_key
        self.openrouter_model = runtime_config.openrouter_model
        self.openrouter_vision_model = runtime_config.openrouter_vision_model
        self.openrouter_router_model = runtime_config.openrouter_router_model
        self.openrouter_url = runtime_config.openrouter_url
        self.openrouter_site_url = runtime_config.openrouter_site_url
        self.openrouter_site_name = runtime_config.openrouter_site_name
        self.openrouter_timeout_seconds = runtime_config.openrouter_timeout_seconds
        self.router_provider = runtime_config.router_provider
        self.ollama_router_model = runtime_config.ollama_router_model
        self.ollama_base_url = runtime_config.ollama_base_url
        self.ollama_keep_alive = runtime_config.ollama_keep_alive
        self.ollama_router_timeout_seconds = runtime_config.ollama_router_timeout_seconds
        self.ollama_router_num_ctx = runtime_config.ollama_router_num_ctx
        self.ollama_router_num_predict = runtime_config.ollama_router_num_predict
        self.openrouter_router_max_tokens = runtime_config.openrouter_router_max_tokens
        self.ollama_router_think = runtime_config.ollama_router_think
        self.gemini_backup_model = runtime_config.gemini_backup_model

        # Config for JARVIS model (full capabilities)
        self.jarvis_config = types.GenerateContentConfig(
            temperature=1.2,
            top_p=0.95,
            top_k=64,
            max_output_tokens=3000,
            thinking_config=types.ThinkingConfig(thinking_budget=self.jarvis_thinking_budget),
            tools=JARVIS_TOOLS,
            tool_config=TOOL_CONFIG,
        )

        # Config for one-shot screen context extraction (no tools, strict JSON response).
        self.screen_judge_config = types.GenerateContentConfig(
            temperature=0.2,
            top_p=0.9,
            top_k=40,
            max_output_tokens=1200,
            response_mime_type="application/json",
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

    def _openrouter_model_enabled(self, model_name: str) -> bool:
        return bool(self.openrouter_api_key and model_name and self.openrouter_url)

    def _openrouter_enabled(self) -> bool:
        return self._openrouter_model_enabled(self.openrouter_model)

    def _openrouter_router_enabled(self) -> bool:
        return self._openrouter_model_enabled(self.openrouter_router_model)

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
        model_name = (model or self.openrouter_model or "").strip()
        if not self._openrouter_model_enabled(model_name):
            raise RuntimeError("OpenRouter fallback is not configured.")
        return call_openrouter_text_sync(
            openrouter_api_key=self.openrouter_api_key,
            openrouter_url=self.openrouter_url,
            openrouter_site_url=self.openrouter_site_url,
            openrouter_site_name=self.openrouter_site_name,
            openrouter_timeout_seconds=self.openrouter_timeout_seconds,
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
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
        model_name = (model or self.openrouter_vision_model or self.openrouter_model or "").strip()
        if not self._openrouter_model_enabled(model_name):
            raise RuntimeError("OpenRouter tool fallback is not configured.")
        return call_openrouter_tool_sync(
            openrouter_api_key=self.openrouter_api_key,
            openrouter_url=self.openrouter_url,
            openrouter_site_url=self.openrouter_site_url,
            openrouter_site_name=self.openrouter_site_name,
            openrouter_timeout_seconds=self.openrouter_timeout_seconds,
            model_name=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            function_declarations=function_declarations,
            temperature=temperature,
            max_tokens=max_tokens,
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
            image_data_url=image_data_url,
        )

    def _call_openrouter_router_sync(self, prompt: str) -> dict[str, Any]:
        return call_openrouter_router_sync(
            openrouter_api_key=self.openrouter_api_key,
            openrouter_url=self.openrouter_url,
            openrouter_site_url=self.openrouter_site_url,
            openrouter_site_name=self.openrouter_site_name,
            openrouter_timeout_seconds=self.openrouter_timeout_seconds,
            openrouter_router_model=self.openrouter_router_model,
            openrouter_router_max_tokens=self.openrouter_router_max_tokens,
            router_system_prompt=OLLAMA_ROUTER_SYSTEM_PROMPT,
            prompt=prompt,
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
            parse_json_object_from_text=_parse_json_object_from_text,
        )

    async def _try_openrouter_text_fallback(
        self,
        *,
        label: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 700,
        purpose: str = "text",
        image: Any = None,
        response_format: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        if not self._openrouter_enabled():
            print(f"[{label}] Gemini quota hit but OPENROUTER_API_KEY is not configured.")
            return None

        image_data_url = image_to_data_url(image)
        models_to_try = get_openrouter_models(purpose)
        if purpose == "text" and self.openrouter_model not in models_to_try:
            models_to_try.insert(0, self.openrouter_model)
        elif purpose != "text" and self.openrouter_vision_model not in models_to_try:
            models_to_try.insert(0, self.openrouter_vision_model)

        for model_name in [model for model in models_to_try if model]:
            try:
                await set_model_name(f"{model_name} (OpenRouter)")
            except Exception as exc:
                print(f"[{label}] Failed to update model label for OpenRouter fallback: {exc}")

            try:
                text = await asyncio.to_thread(
                    self._call_openrouter_text_sync,
                    system_prompt,
                    user_prompt,
                    temperature,
                    max_tokens,
                    model=model_name,
                    response_format=response_format,
                    image_data_url=image_data_url,
                )
                print(f"[{label}] OpenRouter fallback succeeded with model {model_name}")
                return text
            except Exception as fallback_exc:
                print(f"[{label}] OpenRouter fallback failed with {model_name}: {fallback_exc}")
        return None

    async def _try_openrouter_tool_fallback(
        self,
        *,
        label: str,
        system_prompt: str,
        user_prompt: str,
        function_declarations: list[dict[str, Any]],
        image: Any = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        purpose: str = "vision",
    ):
        if not self._openrouter_enabled():
            print(f"[{label}] Gemini quota hit but OPENROUTER_API_KEY is not configured.")
            return None

        image_data_url = image_to_data_url(image)
        models_to_try = get_openrouter_models(purpose)
        if self.openrouter_vision_model and self.openrouter_vision_model not in models_to_try:
            models_to_try.insert(0, self.openrouter_vision_model)

        for model_name in [model for model in models_to_try if model]:
            try:
                await set_model_name(f"{model_name} (OpenRouter)")
            except Exception as exc:
                print(f"[{label}] Failed to update model label for OpenRouter fallback: {exc}")

            try:
                result = await asyncio.to_thread(
                    self._call_openrouter_tool_sync,
                    system_prompt,
                    user_prompt,
                    function_declarations,
                    temperature,
                    max_tokens,
                    model=model_name,
                    image_data_url=image_data_url,
                )
                print(f"[{label}] OpenRouter tool fallback succeeded with model {model_name}")
                return openrouter_tool_result_to_genai_response(result)
            except Exception as fallback_exc:
                print(f"[{label}] OpenRouter tool fallback failed with {model_name}: {fallback_exc}")
        return None

    def _call_ollama_router_sync(self, prompt: str) -> dict[str, Any]:
        return call_ollama_router_sync(
            ollama_base_url=self.ollama_base_url,
            ollama_router_model=self.ollama_router_model,
            ollama_router_num_predict=self.ollama_router_num_predict,
            ollama_router_num_ctx=self.ollama_router_num_ctx,
            ollama_router_think=self.ollama_router_think,
            ollama_keep_alive=self.ollama_keep_alive,
            ollama_router_timeout_seconds=self.ollama_router_timeout_seconds,
            router_system_prompt=OLLAMA_ROUTER_SYSTEM_PROMPT,
            prompt=prompt,
            clean_text=lambda value, fallback, max_len: _clean_text(
                value,
                fallback,
                max_len=max_len,
            ),
            parse_json_object_from_text=_parse_json_object_from_text,
        )

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

    def _router_provider_order(self) -> list[str]:
        return _router_provider_order(
            router_provider=self.router_provider,
            openrouter_enabled=self._openrouter_router_enabled(),
            ollama_enabled=bool(self.ollama_router_model and self.ollama_base_url),
        )

    async def route_request(self, prompt: str) -> dict:
        """
        Use the router model to decide how to handle the request.

        Returns:
            dict with keys:
                - agent: "direct" | "jarvis" | "browser" | "cua_cli" | "cua_vision" | "screen_context"
                - query/task: The query or task to pass to the agent
                - response_text: direct response text when agent == "direct"
                - Additional agent-specific params
        """
        print(f"[Router] Processing via {self.router_provider}...")
        started = time.monotonic()

        provider_order = _router_provider_order(
            router_provider=self.router_provider,
            openrouter_enabled=self._openrouter_router_enabled(),
            ollama_enabled=bool(self.ollama_router_model and self.ollama_base_url),
        )
        if not provider_order:
            raise RuntimeError("Router provider is not configured. Set OPENROUTER_API_KEY for OpenRouter routing.")

        last_error = ""
        for provider in provider_order:
            try:
                if provider == "openrouter":
                    try:
                        await set_model_name(f"{self.openrouter_router_model} (OpenRouter)")
                    except Exception as ui_exc:
                        print(f"[Router] Model label update skipped: {ui_exc}")
                    payload = await asyncio.to_thread(self._call_openrouter_router_sync, prompt)
                    routed = _normalize_router_decision_payload(
                        payload,
                        prompt,
                        provider_name="OpenRouter",
                    )
                else:
                    try:
                        await set_model_name(f"{self.ollama_router_model} (Ollama)")
                    except Exception as ui_exc:
                        print(f"[Router] Model label update skipped: {ui_exc}")
                    payload = await asyncio.to_thread(self._call_ollama_router_sync, prompt)
                    routed = _normalize_router_decision_payload(
                        payload,
                        prompt,
                        provider_name="Ollama",
                    )
                elapsed = time.monotonic() - started
                print(
                    f"[Router] Completed in {elapsed:.2f}s via {provider} "
                    f"with agent={routed.get('agent')}"
                )
                return routed
            except Exception as exc:
                error = _clean_text(str(exc), "Router generation failed.", max_len=420)
                print(f"[Router] {provider} routing failed: {error}")
                last_error = error

        raise RuntimeError(f"Router failed using configured provider(s): {last_error or 'unknown error'}")

    async def generate_screen_context(
        self,
        user_request: str,
        image: Image = None,
        focus: str = "",
    ) -> dict[str, Any]:
        """
        Run one multimodal pass to extract concrete screen context for routing.
        """
        print("[ScreenJudge] Capturing context from screenshot...")
        started = time.monotonic()
        focus_text = _clean_text(focus, "", max_len=200)
        judge_prompt = (
            "You are Screen Judge for a computer-use orchestrator.\n"
            "Analyze the screenshot and extract only high-signal routing context.\n"
            "Return JSON ONLY, no markdown.\n\n"
            "Required JSON schema:\n"
            "{\n"
            '  "summary": "short factual summary",\n'
            '  "repo_url": "github/git url if visible else empty string",\n'
            '  "local_url": "localhost/127.0.0.1 URL if visible else empty string",\n'
            '  "recommended_agent": "cua_cli|cua_vision|browser|jarvis|direct",\n'
            '  "recommended_task": "single concrete next step task",\n'
            '  "hints": "short extra details useful for routing"\n'
            "}\n\n"
            f"User request: {user_request}\n"
            f"Extraction focus: {focus_text if focus_text else 'general execution context'}\n"
            "Do not invent URLs. If uncertain, leave fields empty."
        )

        contents = [judge_prompt]
        if image is not None:
            contents.append(image)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.screen_judge_model,
                contents=contents,
                config=self.screen_judge_config,
            )
        except Exception as exc:
            if (
                self._is_gemini_temporary_error(exc)
                and self.gemini_backup_model
                and self.gemini_backup_model != self.screen_judge_model
            ):
                print(
                    f"[ScreenJudge] Primary model unavailable; retrying with backup "
                    f"{self.gemini_backup_model}"
                )
                response = await self.client.aio.models.generate_content(
                    model=self.gemini_backup_model,
                    contents=contents,
                    config=self.screen_judge_config,
                )
                self.screen_judge_model = self.gemini_backup_model
            elif self._is_gemini_quota_error(exc):
                fallback_text = await self._try_openrouter_text_fallback(
                    label="ScreenJudge",
                    system_prompt=(
                        "You are Screen Judge for a computer-use orchestrator.\n"
                        "Analyze the screenshot when one is attached.\n"
                        "Return JSON only with fields: summary, repo_url, local_url,"
                        " recommended_agent, recommended_task, hints.\n"
                        "If you are uncertain, keep fields empty and explain uncertainty in"
                        " summary."
                    ),
                    user_prompt=(
                        f"User request: {user_request}\n"
                        f"Focus: {focus_text if focus_text else 'general execution context'}\n"
                        "Extract only high-signal routing context."
                    ),
                    temperature=0.1,
                    max_tokens=420,
                    purpose="screen",
                    image=image,
                    response_format={"type": "json_object"},
                )
                if fallback_text:
                    parsed = _parse_json_object_from_text(fallback_text)
                    normalized = _normalize_screen_context_payload(parsed, user_request=user_request)
                    if not normalized.get("summary"):
                        normalized["summary"] = _clean_text(
                            fallback_text,
                            "Gemini screen context hit quota. Used text-only fallback.",
                            max_len=420,
                        )
                    normalized["model"] = f"{self.openrouter_model} (openrouter_fallback)"
                    return normalized
            else:
                raise
        elapsed = time.monotonic() - started
        print(f"[ScreenJudge] Completed in {elapsed:.2f}s")

        raw_text = ""
        if hasattr(response, "text") and response.text:
            raw_text = str(response.text)
        else:
            try:
                raw_text = json.dumps(response.to_dict())
            except Exception:
                raw_text = ""

        parsed = _parse_json_object_from_text(raw_text)
        normalized = _normalize_screen_context_payload(parsed, user_request=user_request)
        if not normalized.get("summary"):
            normalized["summary"] = _clean_text(raw_text, "Screen context captured.", max_len=420)
        normalized["model"] = self.screen_judge_model
        return normalized

    async def generate_jarvis_response(self, prompt: str, image: Image = None) -> dict[str, Any]:
        """
        Call the JARVIS model with full screen annotation capabilities.
        """
        print("[JARVIS] Processing with screenshot...")
        started = time.monotonic()
        try:
            await set_model_name(self.jarvis_model)
        except Exception as ui_exc:
            print(f"[JARVIS] Model label update skipped: {ui_exc}")

        contents = [prompt]
        if image:
            contents.append(image)

        try:
            response = await self.client.aio.models.generate_content(
                model=self.jarvis_model,
                contents=contents,
                config=self.jarvis_config
            )
        except Exception as exc:
            if (
                self._is_gemini_temporary_error(exc)
                and self.gemini_backup_model
                and self.gemini_backup_model != self.jarvis_model
            ):
                print(
                    f"[JARVIS] Primary model unavailable; retrying with backup "
                    f"{self.gemini_backup_model}"
                )
                response = await self.client.aio.models.generate_content(
                    model=self.gemini_backup_model,
                    contents=contents,
                    config=self.jarvis_config
                )
                self.jarvis_model = self.gemini_backup_model
            elif self._is_gemini_quota_error(exc):
                fallback_response = await self._try_openrouter_tool_fallback(
                    label="JARVIS",
                    system_prompt=(
                        "You are JARVIS, a screen annotation assistant. "
                        "Use the available tools when annotation or direct response is needed."
                    ),
                    user_prompt=prompt,
                    function_declarations=JARVIS_FUNCTION_DECLARATIONS,
                    image=image,
                    temperature=0.2,
                    max_tokens=1800,
                    purpose="jarvis",
                )
                if fallback_response is not None:
                    response = fallback_response
                else:
                    fallback_text = await self._try_openrouter_text_fallback(
                        label="JARVIS",
                        system_prompt=(
                            "You are JARVIS fallback. Give a concise response to the user request."
                        ),
                        user_prompt=_extract_latest_request(prompt),
                        temperature=0.2,
                        max_tokens=700,
                        purpose="jarvis",
                        image=image,
                    )
                    if fallback_text:
                        return {
                            "response": None,
                            "summary": _clean_text(
                                f"Gemini quota reached. {fallback_text}",
                                "Gemini quota reached. Please retry shortly.",
                                max_len=420,
                            ),
                        }
            else:
                raise
        elapsed = time.monotonic() - started
        print(
            f"[JARVIS] Model call completed in {elapsed:.2f}s "
            f"(thinking_budget={self.jarvis_thinking_budget})"
        )

        parts = response.candidates[0].content.parts
        function_calls = [part.function_call for part in parts if part.function_call]
        summary_text = None

        if function_calls:
            for function_call in function_calls:
                print(f"\n[JARVIS] Function: {function_call.name}")
                print(f"[JARVIS] Arguments: {function_call.args}")

                if function_call.name == "direct_response":
                    summary_text = function_call.args.get("text") or summary_text

                tool = JARVIS_TOOL_MAP.get(function_call.name)
                if tool:
                    tool(**function_call.args)
                else:
                    raise Exception(f"[JARVIS] Invalid tool: {function_call.name}")
        else:
            print("[JARVIS] No function call in response")
            if response.text:
                print(response.text)
                summary_text = response.text

        return {
            "response": response,
            "summary": _clean_text(summary_text, "", max_len=420),
        }
