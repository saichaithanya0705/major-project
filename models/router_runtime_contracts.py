"""Typed contracts and request-scoped state for the router runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from models.router_backend_types import JsonValue
from models.routing_payload_parser import JsonObject, RoutingResult

RouterProviderName = Literal["nvidia", "openrouter", "ollama"]
RouterProviderFailureKind = Literal[
    "timeout",
    "configuration",
    "provider_call",
    "normalization",
]


RouterProviderPayload = JsonObject
RouterNormalizedPayload = RoutingResult


class RouterProviderCall(Protocol):
    def __call__(self, prompt: str) -> RouterProviderPayload:
        ...


class RouterRuntimeModel(Protocol):
    router_provider: str
    nvidia_api_key: str
    nvidia_router_model: str
    nvidia_url: str
    nvidia_timeout_seconds: float | int
    openrouter_api_key: str
    openrouter_router_model: str
    openrouter_url: str
    openrouter_timeout_seconds: float | int
    ollama_router_model: str
    ollama_base_url: str
    ollama_router_timeout_seconds: float | int
    router_wall_timeout_grace_seconds: float | int

    def _call_nvidia_router_sync(self, prompt: str) -> RouterProviderPayload:
        ...

    def _call_openrouter_router_sync(self, prompt: str) -> RouterProviderPayload:
        ...

    def _call_ollama_router_sync(self, prompt: str) -> RouterProviderPayload:
        ...


@dataclass(frozen=True)
class RouterProviderFailure:
    provider: RouterProviderName
    kind: RouterProviderFailureKind
    message: str
    error: BaseException
    timeout_seconds: float


@dataclass
class RouterRequestContext:
    _provider_failures: list[RouterProviderFailure] = field(default_factory=list)

    @property
    def provider_failures(self) -> tuple[RouterProviderFailure, ...]:
        return tuple(self._provider_failures)

    def reset_provider_failures(self) -> None:
        self._provider_failures.clear()

    def record_provider_failure(
        self,
        *,
        provider: RouterProviderName,
        kind: RouterProviderFailureKind,
        message: str,
        error: BaseException,
        timeout_seconds: float,
    ) -> None:
        self._provider_failures.append(
            RouterProviderFailure(
                provider=provider,
                kind=kind,
                message=message,
                error=error,
                timeout_seconds=timeout_seconds,
            )
        )
