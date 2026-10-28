from __future__ import annotations

import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from agents.direct_chat.mcp_client import TavilyMcpClient, TavilyMcpConfigurationError
from models.brain import generate_brain_reply, wants_strong_model
from models.model_status import set_model_label
from models.routing_question_policy import (
    is_source_grounded_qa_request as _should_use_web_search,
)
from models.text_normalization import clean_text as _clean_text
from models.text_normalization import (
    format_direct_response_text as _format_direct_response_text,
)

SourceList = list[dict[str, str]]
Synthesizer = Callable[..., Awaitable[str]]
SearchPredicate = Callable[[str], bool]
_TEXT_RESULT_LABEL_RE = re.compile(r"^\s*(title|url|content):\s*(.*)$", re.IGNORECASE)
_SOURCES_HEADING_RE = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?sources\s*:?\s*$")


def should_use_web_search(user_prompt: str) -> bool:
    return _should_use_web_search(user_prompt)


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _source_value(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _source_from_mapping(item: dict[str, Any]) -> dict[str, str] | None:
    url = _source_value(item, "url", "link", "href")
    if not _is_http_url(url):
        return None
    title = _source_value(item, "title", "name") or url
    content = _source_value(item, "content", "snippet", "description", "raw_content")
    return {
        "title": title,
        "url": url,
        "content": content,
    }


def _normalize_text_search_sources(text: str, limit: int = 5) -> SourceList:
    if not text or limit <= 0:
        return []

    sources: SourceList = []
    current: dict[str, str] = {}
    content_parts: list[str] = []
    reading_content = False

    def commit_current() -> None:
        nonlocal current, content_parts, reading_content
        if len(sources) >= limit:
            return
        source = _source_from_mapping(
            {
                "title": current.get("title", ""),
                "url": current.get("url", ""),
                "content": " ".join(content_parts).strip(),
            }
        )
        if source is not None:
            sources.append(source)
        current = {}
        content_parts = []
        reading_content = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _TEXT_RESULT_LABEL_RE.match(line)
        if match:
            label = match.group(1).lower()
            value = match.group(2).strip()
            if label == "title":
                if current:
                    commit_current()
                current = {"title": value}
                content_parts = []
                reading_content = False
            elif current and label == "url":
                current["url"] = value
                reading_content = False
            elif current and label == "content":
                content_parts = [value] if value else []
                reading_content = True
            continue

        if current and reading_content:
            content_parts.append(line)

    if current:
        commit_current()

    return sources


def normalize_search_sources(payload: Any, limit: int = 5) -> SourceList:
    if isinstance(payload, dict):
        raw_results = payload.get("results")
        if raw_results is None:
            raw_results = payload.get("data")
        if raw_results is None and payload.get("url"):
            raw_results = [payload]
        if raw_results is None:
            text_sources = _normalize_text_search_sources(
                _source_value(payload, "raw_content", "content", "text"),
                limit=limit,
            )
            if text_sources:
                return text_sources
    elif isinstance(payload, list):
        raw_results = payload
    elif isinstance(payload, str):
        return _normalize_text_search_sources(payload, limit=limit)
    else:
        raw_results = []

    if not isinstance(raw_results, list):
        return []

    sources: SourceList = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        source = _source_from_mapping(item)
        if source is None:
            continue
        sources.append(source)
        if len(sources) >= limit:
            break
    return sources


def build_sources_markdown(sources: SourceList) -> str:
    lines = ["Sources:"]
    for source in sources:
        title = source.get("title") or source.get("url") or "Source"
        url = source.get("url") or ""
        if url:
            lines.append(f"- [{title}]({url})")
        else:
            lines.append(f"- {title}")
    return "\n".join(lines)


def ensure_sources_section(answer: str, sources: SourceList) -> str:
    formatted = _format_direct_response_text(answer, "", max_len=None)
    if not sources:
        return formatted
    if _SOURCES_HEADING_RE.search(formatted):
        return formatted
    if not formatted:
        return build_fallback_source_answer(sources)
    return f"{formatted}\n\n{build_sources_markdown(sources)}"


def build_fallback_source_answer(sources: SourceList) -> str:
    if not sources:
        return "I could not find useful Tavily web results for that question."

    bullets = []
    for source in sources[:3]:
        content = source.get("content", "").strip()
        title = source.get("title") or source.get("url") or "Source"
        if content:
            bullets.append(f"- **{title}:** {content}")
        else:
            bullets.append(f"- **{title}:** See source for details.")
    return "\n".join(bullets) + "\n\n" + build_sources_markdown(sources)


def _source_lines(sources: SourceList) -> list[str]:
    source_lines = []
    for index, source in enumerate(sources[:8], start=1):
        title = _clean_text(source.get("title"), f"Source {index}", max_len=160)
        url = _clean_text(source.get("url"), "", max_len=260)
        content = _format_direct_response_text(source.get("content"), "", max_len=1000)
        source_lines.append(
            f"[{index}] {title}\nURL: {url}\nSnippet: {content or 'No snippet provided.'}"
        )
    return source_lines


class DirectChatAgent:
    def __init__(
        self,
        model: Any | None = None,
        *,
        history_block: str = "",
        search_client: Any | None = None,
        synthesizer: Synthesizer | None = None,
        search_predicate: SearchPredicate = should_use_web_search,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> None:
        self.model = model
        self.history_block = history_block
        self.search_client = search_client or TavilyMcpClient()
        self.synthesizer = synthesizer
        self.search_predicate = search_predicate
        self.max_results = int(max_results)
        self.search_depth = search_depth

    async def _close_search_client(self) -> None:
        close = getattr(self.search_client, "close", None)
        if callable(close):
            maybe_result = close()
            if hasattr(maybe_result, "__await__"):
                await maybe_result

    async def _synthesize(
        self,
        *,
        user_prompt: str,
        sources: SourceList,
    ) -> str:
        if self.synthesizer is not None:
            return await self.synthesizer(
                user_prompt=user_prompt,
                history_block=self.history_block,
                sources=sources,
                web_search_used=bool(sources),
            )

        if self.model is None:
            return build_fallback_source_answer(sources) if sources else ""

        prompt = self._build_model_prompt(user_prompt=user_prompt, sources=sources)
        context = "direct_chat:web_search" if sources else "direct_chat"
        reply = await generate_brain_reply(
            self.model,
            system=self._answer_system_prompt(sources=sources),
            user=prompt,
            temperature=0.2 if sources else 0.4,
            max_tokens=1400 if sources else 1800,
            force_escalation=wants_strong_model(user_prompt),
            allow_self_escalation=not bool(sources),
        )
        await set_model_label(f"{reply.label} (Direct Agent)", context=context)
        return _format_direct_response_text(reply.text, "", max_len=None)

    def _build_model_prompt(self, *, user_prompt: str, sources: SourceList) -> str:
        if sources:
            return (
                "You are JARVIS in direct chat agent mode with Tavily web search results. "
                "Answer the user's question using only the provided web sources. If the "
                "sources disagree or do not contain enough evidence, say that clearly. "
                "Use clean Markdown and do not invent facts beyond the sources.\n\n"
                f"# User's Question\n{user_prompt}\n\n"
                "# Tavily Sources\n"
                + "\n\n".join(_source_lines(sources))
            )

        return (
            "You are JARVIS in direct chat agent mode. Answer the user's factual or "
            "conversational question directly in clean Markdown for chat. Use headings, "
            "bullets, or tables when they make the answer easier to scan. Do not inspect "
            "the screen, use browser automation, or claim to have live/current data unless "
            "the user provided it. Keep the answer useful and structured, but avoid "
            "unnecessary length. Do not use raw HTML.\n"
            f"{self.history_block}\n"
            f"# User's Latest Request:\n{user_prompt}"
        )

    @staticmethod
    def _answer_system_prompt(*, sources: SourceList) -> str:
        if sources:
            return (
                "You are JARVIS in direct chat agent mode. Answer using only the "
                "provided Tavily source snippets. Use clean Markdown."
            )
        return (
            "You are JARVIS in direct chat agent mode. Answer factual or conversational "
            "questions directly in plain text. Do not use screen context."
        )

    async def _search(self, query: str) -> SourceList:
        payload = await self.search_client.search(
            query,
            max_results=self.max_results,
            search_depth=self.search_depth,
        )
        return normalize_search_sources(payload, limit=self.max_results)

    async def _answer_payload(
        self,
        task: str,
        *,
        sources: SourceList | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        user_prompt = _format_direct_response_text(task, "", max_len=None)
        if not user_prompt:
            raise ValueError("Direct chat requires a user prompt.")

        resolved_sources: SourceList = list(sources or [])
        tool_calls: list[dict[str, Any]] = []
        try:
            if sources is None and self.search_predicate(user_prompt):
                query = _format_direct_response_text(user_prompt, "", max_len=420)
                try:
                    resolved_sources = await self._search(query)
                except TavilyMcpConfigurationError as exc:
                    return _format_direct_response_text(str(exc), "", max_len=None), tool_calls
                tool_calls.append(
                    {
                        "name": "tavily_search",
                        "arguments": {
                            "query": query,
                            "max_results": self.max_results,
                            "search_depth": self.search_depth,
                        },
                    }
                )
                if not resolved_sources:
                    return "I could not find useful Tavily web results for that question.", tool_calls

            answer = await self._synthesize(user_prompt=user_prompt, sources=resolved_sources)
            result = (
                ensure_sources_section(answer, resolved_sources)
                if resolved_sources
                else _format_direct_response_text(answer, "", max_len=None)
            )
            if not result:
                result = "I could not produce a direct answer for that request."
            return result, tool_calls
        finally:
            await self._close_search_client()

    async def answer(
        self,
        task: str,
        *,
        sources: SourceList | None = None,
    ) -> str:
        result, _tool_calls = await self._answer_payload(task, sources=sources)
        return result

    async def execute(self, task: str) -> dict[str, Any]:
        try:
            result, tool_calls = await self._answer_payload(task)
            payload: dict[str, Any] = {
                "success": True,
                "result": result,
                "error": "",
                "complete": True,
            }
            if tool_calls:
                payload["tool_calls"] = tool_calls
            return payload
        except Exception as exc:
            return {
                "success": False,
                "result": "",
                "error": str(exc) or "Direct chat agent failed.",
                "complete": True,
            }


__all__ = [
    "DirectChatAgent",
    "SourceList",
    "build_fallback_source_answer",
    "build_sources_markdown",
    "ensure_sources_section",
    "normalize_search_sources",
    "should_use_web_search",
]
