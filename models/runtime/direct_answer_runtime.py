"""Canonical direct-chat runtime delegated to DirectChatAgent."""

from __future__ import annotations

from typing import Any

from agents.direct_chat.agent import DirectChatAgent


async def answer_direct_request(
    model: Any,
    *,
    user_prompt: str,
    history_block: str = "",
) -> str:
    """Answer normal chat requests through the canonical direct chat agent."""
    agent = DirectChatAgent(
        model=model,
        history_block=history_block,
    )
    return await agent.answer(user_prompt)
