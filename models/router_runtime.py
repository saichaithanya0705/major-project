"""Router-provider runtime for GeminiModel-compatible router objects."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from models.model_status import set_model_label
from models.router_backend_types import JsonValue
from models.router_execution_policy import (
    RouterProviderExecution,
    build_router_provider_execution_plan,
    router_provider_order,
    router_wall_timeout_seconds,
)
from models.router_runtime_contracts import (
    RouterProviderCall,
    RouterProviderFailure,
    RouterProviderFailureKind,
    RouterProviderName,
    RouterProviderPayload,
    RouterNormalizedPayload,
    RouterRequestContext,
    RouterRuntimeModel,
)
from models.routing_decision_policy import (
    normalize_router_decision_payload as _normalize_router_decision_payload,
)
from models.text_normalization import clean_text as _clean_text


__all__ = [
    "RouterProviderCall",
    "RouterProviderFailure",
    "RouterProviderFailureKind",
    "RouterProviderName",
    "RouterProviderPayload",
    "RouterNormalizedPayload",
    "RouterRequestContext",
    "RouterRuntimeModel",
    "call_router_provider_with_wall_timeout",
    "route_request",
    "router_provider_order",
    "router_wall_timeout_seconds",
]


def _record_router_provider_failure(
    request_context: RouterRequestContext,
    *,
    provider: RouterProviderName,
    kind: RouterProviderFailureKind,
    error: BaseException,
    message: str,
    timeout_seconds: float,
) -> None:
    request_context.record_provider_failure(
        provider=provider,
        kind=kind,
        message=message,
        error=error,
        timeout_seconds=timeout_seconds,
    )


async def call_router_provider_with_wall_timeout(
    model: RouterRuntimeModel,
    provider: RouterProviderName,
    call: RouterProviderCall,
    prompt: str,
) -> RouterProviderPayload:
    timeout_seconds = router_wall_timeout_seconds(model, provider)
    return await asyncio.wait_for(
        asyncio.to_thread(call, prompt),
        timeout=timeout_seconds,
    )


async def _call_router_payload_with_provider(
    model: RouterRuntimeModel,
    execution: RouterProviderExecution,
    prompt: str,
) -> RouterProviderPayload:
    call = execution.call
    if call is None:
        raise RuntimeError(
            f"{execution.provider} router execution is missing a provider call."
        )
    await set_model_label(
        execution.model_label,
        context=f"router:{execution.provider}",
    )
    return await call_router_provider_with_wall_timeout(
        model,
        execution.provider,
        call,
        prompt,
    )


def _normalize_router_payload(
    *,
    execution: RouterProviderExecution,
    payload: RouterProviderPayload,
    prompt: str,
) -> RouterNormalizedPayload:
    return _normalize_router_decision_payload(
        payload,
        prompt,
        provider_name=execution.display_name,
    )


def _failure_message(
    *,
    provider: RouterProviderName,
    kind: RouterProviderFailureKind,
    error: BaseException,
    timeout_seconds: float,
) -> str:
    if kind == "timeout":
        return f"{provider} router timed out after {timeout_seconds:.1f}s."
    if kind == "configuration":
        return _clean_text(str(error), f"{provider} router is not configured.", max_len=420)
    return _clean_text(str(error), "Router generation failed.", max_len=420)


def _log_router_failure(
    *,
    provider: RouterProviderName,
    kind: RouterProviderFailureKind,
    message: str,
) -> None:
    phase = kind.replace("_", " ")
    print(f"[Router] {provider} routing {phase} failed: {message}")


async def route_request(
    model: RouterRuntimeModel,
    prompt: str,
    *,
    request_context: RouterRequestContext | None = None,
) -> RouterNormalizedPayload:
    """
    Route a prompt through the configured router providers.

    The model object supplies provider configuration plus the provider-call
    methods. This keeps the provider loop out of the model bridge while
    preserving GeminiModel.route_request as a public API.
    """
    active_request_context = request_context or RouterRequestContext()
    active_request_context.reset_provider_failures()
    print(f"[Router] Processing via {getattr(model, 'router_provider', '')}...")
    started = time.monotonic()

    execution_plan = build_router_provider_execution_plan(model)
    if not execution_plan:
        raise RuntimeError(
            "Router provider is not configured. Set NVIDIA_API_KEY for NVIDIA routing, "
            "OPENROUTER_API_KEY for OpenRouter routing, or configure an Ollama router model."
        )

    last_error = ""
    for execution in execution_plan:
        provider = execution.provider
        timeout_seconds = execution.timeout_seconds
        if execution.configuration_error is not None:
            exc = execution.configuration_error
            error = _failure_message(
                provider=provider,
                kind="configuration",
                error=exc,
                timeout_seconds=timeout_seconds,
            )
            _log_router_failure(provider=provider, kind="configuration", message=error)
            _record_router_provider_failure(
                active_request_context,
                provider=provider,
                kind="configuration",
                error=exc,
                message=error,
                timeout_seconds=timeout_seconds,
            )
            last_error = error
            continue

        try:
            payload = await _call_router_payload_with_provider(model, execution, prompt)
        except asyncio.TimeoutError as exc:
            error = _failure_message(
                provider=provider,
                kind="timeout",
                error=exc,
                timeout_seconds=timeout_seconds,
            )
            _log_router_failure(provider=provider, kind="timeout", message=error)
            _record_router_provider_failure(
                active_request_context,
                provider=provider,
                kind="timeout",
                error=exc,
                message=error,
                timeout_seconds=timeout_seconds,
            )
            last_error = error
            continue
        except Exception as exc:
            error = _failure_message(
                provider=provider,
                kind="provider_call",
                error=exc,
                timeout_seconds=timeout_seconds,
            )
            _log_router_failure(provider=provider, kind="provider_call", message=error)
            _record_router_provider_failure(
                active_request_context,
                provider=provider,
                kind="provider_call",
                error=exc,
                message=error,
                timeout_seconds=timeout_seconds,
            )
            last_error = error
            continue

        try:
            routed = _normalize_router_payload(
                execution=execution,
                payload=payload,
                prompt=prompt,
            )
        except Exception as exc:
            error = _failure_message(
                provider=provider,
                kind="normalization",
                error=exc,
                timeout_seconds=timeout_seconds,
            )
            _log_router_failure(provider=provider, kind="normalization", message=error)
            _record_router_provider_failure(
                active_request_context,
                provider=provider,
                kind="normalization",
                error=exc,
                message=error,
                timeout_seconds=timeout_seconds,
            )
            last_error = error
            continue

        elapsed = time.monotonic() - started
        outcome_label = (
            f"plan[{len(routed.get('tasks', []))}]"
            if "tasks" in routed
            else f"agent={routed.get('agent')}"
        )
        print(f"[Router] Completed in {elapsed:.2f}s via {provider} with {outcome_label}")
        return routed

    raise RuntimeError(f"Router failed using configured provider(s): {last_error or 'unknown error'}")
