"""
Router preflight checks and model-runtime defaults.
"""

from __future__ import annotations

from typing import Optional

from models.router_backends import validate_ollama_router_model_sync
from models.router_provider_policy import router_provider_order as _router_provider_order
from models.runtime_config import ModelRuntimeConfig, build_model_runtime_config
from models.text_normalization import clean_text as _clean_text


DEFAULT_OPENROUTER_ROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_OPENROUTER_FALLBACK_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
DEFAULT_NVIDIA_ROUTER_MODEL = "qwen/qwen3.5-397b-a17b"


def looks_like_openrouter_model_name(model_name: str) -> bool:
    cleaned = (model_name or "").strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith("openrouter:"):
        return True
    return "/" in cleaned or cleaned.endswith(":free")


def extract_openrouter_model_name(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if cleaned.lower().startswith("openrouter:"):
        return cleaned.split(":", 1)[1].strip()
    return cleaned


def build_default_model_runtime_config(rapid_response_model: str) -> ModelRuntimeConfig:
    return build_model_runtime_config(
        rapid_response_model,
        default_openrouter_router_model=DEFAULT_OPENROUTER_ROUTER_MODEL,
        default_openrouter_fallback_model=DEFAULT_OPENROUTER_FALLBACK_MODEL,
        default_nvidia_router_model=DEFAULT_NVIDIA_ROUTER_MODEL,
        looks_like_openrouter_model_name=looks_like_openrouter_model_name,
        extract_openrouter_model_name=extract_openrouter_model_name,
    )


def preflight_router_configuration(rapid_response_model: str) -> Optional[str]:
    runtime_config = build_default_model_runtime_config(rapid_response_model)
    provider_order = _router_provider_order(
        router_provider=runtime_config.router_provider,
        nvidia_enabled=bool(runtime_config.nvidia_api_key and runtime_config.nvidia_router_model),
        openrouter_enabled=bool(runtime_config.openrouter_api_key and runtime_config.openrouter_router_model),
        ollama_enabled=bool(runtime_config.ollama_router_model and runtime_config.ollama_base_url),
    )
    if not provider_order:
        return (
            "Router provider is not configured. Set NVIDIA_API_KEY for NVIDIA, OPENROUTER_API_KEY for OpenRouter, "
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
    if provider_order[0] == "nvidia" and not runtime_config.nvidia_api_key:
        return "NVIDIA router provider is selected but NVIDIA_API_KEY is not set."
    return None
