"""Parse explicit user-authored browser handoffs without inspecting page text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


BrowserTabPolicy = Literal["owned_url", "current", "selected_or_ask"]


@dataclass(frozen=True, slots=True)
class BrowserHandoffIntent:
    """A leading ``@browser`` request and the tab policy it explicitly permits."""

    task: str
    direct_url: str | None
    tab_policy: BrowserTabPolicy


_HANDOFF = re.compile(r"^\s*@browser\b\s*(.+?)\s*$", re.IGNORECASE | re.DOTALL)
_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CURRENT_TAB = re.compile(
    r"\b(?:current|already[ -]?open|this|shared)\s+(?:browser\s+)?(?:tab|page|website|webpage)\b",
    re.IGNORECASE,
)


def _ordinary_http_url(task: str) -> str | None:
    for raw in _HTTP_URL.findall(task):
        candidate = raw.rstrip(".,;:!?)]}\"")
        parsed = urlsplit(candidate)
        if (
            parsed.scheme.lower() in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return candidate
    return None


def parse_browser_handoff(text: str) -> BrowserHandoffIntent | None:
    """Return intent only for a leading, non-empty user ``@browser`` marker."""

    match = _HANDOFF.match(text or "")
    if match is None:
        return None
    task = match.group(1).strip()
    if not task:
        return None
    direct_url = _ordinary_http_url(task)
    if _CURRENT_TAB.search(task):
        policy: BrowserTabPolicy = "current"
    elif direct_url:
        policy = "owned_url"
    else:
        policy = "selected_or_ask"
    return BrowserHandoffIntent(task=task, direct_url=direct_url, tab_policy=policy)


def browser_handoff_request(text: str) -> bool:
    return parse_browser_handoff(text) is not None


__all__ = [
    "BrowserHandoffIntent",
    "BrowserTabPolicy",
    "browser_handoff_request",
    "parse_browser_handoff",
]
