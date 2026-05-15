"""
Shared OpenRouter fallback helpers for Gemini-backed agents.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - keeps lightweight test environments usable.
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DOTENV_PATH = _PROJECT_ROOT / ".env"


def _refresh_dotenv() -> None:
    """Refresh local .env values for long-running desktop sessions."""
    try:
        load_dotenv(dotenv_path=_DOTENV_PATH, override=False)
    except Exception as exc:
        print(f"[OpenRouterFallback] Failed to load {_DOTENV_PATH}: {exc}")


_refresh_dotenv()

DEFAULT_OPENROUTER_TEXT_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
DEFAULT_OPENROUTER_VISION_MODELS = (
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "openrouter/free",
)
DEFAULT_OPENROUTER_STRONG_VISION_MODELS = (
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "openrouter/free",
)
DEFAULT_NVIDIA_VISION_MODELS = (
    "mistralai/mistral-small-4-119b-2603",
    "microsoft/phi-4-multimodal-instruct",
    "google/gemma-4-31b-it",
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "qwen/qwen3.5-397b-a17b",
)
DEFAULT_NVIDIA_STRONG_VISION_MODELS = (
    "qwen/qwen3.5-397b-a17b",
    "mistralai/mistral-small-4-119b-2603",
    "meta/llama-4-maverick-17b-128e-instruct",
    "meta/llama-3.2-90b-vision-instruct",
    "google/gemma-4-31b-it",
    "microsoft/phi-4-multimodal-instruct",
)
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_CHAT_URL = f"{DEFAULT_OPENROUTER_BASE_URL}/chat/completions"
DEFAULT_NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


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
    _refresh_dotenv()
    return (os.getenv("OPENROUTER_API_KEY") or "").strip()


def get_nvidia_api_key() -> str:
    _refresh_dotenv()
    return (
        os.getenv("NVIDIA_API_KEY")
        or os.getenv("NVCF_API_KEY")
        or os.getenv("NGC_API_KEY")
        or ""
    ).strip()


def get_openrouter_chat_url() -> str:
    _refresh_dotenv()
    return (os.getenv("OPENROUTER_URL") or DEFAULT_OPENROUTER_CHAT_URL).strip()


def get_nvidia_chat_url() -> str:
    _refresh_dotenv()
    return (
        os.getenv("NVIDIA_URL")
        or os.getenv("NVIDIA_CHAT_URL")
        or DEFAULT_NVIDIA_CHAT_URL
    ).strip()


def get_openrouter_base_url() -> str:
    _refresh_dotenv()
    explicit = (os.getenv("OPENROUTER_BASE_URL") or os.getenv("OPENROUTER_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")

    chat_url = get_openrouter_chat_url().rstrip("/")
    suffix = "/chat/completions"
    if chat_url.endswith(suffix):
        return chat_url[: -len(suffix)]
    return DEFAULT_OPENROUTER_BASE_URL


def get_openrouter_site_url() -> str:
    _refresh_dotenv()
    return (os.getenv("OPENROUTER_SITE_URL") or "").strip()


def get_openrouter_site_name() -> str:
    _refresh_dotenv()
    return (os.getenv("OPENROUTER_SITE_NAME") or "JARVIS").strip()


def get_openrouter_timeout_seconds() -> int:
    _refresh_dotenv()
    raw = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45")
    return _coerce_timeout_seconds(raw)


def get_nvidia_timeout_seconds() -> int:
    _refresh_dotenv()
    raw = os.getenv("NVIDIA_TIMEOUT_SECONDS", os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45"))
    return _coerce_timeout_seconds(raw)


def _coerce_timeout_seconds(raw: object) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 45
    return max(10, min(180, value))


def get_openrouter_model(purpose: str = "text") -> str:
    models = get_openrouter_models(purpose)
    return models[0] if models else ""


def get_openrouter_models(purpose: str = "text") -> list[str]:
    _refresh_dotenv()
    purpose_key = (purpose or "text").strip().upper()

    env_order_by_purpose = _openrouter_vision_env_order()
    if purpose_key in env_order_by_purpose:
        models: list[str] = []
        env_names = [
            f"OPENROUTER_{purpose_key}_MODEL",
            *env_order_by_purpose.get(purpose_key, []),
        ]
        if purpose_key == "BROWSER":
            env_names.extend(["OPENROUTER_MODEL", "OPENROUTER_FALLBACK_MODEL"])

        for env_name in env_names:
            for model in _split_model_list(os.getenv(env_name) or ""):
                if model not in models:
                    models.append(model)
        defaults = (
            DEFAULT_OPENROUTER_STRONG_VISION_MODELS
            if purpose_key.endswith("_STRONG")
            else DEFAULT_OPENROUTER_VISION_MODELS
        )
        for model in defaults:
            if model not in models:
                models.append(model)
        return models

    purpose_specific = (os.getenv(f"OPENROUTER_{purpose_key}_MODEL") or "").strip()
    if purpose_specific:
        return _split_model_list(purpose_specific)

    configured = (
        os.getenv("OPENROUTER_MODEL")
        or os.getenv("OPENROUTER_FALLBACK_MODEL")
        or DEFAULT_OPENROUTER_TEXT_MODEL
    ).strip()
    return _split_model_list(configured)


def get_nvidia_models(purpose: str = "vision") -> list[str]:
    _refresh_dotenv()
    purpose_key = (purpose or "vision").strip().upper()
    env_order_by_purpose = _nvidia_vision_env_order()
    models: list[str] = []
    env_names = [
        f"NVIDIA_{purpose_key}_MODEL",
        *env_order_by_purpose.get(purpose_key, []),
    ]
    if purpose_key not in env_order_by_purpose:
        env_names.extend(["NVIDIA_MODEL", "NVIDIA_FALLBACK_MODEL"])

    for env_name in env_names:
        for model in _split_model_list(os.getenv(env_name) or ""):
            if model not in models:
                models.append(model)
    if purpose_key in env_order_by_purpose:
        defaults = (
            DEFAULT_NVIDIA_STRONG_VISION_MODELS
            if purpose_key.endswith("_STRONG")
            else DEFAULT_NVIDIA_VISION_MODELS
        )
        for model in defaults:
            if model not in models:
                models.append(model)
    return models


def _openrouter_vision_env_order() -> dict[str, list[str]]:
    return {
        "VISION": ["OPENROUTER_VISION_MODEL", "OPENROUTER_JARVIS_MODEL"],
        "JARVIS": ["OPENROUTER_JARVIS_MODEL", "OPENROUTER_VISION_MODEL"],
        "SCREEN": [
            "OPENROUTER_SCREEN_MODEL",
            "OPENROUTER_VISION_MODEL",
            "OPENROUTER_JARVIS_MODEL",
        ],
        "LOCATOR": [
            "OPENROUTER_LOCATOR_MODEL",
            "OPENROUTER_VISION_MODEL",
            "OPENROUTER_JARVIS_MODEL",
        ],
        "BROWSER": [
            "OPENROUTER_BROWSER_MODEL",
            "OPENROUTER_VISION_MODEL",
            "OPENROUTER_JARVIS_MODEL",
        ],
        "VISION_LOW": ["OPENROUTER_VISION_LOW_MODEL", "OPENROUTER_VISION_MODEL"],
        "VISION_STRONG": ["OPENROUTER_VISION_STRONG_MODEL", "OPENROUTER_VISION_MODEL"],
        "CUA_PLANNER_LOW": [
            "OPENROUTER_CUA_PLANNER_LOW_MODEL",
            "OPENROUTER_CUA_LOW_MODEL",
            "OPENROUTER_VISION_LOW_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
        "CUA_PLANNER_STRONG": [
            "OPENROUTER_CUA_PLANNER_STRONG_MODEL",
            "OPENROUTER_CUA_STRONG_MODEL",
            "OPENROUTER_VISION_STRONG_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
        "CUA_GROUNDER_LOW": [
            "OPENROUTER_CUA_GROUNDER_LOW_MODEL",
            "OPENROUTER_CUA_LOW_MODEL",
            "OPENROUTER_VISION_LOW_MODEL",
            "OPENROUTER_LOCATOR_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
        "CUA_GROUNDER_STRONG": [
            "OPENROUTER_CUA_GROUNDER_STRONG_MODEL",
            "OPENROUTER_CUA_STRONG_MODEL",
            "OPENROUTER_VISION_STRONG_MODEL",
            "OPENROUTER_LOCATOR_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
        "CUA_CRITIC_LOW": [
            "OPENROUTER_CUA_CRITIC_LOW_MODEL",
            "OPENROUTER_CUA_LOW_MODEL",
            "OPENROUTER_VISION_LOW_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
        "CUA_CRITIC_STRONG": [
            "OPENROUTER_CUA_CRITIC_STRONG_MODEL",
            "OPENROUTER_CUA_STRONG_MODEL",
            "OPENROUTER_VISION_STRONG_MODEL",
            "OPENROUTER_VISION_MODEL",
        ],
    }


def _nvidia_vision_env_order() -> dict[str, list[str]]:
    return {
        "VISION": ["NVIDIA_VISION_MODEL", "NVIDIA_JARVIS_MODEL"],
        "JARVIS": ["NVIDIA_JARVIS_MODEL", "NVIDIA_VISION_MODEL"],
        "SCREEN": ["NVIDIA_SCREEN_MODEL", "NVIDIA_VISION_MODEL", "NVIDIA_JARVIS_MODEL"],
        "LOCATOR": ["NVIDIA_LOCATOR_MODEL", "NVIDIA_VISION_MODEL", "NVIDIA_JARVIS_MODEL"],
        "BROWSER": ["NVIDIA_BROWSER_MODEL", "NVIDIA_VISION_MODEL", "NVIDIA_JARVIS_MODEL"],
        "VISION_LOW": ["NVIDIA_VISION_LOW_MODEL", "NVIDIA_VISION_MODEL"],
        "VISION_STRONG": ["NVIDIA_VISION_STRONG_MODEL", "NVIDIA_VISION_MODEL"],
        "CUA_PLANNER_LOW": [
            "NVIDIA_CUA_PLANNER_LOW_MODEL",
            "NVIDIA_CUA_LOW_MODEL",
            "NVIDIA_VISION_LOW_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
        "CUA_PLANNER_STRONG": [
            "NVIDIA_CUA_PLANNER_STRONG_MODEL",
            "NVIDIA_CUA_STRONG_MODEL",
            "NVIDIA_VISION_STRONG_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
        "CUA_GROUNDER_LOW": [
            "NVIDIA_CUA_GROUNDER_LOW_MODEL",
            "NVIDIA_CUA_LOW_MODEL",
            "NVIDIA_VISION_LOW_MODEL",
            "NVIDIA_LOCATOR_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
        "CUA_GROUNDER_STRONG": [
            "NVIDIA_CUA_GROUNDER_STRONG_MODEL",
            "NVIDIA_CUA_STRONG_MODEL",
            "NVIDIA_VISION_STRONG_MODEL",
            "NVIDIA_LOCATOR_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
        "CUA_CRITIC_LOW": [
            "NVIDIA_CUA_CRITIC_LOW_MODEL",
            "NVIDIA_CUA_LOW_MODEL",
            "NVIDIA_VISION_LOW_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
        "CUA_CRITIC_STRONG": [
            "NVIDIA_CUA_CRITIC_STRONG_MODEL",
            "NVIDIA_CUA_STRONG_MODEL",
            "NVIDIA_VISION_STRONG_MODEL",
            "NVIDIA_VISION_MODEL",
        ],
    }


def _split_model_list(raw: str) -> list[str]:
    models: list[str] = []
    for item in str(raw or "").split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in models:
            models.append(cleaned)
    return models


def openrouter_configured(purpose: str = "text") -> bool:
    return bool(get_openrouter_api_key() and get_openrouter_model(purpose) and get_openrouter_chat_url())


def nvidia_configured(purpose: str = "vision") -> bool:
    return bool(get_nvidia_api_key() and get_nvidia_models(purpose) and get_nvidia_chat_url())


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


def tool_result_to_vision_response(result: dict[str, Any]):
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


openrouter_tool_result_to_genai_response = tool_result_to_vision_response
