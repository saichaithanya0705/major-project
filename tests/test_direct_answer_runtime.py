"""Checks that the direct-answer runtime delegates to the canonical direct chat agent."""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

import models.runtime.direct_answer_runtime as direct_answer_runtime


def test_answer_direct_request_uses_direct_chat_agent() -> None:
    observed: dict[str, object] = {}
    sentinel_model = object()

    class _FakeDirectChatAgent:
        def __init__(self, model=None, *, history_block: str = "", **_kwargs) -> None:
            observed["model"] = model
            observed["history_block"] = history_block

        async def answer(self, task: str, *, sources=None) -> str:
            observed["task"] = task
            observed["sources"] = sources
            return "delegated direct chat answer"

    original_agent = direct_answer_runtime.DirectChatAgent
    direct_answer_runtime.DirectChatAgent = _FakeDirectChatAgent
    try:
        result = asyncio.run(
            direct_answer_runtime.answer_direct_request(
                sentinel_model,
                user_prompt="What is the latest example update?",
                history_block="history block",
            )
        )
    finally:
        direct_answer_runtime.DirectChatAgent = original_agent

    assert result == "delegated direct chat answer"
    assert observed == {
        "model": sentinel_model,
        "history_block": "history block",
        "task": "What is the latest example update?",
        "sources": None,
    }
