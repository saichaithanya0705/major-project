"""
Checks for OpenRouter fallback failure observability.

Usage:
    python tests/test_openrouter_runtime_failures.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.openrouter_runtime as openrouter_runtime


class _FakeOpenRouterModel:
    openrouter_api_key = "key"
    openrouter_url = "https://openrouter.example.invalid"
    openrouter_site_url = ""
    openrouter_site_name = "tests"
    openrouter_timeout_seconds = 1
    openrouter_model = "fallback-a"
    openrouter_vision_model = ""


def test_text_fallback_records_each_failed_openrouter_model() -> None:
    async def _run() -> None:
        original_get_models = openrouter_runtime.get_openrouter_models
        original_set_label = openrouter_runtime.set_model_label
        original_call_text = openrouter_runtime.call_openrouter_text_sync

        async def _noop_set_label(*_args, **_kwargs) -> bool:
            return True

        def _fail_text(*_args, **kwargs) -> str:
            raise RuntimeError(f"{kwargs.get('model_name')} failed")

        try:
            openrouter_runtime.get_openrouter_models = lambda _purpose: ["fallback-a", "fallback-b"]
            openrouter_runtime.set_model_label = _noop_set_label
            openrouter_runtime.call_openrouter_text_sync = _fail_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

            result = await openrouter_runtime.try_openrouter_text_fallback(
                _FakeOpenRouterModel(),
                label="DirectQA",
                system_prompt="system",
                user_prompt="user",
                purpose="text",
            )

            assert result is None
            failures = openrouter_runtime.get_last_openrouter_fallback_failures()
            assert [failure.model_name for failure in failures] == ["fallback-a", "fallback-b"]
            assert [failure.mode for failure in failures] == ["text", "text"]
            assert failures[0].label == "DirectQA"
            assert "fallback-a failed" in failures[0].message
        finally:
            openrouter_runtime.get_openrouter_models = original_get_models
            openrouter_runtime.set_model_label = original_set_label
            openrouter_runtime.call_openrouter_text_sync = original_call_text
            openrouter_runtime.clear_last_openrouter_fallback_failures()

    asyncio.run(_run())


if __name__ == "__main__":
    test_text_fallback_records_each_failed_openrouter_model()
    print("[test_openrouter_runtime_failures] All checks passed.")
