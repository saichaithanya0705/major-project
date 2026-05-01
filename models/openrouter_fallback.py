"""
Shared OpenRouter fallback helpers for Gemini-backed agents.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

DEFAULT_OPENROUTER_TEXT_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
DEFAULT_OPENROUTER_VISION_MODELS = (
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "openrouter/free",
)
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_CHAT_URL = f"{DEFAULT_OPENROUTER_BASE_URL}/chat/completions"


def is_gemini_quota_error(exc: Exception | str) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower() if not isinstance(exc, str) else exc.lower()
    markers = (
        "429",
        "resource_exhausted",
        "quota",
        "rate limit",
        "rate_limit",
        "too many requests",
        "exceeded your current quota",
        "user rate limit exceeded",
    )
    return any(marker in text for marker in markers)


def get_openrouter_api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY") or "").strip()


def get_openrouter_chat_url() -> str:
    return (os.getenv("OPENROUTER_URL") or DEFAULT_OPENROUTER_CHAT_URL).strip()


def get_openrouter_base_url() -> str:
    explicit = (os.getenv("OPENROUTER_BASE_URL") or os.getenv("OPENROUTER_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    chat_url = get_openrouter_chat_url().rstrip("/")
    suffix = "/chat/completions"
    if chat_url.endswith(suffix):
        return chat_url[: -len(suffix)]
    return DEFAULT_OPENROUTER_BASE_URL


def get_openrouter_site_url() -> str:
    return (os.getenv("OPENROUTER_SITE_URL") or "").strip()


def get_openrouter_site_name() -> str:
    return (os.getenv("OPENROUTER_SITE_NAME") or "JARVIS").strip()


def get_openrouter_timeout_seconds() -> int:
    raw = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 45
    return max(10, min(180, value))


def get_openrouter_model(purpose: str = "text") -> str:
    models = get_openrouter_models(purpose)
    return models[0] if models else ""


def get_openrouter_models(purpose: str = "text") -> list[str]:
    purpose_key = (purpose or "text").strip().upper()
    purpose_specific = (os.getenv(f"OPENROUTER_{purpose_key}_MODEL") or "").strip()
    if purpose_specific:
        return _split_model_list(purpose_specific)

    if purpose_key in {"VISION", "JARVIS", "SCREEN", "LOCATOR"}:
        vision_model = (os.getenv("OPENROUTER_VISION_MODEL") or "").strip()
        if vision_model:
            return _split_model_list(vision_model)
        return list(DEFAULT_OPENROUTER_VISION_MODELS)

    if purpose_key == "BROWSER":
        browser_model = (os.getenv("OPENROUTER_BROWSER_MODEL") or "").strip()
        if browser_model:
            return _split_model_list(browser_model)
        return list(DEFAULT_OPENROUTER_VISION_MODELS)

    configured = (
        os.getenv("OPENROUTER_MODEL")
        or os.getenv("OPENROUTER_FALLBACK_MODEL")
        or DEFAULT_OPENROUTER_TEXT_MODEL
    ).strip()
    return _split_model_list(configured)


def _split_model_list(raw: str) -> list[str]:
    models: list[str] = []
    for item in str(raw or "").split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in models:
            models.append(cleaned)
    return models


def openrouter_configured(purpose: str = "text") -> bool:
    return bool(get_openrouter_api_key() and get_openrouter_model(purpose) and get_openrouter_chat_url())


def image_to_data_url(image: Any) -> Optional[str]:
    if image is None:
        return None
    if isinstance(image, str) and image.startswith("data:image/"):
        return image

    try:
        buffer = BytesIO()
        if getattr(image, "mode", "") not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
        image.save(buffer, format="PNG")
    except Exception:
        return None

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def openrouter_tool_result_to_genai_response(result: dict[str, Any]):
    text = str(result.get("text") or "")
    parts = []
    if text:
        parts.append(SimpleNamespace(text=text, function_call=None))

    for tool_call in result.get("tool_calls") or []:
        if not isinstance(tool_call, dict):
            continue
        name = str(tool_call.get("name") or "").strip()
        if not name:
            continue
        args = tool_call.get("arguments")
        if not isinstance(args, dict):
            args = {}
        parts.append(
            SimpleNamespace(
                text=None,
                function_call=SimpleNamespace(name=name, args=args),
            )
        )

    return SimpleNamespace(
        text=text,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=parts),
            )
        ],
    )
