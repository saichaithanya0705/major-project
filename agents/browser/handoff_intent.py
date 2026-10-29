"""Parse explicit browser handoffs and direct user-authored links."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


BrowserTabPolicy = Literal["owned_url", "owned_start", "current", "selected_or_ask"]


@dataclass(frozen=True, slots=True)
class BrowserHandoffIntent:
    """A browser objective and the tab ownership policy its request permits."""

    task: str
    direct_url: str | None
    tab_policy: BrowserTabPolicy


_HANDOFF = re.compile(r"^\s*@browser\b\s*(.+?)\s*$", re.IGNORECASE | re.DOTALL)
_HTTP_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CURRENT_TAB = re.compile(
    r"\b(?:current|existing|already[ -]?open|this|shared)\s+(?:browser\s+)?(?:tab|page|website|webpage|site)\b",
    re.IGNORECASE,
)
_NEW_NAVIGATION = re.compile(
    r"^\s*(?:please\s+)?(?:open|visit|go\s+to|navigate\s+to|search|research|look\s+up)\b", re.I,
)
_EXISTING_CONTROL = re.compile(r"\b(?:this|that|current|existing)\s+(?:form|menu|dialog|button|link|dropdown)\b", re.I)


def _starts_new_navigation(task: str) -> bool:
    if not _NEW_NAVIGATION.search(task) or _EXISTING_CONTROL.search(task):
        return False
    # Opening a control on an existing page is not opening a new destination.
    first_goal = re.split(r"\b(?:and|then)\b", task, maxsplit=1, flags=re.I)[0]
    return not re.search(r"\b(?:button|control|menu|dialog|dropdown|panel|settings|link)\b", first_goal, re.I)


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
    elif _starts_new_navigation(task):
        policy = "owned_start"
    else:
        policy = "selected_or_ask"
    return BrowserHandoffIntent(task=task, direct_url=direct_url, tab_policy=policy)


def browser_handoff_request(text: str) -> bool:
    return parse_browser_handoff(text) is not None


def parse_browser_start_handoff(text: str) -> BrowserHandoffIntent | None:
    """Start standalone navigation/research without requiring an existing page."""
    task = (text or "").strip()
    if not task or _CURRENT_TAB.search(task) or _EXISTING_CONTROL.search(task):
        return None
    if _starts_new_navigation(task):
        return BrowserHandoffIntent(task=task, direct_url=None, tab_policy="owned_start")
    return None


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
    "parse_browser_start_handoff",
]
