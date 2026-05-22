"""
Shared provider runtime helpers for CUA Vision model roles.

Planner and critic calls use the same provider order and screenshot payload
rules. Keeping that boundary here prevents config drift between role-specific
modules while leaving prompt construction and response parsing with each role.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.cua_vision.contracts import ScreenObservation
from models.openrouter_fallback import (
    get_nvidia_api_key,
    get_nvidia_chat_url,
    get_nvidia_models,
    get_nvidia_timeout_seconds,
    get_openrouter_api_key,
    get_openrouter_chat_url,
    get_openrouter_models,
    get_openrouter_site_name,
    get_openrouter_site_url,
    get_openrouter_timeout_seconds,
)
from models.text_normalization import clean_text


@dataclass(frozen=True, slots=True)
class CuaVisionProvider:
    label: str
    api_key: str
    url: str
    models: tuple[str, ...]
    timeout_seconds: int
    site_url: str = ""
    site_name: str = ""


def iter_cua_vision_providers(purpose: str) -> tuple[CuaVisionProvider, ...]:
    """Return configured CUA vision providers in production fallback order."""
    providers: list[CuaVisionProvider] = []

    nvidia_key = get_nvidia_api_key()
    nvidia_models = tuple(get_nvidia_models(purpose))
    if nvidia_key and nvidia_models:
        providers.append(
            CuaVisionProvider(
                label="NVIDIA",
                api_key=nvidia_key,
                url=get_nvidia_chat_url(),
                models=nvidia_models,
                timeout_seconds=get_nvidia_timeout_seconds(),
            )
        )

    openrouter_key = get_openrouter_api_key()
    openrouter_models = tuple(get_openrouter_models(purpose))
    if openrouter_key and openrouter_models:
        providers.append(
            CuaVisionProvider(
                label="OpenRouter",
                api_key=openrouter_key,
                url=get_openrouter_chat_url(),
                models=openrouter_models,
                timeout_seconds=get_openrouter_timeout_seconds(),
                site_url=get_openrouter_site_url(),
                site_name=get_openrouter_site_name(),
            )
        )

    return tuple(providers)


def observation_image_data_url(observation: ScreenObservation | None) -> str | None:
    if observation is None:
        return None
    return screenshot_base64_to_data_url(observation.screenshot_png_base64)


def screenshot_base64_to_data_url(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.startswith("data:image/"):
        return raw
    return f"data:image/png;base64,{raw}"


def format_provider_failure(
    *,
    provider: CuaVisionProvider,
    model_name: str,
    exc: Exception,
    max_len: int,
) -> str:
    detail = clean_text(str(exc), type(exc).__name__, max_len)
    return f"{provider.label} {model_name}: {detail}"


def provider_failure_summary(
    failures: list[str],
    *,
    max_items: int,
    empty_message: str,
) -> str:
    return "; ".join(failures[-max_items:]) if failures else empty_message


def trim_text(text: object, max_len: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_len:
        return value
    return f"{value[: max_len - 3]}..."
