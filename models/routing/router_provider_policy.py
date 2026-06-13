"""Shared provider-order and eligibility policy for router callers."""

from __future__ import annotations

from typing import Protocol


_KNOWN_ROUTER_PROVIDERS = {"", "nvidia", "openrouter", "ollama"}


class RouterProviderPolicyModel(Protocol):
    router_provider: str
    nvidia_api_key: str
    nvidia_router_model: str
    nvidia_url: str
    openrouter_api_key: str
    openrouter_router_model: str
    openrouter_url: str
    ollama_router_model: str
    ollama_base_url: str


def openrouter_model_enabled(
    *,
    api_key: str,
    model_name: str,
    url: str,
) -> bool:
    return bool(api_key and model_name and url)


def openrouter_router_enabled(model: RouterProviderPolicyModel) -> bool:
    return openrouter_model_enabled(
        api_key=getattr(model, "openrouter_api_key", ""),
        model_name=getattr(model, "openrouter_router_model", ""),
        url=getattr(model, "openrouter_url", ""),
    )


def nvidia_router_enabled(model: RouterProviderPolicyModel) -> bool:
    return bool(
        getattr(model, "nvidia_api_key", "")
        and getattr(model, "nvidia_router_model", "")
        and getattr(model, "nvidia_url", "")
    )


def ollama_router_enabled(model: RouterProviderPolicyModel) -> bool:
    return bool(
        getattr(model, "ollama_router_model", "")
        and getattr(model, "ollama_base_url", "")
    )


def router_provider_order(
    *,
    router_provider: str,
    nvidia_enabled: bool,
    openrouter_enabled: bool,
    ollama_enabled: bool,
) -> list[str]:
    normalized_provider = str(router_provider or "").strip().lower()
    if normalized_provider not in _KNOWN_ROUTER_PROVIDERS:
        raise ValueError(f"Unknown router_provider value: {router_provider}")

    providers: list[str] = []

    def add(provider: str, enabled: bool) -> None:
        if enabled and provider not in providers:
            providers.append(provider)

    if normalized_provider == "nvidia":
        add("nvidia", nvidia_enabled)
        add("ollama", ollama_enabled)
    elif normalized_provider == "openrouter":
        add("openrouter", openrouter_enabled)
        add("nvidia", nvidia_enabled)
        add("ollama", ollama_enabled)
    else:
        add("ollama", ollama_enabled)
        add("nvidia", nvidia_enabled)
        add("openrouter", openrouter_enabled)
    return providers


def router_provider_order_for_model(model: RouterProviderPolicyModel) -> list[str]:
    return router_provider_order(
        router_provider=getattr(model, "router_provider", ""),
        nvidia_enabled=nvidia_router_enabled(model),
        openrouter_enabled=openrouter_router_enabled(model),
        ollama_enabled=ollama_router_enabled(model),
    )
