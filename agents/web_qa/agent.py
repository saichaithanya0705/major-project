from __future__ import annotations

import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from agents.web_qa.mcp_client import TavilyMcpClient
from models.routing_policy import _format_direct_response_text

SourceList = list[dict[str, str]]
Synthesizer = Callable[..., Awaitable[str]]
_TEXT_RESULT_LABEL_RE = re.compile(r"^\s*(title|url|content):\s*(.*)$", re.IGNORECASE)
_SOURCES_HEADING_RE = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?sources\s*:?\s*$")


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
        return build_fallback_answer(sources)
    return f"{formatted}\n\n{build_sources_markdown(sources)}"


def build_fallback_answer(sources: SourceList) -> str:
    if not sources:
        return "I could not find useful web sources for that question."

    bullets = []
    for source in sources[:3]:
        content = source.get("content", "").strip()
        title = source.get("title") or source.get("url") or "Source"
        if content:
            bullets.append(f"- **{title}:** {content}")
        else:
            bullets.append(f"- **{title}:** See source for details.")
    return "\n".join(bullets) + "\n\n" + build_sources_markdown(sources)


class WebQAAgent:
    def __init__(
        self,
        model: Any | None = None,
        *,
        search_client: Any | None = None,
        synthesizer: Synthesizer | None = None,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> None:
        self.model = model
        self.search_client = search_client or TavilyMcpClient()
        self.synthesizer = synthesizer
        self.max_results = int(max_results)
        self.search_depth = search_depth

    async def _synthesize(self, *, query: str, sources: SourceList) -> str:
        if self.synthesizer is not None:
            return await self.synthesizer(query=query, sources=sources)

        if self.model is not None and hasattr(self.model, "answer_web_qa_request"):
            return await self.model.answer_web_qa_request(
                user_prompt=query,
                sources=sources,
            )

        return build_fallback_answer(sources)

    async def execute(self, task: str) -> dict[str, Any]:
        query = _format_direct_response_text(task, "", max_len=420)
        if not query:
            return {
                "success": False,
                "result": "",
                "error": "Web QA requires a question to search for.",
                "complete": True,
            }

        try:
            payload = await self.search_client.search(
                query,
                max_results=self.max_results,
                search_depth=self.search_depth,
            )
            sources = normalize_search_sources(payload, limit=self.max_results)
            if not sources:
                return {
                    "success": False,
                    "result": "",
                    "error": "No useful Tavily web results were found for that question.",
                    "complete": True,
                }

            answer = await self._synthesize(query=query, sources=sources)
            return {
                "success": True,
                "result": ensure_sources_section(answer, sources),
                "error": "",
                "complete": True,
            }
        except Exception as exc:
            return {
                "success": False,
                "result": "",
                "error": str(exc) or "Web QA failed.",
                "complete": True,
            }
        finally:
            close = getattr(self.search_client, "close", None)
            if callable(close):
                maybe_result = close()
                if hasattr(maybe_result, "__await__"):
                    await maybe_result
