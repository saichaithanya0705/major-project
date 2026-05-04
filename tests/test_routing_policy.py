"""
Checks rapid-router policy and capability validation.

Usage:
    python tests/test_routing_policy.py
"""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
from models.function_calls import invoke_cua_cli_declaration, invoke_cua_vision_declaration
from models.prompts import OLLAMA_ROUTER_SYSTEM_PROMPT, RAPID_RESPONSE_SYSTEM_PROMPT
from models.routing_policy import _apply_routing_guardrails


def test_router_prompt_uses_general_capability_fit_not_surface_hardcoding() -> None:
    combined = "\n".join(
        [
            RAPID_RESPONSE_SYSTEM_PROMPT,
            OLLAMA_ROUTER_SYSTEM_PROMPT,
            str(invoke_cua_cli_declaration.get("description", "")),
            str(invoke_cua_vision_declaration.get("description", "")),
        ]
    ).lower()

    assert "capability-fit" in combined
    assert "underlying data source" in combined
    assert "programmatically" in combined
    assert "more deterministic" in combined
    assert "task manager" not in combined


def test_router_tool_descriptions_distinguish_shell_state_from_visual_ui() -> None:
    cli_description = str(invoke_cua_cli_declaration.get("description", "")).lower()
    vision_description = str(invoke_cua_vision_declaration.get("description", "")).lower()

    assert "local machine state" in cli_description
    assert "queried programmatically" in cli_description
    assert "pointer/keyboard" in vision_description
    assert "only on screen" in vision_description
    assert "shell command can inspect" in vision_description


def test_browser_route_with_desktop_app_profile_requirement_is_repaired_to_vision() -> None:
    prompt = (
        "open my installed browser app with the work profile and open a new tab "
        "then go to whatsapp web"
    )

    routed = _apply_routing_guardrails(
        user_prompt=prompt,
        routing_result={"agent": "browser", "task": prompt},
        latest_screen_context=None,
    )

    assert routed["agent"] == "cua_vision", routed
    assert routed["task"] == prompt, routed


def test_plain_web_automation_still_routes_to_browser() -> None:
    prompt = "open whatsapp web and send a message to konda as hi"

    routed = _apply_routing_guardrails(
        user_prompt=prompt,
        routing_result={"agent": "browser", "task": prompt},
        latest_screen_context=None,
    )

    assert routed["agent"] == "browser", routed


async def test_route_request_calls_llm_even_for_deterministic_looking_prompt() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.router_provider = "openrouter"
    model.openrouter_api_key = "test-key"
    model.openrouter_url = "https://router.example.test"
    model.openrouter_router_model = "router-model"
    model.openrouter_router_max_tokens = 300
    model.ollama_router_model = ""
    model.ollama_base_url = ""

    calls: list[str] = []
    original_set_model_name = model_module.set_model_name

    def _fake_openrouter_router(prompt: str) -> dict:
        calls.append(prompt)
        return {"agent": "browser", "task": "open localhost 3000"}

    async def _fake_set_model_name(_value: str) -> None:
        return None

    model._call_openrouter_router_sync = _fake_openrouter_router
    model_module.set_model_name = _fake_set_model_name
    try:
        routed = await model.route_request("# User's Latest Request:\nopen localhost 3000")
    finally:
        model_module.set_model_name = original_set_model_name

    assert len(calls) == 1, calls
    assert routed == {"agent": "browser", "task": "open localhost 3000"}, routed


if __name__ == "__main__":
    test_router_prompt_uses_general_capability_fit_not_surface_hardcoding()
    test_router_tool_descriptions_distinguish_shell_state_from_visual_ui()
    test_browser_route_with_desktop_app_profile_requirement_is_repaired_to_vision()
    test_plain_web_automation_still_routes_to_browser()
    asyncio.run(test_route_request_calls_llm_even_for_deterministic_looking_prompt())
    print("[test_routing_policy] All checks passed.")
