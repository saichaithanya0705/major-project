"""
Checks for runtime environment parsing used by GeminiModel.

Usage:
    python tests/test_model_runtime_config.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.runtime_config import build_model_runtime_config


_ENV_KEYS = [
    "JARVIS_THINKING_BUDGET",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_ROUTER_MODEL",
    "OPENROUTER_URL",
    "OPENROUTER_SITE_URL",
    "OPENROUTER_SITE_NAME",
    "OPENROUTER_TIMEOUT_SECONDS",
    "ROUTER_PROVIDER",
    "OLLAMA_ROUTER_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_ROUTER_TIMEOUT_SECONDS",
    "OLLAMA_ROUTER_NUM_CTX",
    "OLLAMA_ROUTER_NUM_PREDICT",
    "OPENROUTER_ROUTER_MAX_TOKENS",
    "OLLAMA_ROUTER_THINK",
    "GEMINI_BACKUP_MODEL",
]


def _looks_like_openrouter_model_name(model_name: str) -> bool:
    cleaned = (model_name or "").strip().lower()
    if not cleaned:
        return False
    if cleaned.startswith("openrouter:"):
        return True
    return "/" in cleaned or cleaned.endswith(":free")


def _extract_openrouter_model_name(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if cleaned.lower().startswith("openrouter:"):
        return cleaned.split(":", 1)[1].strip()
    return cleaned


def _clear_env():
    for key in _ENV_KEYS:
        os.environ.pop(key, None)


def _build(rapid_response_model: str):
    return build_model_runtime_config(
        rapid_response_model,
        default_openrouter_router_model="router-default",
        default_openrouter_fallback_model="fallback-default",
        looks_like_openrouter_model_name=_looks_like_openrouter_model_name,
        extract_openrouter_model_name=_extract_openrouter_model_name,
    )


def run_checks() -> None:
    original = {key: os.environ.get(key) for key in _ENV_KEYS}
    try:
        _clear_env()
        cfg = _build("openrouter:nvidia/custom-router:free")
        assert cfg.openrouter_model == "nvidia/custom-router:free"
        assert cfg.openrouter_router_model == "nvidia/custom-router:free"
        assert cfg.router_provider == "openrouter"

        _clear_env()
        os.environ["ROUTER_PROVIDER"] = "invalid-provider"
        cfg = _build("qwen3.5:4b-q4_K_M")
        assert cfg.router_provider == "ollama"

        _clear_env()
        os.environ["ROUTER_PROVIDER"] = "invalid-provider"
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        cfg = _build("qwen3.5:4b-q4_K_M")
        assert cfg.router_provider == "openrouter"

        _clear_env()
        os.environ["OLLAMA_ROUTER_MODEL"] = "gemini-3-flash-preview"
        cfg = _build("qwen3.5:4b-q4_K_M")
        assert cfg.ollama_router_model == "qwen3.5:4b-q4_K_M"

        _clear_env()
        os.environ["OLLAMA_ROUTER_THINK"] = "yes"
        cfg = _build("qwen3.5:4b-q4_K_M")
        assert cfg.ollama_router_think is True

        _clear_env()
        os.environ["OPENROUTER_TIMEOUT_SECONDS"] = "1"
        os.environ["OLLAMA_ROUTER_TIMEOUT_SECONDS"] = "9999"
        os.environ["JARVIS_THINKING_BUDGET"] = "5000"
        cfg = _build("qwen3.5:4b-q4_K_M")
        assert cfg.openrouter_timeout_seconds == 10
        assert cfg.ollama_router_timeout_seconds == 180
        assert cfg.jarvis_thinking_budget == 2048
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run_checks()
    print("[test_model_runtime_config] All checks passed.")
