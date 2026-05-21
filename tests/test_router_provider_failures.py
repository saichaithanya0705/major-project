"""
Checks for router provider failure observability.

Usage:
    python tests/test_router_provider_failures.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.router_runtime as router_runtime
from models.router_runtime import route_request
from models.router_runtime_contracts import RouterRequestContext


class _BaseRouterModel:
    router_provider = "openrouter"
    nvidia_api_key = "nvidia-key"
    nvidia_router_model = "nvidia-router"
    nvidia_url = "https://nvidia.example.invalid"
    nvidia_timeout_seconds = 1
    nvidia_router_max_tokens = 10
    openrouter_api_key = "openrouter-key"
    openrouter_router_model = "openrouter-router"
    openrouter_url = "https://openrouter.example.invalid"
    openrouter_timeout_seconds = 1
    openrouter_router_max_tokens = 10
    ollama_router_model = ""
    ollama_base_url = ""
    router_wall_timeout_grace_seconds = 0.01


class _ProviderFailureFallbackModel(_BaseRouterModel):
    def _call_openrouter_router_sync(self, prompt: str):
        raise RuntimeError("openrouter unavailable")

    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "nvidia ok"}


class _NormalizationFailureFallbackModel(_BaseRouterModel):
    def _call_openrouter_router_sync(self, prompt: str):
        return {"agent": "definitely-not-valid"}

    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "nvidia ok"}


class _DirectSuccessRouterModel(_BaseRouterModel):
    def _call_openrouter_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "openrouter ok"}

    def _call_nvidia_router_sync(self, prompt: str):
        raise AssertionError("NVIDIA fallback should not be used.")


class _InternalAttributeErrorFallbackModel(_BaseRouterModel):
    def _call_openrouter_router_sync(self, prompt: str):
        raise AttributeError("provider bug inside call body")

    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "nvidia ok"}


class _MissingOpenRouterContractModel(_BaseRouterModel):
    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "nvidia ok"}


def test_router_records_provider_call_failure_in_request_scope_when_fallback_succeeds() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        try:
            router_runtime.set_model_label = _noop_set_model_label
            request_context = RouterRequestContext()

            routed = await route_request(
                _ProviderFailureFallbackModel(),
                "# User's Latest Request:\nhello",
                request_context=request_context,
            )

            assert routed["agent"] == "direct"
            assert routed["response_text"] == "nvidia ok"
            failures = request_context.provider_failures
            assert len(failures) == 1, failures
            assert failures[0].provider == "openrouter"
            assert failures[0].kind == "provider_call"
            assert failures[0].timeout_seconds == 1.01
            assert "openrouter unavailable" in failures[0].message
            assert isinstance(failures[0].error, RuntimeError)
        finally:
            router_runtime.set_model_label = original_set_model_label

    asyncio.run(_run())


def test_router_records_timeout_failures_explicitly() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label
        original_call_with_timeout = router_runtime.call_router_provider_with_wall_timeout

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        async def _timeout_openrouter(model, provider, call, prompt):
            if provider == "openrouter":
                raise asyncio.TimeoutError()
            return await original_call_with_timeout(model, provider, call, prompt)

        try:
            router_runtime.set_model_label = _noop_set_model_label
            router_runtime.call_router_provider_with_wall_timeout = _timeout_openrouter
            request_context = RouterRequestContext()

            routed = await route_request(
                _ProviderFailureFallbackModel(),
                "# User's Latest Request:\nhello",
                request_context=request_context,
            )

            assert routed["agent"] == "direct"
            assert routed["response_text"] == "nvidia ok"
            failures = request_context.provider_failures
            assert len(failures) == 1, failures
            assert failures[0].provider == "openrouter"
            assert failures[0].kind == "timeout"
            assert failures[0].message == "openrouter router timed out after 1.0s."
            assert isinstance(failures[0].error, asyncio.TimeoutError)
        finally:
            router_runtime.set_model_label = original_set_model_label
            router_runtime.call_router_provider_with_wall_timeout = original_call_with_timeout

    asyncio.run(_run())


def test_router_records_contract_validation_failures_as_configuration() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        try:
            router_runtime.set_model_label = _noop_set_model_label
            request_context = RouterRequestContext()

            routed = await route_request(
                _MissingOpenRouterContractModel(),
                "# User's Latest Request:\nhello",
                request_context=request_context,
            )

            assert routed["agent"] == "direct"
            assert routed["response_text"] == "nvidia ok"
            failures = request_context.provider_failures
            assert len(failures) == 1, failures
            assert failures[0].provider == "openrouter"
            assert failures[0].kind == "configuration"
            assert "missing required router runtime members" in failures[0].message
            assert "_call_openrouter_router_sync" in failures[0].message
        finally:
            router_runtime.set_model_label = original_set_model_label

    asyncio.run(_run())


def test_router_records_normalization_failures_explicitly() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        try:
            router_runtime.set_model_label = _noop_set_model_label
            request_context = RouterRequestContext()

            routed = await route_request(
                _NormalizationFailureFallbackModel(),
                "# User's Latest Request:\nhello",
                request_context=request_context,
            )

            assert routed["agent"] == "direct"
            assert routed["response_text"] == "nvidia ok"
            failures = request_context.provider_failures
            assert len(failures) == 1, failures
            assert failures[0].provider == "openrouter"
            assert failures[0].kind == "normalization"
            assert "invalid agent" in failures[0].message
            assert isinstance(failures[0].error, RuntimeError)
        finally:
            router_runtime.set_model_label = original_set_model_label

    asyncio.run(_run())


def test_router_does_not_misclassify_provider_attribute_errors_as_configuration() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        try:
            router_runtime.set_model_label = _noop_set_model_label
            request_context = RouterRequestContext()

            routed = await route_request(
                _InternalAttributeErrorFallbackModel(),
                "# User's Latest Request:\nhello",
                request_context=request_context,
            )

            assert routed["agent"] == "direct"
            assert routed["response_text"] == "nvidia ok"
            failures = request_context.provider_failures
            assert len(failures) == 1, failures
            assert failures[0].provider == "openrouter"
            assert failures[0].kind == "provider_call"
            assert "provider bug inside call body" in failures[0].message
        finally:
            router_runtime.set_model_label = original_set_model_label

    asyncio.run(_run())


def test_router_provider_failures_are_isolated_per_request_context() -> None:
    async def _run() -> None:
        original_set_model_label = router_runtime.set_model_label

        async def _noop_set_model_label(_label: str, *, context: str) -> bool:
            return True

        try:
            router_runtime.set_model_label = _noop_set_model_label
            first_context = RouterRequestContext()
            second_context = RouterRequestContext()

            first_route = await route_request(
                _ProviderFailureFallbackModel(),
                "# User's Latest Request:\nhello",
                request_context=first_context,
            )
            second_route = await route_request(
                _DirectSuccessRouterModel(),
                "# User's Latest Request:\nhello again",
                request_context=second_context,
            )

            assert first_route["response_text"] == "nvidia ok"
            assert second_route["response_text"] == "openrouter ok"
            assert len(first_context.provider_failures) == 1
            assert first_context.provider_failures[0].provider == "openrouter"
            assert second_context.provider_failures == ()
        finally:
            router_runtime.set_model_label = original_set_model_label

    asyncio.run(_run())


if __name__ == "__main__":
    test_router_records_provider_call_failure_in_request_scope_when_fallback_succeeds()
    test_router_records_timeout_failures_explicitly()
    test_router_records_contract_validation_failures_as_configuration()
    test_router_records_normalization_failures_explicitly()
    test_router_does_not_misclassify_provider_attribute_errors_as_configuration()
    test_router_provider_failures_are_isolated_per_request_context()
    print("[test_router_provider_failures] All checks passed.")
