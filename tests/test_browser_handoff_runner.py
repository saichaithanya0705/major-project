"""Connected-runner regression tests for owned direct-link tabs."""

import json
import pytest
from pathlib import Path

from agents.browser.mcp_client import McpToolResult
from agents.browser.connected_runner import ConnectedBrowserRunner
from tests.test_connected_browser_gateway import Browser

class HandoffClient(Browser):
    extension = True

    def __init__(self) -> None:
        super().__init__()
        self.tabs = [("Welcome", "chrome-extension://playwright/connect.html")]
        self.tab_new_calls: list[dict] = []
        self.selected_index: int | None = None
        self.project_root = Path(__file__).resolve().parents[1]

    async def close(self) -> None:
        return None

    async def call_result(self, name, arguments=None):
        args = arguments or {}
        if name == "browser_tabs":
            action = args.get("action")
            if action == "new":
                self.tab_new_calls.append(dict(args))
                self.tabs.append(("Owned fixture", args["url"]))
                self.selected_index = len(self.tabs) - 1
                self.url = args["url"]
                self.tab_id = "jarvis-owned-tab"
            if action == "select":
                self.selected_index = args["index"]
                self.url = self.tabs[self.selected_index][1]
            lines = "\n".join(
                f"- {index}: {'(current) ' if index == self.selected_index else ''}[{title}]({url})"
                for index, (title, url) in enumerate(self.tabs)
            )
            return McpToolResult("### Open tabs\n" + lines)
        return await super().call_result(name, args)


async def _done(_system: str, _user: str) -> str:
    return json.dumps(
        {"done": True, "summary": "Inspected the selected page.", "evidence": ["Name"]}
    )


async def test_explicit_link_creates_one_owned_tab_before_planning() -> None:
    client = HandoffClient()

    result = await ConnectedBrowserRunner(client, decide=_done).execute(
        "@browser inspect https://example.test/form"
    )

    assert client.tab_new_calls == [{"action": "new", "url": "https://example.test/form"}]
    assert client.selected_index == 1
    assert result["success"] and result["complete"]


async def test_plain_link_creates_one_owned_tab_before_planning() -> None:
    client = HandoffClient()

    result = await ConnectedBrowserRunner(client, decide=_done).execute(
        "Open https://docs.google.com/spreadsheets/d/demo and count its rows"
    )

    assert client.tab_new_calls == [{"action": "new", "url": "https://docs.google.com/spreadsheets/d/demo"}]
    assert client.selected_index == 1
    assert result["success"] and result["complete"]


async def test_current_tab_request_never_creates_an_owned_tab() -> None:
    client = HandoffClient()

    result = await ConnectedBrowserRunner(client, decide=_done).execute(
        "@browser use the current tab and summarize it"
    )

    assert client.tab_new_calls == []
    assert result["result"]["awaiting_input"]


@pytest.mark.parametrize("task", [
    "@browser open the chatgpt website and give a prompt what si the news on arnab cycloen",
    "open the chatgpt website and draft a question",
    "@browser search for the latest cyclone news",
])
async def test_new_site_or_research_starts_without_an_existing_shared_page(task):
    client = HandoffClient()
    result = await ConnectedBrowserRunner(client, decide=_done).execute(task)
    assert client.tab_new_calls == [{"action": "new", "url": "about:blank"}]
    assert result["success"] and result["complete"]


async def test_named_site_can_navigate_and_enter_a_prompt_from_blank_start():
    client = HandoffClient()
    client.snapshot = '- textbox "Prompt" [ref=e1]'
    client.nodes["e1"] = {"tag": "textarea", "type": "textarea", "label": "Prompt", "value": "", "form": None}
    proposals = iter([
        {"tool": "browser_navigate", "arguments": {"url": "https://chatgpt.com/"}},
        {"tool": "browser_type", "arguments": {"target": "e1", "text": "What is the news on Arnab cyclone?", "submit": False}},
        {"done": True, "summary": "Opened ChatGPT and entered the draft.", "evidence": ["Prompt"]},
    ])
    async def decide(_system, _user):
        return json.dumps(next(proposals))
    result = await ConnectedBrowserRunner(client, decide=decide).execute(
        "@browser open the chatgpt website and give a prompt what si the news on arnab cycloen"
    )
    assert result["success"] and result["complete"]
    assert client.nodes["e1"]["value"] == "What is the news on Arnab cyclone?"
    assert [name for name, _ in client.effects] == ["browser_navigate", "browser_type"]
