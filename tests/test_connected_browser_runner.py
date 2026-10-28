import asyncio
import json

from tests.test_connected_browser_gateway import Browser


def runner_class():
    from agents.browser.connected_runner import ConnectedBrowserRunner
    return ConnectedBrowserRunner


class Client(Browser):
    def __init__(self, root):
        super().__init__()
        self.project_root = root
        self.closed = False

    async def close(self): self.closed = True


def decisions(*items):
    responses = iter(items)
    async def decide(system, user):
        item = next(responses)
        return item if isinstance(item, str) else json.dumps(item)
    return decide


async def test_novel_task_runs_without_a_matching_specialized_skill(tmp_path):
    client = Client(tmp_path)
    client.nodes["e2"] = {"tag": "button", "type": "button", "label": "Details", "form": None}
    run = runner_class()(client, decide=decisions(
        {"tool": "browser_click", "arguments": {"target": "e2"}},
        {"done": True, "summary": "Opened details.", "evidence": ["Verified click"]}))
    result = await run.execute("Open the details control in this unfamiliar web app")
    assert result["success"] and result["complete"]
    assert client.effects[0][0] == "browser_click"


async def test_malformed_model_outputs_do_not_cause_side_effects(tmp_path):
    client = Client(tmp_path)
    run = runner_class()(client, decide=decisions("not JSON", "[]", '{"tool":"browser_evaluate","arguments":{}}'))
    result = await run.execute("Inspect the current page")
    assert not result["complete"] and not client.effects


async def test_model_cannot_claim_completion_without_observed_evidence(tmp_path):
    client = Client(tmp_path)
    invented = {"done": True, "summary": "Submitted!", "evidence": ["Server accepted the application"]}
    run = runner_class()(client, decide=decisions(invented, invented, invented))
    result = await run.execute("Submit the form")
    assert not result["complete"] and not client.effects


async def test_declined_submission_stops_without_trying_another_tool(tmp_path):
    client = Client(tmp_path)
    asked = []
    async def deny(message): asked.append(message); return False
    run = runner_class()(client, confirm=deny, decide=decisions(
        {"tool": "browser_click", "arguments": {"target": "e2"}},
        {"tool": "browser_press_key", "arguments": {"key": "Enter"}}))
    result = await run.execute("Submit the form")
    assert not result["complete"] and len(asked) == 1 and not client.effects


async def test_stop_cancels_model_and_keeps_objective_for_resume(tmp_path):
    client = Client(tmp_path)
    started = asyncio.Event()
    async def slow(*_):
        started.set()
        await asyncio.Event().wait()
    run = runner_class()(client, decide=slow)
    task = asyncio.create_task(run.execute("Find information in the selected tab"))
    await started.wait()
    run.request_stop()
    result = await task
    assert not result["complete"] and run.last_objective and not client.effects
    await run.disconnect()
    assert client.closed


async def test_provider_failure_is_incomplete_without_raw_exception_leak(tmp_path):
    client = Client(tmp_path)
    async def fail(*_): raise RuntimeError("secret-value-token")
    run = runner_class()(client, decide=fail)
    result = await run.execute("Inspect tab")
    assert not result["complete"] and "secret-value-token" not in str(result)


async def test_multipage_comparison_retains_bounded_source_evidence(tmp_path):
    client = Client(tmp_path)
    client.snapshot = '- heading "Quartz battery: 9 hours" [ref=e1]'
    original = client.call_result
    async def call(name, args=None):
        reply = await original(name, args)
        if name == "browser_navigate":
            client.snapshot = '- heading "Lumen battery: 14 hours" [ref=e2]'
        return reply
    client.call_result = call
    prompts = []
    async def decide(_system, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return json.dumps({"tool":"browser_navigate", "arguments":{"url":"https://forms.example/lumen"}})
        return json.dumps({"done":True,"summary":"Quartz lasts 9 hours; Lumen lasts 14 hours.",
            "evidence":["Quartz battery: 9 hours","Lumen battery: 14 hours"]})
    result = await runner_class()(client, decide=decide).execute("Compare battery measurements across both reports")
    assert result["complete"] and "Quartz battery: 9 hours" in prompts[1]


async def test_action_status_metadata_cannot_claim_completion(tmp_path):
    client = Client(tmp_path)
    run = runner_class()(client, decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":"Demo"},
         "done":False,"summary":"Entered the name","evidence":[]},
        {"done":True,"summary":"Draft filled","evidence":["Verified type"]}))
    result = await run.execute("Fill the name with Demo and leave a draft")
    assert result["complete"] and len(client.effects) == 1


async def test_action_with_done_true_is_not_executed(tmp_path):
    client = Client(tmp_path)
    bad = {"tool":"browser_click","arguments":{"target":"e2"},"done":True,"summary":"Submitted","evidence":[]}
    result = await runner_class()(client, decide=decisions(bad,bad,bad)).execute("Submit the form")
    assert not result["complete"] and not client.effects


async def test_invalid_arguments_are_corrected_before_any_action(tmp_path):
    client = Client(tmp_path)
    result = await runner_class()(client, decide=decisions(
        {"tool":"browser_type","arguments":{"target":"e1","text":123}},
        {"tool":"browser_type","arguments":{"target":"e1","text":"Demo"}},
        {"done":True,"summary":"Draft filled","evidence":["Verified type"]},
    )).execute("Fill the name with Demo")
    assert result["complete"] and len(client.effects) == 1


async def test_successful_action_resets_consecutive_schema_corrections(tmp_path):
    client = Client(tmp_path)
    bad = {"tool":"browser_type","arguments":{"target":"e1","text":123}}
    bad_finish = {"done":True,"summary":"Filled", "evidence":["Invented receipt"]}
    result = await runner_class()(client, decide=decisions(bad, bad,
        {"tool":"browser_type","arguments":{"target":"e1","text":"Demo"}},
        bad_finish,
        {"done":True,"summary":"Draft filled", "evidence":["Verified type"]}
    )).execute("Fill the name with Demo")
    assert result["complete"] and len(client.effects) == 1


async def test_browser_provider_override_does_not_mutate_shared_brain(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.skills import brain_bridge
    from models import brain
    shared = SimpleNamespace(brain_primary="nvidia", brain_escalation=("gemini","openrouter"), jarvis_model="old-model")
    seen = []
    monkeypatch.setattr(brain_bridge, "_brain_model", lambda: shared)
    monkeypatch.setenv("JARVIS_BROWSER_BRAIN_PRIMARY", "gemini")
    monkeypatch.setenv("JARVIS_BROWSER_GEMINI_MODEL", "gemini-3.1-flash-lite")
    async def generate(model, **_):
        seen.append((model.brain_primary, model.jarvis_model))
        return SimpleNamespace(text='{"done":false,"summary":"Need input","evidence":[]}', provider="gemini")
    monkeypatch.setattr(brain, "generate_brain_reply", generate)
    await runner_class()(Client(tmp_path))._brain_decide("system", "user")
    assert seen == [("gemini", "gemini-3.1-flash-lite")]
    assert shared.brain_primary == "nvidia" and shared.jarvis_model == "old-model"


async def test_browser_nvidia_model_is_scoped_to_its_own_brain_copy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from agents.skills import brain_bridge
    from models import brain
    shared = SimpleNamespace(brain_primary="nvidia", brain_escalation=(), jarvis_model="gemini")
    monkeypatch.setattr(brain_bridge, "_brain_model", lambda: shared)
    monkeypatch.setenv("JARVIS_BROWSER_NVIDIA_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    seen = []
    async def generate(model, **_):
        seen.append(getattr(model, "nvidia_brain_model", None))
        return SimpleNamespace(text="{}", provider="nvidia")
    monkeypatch.setattr(brain, "generate_brain_reply", generate)
    await runner_class()(Client(tmp_path))._brain_decide("system", "user")
    assert seen == ["nvidia/nemotron-3.5-super-vl-120b-a12b"]
    assert not hasattr(shared, "nvidia_brain_model")


async def test_completion_correction_supplies_real_quote_candidates(tmp_path):
    client = Client(tmp_path)
    client.snapshot = '- heading "Actual result on the page" [ref=e1]'
    calls = 0
    async def decide(_system, user):
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"done":True,"summary":"Read result","evidence":["The page says a paraphrased result"]})
        quotes = json.loads(user)["available_evidence_quotes"]
        assert "Actual result on the page" in quotes
        return json.dumps({"done":True,"summary":"Actual result on the page","evidence":["Actual result on the page"]})
    result = await runner_class()(client, decide=decide).execute("Read the result on this page")
    assert result["complete"] and not client.effects


async def test_comparison_can_cite_eight_observed_facts(tmp_path):
    client = Client(tmp_path)
    facts = [f"Observed fact {i}" for i in range(8)]
    client.snapshot = "\n".join(f'- heading "{fact}" [ref=e{i}]' for i,fact in enumerate(facts))
    done = {"done":True,"summary":"Compared all eight observed facts","evidence":facts}
    result = await runner_class()(client, decide=decisions(done,done,done)).execute("Compare the eight facts")
    assert result["complete"]


class TokenClient(Client):
    extension = True
    def __init__(self, root):
        super().__init__(root)
        self.tab_calls = []
        self.tab_url = "https://forms.example/application"
        self.chosen = False
    async def call_result(self, name, args=None):
        from agents.browser.mcp_client import McpToolResult
        if name == "browser_tabs":
            action = (args or {}).get("action")
            self.tab_calls.append(action)
            if action == "select": self.chosen = True
            return McpToolResult(f"### Open tabs\n- 0: [Application]({self.tab_url})")
        assert self.chosen, "Private page must not be read before explicit tab selection"
        return await super().call_result(name, args)


async def test_pairing_token_lists_tabs_before_reading_private_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "test-pair-token")
    client = TokenClient(tmp_path)
    run = runner_class()(client)
    message = await run.connect()
    assert run.state == "awaiting_tab_selection" and "0:" in message
    assert client.tab_calls == ["list"] and not client.chosen
    await run.select_tab(0)
    assert run.state == "ready" and client.chosen


async def test_changed_tab_metadata_is_not_selected(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_MCP_EXTENSION_TOKEN", "test-pair-token")
    client = TokenClient(tmp_path)
    run = runner_class()(client)
    await run.connect()
    client.tab_url = "https://different.example/"
    import pytest
    with pytest.raises(RuntimeError, match="changed|stale"):
        await run.select_tab(0)
    assert "select" not in client.tab_calls
