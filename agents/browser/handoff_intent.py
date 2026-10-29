"""Parse explicit browser handoffs and direct user-authored links."""
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


def parse_direct_url_handoff(text: str) -> BrowserHandoffIntent | None:
    """Return a deterministic tab policy for a normal browser task with a URL.

    This remains separate from :func:`parse_browser_handoff`: routing uses the
    latter to reserve the explicit ``@browser`` marker, while the connected
    runner uses this helper after browser routing has already been chosen.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    task = text.strip()
    if _CURRENT_TAB.search(task):
        return BrowserHandoffIntent(task=task, direct_url=None, tab_policy="current")
    direct_url = _ordinary_http_url(task)
    if direct_url is None:
        return None
    return BrowserHandoffIntent(task=task, direct_url=direct_url, tab_policy="owned_url")


__all__ = [
    "BrowserHandoffIntent",
    "BrowserTabPolicy",
    "browser_handoff_request",
    "parse_direct_url_handoff",
    "parse_browser_handoff",
]
