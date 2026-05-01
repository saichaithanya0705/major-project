"""
Runtime configuration resolution for GeminiModel.

This isolates environment parsing and defaults from orchestration logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ModelRuntimeConfig:
    jarvis_thinking_budget: int
    openrouter_api_key: str
    openrouter_model: str
    openrouter_vision_model: str
    openrouter_router_model: str
    openrouter_url: str
    openrouter_site_url: str
    openrouter_site_name: str
    openrouter_timeout_seconds: int
    router_provider: str
    ollama_router_model: str
    ollama_base_url: str
    ollama_keep_alive: str
    ollama_router_timeout_seconds: int
    ollama_router_num_ctx: int
    ollama_router_num_predict: int
    openrouter_router_max_tokens: int
    ollama_router_think: bool
    gemini_backup_model: str


def _bounded_int(env_name: str, fallback: int, lower: int, upper: int) -> int:
    raw = os.getenv(env_name, str(fallback))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = fallback
    return max(lower, min(upper, value))


def _truthy_env(env_name: str, fallback: str = "false") -> bool:
    return os.getenv(env_name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def build_model_runtime_config(
    rapid_response_model: str,
    *,
    default_openrouter_router_model: str,
    default_openrouter_fallback_model: str,
    looks_like_openrouter_model_name: Callable[[str], bool],
    extract_openrouter_model_name: Callable[[str], str],
) -> ModelRuntimeConfig:
    configured_rapid_model = (rapid_response_model or "").strip()
    rapid_model_requests_openrouter = looks_like_openrouter_model_name(configured_rapid_model)
    rapid_openrouter_model = extract_openrouter_model_name(configured_rapid_model)

    openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    openrouter_model = (
        os.getenv("OPENROUTER_MODEL")
        or (rapid_openrouter_model if rapid_model_requests_openrouter else "")
        or default_openrouter_fallback_model
    ).strip()
    openrouter_router_model = (
        os.getenv("OPENROUTER_ROUTER_MODEL")
        or (rapid_openrouter_model if rapid_model_requests_openrouter else "")
        or default_openrouter_router_model
    ).strip()
    openrouter_vision_model = (
        os.getenv("OPENROUTER_VISION_MODEL")
        or os.getenv("OPENROUTER_JARVIS_MODEL")
        or "google/gemma-4-31b-it:free"
    ).strip()
    openrouter_url = (
        os.getenv("OPENROUTER_URL") or "https://openrouter.ai/api/v1/chat/completions"
    ).strip()
    openrouter_site_url = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
    openrouter_site_name = (os.getenv("OPENROUTER_SITE_NAME") or "JARVIS").strip()
    openrouter_timeout_seconds = _bounded_int(
        "OPENROUTER_TIMEOUT_SECONDS",
        fallback=45,
        lower=10,
        upper=180,
    )

    configured_router_provider = (
        os.getenv("ROUTER_PROVIDER")
        or ("openrouter" if rapid_model_requests_openrouter else "")
        or ("openrouter" if openrouter_api_key else "ollama")
    ).strip().lower()
    if configured_router_provider not in {"openrouter", "ollama"}:
        configured_router_provider = "openrouter" if openrouter_api_key else "ollama"

    configured_router_model = (
        os.getenv("OLLAMA_ROUTER_MODEL")
        or rapid_response_model
        or ""
    ).strip()
    if (
        not configured_router_model
        or "gemini" in configured_router_model.lower()
        or looks_like_openrouter_model_name(configured_router_model)
    ):
        configured_router_model = "qwen3.5:4b-q4_K_M"

    ollama_base_url = (
        os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    ).strip().rstrip("/")
    ollama_keep_alive = (os.getenv("OLLAMA_KEEP_ALIVE") or "10m").strip()
    ollama_router_timeout_seconds = _bounded_int(
        "OLLAMA_ROUTER_TIMEOUT_SECONDS",
        fallback=90,
        lower=5,
        upper=180,
    )
    ollama_router_num_ctx = _bounded_int(
        "OLLAMA_ROUTER_NUM_CTX",
        fallback=2048,
        lower=512,
        upper=8192,
    )
    ollama_router_num_predict = _bounded_int(
        "OLLAMA_ROUTER_NUM_PREDICT",
        fallback=240,
        lower=80,
        upper=2048,
    )
    openrouter_router_max_tokens = _bounded_int(
        "OPENROUTER_ROUTER_MAX_TOKENS",
        fallback=260,
        lower=80,
        upper=2048,
    )
    ollama_router_think = _truthy_env("OLLAMA_ROUTER_THINK", fallback="false")
    gemini_backup_model = (
        os.getenv("GEMINI_BACKUP_MODEL") or "gemini-2.0-flash"
    ).strip()
    jarvis_thinking_budget = _bounded_int(
        "JARVIS_THINKING_BUDGET",
        fallback=256,
        lower=0,
        upper=2048,
    )

    return ModelRuntimeConfig(
        jarvis_thinking_budget=jarvis_thinking_budget,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        openrouter_vision_model=openrouter_vision_model,
        openrouter_router_model=openrouter_router_model,
        openrouter_url=openrouter_url,
        openrouter_site_url=openrouter_site_url,
        openrouter_site_name=openrouter_site_name,
        openrouter_timeout_seconds=openrouter_timeout_seconds,
        router_provider=configured_router_provider,
        ollama_router_model=configured_router_model,
        ollama_base_url=ollama_base_url,
        ollama_keep_alive=ollama_keep_alive,
        ollama_router_timeout_seconds=ollama_router_timeout_seconds,
        ollama_router_num_ctx=ollama_router_num_ctx,
        ollama_router_num_predict=ollama_router_num_predict,
        openrouter_router_max_tokens=openrouter_router_max_tokens,
        ollama_router_think=ollama_router_think,
        gemini_backup_model=gemini_backup_model,
    )
