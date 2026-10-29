import json

from agents.browser.mcp_client import McpToolResult
from tests.test_connected_browser_gateway import Browser


def runner_class():
    from agents.browser.connected_runner import ConnectedBrowserRunner
    return ConnectedBrowserRunner


class HandoffClient(Browser):
    extension = True

    def __init__(self, root):
        super().__init__()
        self.project_root = root
        self.created_urls = []
        self.selected = False

    async def close(self):
        pass

    async def call_result(self, name, arguments=None):
        args = arguments or {}
        if name == "browser_tabs":
            action = args.get("action")
            if action == "list":
                current = "(current) " if self.selected else ""
                return McpToolResult(f"### Open tabs\n- 0: {current}[Google Search]({self.url})")
            if action == "new":
                self.created_urls.append(args["url"])
                self.url = args["url"]
                self.selected = True
                self.tab_id = "jarvis-owned-tab"
                return McpToolResult("### Result\nnew tab")
            if action == "select":
                self.selected = True
                return McpToolResult("### Result\nselected")
        if name not in {"browser_run_code_unsafe"}:
            assert self.selected, "A private page must only be read after JARVIS opens or selects it."
        return await super().call_result(name, args)


async def test_direct_url_opens_a_jarvis_owned_tab_before_the_agent_reads_it(tmp_path):
    async def decide(_system, _prompt):
        return json.dumps({"done": True, "summary": "Read the new tab.", "evidence": ["Name"]})

    client = HandoffClient(tmp_path)
    result = await runner_class()(client, decide=decide).execute(
        "Open https://docs.google.com/spreadsheets/d/demo and count its rows"
    )

    assert result["success"] and result["complete"]
    assert client.created_urls == ["https://docs.google.com/spreadsheets/d/demo"]
    assert client.selected
