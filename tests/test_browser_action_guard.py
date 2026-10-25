"""
Risky browser actions need the user's approval; the browser model chain works without Gemini.
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import agents.browser.agent as browser_agent_module  # noqa: E402
from agents.browser.action_guard import ActionGuard, declined_message, guarded_tools_class  # noqa: E402
from agents.browser.agent import BrowserAgent  # noqa: E402
from core.confirmations import ConfirmationBroker  # noqa: E402


class _Node:
    def __init__(self, tag: str, text: str = "", **attributes: str) -> None:
        self.tag_name = tag
        self.attributes = attributes
        self._text = text

    def get_all_children_text(self, max_depth: int = -1) -> str:
        return self._text


class _Session:
    def __init__(self, nodes: dict[int, _Node], url: str = "https://www.amazon.in/checkout") -> None:
        self.nodes = nodes
        self.url = url

    async def get_current_page_url(self) -> str:
        return self.url

    async def get_element_by_index(self, index: int):
        return self.nodes.get(index)

    async def get_dom_element_at_coordinates(self, x: int, y: int):
        return self.nodes.get(x)


def _guard(answer: bool = True):
    asked: list[str] = []

    async def _confirm(description: str) -> bool:
        asked.append(description)
        return answer

    return ActionGuard(confirm=_confirm), asked


SESSION = _Session(
    {
        1: _Node("button", "Place your order"),
        2: _Node("button", "Add to cart"),
        3: _Node("input", "", type="submit", value="Continue"),
        4: _Node("input", "", type="password", name="password", placeholder="Password"),
        5: _Node("input", "", type="search", name="q", placeholder="Search Amazon"),
        6: _Node("input", "", type="text", name="full_name", placeholder="Full name"),
        7: _Node("input", "", type="text", name="cardnumber", **{"aria-label": "Card number"}),
        8: _Node("a", "Sign up for free"),
    }
)


@pytest.mark.parametrize(
    ("action", "params", "expected"),
    [
        ("click", {"index": 1}, "click \u201cPlace your order\u201d on www.amazon.in"),
        ("click", {"index": 3}, "click \u201cContinue\u201d on www.amazon.in"),
        ("click", {"coordinate_x": 8, "coordinate_y": 0}, "click \u201cSign up for free\u201d on www.amazon.in"),
        ("input", {"index": 4, "text": "hunter2"}, "type into \u201cPassword\u201d on www.amazon.in"),
        ("input", {"index": 7, "text": "4111"}, "type into \u201cCard number\u201d on www.amazon.in"),
        ("upload_file", {"index": 2, "path": "C:\\Users\\me\\resume.pdf"}, "upload C:\\Users\\me\\resume.pdf to www.amazon.in"),
        ("evaluate", {"code": "document.forms[0].submit()"}, "run custom JavaScript on www.amazon.in"),
        ("click", {"index": 2}, None),
        ("click", {"index": 99}, None),
        ("navigate", {"url": "https://example.com"}, None),
        ("input", {"index": 5, "text": "laptop"}, None),
    ],
)
async def test_risky_action_detection(action, params, expected) -> None:
    guard, _ = _guard()
    assert await guard.risky_action(action, params, SESSION) == expected


async def test_enter_is_gated_only_after_typing_into_a_form() -> None:
    guard, _ = _guard()
    await guard.risky_action("input", {"index": 5, "text": "laptop"}, SESSION)
    assert await guard.risky_action("send_keys", {"keys": "Enter"}, SESSION) is None

    await guard.risky_action("input", {"index": 6, "text": "Sai"}, SESSION)
    assert await guard.risky_action("send_keys", {"keys": "Enter"}, SESSION) == "press Enter to submit the form on www.amazon.in"
    assert await guard.risky_action("send_keys", {"keys": "Tab"}, SESSION) is None


async def test_allow_asks_only_for_risky_actions() -> None:
    approving, asked = _guard(answer=True)
    assert await approving.allow("click", {"index": 2}, SESSION) is None
    assert asked == []
    assert await approving.allow("click", {"index": 1}, SESSION) is None
    assert asked == ["click \u201cPlace your order\u201d on www.amazon.in"]
    assert approving.approved_actions == asked

    declining, _ = _guard(answer=False)
    assert await declining.allow("click", {"index": 1}, SESSION) == "click \u201cPlace your order\u201d on www.amazon.in"


class _Action:
    def __init__(self, **actions) -> None:
        self._actions = actions

    def model_dump(self, exclude_unset: bool = False) -> dict:
        return dict(self._actions)


class _BaseTools:
    def __init__(self) -> None:
        self.ran: list[dict] = []

    async def act(self, action, browser_session, *args, **kwargs):
        self.ran.append(action.model_dump())
        return "ran"


async def test_guarded_tools_block_declined_actions_and_run_others() -> None:
    guard, _ = _guard(answer=False)
    tools = guarded_tools_class(_BaseTools, SimpleNamespace, guard)()

    assert await tools.act(_Action(click={"index": 2}), SESSION) == "ran"
    declined = await tools.act(_Action(click={"index": 1}), SESSION)

    assert tools.ran == [{"click": {"index": 2}}]
    assert declined.is_done is True and declined.success is False
    assert declined.extracted_content == declined_message("click \u201cPlace your order\u201d on www.amazon.in")
    assert "do not retry" in declined.extracted_content


def test_guard_plugs_into_real_browser_use_tools() -> None:
    from browser_use.agent.views import ActionResult
    from browser_use.tools.service import Tools

    guard, _ = _guard()
    tools = guarded_tools_class(Tools, ActionResult, guard)(exclude_actions=["write_file", "replace_file"])

    assert isinstance(tools, Tools)
    assert {"click", "input", "send_keys", "upload_file", "evaluate"} <= set(tools.registry.registry.actions)
    declined = ActionResult(is_done=True, success=False, extracted_content="x", long_term_memory="x")
    assert declined.is_done and declined.success is False


# Confirmation broker --------------------------------------------------------------------


async def test_broker_yes_approves_and_other_replies_decline(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CONFIRM_RISKY_ACTIONS", raising=False)
    shown: list[str] = []

    async def _notify(text: str) -> None:
        shown.append(text)

    broker = ConfirmationBroker(notify=_notify, timeout_seconds=5)
    assert broker.answer("yes") is False  # nothing pending

    for reply, expected in (("Yes!", True), ("go ahead", True), ("no", False), ("wait, what is it buying?", False)):
        pending = asyncio.create_task(broker.request("click \u201cPay\u201d on bank.example"))
        while not broker.has_pending:
            await asyncio.sleep(0)
        assert broker.answer(reply) is True
        assert await pending is expected, reply
        assert not broker.has_pending

    assert "**Confirm:** Jarvis wants to click \u201cPay\u201d on bank.example." in shown[0]


async def test_broker_times_out_to_no_and_declines_concurrent_requests(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CONFIRM_RISKY_ACTIONS", raising=False)
    shown: list[str] = []

    async def _notify(text: str) -> None:
        shown.append(text)

    broker = ConfirmationBroker(notify=_notify, timeout_seconds=0.05)
    first = asyncio.create_task(broker.request("pay"))
    while not broker.has_pending:
        await asyncio.sleep(0)
    assert await broker.request("also pay") is False
    assert await first is False
    assert shown[-1] == "No answer, so I cancelled that action."


async def test_broker_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONFIRM_RISKY_ACTIONS", "off")

    async def _notify(text: str) -> None:
        raise AssertionError("should not ask")

    assert await ConfirmationBroker(notify=_notify).request("pay") is True


# Browser model chain -----------------------------------------------------------------------


class _Boundary:
    def import_google_llm_class(self):
        return lambda **kwargs: ("gemini", kwargs)

    def import_openrouter_llm_class(self):
        return lambda **kwargs: ("openrouter", kwargs)

    def import_ollama_llm_class(self):
        return lambda **kwargs: ("ollama", kwargs)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("GEMINI_API_KEY", "JARVIS_BROWSER_LLM_ORDER", "JARVIS_BROWSER_OLLAMA_MODEL", "OLLAMA_ROUTER_MODEL", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(browser_agent_module, "get_openrouter_api_key", lambda: "")
    monkeypatch.setattr(browser_agent_module, "get_openrouter_models", lambda purpose: ["or/model-a"])
    return monkeypatch


def test_browser_models_without_cloud_keys_use_local_ollama(clean_env) -> None:
    candidates = BrowserAgent(model_name="gemini-x")._browser_llm_candidates(_Boundary())
    assert [label for label, _ in candidates] == ["ollama nemotron-3.5-bolt"]
    assert candidates[0][1]() == ("ollama", {"model": "nemotron-3.5-bolt", "host": "http://127.0.0.1:11434"})


def test_browser_model_order_with_keys(clean_env) -> None:
    clean_env.setenv("GEMINI_API_KEY", "g")
    clean_env.setattr(browser_agent_module, "get_openrouter_api_key", lambda: "o")
    agent = BrowserAgent(model_name="gemini-x")
    assert [label for label, _ in agent._browser_llm_candidates(_Boundary())] == [
        "gemini", "openrouter or/model-a", "ollama nemotron-3.5-bolt",
    ]
    clean_env.setenv("JARVIS_BROWSER_LLM_ORDER", "ollama,gemini")
    assert [label for label, _ in agent._browser_llm_candidates(_Boundary())] == ["ollama nemotron-3.5-bolt", "gemini"]


async def test_browser_use_tries_next_model_only_for_quota_or_unavailable(clean_env) -> None:
    agent = BrowserAgent(model_name="gemini-x")
    tried: list[str] = []

    def _candidates(errors):
        def make(label, error):
            def factory():
                tried.append(label)
                if error:
                    raise RuntimeError(error)
                return label
            return factory
        return lambda boundary: [(label, make(label, error)) for label, error in errors]

    async def _session():
        return object()

    agent._get_or_create_browser_use_session = _session
    original = (BrowserAgent._ensure_external_browser_use_resolution, BrowserAgent._browser_use_boundary)
    BrowserAgent._ensure_external_browser_use_resolution = classmethod(lambda cls: None)
    BrowserAgent._browser_use_boundary = SimpleNamespace(create_agent=lambda **kwargs: (_ for _ in ()).throw(AssertionError("not reached")))
    try:
        agent._browser_llm_candidates = _candidates([("gemini", "400 bad request"), ("ollama", None)])
        result = await agent._execute_with_browser_use("fill the form", close_when_done=False)
        assert result == {"success": False, "result": None, "error": "400 bad request"}
        assert tried == ["gemini"]

        tried.clear()
        agent._browser_llm_candidates = _candidates([("gemini", "429 RESOURCE_EXHAUSTED quota"), ("ollama", "connection refused")])
        result = await agent._execute_with_browser_use("fill the form", close_when_done=False)
        assert tried == ["gemini", "ollama"]
        assert result["error"] == "connection refused"

        agent._browser_llm_candidates = lambda boundary: []
        result = await agent._execute_with_browser_use("fill the form", close_when_done=False)
        assert "No browser model is configured" in result["error"]
    finally:
        BrowserAgent._ensure_external_browser_use_resolution, BrowserAgent._browser_use_boundary = original
