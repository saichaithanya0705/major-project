"""Exercise the merged direct-chat path through the provider escalation brain."""

from types import SimpleNamespace

import pytest

from agents.direct_chat import agent as direct_chat
from models import brain


@pytest.mark.parametrize("mode", ["local", "sourced", "escalated"])
async def test_direct_chat_preserves_search_and_uses_brain_providers(monkeypatch, mode):
    calls = []
    labels = []
    search = SimpleNamespace(queries=[], closed=False)
    source = {
        "title": "Example source",
        "url": "https://example.com/source",
        "content": "A supplied current fact.",
    }

    async def search_sources(query, **_kwargs):
        search.queries.append(query)
        return {"results": [source]}

    async def close_search():
        search.closed = True

    async def local_reply(model, system, user, *_args, **_kwargs):
        assert model.client is None
        calls.append(("local", system, user))
        return "Local answer."

    async def stronger_reply(_model, system, user, *_args, **_kwargs):
        calls.append(("codex", system, user))
        return "Stronger answer."

    async def set_label(label, *, context):
        labels.append((label, context))

    search.search = search_sources
    search.close = close_search
    monkeypatch.setattr(brain, "_PROVIDERS", {"local": local_reply, "codex": stronger_reply})
    monkeypatch.setattr(brain, "provider_configured", lambda _model, _name: True)
    monkeypatch.setattr(direct_chat, "set_model_label", set_label)
    model = SimpleNamespace(
        client=None,
        brain_primary="local",
        brain_model="test-local",
        brain_escalation=("codex",),
        brain_self_escalate=True,
    )
    prompt = "Please think harder about this" if mode == "escalated" else "Explain this fact"
    agent = direct_chat.DirectChatAgent(
        model=model,
        history_block="Earlier conversation.",
        search_client=search,
        search_predicate=lambda _prompt: mode == "sourced",
    )

    result = await agent.execute(prompt)

    assert result["success"], result
    assert search.closed
    assert [call[0] for call in calls] == (["codex"] if mode == "escalated" else ["local"])
    assert prompt in calls[0][2]
    if mode == "sourced":
        assert search.queries == [prompt]
        assert source["content"] in calls[0][2]
        assert "only the provided" in calls[0][1]
        assert brain.SELF_ESCALATION_INSTRUCTION not in calls[0][1]
        assert "[Example source](https://example.com/source)" in result["result"]
        assert result["tool_calls"][0]["name"] == "tavily_search"
        assert labels == [("test-local (local) (Direct Agent)", "direct_chat:web_search")]
    else:
        assert not search.queries
        assert "Earlier conversation." in calls[0][2]
        assert result["result"] == ("Stronger answer." if mode == "escalated" else "Local answer.")
