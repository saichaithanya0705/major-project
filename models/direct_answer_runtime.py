"""Direct-answer and source-grounded answer runtime for GeminiModel objects."""

from __future__ import annotations

import asyncio
from typing import Any

from models.model_status import set_model_label
from models.text_normalization import clean_text as _clean_text
from models.text_normalization import (
    format_direct_response_text as _format_direct_response_text,
)


async def _generate_text(
    model: Any,
    *,
    model_name: str,
    prompt: str,
    timeout_seconds: float,
) -> str:
    response = await asyncio.wait_for(
        model.client.aio.models.generate_content(
            model=model_name,
            contents=[prompt],
            config=model.direct_answer_config,
        ),
        timeout=timeout_seconds,
    )
    text = _format_direct_response_text(getattr(response, "text", ""), "", max_len=None)
    if not text:
        raise RuntimeError("Answer model returned empty text.")
    return text


async def _try_backup_text(
    model: Any,
    *,
    label: str,
    prompt: str,
    primary_model: str,
    timeout_seconds: float,
) -> str | None:
    if not (
        model.gemini_backup_model
        and model.gemini_backup_model != primary_model
    ):
        return None

    try:
        print(
            f"[{label}] Primary model unavailable; retrying with backup "
            f"{model.gemini_backup_model}"
        )
        return await _generate_text(
            model,
            model_name=model.gemini_backup_model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
        )
    except Exception as backup_exc:
        print(f"[{label}] Gemini backup failed: {backup_exc}")
        return None


async def answer_direct_request(
    model: Any,
    *,
    user_prompt: str,
    history_block: str = "",
) -> str:
    """Answer general Q&A directly without screen capture or agent routing."""
    direct_prompt = (
        "You are JARVIS in direct Q&A mode. Answer the user's factual or conversational "
        "question directly in clean Markdown for chat. Use headings, bullets, or tables when "
        "they make the answer easier to scan. Do not inspect the screen, use browser automation, "
        "or claim to have live/current data unless the user provided it. Keep the answer useful "
        "and structured, but avoid unnecessary length. Do not use raw HTML.\n"
        f"{history_block}\n"
        f"# User's Latest Request:\n{user_prompt}"
    )

    try:
        await set_model_label(
            f"{model.jarvis_model} (Direct)",
            context="direct_qa",
        )

        return await _generate_text(
            model,
            model_name=model.jarvis_model,
            prompt=direct_prompt,
            timeout_seconds=45,
        )
    except Exception as exc:
        if model._is_gemini_temporary_error(exc):
            backup_text = await _try_backup_text(
                model,
                label="DirectQA",
                prompt=direct_prompt,
                primary_model=model.jarvis_model,
                timeout_seconds=45,
            )
            if backup_text:
                return backup_text

        fallback_text = await model._try_openrouter_text_fallback(
            label="DirectQA",
            system_prompt=(
                "You are JARVIS in direct Q&A mode. Answer factual or conversational "
                "questions directly in plain text. Do not use screen context."
            ),
            user_prompt=user_prompt,
            temperature=0.4,
            max_tokens=1400,
            purpose="text",
        )
        if fallback_text:
            return _format_direct_response_text(fallback_text, "", max_len=None)
        raise


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
        "You are JARVIS in source-grounded web Q&A mode. Answer the user's question "
        "using only the provided Tavily web search sources. If the sources disagree or "
        "do not contain enough evidence, say that clearly. Keep the answer concise, "
        "use clean Markdown, and do not invent facts beyond the sources.\n\n"
        f"# User's Question\n{user_prompt}\n\n"
        "# Tavily Sources\n"
        + "\n\n".join(source_lines)
    )

    try:
        await set_model_label(
            f"{model.jarvis_model} (Web QA)",
            context="web_qa",
        )

        return await _generate_text(
            model,
            model_name=model.jarvis_model,
            prompt=web_prompt,
            timeout_seconds=45,
        )
    except Exception as exc:
        if model._is_gemini_temporary_error(exc):
            backup_text = await _try_backup_text(
                model,
                label="WebQA",
                prompt=web_prompt,
                primary_model=model.jarvis_model,
                timeout_seconds=45,
            )
            if backup_text:
                return backup_text

        fallback_text = await model._try_openrouter_text_fallback(
            label="WebQA",
            system_prompt=(
                "You are JARVIS in source-grounded web Q&A mode. Answer using only "
                "the provided search source snippets. Use clean Markdown."
            ),
            user_prompt=web_prompt,
            temperature=0.2,
            max_tokens=1400,
            purpose="text",
        )
        if fallback_text:
            return _format_direct_response_text(fallback_text, "", max_len=None)
        raise
