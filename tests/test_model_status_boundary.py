"""
Checks for optional model-status UI update boundaries.

Usage:
    python tests/test_model_status_boundary.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
from models.model_status import (
    clear_last_model_status_update_failures,
    get_last_model_status_update_failures,
)
from models.router_runtime import route_request


class _FakeRouterModel:
    router_provider = "nvidia"
    nvidia_api_key = "key"
    nvidia_router_model = "nvidia-router"
    nvidia_url = "https://example.invalid"
    nvidia_timeout_seconds = 1
    nvidia_router_max_tokens = 10
    openrouter_api_key = ""
    openrouter_router_model = ""
    openrouter_url = ""
    ollama_router_model = ""
    ollama_base_url = ""
    router_wall_timeout_grace_seconds = 0.01

    def _call_nvidia_router_sync(self, prompt: str):
        return {"agent": "direct", "response_text": "ok"}


async def test_router_records_model_label_update_failure_without_blocking_route() -> None:
    original_set_model_name = model_module.set_model_name

    async def _fail_set_model_name(_label: str) -> None:
        raise RuntimeError("status UI unavailable")

    try:
        model_module.set_model_name = _fail_set_model_name
        clear_last_model_status_update_failures()

        routed = await route_request(_FakeRouterModel(), "# User's Latest Request:\nhello")

        assert routed["agent"] == "direct"
        failures = get_last_model_status_update_failures()
        assert len(failures) == 1, failures
        assert failures[0].label == "nvidia-router (NVIDIA)"
        assert failures[0].context == "router:nvidia"
        assert "status UI unavailable" in str(failures[0].error)
    finally:
        model_module.set_model_name = original_set_model_name
        clear_last_model_status_update_failures()


def run_checks() -> None:
    asyncio.run(test_router_records_model_label_update_failure_without_blocking_route())


if __name__ == "__main__":
    run_checks()
    print("[test_model_status_boundary] All checks passed.")
