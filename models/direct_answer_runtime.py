"""Direct-answer and source-grounded answer runtime for GeminiModel objects."""

from __future__ import annotations

from typing import Any

from models.brain import generate_brain_reply, wants_strong_model
from models.model_status import set_model_label
from models.text_normalization import clean_text as _clean_text
from models.text_normalization import (
    format_direct_response_text as _format_direct_response_text,
)


_DIRECT_SYSTEM_PROMPT = (
    "You are JARVIS in direct Q&A mode. Answer the user's factual or conversational "
    "question directly in clean Markdown for chat. Use headings, bullets, or tables when "
    "they make the answer easier to scan. Do not inspect the screen, use browser automation, "
    "or claim to have live/current data unless the user provided it. Keep the answer useful "
    "and structured, but avoid unnecessary length. Do not use raw HTML."
)

_WEB_QA_SYSTEM_PROMPT = (
    "You are JARVIS in source-grounded web Q&A mode. Answer the user's question "
    "using only the provided Tavily web search sources. If the sources disagree or "
    "do not contain enough evidence, say that clearly. Keep the answer concise, "
    "use clean Markdown, and do not invent facts beyond the sources."
)


async def answer_direct_request(
    model: Any,
    *,
    user_prompt: str,
    history_block: str = "",
) -> str:
    """Answer general Q&A directly without screen capture or agent routing."""
    reply = await generate_brain_reply(
        model,
        system=_DIRECT_SYSTEM_PROMPT,
        user=f"{history_block}\n# User's Latest Request:\n{user_prompt}".strip(),
        temperature=0.4,
        max_tokens=1800,
        force_escalation=wants_strong_model(user_prompt),
    )
    await set_model_label(f"{reply.label} (Direct)", context="direct_qa")
    return _format_direct_response_text(reply.text, "", max_len=None)


async def answer_web_qa_request(
    model: Any,
    *,
    user_prompt: str,
    sources: list[dict[str, str]],
) -> str:
    """Synthesize a source-grounded web answer from Tavily search results."""
    source_lines = []
    for index, source in enumerate(sources[:8], start=1):
        title = _clean_text(source.get("title"), f"Source {index}", max_len=160)
        url = _clean_text(source.get("url"), "", max_len=260)
        content = _format_direct_response_text(source.get("content"), "", max_len=1000)
        source_lines.append(
            f"[{index}] {title}\nURL: {url}\nSnippet: {content or 'No snippet provided.'}"
        )

    if not source_lines:
        return "I could not find useful web sources for that question."

    web_prompt = (
        f"# User's Question\n{user_prompt}\n\n"
        "# Tavily Sources\n"
        + "\n\n".join(source_lines)
    )
    # Summarizing provided sources is within a small model's reach, so only
    # failures (not self-assessed difficulty) escalate here.
    reply = await generate_brain_reply(
        model,
        system=_WEB_QA_SYSTEM_PROMPT,
        user=web_prompt,
        temperature=0.2,
        max_tokens=1400,
        force_escalation=wants_strong_model(user_prompt),
        allow_self_escalation=False,
    )
    await set_model_label(f"{reply.label} (Web QA)", context="web_qa")
    return _format_direct_response_text(reply.text, "", max_len=None)
