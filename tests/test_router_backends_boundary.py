"""
Checks for extracted router backend client helpers.

Usage:
    python tests/test_router_backends_boundary.py
"""

import os
import sys
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.router_backends as backend_module
import models.openrouter_fallback as openrouter_fallback_module


def _clean_text(value: object, fallback: str, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return text[:max_len]


def run_checks() -> None:
    captured_openrouter: dict[str, Any] = {}
    captured_router: dict[str, Any] = {}

    original_post = backend_module.requests.post

    class _OpenRouterResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"text": "first part"},
                                {"text": "second part"},
                            ]
                        }
                    }
                ]
            }

    class _OpenRouterRouterResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"agent":"browser","task":"open https://example.com"}',
                        }
                    }
                ]
            }

    def _fake_post(url, headers=None, json=None, timeout=None):
        if json and json.get("response_format") == {"type": "json_object"}:
            captured_router.update(
                {
                    "url": url,
                    "headers": dict(headers or {}),
                    "json": dict(json or {}),
                    "timeout": timeout,
                }
            )
            return _OpenRouterRouterResponse()

        captured_openrouter.update(
            {
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json or {}),
                "timeout": timeout,
            }
        )
        return _OpenRouterResponse()

    backend_module.requests.post = _fake_post
    try:
        text = backend_module.call_openrouter_text_sync(
            openrouter_api_key="api-key",
            openrouter_url="https://openrouter.ai/api/v1/chat/completions",
            openrouter_site_url="https://example.com",
            openrouter_site_name="Jarvis",
            openrouter_timeout_seconds=45,
            model_name="model-a",
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            max_tokens=400,
            clean_text=_clean_text,
        )
        route = backend_module.call_openrouter_router_sync(
            openrouter_api_key="api-key",
            openrouter_url="https://openrouter.ai/api/v1/chat/completions",
            openrouter_site_url="https://example.com",
            openrouter_site_name="Jarvis",
            openrouter_timeout_seconds=45,
            openrouter_router_model="router-model",
            openrouter_router_max_tokens=300,
            router_system_prompt="router-system",
            prompt="open example",
            clean_text=_clean_text,
            parse_json_object_from_text=lambda value: {"agent": "browser", "task": "open https://example.com"},
        )
    finally:
        backend_module.requests.post = original_post

    assert text == "first part\nsecond part", text
    assert captured_openrouter["json"]["model"] == "model-a", captured_openrouter
    assert captured_openrouter["headers"]["HTTP-Referer"] == "https://example.com", captured_openrouter
    assert captured_openrouter["headers"]["X-Title"] == "Jarvis", captured_openrouter
    assert route == {"agent": "browser", "task": "open https://example.com"}, route
    assert captured_router["json"]["response_format"] == {"type": "json_object"}, captured_router
    assert captured_router["json"]["temperature"] == 0.0, captured_router

    original_post = backend_module.requests.post

    class _OpenRouterToolTextResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"name":"go_to_element",'
                                '"arguments":{"target_description":"WhatsApp search field"}}'
                            ),
                        }
                    }
                ]
            }

    def _fake_tool_post(url, headers=None, json=None, timeout=None):
        del url, headers, json, timeout
        return _OpenRouterToolTextResponse()

    backend_module.requests.post = _fake_tool_post
    try:
        tool_result = backend_module.call_openrouter_tool_sync(
            openrouter_api_key="api-key",
            openrouter_url="https://openrouter.ai/api/v1/chat/completions",
            openrouter_site_url="",
            openrouter_site_name="Jarvis",
            openrouter_timeout_seconds=45,
            model_name="vision-model",
            system_prompt="system",
            user_prompt="click the search field",
            function_declarations=[
                {
                    "name": "go_to_element",
                    "description": "Move to a visible UI target.",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            temperature=0.2,
            max_tokens=400,
            clean_text=_clean_text,
        )
    finally:
        backend_module.requests.post = original_post

    assert tool_result == {
        "text": '{"name":"go_to_element","arguments":{"target_description":"WhatsApp search field"}}',
        "tool_calls": [
            {
                "name": "go_to_element",
                "arguments": {"target_description": "WhatsApp search field"},
            }
        ],
    }, tool_result

    env_keys = [
        "OPENROUTER_MODEL",
        "OPENROUTER_FALLBACK_MODEL",
        "OPENROUTER_VISION_MODEL",
        "OPENROUTER_JARVIS_MODEL",
        "OPENROUTER_BROWSER_MODEL",
        "OPENROUTER_SCREEN_MODEL",
        "OPENROUTER_LOCATOR_MODEL",
    ]
    saved_env = {key: os.environ.get(key) for key in env_keys}
    try:
        for key in env_keys:
            os.environ.pop(key, None)
        os.environ["OPENROUTER_MODEL"] = "openai/gpt-4.1-mini"
        for key in env_keys:
            if key != "OPENROUTER_MODEL":
                os.environ[key] = ""
        vision_models = openrouter_fallback_module.get_openrouter_models("vision")
        browser_models = openrouter_fallback_module.get_openrouter_models("browser")
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert "openai/gpt-4.1-mini" not in vision_models, vision_models
    assert browser_models[0] == "openai/gpt-4.1-mini", browser_models
    assert "google/gemma-4-31b-it:free" in vision_models, vision_models

    nvidia_env_keys = [
        "NVIDIA_MODEL",
        "NVIDIA_FALLBACK_MODEL",
        "NVIDIA_VISION_MODEL",
        "NVIDIA_JARVIS_MODEL",
        "NVIDIA_SCREEN_MODEL",
        "NVIDIA_LOCATOR_MODEL",
        "NVIDIA_BROWSER_MODEL",
    ]
    saved_env = {key: os.environ.get(key) for key in nvidia_env_keys}
    try:
        for key in nvidia_env_keys:
            os.environ.pop(key, None)
        os.environ["NVIDIA_VISION_MODEL"] = "meta/llama-4-maverick-17b-128e-instruct"
        nvidia_models = openrouter_fallback_module.get_nvidia_models("vision")
        os.environ["NVIDIA_VISION_MODEL"] = ""
        default_nvidia_models = openrouter_fallback_module.get_nvidia_models("vision")
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert nvidia_models[0] == "meta/llama-4-maverick-17b-128e-instruct", nvidia_models
    assert "google/gemma-4-31b-it" in nvidia_models, nvidia_models
    assert "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning" not in nvidia_models, nvidia_models
    assert default_nvidia_models[0] == "mistralai/mistral-small-4-119b-2603", default_nvidia_models

    captured_ollama_get: dict[str, Any] = {}
    original_get = backend_module.requests.get

    class _OllamaTagsResponse:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "llama3.2:3b"},
                    {"model": "qwen2.5:7b"},
                ]
            }

    def _fake_get(url, timeout=None):
        captured_ollama_get.update({"url": url, "timeout": timeout})
        return _OllamaTagsResponse()

    backend_module.requests.get = _fake_get
    try:
        warning = backend_module.validate_ollama_router_model_sync(
            ollama_base_url="http://127.0.0.1:11434",
            ollama_router_model="qwen3.5:4b-q4_K_M",
            timeout_seconds=2,
            clean_text=_clean_text,
        )
    finally:
        backend_module.requests.get = original_get

    assert "not found" in str(warning).lower(), warning
    assert "qwen3.5:4b-q4_K_M" in str(warning), warning
    assert captured_ollama_get["url"] == "http://127.0.0.1:11434/api/tags", captured_ollama_get


if __name__ == "__main__":
    run_checks()
    print("[test_router_backends_boundary] All checks passed.")
