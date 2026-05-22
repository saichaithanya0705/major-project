"""
Checks for shared CUA vision provider runtime helpers.

Usage:
    python tests/test_cua_vision_provider_runtime.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.cua_vision.provider_runtime as runtime  # noqa: E402
from agents.cua_vision.contracts import ScreenObservation  # noqa: E402


def test_iter_cua_vision_providers_preserves_provider_order() -> None:
    originals = {
        "get_nvidia_api_key": runtime.get_nvidia_api_key,
        "get_nvidia_models": runtime.get_nvidia_models,
        "get_nvidia_chat_url": runtime.get_nvidia_chat_url,
        "get_nvidia_timeout_seconds": runtime.get_nvidia_timeout_seconds,
        "get_openrouter_api_key": runtime.get_openrouter_api_key,
        "get_openrouter_models": runtime.get_openrouter_models,
        "get_openrouter_chat_url": runtime.get_openrouter_chat_url,
        "get_openrouter_timeout_seconds": runtime.get_openrouter_timeout_seconds,
        "get_openrouter_site_url": runtime.get_openrouter_site_url,
        "get_openrouter_site_name": runtime.get_openrouter_site_name,
    }
    runtime.get_nvidia_api_key = lambda: "nvidia-key"
    runtime.get_nvidia_models = lambda purpose: [f"{purpose}-nvidia"]
    runtime.get_nvidia_chat_url = lambda: "https://nvidia.example/chat"
    runtime.get_nvidia_timeout_seconds = lambda: 31
    runtime.get_openrouter_api_key = lambda: "openrouter-key"
    runtime.get_openrouter_models = lambda purpose: [f"{purpose}-openrouter"]
    runtime.get_openrouter_chat_url = lambda: "https://openrouter.example/chat"
    runtime.get_openrouter_timeout_seconds = lambda: 32
    runtime.get_openrouter_site_url = lambda: "https://app.example"
    runtime.get_openrouter_site_name = lambda: "App"
    try:
        providers = runtime.iter_cua_vision_providers("cua_planner_low")
    finally:
        for name, original in originals.items():
            setattr(runtime, name, original)

    assert [provider.label for provider in providers] == ["NVIDIA", "OpenRouter"]
    assert providers[0].models == ("cua_planner_low-nvidia",)
    assert providers[1].site_name == "App"


def test_screenshot_base64_to_data_url_is_idempotent() -> None:
    assert runtime.screenshot_base64_to_data_url(None) is None
    assert runtime.screenshot_base64_to_data_url("abc") == "data:image/png;base64,abc"
    assert (
        runtime.screenshot_base64_to_data_url("data:image/png;base64,abc")
        == "data:image/png;base64,abc"
    )


def test_observation_image_data_url_uses_observation_screenshot() -> None:
    observation = ScreenObservation(
        screenshot_png_base64="abc",
        active_window_title="Test",
        capture_context={},
    )

    assert runtime.observation_image_data_url(observation) == "data:image/png;base64,abc"


def run_checks() -> None:
    test_iter_cua_vision_providers_preserves_provider_order()
    test_screenshot_base64_to_data_url_is_idempotent()
    test_observation_image_data_url_uses_observation_screenshot()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_provider_runtime] All checks passed.")
