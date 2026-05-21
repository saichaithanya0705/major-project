"""
Checks for extracted router backend client helpers.

Usage:
    python tests/test_router_backends_boundary.py
"""

import asyncio
import os
import sys
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.openrouter_fallback as openrouter_fallback_module
import models.openrouter_runtime as openrouter_runtime
import models.router_backends as backend_module


def _clean_text(value: object, fallback: str, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    return text[:max_len]


class _FakeOpenRouterFallbackModel:
    openrouter_api_key = "key"
    openrouter_url = "https://openrouter.example.invalid"
    openrouter_site_url = ""
    openrouter_site_name = "tests"
    openrouter_timeout_seconds = 1
    openrouter_model = "fallback-a"
    openrouter_vision_model = "vision-a"


def test_legacy_router_text_tool_call_is_supported() -> None:
    legacy_web_qa = backend_module._parse_router_text_tool_call(
        'invoke_web_qa(task="What is the latest news about SpaceX?")'
    )
    assert legacy_web_qa == {
        "agent": "web_qa",
        "task": "What is the latest news about SpaceX?",
    }, legacy_web_qa


def test_openrouter_text_and_router_payloads_are_forwarded() -> None:
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
            parse_json_object_from_text=lambda value: {
                "agent": "browser",
                "task": "open https://example.com",
            },
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


def test_openrouter_router_preserves_plan_payload_for_runtime_normalization() -> None:
    original_post = backend_module.requests.post

    class _OpenRouterPlanResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"tasks":['
                                '{"id":"research","agent":"web_qa","task":"Find release notes"},'
                                '{"id":"patch","agent":"cua_cli","task":"Update changelog","depends_on":["research"]}'
                                '],"max_parallel":2}'
                            ),
                        }
                    }
                ]
            }

    def _fake_post(url, headers=None, json=None, timeout=None):
        del url, headers, json, timeout
        return _OpenRouterPlanResponse()

    backend_module.requests.post = _fake_post
    try:
        payload = backend_module.call_openrouter_router_sync(
            openrouter_api_key="api-key",
            openrouter_url="https://openrouter.ai/api/v1/chat/completions",
            openrouter_site_url="https://example.com",
            openrouter_site_name="Jarvis",
            openrouter_timeout_seconds=45,
            openrouter_router_model="router-model",
            openrouter_router_max_tokens=300,
            router_system_prompt="router-system",
            prompt="research then patch",
            clean_text=_clean_text,
            parse_json_object_from_text=lambda _value: {
                "tasks": [
                    {"id": "research", "agent": "web_qa", "task": "Find release notes"},
                    {
                        "id": "patch",
                        "agent": "cua_cli",
                        "task": "Update changelog",
                        "depends_on": ["research"],
                    },
                ],
                "max_parallel": 2,
            },
        )
    finally:
        backend_module.requests.post = original_post

    assert payload == {
        "tasks": [
            {"id": "research", "agent": "web_qa", "task": "Find release notes"},
            {
                "id": "patch",
                "agent": "cua_cli",
                "task": "Update changelog",
                "depends_on": ["research"],
            },
        ],
        "max_parallel": 2,
    }, payload


def test_openrouter_tool_payload_parses_json_string_tool_call() -> None:
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


def test_openrouter_tool_payload_rejects_non_object_arguments() -> None:
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
                                '"arguments":["WhatsApp search field"]}'
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
        "text": '{"name":"go_to_element","arguments":["WhatsApp search field"]}',
        "tool_calls": [],
    }, tool_result


def test_openrouter_text_transport_failures_raise_backend_transport_error() -> None:
    original_post = backend_module.requests.post

    def _failing_post(url, headers=None, json=None, timeout=None):
        del url, headers, json, timeout
        raise backend_module.requests.ConnectionError("network down")

    backend_module.requests.post = _failing_post
    try:
        try:
            backend_module.call_openrouter_text_sync(
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
            raise AssertionError("Expected transport failure to be wrapped.")
        except backend_module.RouterBackendTransportError as exc:
            assert "ConnectionError" in str(exc), exc
            assert "network down" in str(exc), exc
    finally:
        backend_module.requests.post = original_post


def test_openrouter_text_fallback_retries_expected_backend_failures() -> None:
    async def _run() -> None:
        original_get_models = openrouter_runtime.get_openrouter_models
        original_set_label = openrouter_runtime.set_model_label
        original_call_text = openrouter_runtime.call_openrouter_text_sync
        attempted_models: list[str] = []

        async def _noop_set_label(*_args, **_kwargs) -> bool:
            return True

        def _fail_text(*_args, **kwargs) -> str:
            model_name = str(kwargs.get("model_name") or "")
            attempted_models.append(model_name)
            raise backend_module.RouterBackendResponseError(f"{model_name} failed")

        try:
            openrouter_runtime.get_openrouter_models = lambda _purpose: ["fallback-a", "fallback-b"]
            openrouter_runtime.set_model_label = _noop_set_label
            openrouter_runtime.call_openrouter_text_sync = _fail_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

            result = await openrouter_runtime.try_openrouter_text_fallback(
                _FakeOpenRouterFallbackModel(),
                label="DirectQA",
                system_prompt="system",
                user_prompt="user",
                purpose="text",
            )

            assert result is None
            failures = openrouter_runtime.get_last_openrouter_fallback_failures()
            assert attempted_models == ["fallback-a", "fallback-b"], attempted_models
            assert [failure.model_name for failure in failures] == ["fallback-a", "fallback-b"]
            assert [failure.mode for failure in failures] == ["text", "text"]
            assert "fallback-a failed" in failures[0].message
        finally:
            openrouter_runtime.get_openrouter_models = original_get_models
            openrouter_runtime.set_model_label = original_set_label
            openrouter_runtime.call_openrouter_text_sync = original_call_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

    asyncio.run(_run())


def test_openrouter_text_fallback_propagates_programmer_errors_without_retrying() -> None:
    async def _run() -> None:
        original_get_models = openrouter_runtime.get_openrouter_models
        original_set_label = openrouter_runtime.set_model_label
        original_call_text = openrouter_runtime.call_openrouter_text_sync
        attempted_models: list[str] = []

        async def _noop_set_label(*_args, **_kwargs) -> bool:
            return True

        def _buggy_text(*_args, **kwargs) -> str:
            attempted_models.append(str(kwargs.get("model_name") or ""))
            raise AttributeError("bug inside fallback")

        try:
            openrouter_runtime.get_openrouter_models = lambda _purpose: ["fallback-a", "fallback-b"]
            openrouter_runtime.set_model_label = _noop_set_label
            openrouter_runtime.call_openrouter_text_sync = _buggy_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

            try:
                await openrouter_runtime.try_openrouter_text_fallback(
                    _FakeOpenRouterFallbackModel(),
                    label="DirectQA",
                    system_prompt="system",
                    user_prompt="user",
                    purpose="text",
                )
                raise AssertionError("Expected programmer error to propagate.")
            except AttributeError as exc:
                assert str(exc) == "bug inside fallback", exc

            assert attempted_models == ["fallback-a"], attempted_models
            assert openrouter_runtime.get_last_openrouter_fallback_failures() == ()
        finally:
            openrouter_runtime.get_openrouter_models = original_get_models
            openrouter_runtime.set_model_label = original_set_label
            openrouter_runtime.call_openrouter_text_sync = original_call_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

    asyncio.run(_run())


def test_openrouter_fallback_model_lists_respect_scope() -> None:
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


def test_nvidia_fallback_model_lists_respect_scope() -> None:
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


def test_cua_planner_model_lists_read_override_env() -> None:
    cua_env_keys = [
        "OPENROUTER_CUA_PLANNER_LOW_MODEL",
        "OPENROUTER_CUA_PLANNER_STRONG_MODEL",
        "OPENROUTER_CUA_LOW_MODEL",
        "OPENROUTER_CUA_STRONG_MODEL",
        "OPENROUTER_VISION_LOW_MODEL",
        "OPENROUTER_VISION_STRONG_MODEL",
        "OPENROUTER_VISION_MODEL",
        "NVIDIA_CUA_PLANNER_LOW_MODEL",
        "NVIDIA_CUA_PLANNER_STRONG_MODEL",
        "NVIDIA_CUA_LOW_MODEL",
        "NVIDIA_CUA_STRONG_MODEL",
        "NVIDIA_VISION_LOW_MODEL",
        "NVIDIA_VISION_STRONG_MODEL",
        "NVIDIA_VISION_MODEL",
    ]
    saved_env = {key: os.environ.get(key) for key in cua_env_keys}
    try:
        for key in cua_env_keys:
            os.environ[key] = ""
        os.environ["OPENROUTER_CUA_PLANNER_LOW_MODEL"] = "openrouter-low-cua"
        os.environ["OPENROUTER_CUA_PLANNER_STRONG_MODEL"] = "openrouter-strong-cua"
        os.environ["NVIDIA_CUA_PLANNER_LOW_MODEL"] = "nvidia-low-cua"
        os.environ["NVIDIA_CUA_PLANNER_STRONG_MODEL"] = "nvidia-strong-cua"

        openrouter_low = openrouter_fallback_module.get_openrouter_models("cua_planner_low")
        openrouter_strong = openrouter_fallback_module.get_openrouter_models("cua_planner_strong")
        nvidia_low = openrouter_fallback_module.get_nvidia_models("cua_planner_low")
        nvidia_strong = openrouter_fallback_module.get_nvidia_models("cua_planner_strong")
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert openrouter_low[0] == "openrouter-low-cua", openrouter_low
    assert openrouter_strong[0] == "openrouter-strong-cua", openrouter_strong
    assert nvidia_low[0] == "nvidia-low-cua", nvidia_low
    assert nvidia_strong[0] == "nvidia-strong-cua", nvidia_strong
    assert openrouter_strong[1] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", openrouter_strong


def test_ollama_router_model_validation_lists_installed_models() -> None:
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


def test_ollama_router_model_validation_propagates_unexpected_request_errors() -> None:
    original_get = backend_module.requests.get

    def _buggy_get(url, timeout=None):
        del url, timeout
        raise ValueError("unexpected bug")

    backend_module.requests.get = _buggy_get
    try:
        try:
            backend_module.validate_ollama_router_model_sync(
                ollama_base_url="http://127.0.0.1:11434",
                ollama_router_model="qwen3.5:4b-q4_K_M",
                timeout_seconds=2,
                clean_text=_clean_text,
            )
            raise AssertionError("Expected unexpected request bug to propagate.")
        except ValueError as exc:
            assert str(exc) == "unexpected bug", exc
    finally:
        backend_module.requests.get = original_get


def run_checks() -> None:
    test_legacy_router_text_tool_call_is_supported()
    test_openrouter_text_and_router_payloads_are_forwarded()
    test_openrouter_tool_payload_parses_json_string_tool_call()
    test_openrouter_tool_payload_rejects_non_object_arguments()
    test_openrouter_text_transport_failures_raise_backend_transport_error()
    test_openrouter_text_fallback_retries_expected_backend_failures()
    test_openrouter_text_fallback_propagates_programmer_errors_without_retrying()
    test_openrouter_fallback_model_lists_respect_scope()
    test_nvidia_fallback_model_lists_respect_scope()
    test_cua_planner_model_lists_read_override_env()
    test_ollama_router_model_validation_lists_installed_models()
    test_ollama_router_model_validation_propagates_unexpected_request_errors()


if __name__ == "__main__":
    run_checks()
    print("[test_router_backends_boundary] All checks passed.")
