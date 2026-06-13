"""Provider-execution policy assembly for the router runtime."""

from __future__ import annotations

from dataclasses import dataclass

from models.router_provider_policy import router_provider_order_for_model
from models.router_runtime_contracts import (
    RouterProviderCall,
    RouterProviderName,
    RouterRuntimeModel,
)


@dataclass(frozen=True)
class RouterProviderExecution:
    provider: RouterProviderName
    display_name: str
    model_label: str
    timeout_seconds: float
    call: RouterProviderCall | None
    configuration_error: RuntimeError | None = None


class RouterProviderConfigurationError(RuntimeError):
    pass


def router_provider_order(model: RouterRuntimeModel) -> list[RouterProviderName]:
    return router_provider_order_for_model(model)


def router_wall_timeout_seconds(model: RouterRuntimeModel, provider: RouterProviderName) -> float:
    if provider == "nvidia":
        provider_timeout = getattr(model, "nvidia_timeout_seconds", 45)
    elif provider == "openrouter":
        provider_timeout = getattr(model, "openrouter_timeout_seconds", 45)
    else:
        provider_timeout = getattr(model, "ollama_router_timeout_seconds", 90)
    grace_seconds = getattr(model, "router_wall_timeout_grace_seconds", 5.0)
    return max(0.001, float(provider_timeout) + float(grace_seconds))


def _provider_required_members(provider: RouterProviderName) -> tuple[str, ...]:
    if provider == "nvidia":
        return (
            "nvidia_router_model",
            "nvidia_timeout_seconds",
            "_call_nvidia_router_sync",
        )
    if provider == "openrouter":
        return (
            "openrouter_router_model",
            "openrouter_timeout_seconds",
            "_call_openrouter_router_sync",
        )
    return (
        "ollama_router_model",
        "ollama_router_timeout_seconds",
        "_call_ollama_router_sync",
    )


def _validate_router_provider_contract(
    model: RouterRuntimeModel,
    provider: RouterProviderName,
) -> float:
    missing_members: list[str] = []
    for member in _provider_required_members(provider):
        value = getattr(model, member, None)
        if member.startswith("_call_"):
            if not callable(value):
                missing_members.append(member)
            continue
        if value is None:
            missing_members.append(member)
    if missing_members:
        missing = ", ".join(missing_members)
        raise RouterProviderConfigurationError(
            f"{provider} router is missing required router runtime members: {missing}."
        )
    try:
        return router_wall_timeout_seconds(model, provider)
    except (TypeError, ValueError) as exc:
        raise RouterProviderConfigurationError(
            f"{provider} router timeout configuration is invalid: {exc}"
        ) from exc


def _provider_display_name(provider: RouterProviderName) -> str:
    if provider == "nvidia":
        return "NVIDIA"
    if provider == "openrouter":
        return "OpenRouter"
    return "Ollama"


def _provider_model_label(model: RouterRuntimeModel, provider: RouterProviderName) -> str:
    if provider == "nvidia":
        return f"{model.nvidia_router_model} (NVIDIA)"
    if provider == "openrouter":
        return f"{model.openrouter_router_model} (OpenRouter)"
    return f"{model.ollama_router_model} (Ollama)"


def _provider_call(model: RouterRuntimeModel, provider: RouterProviderName) -> RouterProviderCall:
    if provider == "nvidia":
        return model._call_nvidia_router_sync
    if provider == "openrouter":
        return model._call_openrouter_router_sync
    return model._call_ollama_router_sync


def build_router_provider_execution_plan(
    model: RouterRuntimeModel,
) -> tuple[RouterProviderExecution, ...]:
    plan: list[RouterProviderExecution] = []
    for provider in router_provider_order(model):
        display_name = _provider_display_name(provider)
        try:
            plan.append(
                RouterProviderExecution(
                    provider=provider,
                    display_name=display_name,
                    model_label=_provider_model_label(model, provider),
                    timeout_seconds=_validate_router_provider_contract(model, provider),
                    call=_provider_call(model, provider),
                )
            )
        except RouterProviderConfigurationError as exc:
            plan.append(
                RouterProviderExecution(
                    provider=provider,
                    display_name=display_name,
                    model_label="",
                    timeout_seconds=0.0,
                    call=None,
                    configuration_error=exc,
                )
            )
    return tuple(plan)
