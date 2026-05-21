"""Checks extracted provider config boundary for router and OpenRouter wrappers."""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.openrouter_runtime as openrouter_runtime
import models.router_provider_calls as router_provider_calls
import models.router_provider_config as router_provider_config


class _ProviderConfigModel:
    openrouter_api_key = "openrouter-key"
    openrouter_url = "https://openrouter.example.invalid"
    openrouter_site_url = "https://example.com"
    openrouter_site_name = "tests"
    openrouter_timeout_seconds = 12
    openrouter_model = "text-model"
    openrouter_vision_model = "vision-model"
    openrouter_router_model = "router-model"
    openrouter_router_max_tokens = 345
    nvidia_api_key = "nvidia-key"
    nvidia_url = "https://nvidia.example.invalid"
    nvidia_timeout_seconds = 7
    nvidia_router_model = "nvidia-router"
    nvidia_router_max_tokens = 222
    ollama_base_url = "http://127.0.0.1:11434"
    ollama_router_model = "ollama-router"
    ollama_router_num_predict = 555
    ollama_router_num_ctx = 4444
    ollama_router_think = True
    ollama_keep_alive = "15m"
    ollama_router_timeout_seconds = 77


def test_provider_config_extractors_capture_shared_fields() -> None:
    model = _ProviderConfigModel()

    openrouter_config = router_provider_config.openrouter_provider_config_from_model(model)
    nvidia_config = router_provider_config.nvidia_router_config_from_model(model)
    ollama_config = router_provider_config.ollama_router_config_from_model(model)

    assert openrouter_config.default_text_model == "text-model"
    assert openrouter_config.default_vision_model == "vision-model"
    assert openrouter_config.router_model == "router-model"
    assert openrouter_config.router_max_tokens == 345
    assert nvidia_config.router_model == "nvidia-router"
    assert nvidia_config.router_max_tokens == 222
    assert ollama_config.router_model == "ollama-router"
    assert ollama_config.router_num_predict == 555
    assert ollama_config.router_num_ctx == 4444
    assert ollama_config.router_think is True
    assert ollama_config.keep_alive == "15m"


def test_openrouter_runtime_uses_shared_provider_config_boundary() -> None:
    original_config_from_model = openrouter_runtime.openrouter_provider_config_from_model
    original_backend = openrouter_runtime.call_openrouter_text_backend_sync

    captured: dict[str, object] = {}
    config = router_provider_config.OpenRouterProviderConfig(
        api_key="cfg-key",
        url="https://cfg.example.invalid",
        site_url="https://cfg.example.com",
        site_name="cfg-tests",
        timeout_seconds=21,
        default_text_model="cfg-text",
        default_vision_model="cfg-vision",
        router_model="cfg-router",
        router_max_tokens=321,
    )

    def _fake_backend(**kwargs):
        captured.update(kwargs)
        return "ok"

    openrouter_runtime.openrouter_provider_config_from_model = lambda _model: config
    openrouter_runtime.call_openrouter_text_backend_sync = _fake_backend
    try:
        text = openrouter_runtime.call_openrouter_text_sync(
            object(),
            "system",
            "user",
            0.2,
            100,
        )
    finally:
        openrouter_runtime.openrouter_provider_config_from_model = original_config_from_model
        openrouter_runtime.call_openrouter_text_backend_sync = original_backend

    assert text == "ok"
    assert captured["openrouter_api_key"] == "cfg-key"
    assert captured["openrouter_url"] == "https://cfg.example.invalid"
    assert captured["openrouter_site_url"] == "https://cfg.example.com"
    assert captured["openrouter_site_name"] == "cfg-tests"
    assert captured["openrouter_timeout_seconds"] == 21
    assert captured["model_name"] == "cfg-text"


def test_router_provider_calls_use_shared_router_configs() -> None:
    original_config_from_model = router_provider_calls.openrouter_provider_config_from_model
    original_backend = router_provider_calls._call_openrouter_router_backend_sync

    captured: dict[str, object] = {}
    config = router_provider_config.OpenRouterProviderConfig(
        api_key="cfg-key",
        url="https://cfg.example.invalid",
        site_url="https://cfg.example.com",
        site_name="cfg-tests",
        timeout_seconds=21,
        default_text_model="cfg-text",
        default_vision_model="cfg-vision",
        router_model="cfg-router",
        router_max_tokens=321,
    )

    def _fake_backend(**kwargs):
        captured.update(kwargs)
        return {"agent": "direct", "response_text": "ok"}

    router_provider_calls.openrouter_provider_config_from_model = lambda _model: config
    router_provider_calls._call_openrouter_router_backend_sync = _fake_backend
    try:
        routed = router_provider_calls.call_openrouter_router_sync(object(), "open example")
    finally:
        router_provider_calls.openrouter_provider_config_from_model = original_config_from_model
        router_provider_calls._call_openrouter_router_backend_sync = original_backend

    assert routed == {"agent": "direct", "response_text": "ok"}
    assert captured["openrouter_api_key"] == "cfg-key"
    assert captured["openrouter_url"] == "https://cfg.example.invalid"
    assert captured["openrouter_site_url"] == "https://cfg.example.com"
    assert captured["openrouter_site_name"] == "cfg-tests"
    assert captured["openrouter_timeout_seconds"] == 21
    assert captured["openrouter_router_model"] == "cfg-router"
    assert captured["openrouter_router_max_tokens"] == 321
