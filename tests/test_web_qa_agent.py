"""
Checks Web QA agent search and synthesis behavior.

Usage:
    python tests/test_web_qa_agent.py
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.web_qa.agent import WebQAAgent, ensure_sources_section, normalize_search_sources
from agents.web_qa.mcp_client import TavilyMcpClient
from agents.web_qa import mcp_client as mcp_client_module


async def test_web_qa_agent_builds_sourced_markdown_answer() -> None:
    observed = {}

    class _FakeSearchClient:
        async def search(self, query: str, max_results: int = 5, search_depth: str = "basic"):
            observed["query"] = query
            observed["max_results"] = max_results
            observed["search_depth"] = search_depth
            return {
                "results": [
                    {
                        "title": "Example Result",
                        "url": "https://example.com/result",
                        "content": "Fresh sourced fact from the web.",
                    }
                ]
            }

        async def close(self):
            observed["closed"] = True

    async def _fake_synthesizer(*, query: str, sources: list[dict[str, str]]) -> str:
        observed["synthesis_query"] = query
        observed["sources"] = sources
        return "Fresh sourced fact from the web.\n\nSources:\n- [Example Result](https://example.com/result)"

    agent = WebQAAgent(
        search_client=_FakeSearchClient(),
        synthesizer=_fake_synthesizer,
    )

    result = await agent.execute("latest example topic")

    assert result == {
        "success": True,
        "result": "Fresh sourced fact from the web.\n\nSources:\n- [Example Result](https://example.com/result)",
        "error": "",
        "complete": True,
    }, result
    assert observed["query"] == "latest example topic"
    assert observed["sources"] == [
        {
            "title": "Example Result",
            "url": "https://example.com/result",
            "content": "Fresh sourced fact from the web.",
        }
    ]
    assert observed["search_depth"] == "basic"
    assert observed["closed"] is True


async def test_web_qa_agent_accepts_tavily_text_payload() -> None:
    class _FakeSearchClient:
        async def search(self, query: str, max_results: int = 5, search_depth: str = "basic"):
            return {
                "raw_content": (
                    "Detailed Results:\n\n"
                    "Title: Bill Gates Net Worth | Example Finance\n"
                    "URL: https://example.com/bill-gates-net-worth\n"
                    "Content: Bill Gates has an estimated net worth of $105 billion.\n\n"
                    "Title: Billionaire Index\n"
                    "URL: https://example.com/billionaires/bill-gates\n"
                    "Content: The estimate changes with markets and donations."
                )
            }

        async def close(self):
            pass

    async def _fake_synthesizer(*, query: str, sources: list[dict[str, str]]) -> str:
        assert sources == [
            {
                "title": "Bill Gates Net Worth | Example Finance",
                "url": "https://example.com/bill-gates-net-worth",
                "content": "Bill Gates has an estimated net worth of $105 billion.",
            },
            {
                "title": "Billionaire Index",
                "url": "https://example.com/billionaires/bill-gates",
                "content": "The estimate changes with markets and donations.",
            },
        ]
        return "Bill Gates has an estimated net worth of $105 billion."

    agent = WebQAAgent(
        search_client=_FakeSearchClient(),
        synthesizer=_fake_synthesizer,
    )

    result = await agent.execute("what is the net worth of bill gates")

    assert result["success"] is True, result
    assert "Bill Gates has an estimated net worth of $105 billion." in result["result"]
    assert "- [Bill Gates Net Worth | Example Finance](https://example.com/bill-gates-net-worth)" in result["result"]


def test_normalize_search_sources_parses_tavily_text_safely() -> None:
    payload = {
        "raw_content": (
            "Detailed Results:\n\n"
            "title: Unsafe Result\n"
            "url: javascript:alert(1)\n"
            "content: This should not become a clickable source.\n\n"
            "TITLE: Safe Result\n"
            "URL: https://example.com/safe\n"
            "CONTENT: First line of sourced content.\n"
            "Second line of sourced content.\n"
        )
    }

    assert normalize_search_sources(payload, limit=5) == [
        {
            "title": "Safe Result",
            "url": "https://example.com/safe",
            "content": "First line of sourced content. Second line of sourced content.",
        }
    ]


def test_ensure_sources_section_requires_real_section_heading() -> None:
    sources = [
        {
            "title": "Example Result",
            "url": "https://example.com/result",
            "content": "Example sourced content.",
        }
    ]

    answer = "The answer mentions sources: casually, but has no citation section."
    formatted = ensure_sources_section(answer, sources)

    assert formatted.startswith(answer)
    assert "\n\nSources:\n- [Example Result](https://example.com/result)" in formatted


async def test_tavily_client_connect_times_out_and_clears_cached_state() -> None:
    class _SlowConnectClient(TavilyMcpClient):
        async def _open_session(self):
            await asyncio.sleep(0.05)
            return object(), AsyncExitStack()

    client = _SlowConnectClient(api_key="test-key", timeout_seconds=0.01)

    try:
        try:
            await client.connect()
        except asyncio.TimeoutError:
            pass
        else:
            raise AssertionError("Expected connect() to respect timeout_seconds")

        assert client._session is None
        assert client._exit_stack is None
    finally:
        await client.close()


async def test_tavily_client_opens_and_closes_session_in_same_task() -> None:
    events = {}

    class _TaskBoundContext:
        async def __aenter__(self):
            events["enter_task"] = asyncio.current_task()
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            events["exit_task"] = asyncio.current_task()
            if events["exit_task"] is not events["enter_task"]:
                raise RuntimeError("session closed in different task")
            return False

    class _TaskBoundClient(TavilyMcpClient):
        async def _open_session(self):
            exit_stack = AsyncExitStack()
            await exit_stack.enter_async_context(_TaskBoundContext())
            return object(), exit_stack

    caller_task = asyncio.current_task()
    client = _TaskBoundClient(api_key="test-key", timeout_seconds=1.0)

    await client.connect()
    await client.close()

    assert events["enter_task"] is caller_task
    assert events["exit_task"] is caller_task


def test_tavily_client_reads_key_from_project_env_file(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('TAVILY_API_KEY="file-key"\n', encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "os-env-key")
    monkeypatch.setattr(mcp_client_module, "_PROJECT_ENV_PATH", env_path)

    client = TavilyMcpClient()

    assert client.api_key == "file-key"


def test_tavily_client_ignores_os_env_without_project_env_key(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('GEMINI_API_KEY="test-gemini-key"\n', encoding="utf-8")
    monkeypatch.setenv("TAVILY_API_KEY", "os-env-key")
    monkeypatch.setattr(mcp_client_module, "_PROJECT_ENV_PATH", env_path)

    client = TavilyMcpClient()

    assert client.api_key == ""
    assert client.is_configured() is False


async def test_tavily_client_tool_listing_times_out() -> None:
    class _SlowListSession:
        async def list_tools(self):
            await asyncio.sleep(0.05)
            return []

    class _SlowListClient(TavilyMcpClient):
        async def connect(self):
            return _SlowListSession()

    client = _SlowListClient(api_key="test-key", timeout_seconds=0.01)

    try:
        try:
            await client._resolve_search_tool_name()
        except asyncio.TimeoutError:
            pass
        else:
            raise AssertionError("Expected tool listing to respect timeout_seconds")
    finally:
        await client.close()


async def run_checks() -> None:
    await test_web_qa_agent_builds_sourced_markdown_answer()
    await test_web_qa_agent_accepts_tavily_text_payload()
    test_normalize_search_sources_parses_tavily_text_safely()
    test_ensure_sources_section_requires_real_section_heading()
    await test_tavily_client_connect_times_out_and_clears_cached_state()
    await test_tavily_client_opens_and_closes_session_in_same_task()
    await test_tavily_client_tool_listing_times_out()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_web_qa_agent] All checks passed.")
