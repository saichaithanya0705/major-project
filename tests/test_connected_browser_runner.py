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
