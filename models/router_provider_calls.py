"""Bridge helpers for provider-specific router backend calls."""

from __future__ import annotations

from typing import Any

from models.prompts import OLLAMA_ROUTER_SYSTEM_PROMPT
from models.router_provider_config import (
    nvidia_router_config_from_model,
    ollama_router_config_from_model,
    openrouter_provider_config_from_model,
)
from models.router_backends import (
    call_ollama_router_sync as _call_ollama_router_backend_sync,
    call_nvidia_router_sync as _call_nvidia_router_backend_sync,
    call_openrouter_router_sync as _call_openrouter_router_backend_sync,
)
from models.routing_payload_parser import parse_json_object as _parse_json_object_from_text
from models.text_normalization import clean_text as _clean_text


def _clean_router_text(value: object, fallback: str, max_len: int | None) -> str:
    return _clean_text(value, fallback, max_len=max_len)


def call_openrouter_router_sync(model: Any, prompt: str) -> dict[str, Any]:
    config = openrouter_provider_config_from_model(model)
    return _call_openrouter_router_backend_sync(
        openrouter_api_key=config.api_key,
        openrouter_url=config.url,
        openrouter_site_url=config.site_url,
        openrouter_site_name=config.site_name,
        openrouter_timeout_seconds=config.timeout_seconds,
        openrouter_router_model=config.router_model,
        openrouter_router_max_tokens=config.router_max_tokens,
        router_system_prompt=OLLAMA_ROUTER_SYSTEM_PROMPT,
        prompt=prompt,
        clean_text=_clean_router_text,
        parse_json_object_from_text=_parse_json_object_from_text,
    )


def call_nvidia_router_sync(model: Any, prompt: str) -> dict[str, Any]:
    config = nvidia_router_config_from_model(model)
    return _call_nvidia_router_backend_sync(
        nvidia_api_key=config.api_key,
        nvidia_url=config.url,
        nvidia_timeout_seconds=config.timeout_seconds,
        nvidia_router_model=config.router_model,
        nvidia_router_max_tokens=config.router_max_tokens,
        router_system_prompt=OLLAMA_ROUTER_SYSTEM_PROMPT,
        prompt=prompt,
        clean_text=_clean_router_text,
        parse_json_object_from_text=_parse_json_object_from_text,
    )


def call_ollama_router_sync(model: Any, prompt: str) -> dict[str, Any]:
    config = ollama_router_config_from_model(model)
    return _call_ollama_router_backend_sync(
        ollama_base_url=config.base_url,
        ollama_router_model=config.router_model,
        ollama_router_num_predict=config.router_num_predict,
        ollama_router_num_ctx=config.router_num_ctx,
        ollama_router_think=config.router_think,
        ollama_keep_alive=config.keep_alive,
        ollama_router_timeout_seconds=config.timeout_seconds,
        router_system_prompt=OLLAMA_ROUTER_SYSTEM_PROMPT,
        prompt=prompt,
        clean_text=_clean_router_text,
        parse_json_object_from_text=_parse_json_object_from_text,
    )
