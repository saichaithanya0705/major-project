"""OpenRouter adapter and fallback retry runtime for model objects."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from models.openrouter_fallback import (
    get_openrouter_models,
    image_to_data_url,
    openrouter_tool_result_to_genai_response,
)
from models.model_status import set_model_label
from models.router_provider_config import (
    OpenRouterProviderConfig,
    openrouter_config_enabled,
    openrouter_provider_config_from_model,
)
from models.text_normalization import clean_text as _clean_text
from models.router_backends import (
    call_openrouter_text_sync as call_openrouter_text_backend_sync,
    call_openrouter_tool_sync as call_openrouter_tool_backend_sync,
)


@dataclass(frozen=True)
class OpenRouterFallbackFailure:
    mode: str
    label: str
    model_name: str
    message: str
    error: BaseException


_LAST_OPENROUTER_FALLBACK_FAILURES: tuple[OpenRouterFallbackFailure, ...] = ()


def get_last_openrouter_fallback_failures() -> tuple[OpenRouterFallbackFailure, ...]:
    return _LAST_OPENROUTER_FALLBACK_FAILURES


def clear_last_openrouter_fallback_failures() -> None:
    global _LAST_OPENROUTER_FALLBACK_FAILURES
    _LAST_OPENROUTER_FALLBACK_FAILURES = ()


def _record_openrouter_fallback_failure(
    *,
    mode: str,
    label: str,
    model_name: str,
    error: BaseException,
) -> None:
    global _LAST_OPENROUTER_FALLBACK_FAILURES
    message = f"{type(error).__name__}: {error}"
    _LAST_OPENROUTER_FALLBACK_FAILURES = (
        *_LAST_OPENROUTER_FALLBACK_FAILURES,
        OpenRouterFallbackFailure(
            mode=mode,
            label=label,
            model_name=model_name,
            message=message,
            error=error,
        ),
    )


def _openrouter_model_enabled_from_config(
    config: OpenRouterProviderConfig,
    model_name: str,
) -> bool:
    return openrouter_config_enabled(config, model_name)


def openrouter_model_enabled(model: Any, model_name: str) -> bool:
    return _openrouter_model_enabled_from_config(
        openrouter_provider_config_from_model(model),
        model_name,
    )


def openrouter_enabled(model: Any) -> bool:
    return openrouter_model_enabled(model, getattr(model, "openrouter_model", ""))


def call_openrouter_text_sync(
    model: Any,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    *,
    model_name: Optional[str] = None,
    response_format: Optional[dict[str, Any]] = None,
    image_data_url: Optional[str] = None,
) -> str:
    config = openrouter_provider_config_from_model(model)
    selected_model = (model_name or config.default_text_model or "").strip()
    if not _openrouter_model_enabled_from_config(config, selected_model):
        raise RuntimeError("OpenRouter fallback is not configured.")
    return call_openrouter_text_backend_sync(
        openrouter_api_key=config.api_key,
        openrouter_url=config.url,
        openrouter_site_url=config.site_url,
        openrouter_site_name=config.site_name,
        openrouter_timeout_seconds=config.timeout_seconds,
        model_name=selected_model,
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


def call_openrouter_tool_sync(
    model: Any,
    system_prompt: str,
    user_prompt: str,
    function_declarations: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    *,
    model_name: Optional[str] = None,
    image_data_url: Optional[str] = None,
) -> dict[str, Any]:
    config = openrouter_provider_config_from_model(model)
    selected_model = (
        model_name
        or config.default_vision_model
        or config.default_text_model
        or ""
    ).strip()
    if not _openrouter_model_enabled_from_config(config, selected_model):
        raise RuntimeError("OpenRouter tool fallback is not configured.")
    return call_openrouter_tool_backend_sync(
        openrouter_api_key=config.api_key,
        openrouter_url=config.url,
        openrouter_site_url=config.site_url,
        openrouter_site_name=config.site_name,
        openrouter_timeout_seconds=config.timeout_seconds,
        model_name=selected_model,
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


async def try_openrouter_text_fallback(
    model: Any,
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
    clear_last_openrouter_fallback_failures()
    if not openrouter_enabled(model):
        print(f"[{label}] Gemini quota hit but OPENROUTER_API_KEY is not configured.")
        return None

    config = openrouter_provider_config_from_model(model)
    image_data_url = image_to_data_url(image)
    models_to_try = get_openrouter_models(purpose)
    if purpose == "text" and config.default_text_model not in models_to_try:
        models_to_try.insert(0, config.default_text_model)
    elif purpose != "text" and config.default_vision_model not in models_to_try:
        models_to_try.insert(0, config.default_vision_model)

    for selected_model in [candidate for candidate in models_to_try if candidate]:
        await set_model_label(
            f"{selected_model} (OpenRouter)",
            context=f"openrouter_text:{label}",
        )

        try:
            text = await asyncio.to_thread(
                call_openrouter_text_sync,
                model,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                model_name=selected_model,
                response_format=response_format,
                image_data_url=image_data_url,
            )
            print(f"[{label}] OpenRouter fallback succeeded with model {selected_model}")
            return text
        except RuntimeError as fallback_exc:
            _record_openrouter_fallback_failure(
                mode="text",
                label=label,
                model_name=selected_model,
                error=fallback_exc,
            )
            print(f"[{label}] OpenRouter fallback failed with {selected_model}: {fallback_exc}")
    return None


async def try_openrouter_tool_fallback(
    model: Any,
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
    clear_last_openrouter_fallback_failures()
    if not openrouter_enabled(model):
        print(f"[{label}] Gemini quota hit but OPENROUTER_API_KEY is not configured.")
        return None

    config = openrouter_provider_config_from_model(model)
    image_data_url = image_to_data_url(image)
    models_to_try = get_openrouter_models(purpose)
    if config.default_vision_model and config.default_vision_model not in models_to_try:
        models_to_try.insert(0, config.default_vision_model)

    for selected_model in [candidate for candidate in models_to_try if candidate]:
        await set_model_label(
            f"{selected_model} (OpenRouter)",
            context=f"openrouter_tool:{label}",
        )

        try:
            result = await asyncio.to_thread(
                call_openrouter_tool_sync,
                model,
                system_prompt,
                user_prompt,
                function_declarations,
                temperature,
                max_tokens,
                model_name=selected_model,
                image_data_url=image_data_url,
            )
            print(f"[{label}] OpenRouter tool fallback succeeded with model {selected_model}")
            return openrouter_tool_result_to_genai_response(result)
        except RuntimeError as fallback_exc:
            _record_openrouter_fallback_failure(
                mode="tool",
                label=label,
                model_name=selected_model,
                error=fallback_exc,
            )
            print(f"[{label}] OpenRouter tool fallback failed with {selected_model}: {fallback_exc}")
    return None
