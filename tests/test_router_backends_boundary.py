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


if __name__ == "__main__":
    run_checks()
    print("[test_router_backends_boundary] All checks passed.")
