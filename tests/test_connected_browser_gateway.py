import copy
import json

import pytest

from agents.browser.mcp_client import McpToolResult
from core.confirmations import ConfirmationBroker


def gateway_class():
    from agents.browser.connected_gateway import ConnectedGateway
    return ConnectedGateway


class Browser:
    """In-memory page state; assertions exercise production gateway decisions."""
    def __init__(self):
        self.url = "https://forms.example/application"
        self.snapshot = '- textbox "Name" [ref=e1]\n- button "Submit" [ref=e2]\n- searchbox "Search" [ref=e3]'
        self.nodes = {
            "e1": {"tag": "input", "type": "text", "label": "Name", "value": "", "checked": False,
                   "form": {"id": "application", "search": False, "values": [["name", ""]]}},
            "e2": {"tag": "button", "type": "submit", "label": "Submit", "form": {"id": "application", "search": False, "values": [["name", ""]]}},
            "e3": {"tag": "input", "type": "search", "label": "Search", "value": "", "form": {"id": "search", "search": True, "values": []}},
        }
        self.active = "e1"
        self.effects = []
        self.error = False

    async def tool_schemas(self):
        def schema(props, required=()):
            return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}
        string = {"type": "string"}
        return {
            "browser_snapshot": schema({"target": string, "depth": {"type":"number"}, "filename": string}),
            "browser_tabs": schema({"action":{"type":"string","enum":["list","new","select","close"]},"index":{"type":"integer"}}, ["action"]),
            "browser_evaluate": schema({"function": string, "target": string}, ["function"]),
            "browser_click": schema({"target": string}, ["target"]),
            "browser_type": schema({"target": string, "text": string, "submit": {"type": "boolean"}}, ["target", "text"]),
            "browser_press_key": schema({"key": string}, ["key"]),
            "browser_navigate": schema({"url": string}, ["url"]),
            "browser_fill_form": schema({"fields": {"type": "array"}}, ["fields"]),
        }

    async def call_result(self, name, arguments=None):
        args = arguments or {}
        if name == "browser_tabs" and args.get("action") == "list":
            return McpToolResult("### Open tabs\n- 0: (current) [Application](https://forms.example/application)")
        if name == "browser_snapshot":
            return McpToolResult("### Snapshot\n" + self.snapshot)
        if name == "browser_evaluate":
            if "JARVIS_PAGE_INFO" in args["function"]:
                data = {"url": self.url, "title": "Application"}
            else:
                data = copy.deepcopy(self.nodes[args.get("target", self.active)])
            return McpToolResult("### Result\n" + json.dumps(data))
        self.effects.append((name, args))
        if name == "browser_type":
            self.active = args["target"]
            self.nodes[self.active]["value"] = args["text"]
            for node in self.nodes.values():
                if (node.get("form") or {}).get("id") == "application":
                    node["form"]["values"] = [["name", args["text"]]]
        if name == "browser_navigate":
            self.url = args["url"]
        return McpToolResult("ok", self.error)


async def ready(browser=None, confirm=None):
    browser = browser or Browser()
    asked = []
    async def approve(message):
        asked.append(message)
        return True
    gateway = gateway_class()(browser, confirm=confirm or approve, stopped=lambda: False)
    await gateway.observe()
    return gateway, browser, asked


async def test_typing_is_automatic_and_read_back():
    gateway, browser, asked = await ready()
    await gateway.act("browser_type", {"target": "e1", "text": "Demo User"})
    assert browser.nodes["e1"]["value"] == "Demo User"
    assert not asked and gateway.verified_steps


async def test_submission_requires_chat_review_after_filling():
    gateway, browser, asked = await ready()
    await gateway.act("browser_type", {"target": "e1", "text": "Demo User"})
    await gateway.act("browser_click", {"target": "e2"})
    assert len(asked) == 1 and "forms.example" in asked[0] and "Submit" in asked[0]
    assert browser.effects[-1][0] == "browser_click"


async def test_refusal_does_not_submit_or_remove_draft():
    async def deny(_): return False
    gateway, browser, _ = await ready(confirm=deny)
    await gateway.act("browser_type", {"target": "e1", "text": "Demo User"})
    with pytest.raises(RuntimeError, match="declined|cancelled"):
        await gateway.act("browser_click", {"target": "e2"})
    assert len(browser.effects) == 1 and browser.nodes["e1"]["value"] == "Demo User"


@pytest.mark.parametrize("node", [
    {"tag": "button", "type": "submit", "label": "Continue", "form": {"search": False}},
    {"tag": "button", "type": "button", "label": "Submit application", "form": None},
])
async def test_default_and_spa_submissions_are_reviewed(node):
    gateway, browser, asked = await ready()
    browser.nodes["e2"] = node
    await gateway.act("browser_click", {"target": "e2"})
    assert len(asked) == 1


async def test_search_enter_is_automatic_but_form_enter_is_reviewed():
    gateway, browser, asked = await ready()
    browser.active = "e3"
    await gateway.act("browser_press_key", {"key": "Enter"})
    assert not asked
    browser.active = "e1"
    await gateway.act("browser_press_key", {"key": "Enter"})
    assert len(asked) == 1


async def test_changed_form_after_approval_is_not_submitted():
    browser = Browser()
    async def approve(_):
        browser.nodes["e2"]["form"]["values"] = [["name", "Changed elsewhere"]]
        return True
    gateway, _, _ = await ready(browser, approve)
    with pytest.raises(RuntimeError, match="changed|stale"):
        await gateway.act("browser_click", {"target": "e2"})
    assert not browser.effects


@pytest.mark.parametrize("name,args", [
    ("browser_evaluate", {"function": "fetch('/delete')"}),
    ("browser_navigate", {"url": "javascript:alert(1)"}),
    ("browser_navigate", {"url": "file:///private.txt"}),
    ("browser_click", {"target": "#submit"}),
    ("browser_click", {"target": "e99"}),
    ("browser_click", {"target": "e1", "extra": "bad"}),
])
async def test_unapproved_tools_refs_urls_and_arguments_have_no_effect(name, args):
    gateway, browser, _ = await ready()
    with pytest.raises(RuntimeError):
        await gateway.act(name, args)
    assert not browser.effects


async def test_mcp_error_never_becomes_verified_progress():
    gateway, browser, _ = await ready()
    browser.error = True
    with pytest.raises(RuntimeError):
        await gateway.act("browser_type", {"target": "e1", "text": "Demo"})
    assert not gateway.verified_steps


async def test_required_review_cannot_use_legacy_bypass(monkeypatch):
    monkeypatch.setenv("JARVIS_CONFIRM_RISKY_ACTIONS", "off")
    messages = []
    broker = None
    async def notify(message):
        messages.append(message)
        broker.answer("no")
    broker = ConfirmationBroker(notify=notify)
    assert await broker.request("submit the application", required=True) is False
    assert messages


async def test_space_in_text_field_is_not_a_submission():
    gateway, _, asked = await ready()
    await gateway.act("browser_press_key", {"key": "Space"})
    assert not asked


async def test_enter_with_unresolved_active_control_stops():
    gateway, browser, _ = await ready()
    browser.nodes["e1"] = {"tag": "body", "label": "page", "form": None}
    with pytest.raises(RuntimeError, match="active|inspect|control"):
        await gateway.act("browser_press_key", {"key": "Enter"})
    assert not browser.effects


async def test_type_and_submit_fills_then_reviews_without_bypass():
    async def deny(_): return False
    gateway, browser, _ = await ready(confirm=deny)
    with pytest.raises(RuntimeError, match="declined|cancelled"):
        await gateway.act("browser_type", {"target": "e1", "text": "Demo", "submit": True})
    assert browser.nodes["e1"]["value"] == "Demo"
    assert [name for name, _ in browser.effects] == ["browser_type"]


async def test_stale_snapshot_and_bad_batch_do_not_write():
    gateway, browser, _ = await ready()
    browser.snapshot += '\n- button "New" [ref=e4]'
    with pytest.raises(RuntimeError, match="changed"):
        await gateway.act("browser_click", {"target": "e1"})
    await gateway.observe()
    with pytest.raises(RuntimeError):
        await gateway.act("browser_fill_form", {"fields": [
            {"target": "e1", "name": "Name", "type": "textbox", "value": "Demo"},
            {"target": "e99", "name": "Invalid", "type": "textbox", "value": "Bad"}]})
    assert not browser.effects


async def test_readback_mismatch_is_incomplete():
    browser = Browser()
    original = browser.call_result
    async def call(name, args=None):
        result = await original(name, args)
        if name == "browser_type": browser.nodes["e1"]["value"] = ""
        return result
    browser.call_result = call
    gateway, _, _ = await ready(browser)
    with pytest.raises(RuntimeError, match="read-back"):
        await gateway.act("browser_type", {"target": "e1", "text": "Demo"})
    assert not gateway.verified_steps


async def test_snapshot_catalog_exposes_only_a_whole_page_read():
    gateway, _, _ = await ready()
    assert gateway.tool_catalog()["browser_snapshot"]["properties"] == {}


async def test_batch_noneditable_target_is_rejected_before_any_write():
    gateway, browser, _ = await ready()
    with pytest.raises(RuntimeError):
        await gateway.act("browser_fill_form", {"fields":[
            {"target":"e1","name":"Name","type":"textbox","value":"Demo"},
            {"target":"e2","name":"Not a field","type":"textbox","value":"Wrong"}]})
    assert not browser.effects


@pytest.mark.parametrize("reference", ["ref=e1", "[ref=e1]"])
async def test_displayed_reference_notation_is_canonicalized_safely(reference):
    gateway, browser, _ = await ready()
    await gateway.act("browser_type", {"target":reference,"text":"Demo"})
    assert browser.effects[-1][1]["target"] == "e1"


async def test_tab_listing_is_retained_as_observed_evidence():
    gateway, _, _ = await ready()
    await gateway.act("browser_tabs", {"action":"list"})
    assert "0: Application" in "\n".join(gateway.verified_steps)


def test_public_urls_do_not_disclose_embedded_credentials():
    from agents.browser.connected_gateway import public_url
    assert public_url("https://username:private@example.org/path?secret=value#part") == "https://example.org/path"
