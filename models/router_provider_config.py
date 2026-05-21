"""Typed provider configuration extracted from GeminiModel-style attribute bags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpenRouterProviderConfig:
    api_key: str
    url: str
    site_url: str
    site_name: str
    timeout_seconds: int
    default_text_model: str
    default_vision_model: str
    router_model: str
    router_max_tokens: int


@dataclass(frozen=True)
class NvidiaRouterConfig:
    api_key: str
    url: str
    timeout_seconds: int
    router_model: str
    router_max_tokens: int


@dataclass(frozen=True)
class OllamaRouterConfig:
    base_url: str
    router_model: str
    router_num_predict: int
    router_num_ctx: int
    router_think: bool
    keep_alive: str
    timeout_seconds: int


def openrouter_provider_config_from_model(model: Any) -> OpenRouterProviderConfig:
    return OpenRouterProviderConfig(
        api_key=str(getattr(model, "openrouter_api_key", "") or ""),
        url=str(getattr(model, "openrouter_url", "") or ""),
        site_url=str(getattr(model, "openrouter_site_url", "") or ""),
        site_name=str(getattr(model, "openrouter_site_name", "") or ""),
        timeout_seconds=int(getattr(model, "openrouter_timeout_seconds", 45) or 45),
        default_text_model=str(getattr(model, "openrouter_model", "") or ""),
        default_vision_model=str(getattr(model, "openrouter_vision_model", "") or ""),
        router_model=str(getattr(model, "openrouter_router_model", "") or ""),
        router_max_tokens=int(getattr(model, "openrouter_router_max_tokens", 300) or 300),
    )


def nvidia_router_config_from_model(model: Any) -> NvidiaRouterConfig:
    return NvidiaRouterConfig(
        api_key=str(getattr(model, "nvidia_api_key", "") or ""),
        url=str(getattr(model, "nvidia_url", "") or ""),
        timeout_seconds=int(getattr(model, "nvidia_timeout_seconds", 45) or 45),
        router_model=str(getattr(model, "nvidia_router_model", "") or ""),
        router_max_tokens=int(getattr(model, "nvidia_router_max_tokens", 300) or 300),
    )


def ollama_router_config_from_model(model: Any) -> OllamaRouterConfig:
    return OllamaRouterConfig(
        base_url=str(getattr(model, "ollama_base_url", "") or ""),
        router_model=str(getattr(model, "ollama_router_model", "") or ""),
        router_num_predict=int(getattr(model, "ollama_router_num_predict", 700) or 700),
        router_num_ctx=int(getattr(model, "ollama_router_num_ctx", 8192) or 8192),
        router_think=bool(getattr(model, "ollama_router_think", False)),
        keep_alive=str(getattr(model, "ollama_keep_alive", "") or ""),
        timeout_seconds=int(getattr(model, "ollama_router_timeout_seconds", 90) or 90),
    )


def openrouter_config_enabled(config: OpenRouterProviderConfig, model_name: str) -> bool:
    return bool(config.api_key and model_name and config.url)


__all__ = [
    "NvidiaRouterConfig",
    "OllamaRouterConfig",
    "OpenRouterProviderConfig",
    "nvidia_router_config_from_model",
    "ollama_router_config_from_model",
    "openrouter_config_enabled",
    "openrouter_provider_config_from_model",
]
