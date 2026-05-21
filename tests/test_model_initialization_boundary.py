import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.model_initialization as init_module
import models.models as model_module
from models.runtime_config import ModelRuntimeConfig


class _FakeThinkingConfig:
    def __init__(self, *, thinking_budget: int):
        self.thinking_budget = thinking_budget


class _FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)


class _FakeTypes:
    ThinkingConfig = _FakeThinkingConfig
    GenerateContentConfig = _FakeGenerateContentConfig


def _runtime_config() -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        jarvis_thinking_budget=321,
        nvidia_api_key="nvidia-key",
        nvidia_router_model="nvidia-router",
        nvidia_url="https://nvidia.example",
        nvidia_timeout_seconds=31,
        openrouter_api_key="openrouter-key",
        openrouter_model="openrouter-model",
        openrouter_vision_model="openrouter-vision",
        openrouter_router_model="openrouter-router",
        openrouter_url="https://openrouter.example",
        openrouter_site_url="https://site.example",
        openrouter_site_name="Site",
        openrouter_timeout_seconds=41,
        router_provider="openrouter",
        ollama_router_model="ollama-router",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_keep_alive="15m",
        ollama_router_timeout_seconds=91,
        ollama_router_num_ctx=4096,
        ollama_router_num_predict=333,
        nvidia_router_max_tokens=444,
        openrouter_router_max_tokens=555,
        ollama_router_think=True,
        gemini_backup_model="gemini-backup",
    )


def test_initialize_gemini_model_runtime_applies_runtime_config_and_builds_configs() -> None:
    model = type("FakeModel", (), {})()
    captured: dict[str, str] = {}

    def _fake_build_default_model_runtime_config(rapid_response_model: str) -> ModelRuntimeConfig:
        captured["rapid_response_model"] = rapid_response_model
        return _runtime_config()

    init_module.initialize_gemini_model_runtime(
        model,
        rapid_response_model="rapid-model",
        types_module=_FakeTypes,
        build_default_model_runtime_config=_fake_build_default_model_runtime_config,
        jarvis_tools=[{"name": "annotate"}],
        tool_config={"mode": "AUTO"},
    )

    assert captured["rapid_response_model"] == "rapid-model"
    assert model.jarvis_thinking_budget == 321
    assert model.nvidia_api_key == "nvidia-key"
    assert model.openrouter_router_model == "openrouter-router"
    assert model.ollama_router_num_predict == 333
    assert model.router_wall_timeout_grace_seconds == 5.0
    assert model.screen_judge_model == "gemini-3-flash-preview"
    assert model.jarvis_config.kwargs["tools"] == [{"name": "annotate"}]
    assert model.jarvis_config.kwargs["tool_config"] == {"mode": "AUTO"}
    thinking_config = model.jarvis_config.kwargs["thinking_config"]
    assert thinking_config.thinking_budget == 321
    assert model.screen_judge_config.kwargs["response_mime_type"] == "application/json"
    assert model.direct_answer_config.kwargs["max_output_tokens"] == 1800


def test_gemini_model_init_uses_extracted_runtime_initializer() -> None:
    original_genai = model_module.genai
    original_types = model_module.types
    original_initializer = model_module.initialize_gemini_model_runtime
    original_api_key = os.environ.get("GEMINI_API_KEY")
    captured: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key

    class _FakeGenAI:
        Client = _FakeClient

    class _FakeTypesForInit:
        pass

    def _fake_initialize_gemini_model_runtime(
        model,
        *,
        rapid_response_model: str,
        types_module,
    ) -> None:
        captured["model"] = model
        captured["rapid_response_model"] = rapid_response_model
        captured["types_module"] = types_module

    os.environ["GEMINI_API_KEY"] = "test-gemini-key"
    model_module.genai = _FakeGenAI
    model_module.types = _FakeTypesForInit
    model_module.initialize_gemini_model_runtime = _fake_initialize_gemini_model_runtime
    try:
        model = model_module.GeminiModel(
            jarvis_model="jarvis-model",
            rapid_response_model="rapid-model",
        )
    finally:
        model_module.genai = original_genai
        model_module.types = original_types
        model_module.initialize_gemini_model_runtime = original_initializer
        if original_api_key is None:
            del os.environ["GEMINI_API_KEY"]
        else:
            os.environ["GEMINI_API_KEY"] = original_api_key

    assert captured["api_key"] == "test-gemini-key"
    assert captured["model"] is model
    assert captured["rapid_response_model"] == "rapid-model"
    assert captured["types_module"] is _FakeTypesForInit
    assert model.jarvis_model == "jarvis-model"
    assert model.rapid_response_model == "rapid-model"
