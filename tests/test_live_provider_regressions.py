"""Regressions reproduced against the presentation machine's live providers."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.cua_cli.backends import BackendRequest
from agents.cua_cli.backends.copilot import CopilotBackend
from models import brain
from models.routing import router_backends


def test_nvidia_is_a_selectable_brain_provider(monkeypatch):
    monkeypatch.setenv("JARVIS_BRAIN_PRIMARY", "nvidia")
    monkeypatch.setenv("JARVIS_BRAIN_ESCALATION", "gemini,openrouter")
    from models.routing.router_preflight import build_default_model_runtime_config
    config = build_default_model_runtime_config("qwen3.5:4b-fast")
    assert config.brain_primary == "nvidia"
    assert "nvidia" in brain._PROVIDERS


@pytest.mark.parametrize("json_mode", [False, True])
async def test_nvidia_brain_returns_content_and_disables_thinking(monkeypatch, json_mode):
    observed = {}
    content = '{"answer":42}' if json_mode else "42"
    monkeypatch.setenv("NVIDIA_BRAIN_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

    def post(url, *, headers, json, timeout):
        observed.update(url=url, headers=headers, payload=json, timeout=timeout)
        assert json.get("chat_template_kwargs") == {"enable_thinking": False}
        return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr(router_backends.requests, "post", post)
    model = SimpleNamespace(nvidia_api_key="test-key", nvidia_url="https://nvidia.invalid/v1/chat/completions",
        nvidia_router_model="router-model", nvidia_timeout_seconds=15)
    provider = brain._PROVIDERS.get("nvidia")
    assert provider is not None, "NVIDIA must be available to normal chat and structured skills"
    assert await provider(model, "SYS", "17 plus 25", 0.1, 160, json_mode=json_mode) == content
    assert observed["payload"]["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert observed["payload"].get("response_format") == ({"type": "json_object"} if json_mode else None)
    assert brain.provider_configured(model, "nvidia")
    assert "lightning" in brain.provider_label(model, "nvidia")


def test_nvidia_router_does_not_spend_small_output_budget_on_reasoning(monkeypatch):
    def post(_url, *, headers, json, timeout):
        # This reproduces the live empty-content response when thinking is enabled.
        content = '{"agent":"direct","response_text":"42"}' if json.get("chat_template_kwargs") == {"enable_thinking": False} else ""
        return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": {"content": content}}]})
    monkeypatch.setattr(router_backends.requests, "post", post)
    route = router_backends.call_nvidia_router_sync(nvidia_api_key="test-key",
        nvidia_url="https://nvidia.invalid/v1/chat/completions", nvidia_timeout_seconds=15,
        nvidia_router_model="nvidia/nemotron-3.5-lightning-30b-a3b", nvidia_router_max_tokens=240,
        router_system_prompt="Return JSON.", prompt="17 plus 25", clean_text=lambda x, *_: str(x),
        parse_json_object_from_text=json.loads)
    assert route["agent"] == "direct"


@pytest.mark.parametrize("bad_reply", ["not JSON", "[]", '{"answer":'])
async def test_structured_brain_rejects_malformed_output_and_uses_fallback(monkeypatch, bad_reply):
    model = SimpleNamespace(brain_primary="local", brain_escalation=("gemini",), brain_model="test-local",
        brain_self_escalate=False, jarvis_model="test-gemini")
    monkeypatch.setattr(brain, "provider_configured", lambda *_: True)
    async def primary(*_args, **_kwargs):
        return bad_reply
    async def fallback(*_args, **_kwargs):
        return '{"answer":42}'
    reply = await brain.generate_brain_reply(model, system="Return JSON.", user="Question",
        json_mode=True, providers={"local": primary, "gemini": fallback})
    assert reply.provider == "gemini"
    assert json.loads(reply.text) == {"answer": 42}


def test_copilot_invocation_avoids_removed_flag_and_stays_noninteractive():
    args = CopilotBackend().build_args(BackendRequest(prompt="17 plus 25", cwd=".", answer_only=True))
    assert "--disable-client-telemetry" not in args
    assert "--deny-tool" in args
    assert "--prompt" in args
    assert "17 plus 25" not in args


def test_provider_helpers_load_the_project_dotenv_after_module_move():
    from models.shared import openrouter_fallback
    assert openrouter_fallback._DOTENV_PATH == Path(__file__).resolve().parents[1] / ".env"


@pytest.mark.parametrize("prompt", [
    "Find the current Python release on python.org and cite your source.",
    "What is the latest Node.js release with sources?",
    "Search the web for the latest Python release.",
])
def test_software_release_questions_use_sourced_chat(prompt):
    from models.routing.routing_question_policy import is_source_grounded_qa_request, is_direct_chat_request
    assert is_source_grounded_qa_request(prompt)
    assert is_direct_chat_request(prompt)


@pytest.mark.parametrize("prompt", [
    "Install the latest Python release.",
    "Run python to show its current version.",
    "Find current Python files in this repository.",
])
def test_software_execution_and_local_state_stay_out_of_sourced_chat(prompt):
    from models.routing.routing_question_policy import is_source_grounded_qa_request, is_direct_chat_request
    assert not is_source_grounded_qa_request(prompt)
    assert not is_direct_chat_request(prompt)


async def test_annotation_queue_preserves_spacing_and_reading_time(monkeypatch):
    from agents.jarvis import tools
    tools.stop_all_actions()
    elapsed = 0.0
    events = []
    class Finished(Exception):
        pass
    async def sleep(delay):
        nonlocal elapsed
        elapsed += delay
    async def draw():
        events.append(("draw", elapsed))
    async def _clear_screen_with_layout_reset():
        events.append(("clear", elapsed))
        raise Finished
    monkeypatch.setattr(tools, "asyncio", SimpleNamespace(sleep=sleep))
    tools.ACTION_QUEUE.extend([(0.0, draw, (), {}), (2.0, draw, (), {}),
                              (9.0, _clear_screen_with_layout_reset, (), {})])
    try:
        with pytest.raises(Finished):
            await tools._run_queue_async()
        assert events == [("draw", 0.0), ("draw", 2.0), ("clear", 9.0)]
    finally:
        tools.stop_all_actions()
