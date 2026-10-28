"""
Decide which browser-use actions need the user's approval before they run.

Gated: clicks on buttons that submit, pay, send, delete, or book; typing into
password, card, OTP, or ID-number fields; uploading files; running page
JavaScript; and pressing Enter after typing into a non-search form field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

RISKY_BUTTON = re.compile(
    r"\b(?:submit|send|pay|pay now|place (?:your )?order|buy(?: now)?|purchase|check ?out|confirm|"
    r"delete|remove account|close account|transfer|book(?: now)?|reserve|subscribe|sign ?up|register|"
    r"post|publish|withdraw|donate|unsubscribe|apply now|submit application|complete (?:order|purchase|booking))\b",
    re.IGNORECASE,
)
SENSITIVE_FIELD = re.compile(
    r"(?:password|passwd|pwd|card|cc-|credit|debit|cvv|cvc|expir|otp|one[-_ ]?time|passcode|pin\b|ssn|"
    r"aadhaar|aadhar|\bpan\b|iban|routing|account[-_ ]?(?:no|num)|upi)",
    re.IGNORECASE,
)
SEARCH_FIELD = re.compile(r"(?:search|query|\bq\b|find)", re.IGNORECASE)
_ENTER = re.compile(r"\benter\b|\breturn\b", re.IGNORECASE)

Confirm = Callable[[str], Awaitable[bool]]


def _host(url: str | None) -> str:
    return urlparse(url or "").hostname or "this page"


def _attributes(node: Any) -> dict[str, str]:
    attributes = getattr(node, "attributes", None) or {}
    return {str(k).lower(): str(v) for k, v in attributes.items()}


def _visible_text(node: Any) -> str:
    getters = (
        lambda: node.get_all_children_text(max_depth=3),
        lambda: node.get_meaningful_text_for_llm(),
    )
    for getter in getters:
        try:
            text = getter()
        except Exception:  # noqa: BLE001 - nodes from other browser-use versions may lack a getter.
            continue
        if text and str(text).strip():
            return " ".join(str(text).split())
    return ""


def describe_element(node: Any) -> tuple[str, str, dict[str, str]]:
    """(tag, label, attributes) for a DOM node from browser-use's selector map."""
    attributes = _attributes(node)
    tag = str(getattr(node, "tag_name", "") or getattr(node, "node_name", "")).lower()
    label = (
        _visible_text(node)
        or attributes.get("aria-label")
        or attributes.get("value")
        or attributes.get("title")
        or attributes.get("name")
        or attributes.get("id")
        or tag
    )
    return tag, label[:80], attributes


@dataclass
class ActionGuard:
    confirm: Confirm
    typed_into_form: bool = False
    approved_actions: list[str] = field(default_factory=list)

    async def _element(self, browser_session: Any, params: dict[str, Any]) -> Any:
        index = params.get("index")
        try:
            if index is not None:
                return await browser_session.get_element_by_index(int(index))
            x, y = params.get("coordinate_x"), params.get("coordinate_y")
            if x is not None and y is not None:
                return await browser_session.get_dom_element_at_coordinates(int(x), int(y))
        except Exception:  # noqa: BLE001 - an unreadable element is judged on params alone.
            return None
        return None

    async def risky_action(self, action_name: str, params: dict[str, Any], browser_session: Any) -> str | None:
        """A sentence describing the action if it needs approval, else None."""
        try:
            url = await browser_session.get_current_page_url()
        except Exception:  # noqa: BLE001
            url = None
        host = _host(url)

        if action_name == "click":
            node = await self._element(browser_session, params)
            if node is None:
                return None
            tag, label, attributes = describe_element(node)
            is_submit = attributes.get("type", "").lower() == "submit" and tag in {"input", "button"}
            if is_submit or RISKY_BUTTON.search(label):
                return f"click “{label}” on {host}"
            return None

        if action_name == "input":
            node = await self._element(browser_session, params)
            attributes = _attributes(node) if node is not None else {}
            identity = " ".join(
                attributes.get(key, "") for key in ("type", "name", "id", "autocomplete", "placeholder", "aria-label")
            )
            if not SEARCH_FIELD.search(identity) and attributes.get("type", "").lower() != "search":
                self.typed_into_form = True
            if attributes.get("type", "").lower() == "password" or SENSITIVE_FIELD.search(identity):
                field_name = attributes.get("aria-label") or attributes.get("placeholder") or attributes.get("name") or "a sensitive field"
                return f"type into “{field_name[:60]}” on {host}"
            return None

        if action_name == "upload_file":
            return f"upload {params.get('path') or 'a file'} to {host}"

        if action_name == "evaluate":
            return f"run custom JavaScript on {host}"

        if action_name == "send_keys" and self.typed_into_form and _ENTER.search(str(params.get("keys") or "")):
            return f"press Enter to submit the form on {host}"

        return None

    async def allow(self, action_name: str, params: dict[str, Any], browser_session: Any) -> str | None:
        """None if the action may run; otherwise the declined action's description."""
        description = await self.risky_action(action_name, params, browser_session)
        if description is None:
            return None
        if await self.confirm(description):
            self.approved_actions.append(description)
            return None
        return description


def declined_message(description: str) -> str:
    return (
        f"The user declined: {description}. Stop here: do not retry this or work around it. "
        "Report what was completed and what the user still needs to do themselves."
    )


def guarded_tools_class(tools_cls: type, action_result_cls: type, guard: ActionGuard) -> type:
    """Subclass browser-use's Tools so every action passes ``guard`` before it runs."""

    class GuardedTools(tools_cls):  # type: ignore[misc, valid-type]
        async def act(self, action, browser_session, *args, **kwargs):
            for action_name, params in action.model_dump(exclude_unset=True).items():
                if params is None:
                    continue
                declined = await guard.allow(action_name, params if isinstance(params, dict) else {}, browser_session)
                if declined is not None:
                    message = declined_message(declined)
                    return action_result_cls(is_done=True, success=False, extracted_content=message, long_term_memory=message)
            return await super().act(action, browser_session, *args, **kwargs)

    GuardedTools.__name__ = f"Guarded{tools_cls.__name__}"
    return GuardedTools
