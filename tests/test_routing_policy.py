"""
Checks rapid-router policy and capability validation.

Usage:
    python tests/test_routing_policy.py
"""

import asyncio
import os
import sys
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.models as model_module
from models.function_calls import (
    invoke_cua_cli_declaration,
    invoke_cua_vision_declaration,
    invoke_web_qa_declaration,
)
from models.prompts import OLLAMA_ROUTER_SYSTEM_PROMPT, RAPID_RESPONSE_SYSTEM_PROMPT
from models.routing_intent_policy import (
    has_context_dependent_reference,
    is_direct_qa_request,
    is_web_qa_request,
)
from models.routing_guardrails import apply_routing_guardrails
from models.routing_prompt_parser import extract_latest_request_from_router_prompt
from models.routing_payload_parser import (
    EmptyJsonObjectBoundary,
    MalformedJsonObjectBoundary,
    parse_json_object_boundary_text,
    parse_json_object_text,
)
from models.routing_policy import (
    _apply_routing_guardrails,
    _extract_latest_request,
    _is_direct_qa_request,
    _is_web_qa_request,
    _parse_json_object_boundary_from_text,
    _parse_json_object_from_text,
    _router_provider_order,
)


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


def test_router_prompt_exposes_web_qa_for_source_grounded_questions() -> None:
    combined = "\n".join(
        [
            RAPID_RESPONSE_SYSTEM_PROMPT,
            OLLAMA_ROUTER_SYSTEM_PROMPT,
            str(invoke_web_qa_declaration.get("description", "")),
        ]
    ).lower()

    assert "web_qa" in combined
    assert "tavily" in combined
    assert "current" in combined
    assert "sources" in combined


def test_web_qa_intent_bypasses_direct_fast_path() -> None:
    current_prompt = "What is the latest news about Elon Musk?"
    sourced_prompt = "Tell me everything about Elon Musk with sources."
    timeless_prompt = "Explain what recursion is."

    assert _is_web_qa_request(current_prompt) is True
    assert _is_web_qa_request(sourced_prompt) is True
    assert _is_direct_qa_request(current_prompt) is False
    assert _is_direct_qa_request(sourced_prompt) is False
    assert _is_web_qa_request(timeless_prompt) is False
    assert _is_direct_qa_request(timeless_prompt) is True


def test_web_qa_intent_is_not_blocked_by_bare_deictic_subject() -> None:
    prompt = "What is the latest news about this company with sources?"

    assert _is_web_qa_request(prompt) is True
    assert _is_direct_qa_request(prompt) is False


def test_intent_policy_boundary_separates_local_deixis_from_dynamic_subjects() -> None:
    dynamic_subject_prompt = "What is the latest news about this company with sources?"
    local_reference_prompt = "Explain what is happening on this page."

    assert has_context_dependent_reference(dynamic_subject_prompt) is False
    assert has_context_dependent_reference(local_reference_prompt) is True
    assert is_web_qa_request(dynamic_subject_prompt) is True
    assert is_direct_qa_request(dynamic_subject_prompt) is False
    assert _is_web_qa_request(dynamic_subject_prompt) == is_web_qa_request(dynamic_subject_prompt)
    assert _is_direct_qa_request(dynamic_subject_prompt) == is_direct_qa_request(dynamic_subject_prompt)


def test_json_object_parser_reports_salvaged_embedded_object() -> None:
    raw = 'Route this request: {"agent":"browser","task":"open https://example.com"}'

    parsed = parse_json_object_text(raw)

    assert parsed.payload == {
        "agent": "browser",
        "task": "open https://example.com",
    }
    assert parsed.mode == "embedded_object"
    assert [failure.stage for failure in parsed.failures] == ["full_text"]
    assert "Expecting value" in parsed.failures[0].message
    assert _parse_json_object_from_text(raw) == parsed.payload


def test_json_object_parser_reports_non_object_failure_without_salvage() -> None:
    parsed = parse_json_object_text('["browser", "open example.com"]')

    assert parsed.payload == {}
    assert parsed.mode == "invalid"
    assert [failure.stage for failure in parsed.failures] == ["full_text"]
    assert "JSON object" in parsed.failures[0].message


def test_json_object_boundary_distinguishes_empty_from_malformed_payload() -> None:
    empty = _parse_json_object_boundary_from_text("   ")
    malformed = _parse_json_object_boundary_from_text('["browser", "open example.com"]')

    assert isinstance(empty, EmptyJsonObjectBoundary)
    assert empty.kind == "empty"
    assert isinstance(malformed, MalformedJsonObjectBoundary)
    assert malformed.kind == "malformed"
    assert [failure.stage for failure in malformed.failures] == ["full_text"]


def test_payload_only_json_object_helper_preserves_compatibility_behavior() -> None:
    assert _parse_json_object_from_text("   ") == {}
    assert _parse_json_object_from_text('["browser", "open example.com"]') == {}
    assert parse_json_object_boundary_text('["browser", "open example.com"]').kind == "malformed"


def test_latest_request_extraction_is_shared_router_prompt_boundary() -> None:
    prompt = "# User's Latest Request:\nopen localhost 3000"

    assert extract_latest_request_from_router_prompt(prompt) == "open localhost 3000"
    assert _extract_latest_request(prompt) == "open localhost 3000"


def test_source_grounded_direct_route_is_repaired_to_web_qa() -> None:
    prompt = "Tell me the latest about Elon Musk with sources."
    route = _apply_routing_guardrails(
        user_prompt=prompt,
        routing_result={"agent": "direct", "response_text": "Elon Musk is a business executive."},
        latest_screen_context=None,
    )

    assert route == {"agent": "web_qa", "task": prompt}, route


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


def test_guardrail_helper_reports_rewrite_provenance_for_execution_rewrite() -> None:
    prompt = "Minimize the codex app on my screen"

    guarded = apply_routing_guardrails(
        user_prompt=prompt,
        routing_result={"agent": "jarvis", "query": prompt},
        latest_screen_context=None,
        build_browser_resume_route=lambda _prompt: None,
    )

    assert guarded.route == {"agent": "cua_vision", "task": prompt}
    assert guarded.rewritten_from == {"agent": "jarvis", "query": prompt}
    assert guarded.rewrite_reason == "execution_request_needs_actionable_agent"


def test_router_provider_order_rejects_unknown_provider_value() -> None:
    try:
        _router_provider_order(
            router_provider="mystery-router",
            nvidia_enabled=True,
            openrouter_enabled=True,
            ollama_enabled=True,
        )
        raise AssertionError("Expected unknown router provider to fail fast.")
    except ValueError as exc:
        assert "unknown router_provider" in str(exc).lower()


async def test_route_request_calls_llm_even_for_deterministic_looking_prompt() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.router_provider = "openrouter"
    model.nvidia_api_key = ""
    model.nvidia_router_model = ""
    model.nvidia_url = ""
    model.openrouter_api_key = "test-key"
    model.openrouter_url = "https://router.example.test"
    model.openrouter_router_model = "router-model"
    model.openrouter_timeout_seconds = 45
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


async def test_route_request_wall_timeout_falls_back_to_next_provider() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.router_provider = "openrouter"
    model.nvidia_api_key = "nvidia-key"
    model.nvidia_router_model = "nvidia-router"
    model.nvidia_url = "https://nvidia.example.test"
    model.nvidia_timeout_seconds = 1
    model.openrouter_api_key = "openrouter-key"
    model.openrouter_url = "https://router.example.test"
    model.openrouter_router_model = "openrouter-router"
    model.openrouter_timeout_seconds = 0.01
    model.ollama_router_model = ""
    model.ollama_base_url = ""
    model.router_wall_timeout_grace_seconds = 0.01

    calls: list[str] = []
    original_set_model_name = model_module.set_model_name

    def _slow_openrouter_router(prompt: str) -> dict:
        calls.append("openrouter")
        time.sleep(0.2)
        return {"agent": "direct", "response_text": "late"}

    def _working_nvidia_router(prompt: str) -> dict:
        calls.append("nvidia")
        return {"agent": "direct", "response_text": "done"}

    async def _fake_set_model_name(_value: str) -> None:
        return None

    model._call_openrouter_router_sync = _slow_openrouter_router
    model._call_nvidia_router_sync = _working_nvidia_router
    model_module.set_model_name = _fake_set_model_name
    try:
        routed = await model.route_request("# User's Latest Request:\nhello")
    finally:
        model_module.set_model_name = original_set_model_name

    assert calls[:2] == ["openrouter", "nvidia"], calls
    assert routed == {"agent": "direct", "response_text": "done"}, routed


async def test_route_request_normalizes_plan_payload_from_provider() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.router_provider = "openrouter"
    model.nvidia_api_key = ""
    model.nvidia_router_model = ""
    model.nvidia_url = ""
    model.openrouter_api_key = "openrouter-key"
    model.openrouter_url = "https://router.example.test"
    model.openrouter_router_model = "openrouter-router"
    model.openrouter_timeout_seconds = 45
    model.openrouter_router_max_tokens = 300
    model.ollama_router_model = ""
    model.ollama_base_url = ""

    original_set_model_name = model_module.set_model_name

    def _plan_openrouter_router(prompt: str) -> dict:
        return {
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
        }

    async def _fake_set_model_name(_value: str) -> None:
        return None

    model._call_openrouter_router_sync = _plan_openrouter_router
    model_module.set_model_name = _fake_set_model_name
    try:
        routed = await model.route_request(
            "# User's Latest Request:\nFind release notes and update changelog."
        )
    finally:
        model_module.set_model_name = original_set_model_name

    assert routed == {
        "tasks": [
            {
                "id": "research",
                "agent": "web_qa",
                "task": "Find release notes",
                "resources": ["web_qa"],
            },
            {
                "id": "patch",
                "agent": "cua_cli",
                "task": "Update changelog",
                "depends_on": ["research"],
                "resources": ["cli"],
            },
        ],
        "max_parallel": 2,
    }, routed


async def test_route_request_rejects_unknown_router_provider_value() -> None:
    model = model_module.GeminiModel.__new__(model_module.GeminiModel)
    model.router_provider = "mystery-router"
    model.nvidia_api_key = "nvidia-key"
    model.nvidia_router_model = "nvidia-router"
    model.nvidia_url = "https://nvidia.example.test"
    model.openrouter_api_key = "openrouter-key"
    model.openrouter_url = "https://router.example.test"
    model.openrouter_router_model = "openrouter-router"
    model.ollama_router_model = "ollama-router"
    model.ollama_base_url = "http://localhost:11434"

    try:
        await model.route_request("# User's Latest Request:\nhello")
        raise AssertionError("Expected unknown router provider to fail fast.")
    except ValueError as exc:
        assert "unknown router_provider" in str(exc).lower()


if __name__ == "__main__":
    test_router_prompt_uses_general_capability_fit_not_surface_hardcoding()
    test_router_tool_descriptions_distinguish_shell_state_from_visual_ui()
    test_router_prompt_exposes_web_qa_for_source_grounded_questions()
    test_web_qa_intent_bypasses_direct_fast_path()
    test_source_grounded_direct_route_is_repaired_to_web_qa()
    test_browser_route_with_desktop_app_profile_requirement_is_repaired_to_vision()
    test_plain_web_automation_still_routes_to_browser()
    asyncio.run(test_route_request_calls_llm_even_for_deterministic_looking_prompt())
    asyncio.run(test_route_request_wall_timeout_falls_back_to_next_provider())
    asyncio.run(test_route_request_rejects_unknown_router_provider_value())
    print("[test_routing_policy] All checks passed.")
