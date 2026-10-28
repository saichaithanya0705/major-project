"""Narrow, inspected action boundary for the user's connected browser.

The model never receives an evaluation tool. Fixed readers below are runtime
implementation details, and never interpolate model, skill, or page source.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jsonschema

from agents.browser.mcp_client import McpToolError, McpToolResult


PAGE_INFO = "() => { /* JARVIS_PAGE_INFO */ return {url: location.href, title: document.title}; }"
ELEMENT_STATE = r"""(element) => { /* JARVIS_ELEMENT_STATE */
 const e = element || document.activeElement;
 if (!e || !e.isConnected) return null;
 const scope = e.form || e.closest('form,[role="form"],[role="search"]');
 const sensitive = n => /password|otp|one-time|card|cvv|cvc|ssn|aadhaar|passcode|pin\b/i.test(
   [n.type,n.name,n.id,n.autocomplete,n.getAttribute('aria-label')].join(' '));
 const label = n => (n.getAttribute('aria-label') || n.labels?.[0]?.innerText ||
   n.innerText || n.getAttribute('placeholder') || n.name || n.id || n.tagName).slice(0,120);
 const controls = scope ? Array.from(scope.querySelectorAll('input,textarea,select')).slice(0,30) : [];
 const editable = controls.filter(n => !['hidden','submit','button','reset'].includes(n.type));
 const search = e.type === 'search' || e.getAttribute('role') === 'searchbox' ||
   scope?.getAttribute('role') === 'search' || (editable.length > 0 && editable.every(n =>
     n.type === 'search' || /^(q|query|search|search_query)$/i.test(n.name || n.id)));
 const read = n => ({name:label(n), sensitive:sensitive(n),
   value:sensitive(n) ? (n.value ? '[present]' : '') : String(n.value ?? '').slice(0,4096),
   checked:!!n.checked, selected:n.selectedOptions ? Array.from(n.selectedOptions).map(o=>o.value) : []});
 return {tag:e.tagName.toLowerCase(), type:e.type || '', role:e.getAttribute('role') || '',
   label:label(e), value:sensitive(e) ? (e.value ? '[present]' : '') : String(e.value ?? '').slice(0,4096),
   sensitive:sensitive(e), checked:!!e.checked, disabled:!!e.disabled,
   selected:e.selectedOptions ? Array.from(e.selectedOptions).map(o=>({value:o.value,text:o.text})) : [],
   valid:e.validity ? e.validity.valid : true,
   form:scope ? {id:scope.id || scope.getAttribute('aria-label') || 'form',
     action:scope.action || location.href, method:scope.method || '', search:!!search,
     values:controls.map(read)} : null, search:!!search};
}"""
ACTIVE_STATE = ELEMENT_STATE.replace("(element) =>", "() =>").replace(
    "const e = element || document.activeElement;", "const e = document.activeElement;")

TOOLS = frozenset({"browser_snapshot", "browser_tabs", "browser_navigate", "browser_navigate_back",
    "browser_click", "browser_type", "browser_fill_form", "browser_select_option", "browser_press_key",
    "browser_wait_for", "browser_hover"})
_REF = re.compile(r"^(?:f\d+)?e\d+$")
_SUBMIT = re.compile(r"\b(submit|send|pay|place order|purchase|buy now|book|reserve|register|sign up|sign in|log in|save|apply|publish|post|complete|confirm)\b", re.I)
_KEYS = frozenset({"Enter", "Return", "Tab", "Shift+Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft",
    "ArrowRight", "PageDown", "PageUp", "Home", "End", "Space", " "})


class StalePageError(McpToolError):
    pass


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _json_result(result: McpToolResult) -> dict:
    result.require_success()
    if result.structured and ("tag" in result.structured or "url" in result.structured):
        return result.structured
    text = result.text.split("### Result", 1)[-1].lstrip()
    start = text.find("{")
    if start < 0:
        raise McpToolError("The browser could not inspect this control safely.")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError as exc:
        raise McpToolError("The browser returned an invalid inspection result.") from exc
    if not isinstance(value, dict):
        raise McpToolError("The browser returned an unreadable control.")
    return value


class ConnectedGateway:
    def __init__(self, client, confirm, stopped=lambda: False):
        self.client, self.confirm, self.stopped = client, confirm, stopped
        self.generation = 0
        self.url = ""
        self.title = ""
        self.verified_steps: list[str] = []
        self.approval_wait = 0.0
        self._schemas: dict[str, dict] = {}
        self._raw_snapshot = ""
        self._refs: set[str] = set()
        self._draft_refs: set[str] = set()
        self._secrets: set[str] = set()

    def _check_stop(self):
        if self.stopped():
            raise McpToolError("Browser task stopped; no further action was sent.")

    async def _call(self, name, args=None) -> McpToolResult:
        self._check_stop()
        return (await self.client.call_result(name, args or {})).require_success()

    async def _page(self) -> dict:
        return _json_result(await self._call("browser_evaluate", {"function": PAGE_INFO}))

    async def _inspect(self, target: str | None = None) -> dict:
        args = {"function": ELEMENT_STATE, "target": target} if target else {"function": ACTIVE_STATE}
        node = _json_result(await self._call("browser_evaluate", args))
        if not node.get("tag"):
            raise McpToolError("This control is not inspectable; user takeover is needed.")
        return node

    @staticmethod
    def _tree(text: str) -> str:
        return text.split("### Snapshot", 1)[-1].strip()

    async def observe(self) -> str:
        if not self._schemas:
            self._schemas = await self.client.tool_schemas()
            if not {"browser_snapshot", "browser_evaluate"} <= self._schemas.keys():
                raise McpToolError("This MCP version does not provide the required browser inspection tools.")
        page = await self._page()
        snapshot = await self._call("browser_snapshot")
        new_url = str(page.get("url") or "")
        if new_url != self.url:
            self._draft_refs.clear()
        self.url, self.title = new_url, str(page.get("title") or "")[:160]
        self._raw_snapshot = self._tree(snapshot.text)
        self._refs = set(re.findall(r"\[ref=([^\]\s]+)\]", self._raw_snapshot))
        self.generation += 1
        return self.observation()

    def observation(self) -> str:
        # Private form values are checked in runtime, not sent back to the model.
        tree = re.sub(r'(?m)^(\s*- (?:textbox|searchbox|spinbutton)[^\n]*?\[ref=[^\]]+\][^:\n]*):[^\n]*', r'\1: [value hidden]', self._raw_snapshot)
        for secret in sorted(self._secrets, key=len, reverse=True):
            tree = tree.replace(secret, "[hidden]")
        tree = re.sub(r"https?://[^\s\]<>\"`]+", lambda m: public_url(m.group(0)), tree)
        return f"Page: {self.title}\nURL: {public_url(self.url)}\nSnapshot generation: {self.generation}\n{tree[:24000]}"

    def tool_catalog(self) -> dict:
        catalog = {}
        for name in sorted(TOOLS & self._schemas.keys()):
            schema = json.loads(json.dumps(self._schemas[name]))
            schema.get("properties", {}).pop("filename", None)
            if name == "browser_tabs":
                schema["properties"]["action"]["enum"] = ["list", "new"]
            catalog[name] = schema
        return catalog

    async def _fresh(self):
        page = await self._page()
        snapshot = await self._call("browser_snapshot")
        if page.get("url") != self.url or self._tree(snapshot.text) != self._raw_snapshot:
            raise StalePageError("The page changed; take a fresh snapshot before continuing.")

    def _validate(self, name: str, args: dict):
        catalog = self.tool_catalog()
        if name not in catalog or not isinstance(args, dict):
            raise McpToolError("That browser tool is not available to the agent.")
        try:
            if len(json.dumps(args)) > 32000:
                raise ValueError()
            jsonschema.validate(args, catalog[name])
        except (jsonschema.ValidationError, ValueError, TypeError) as exc:
            raise McpToolError("Invalid browser action arguments; no action was sent.") from exc
        if "filename" in args or args.get("doubleClick") or args.get("modifiers") or args.get("button", "left") != "left":
            raise McpToolError("This action variant is not supported in connected mode.")
        fields = args.get("fields", [])
        if len(fields) > 20:
            raise McpToolError("Fill at most 20 fields in one action.")
        for value in [args, *fields]:
            target = value.get("target")
            if target is not None and (not isinstance(target, str) or not _REF.fullmatch(target) or target not in self._refs):
                raise StalePageError("Unknown or stale control reference; refresh the snapshot.")
            for key in ("text", "value"):
                if key in value and (not isinstance(value[key], str) or len(value[key]) > 4096):
                    raise McpToolError("Field values must be bounded strings.")
        if name in {"browser_navigate", "browser_tabs"} and args.get("url"):
            parsed = urlsplit(args["url"])
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise McpToolError("Only ordinary HTTP(S) navigation is supported.")
        if name == "browser_press_key" and args["key"] not in _KEYS:
            raise McpToolError("Use inspected typing tools instead of browser-wide keyboard shortcuts.")
        if name == "browser_wait_for" and not 0 <= args.get("time", 0) <= 5:
            raise McpToolError("Waits must be between zero and five seconds.")

    @staticmethod
    def _submission(node: dict, *, enter=False) -> bool:
        form = node.get("form") or {}
        if node.get("search") or form.get("search") or node.get("type") == "search":
            return False
        if enter and node.get("tag") in {"input", "select", "button"} and form:
            return True
        if node.get("tag") in {"button", "input"} and node.get("type") == "submit" and form:
            return True
        return bool(node.get("tag") in {"button", "input", "a"} or node.get("role") == "button") and bool(_SUBMIT.search(str(node.get("label", ""))))

    async def _approval_state(self, node: dict) -> str:
        drafts = []
        for ref in sorted(self._draft_refs):
            if ref not in self._refs:
                raise StalePageError("A filled control changed; inspect the form again before submission.")
            drafts.append(await self._inspect(ref))
        return hashlib.sha256(json.dumps([self.url, node, drafts], sort_keys=True).encode()).hexdigest()

    async def _review(self, node: dict, target: str | None):
        before = await self._approval_state(node)
        form = node.get("form") or {}
        labels = []
        for value in form.get("values", [])[:12]:
            if isinstance(value, dict):
                shown = "[hidden]" if value.get("sensitive") else str(value.get("value", ""))[:80]
                labels.append(f"{value.get('name', 'field')}: {shown}")
        description = f"submit “{node.get('label', 'this form')}” on {urlsplit(self.url).hostname or 'the selected page'}"
        if labels:
            description += "\n\nReview: " + "; ".join(labels)
        started = time.monotonic()
        try:
            approved = await self.confirm(description)
        finally:
            self.approval_wait += time.monotonic() - started
        self._check_stop()
        if not approved:
            raise McpToolError("Form submission declined or cancelled; the draft remains filled.")
        await self._fresh()
        after = await self._inspect(target)
        if await self._approval_state(after) != before:
            raise StalePageError("The form changed during approval; submission was not sent.")

    async def select_tab(self, index: int) -> str:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise McpToolError("Choose a nonnegative tab index from browser status.")
        # Called only for an explicit user chat command, never from model actions.
        await self._call("browser_tabs", {"action": "list"})
        await self._call("browser_tabs", {"action": "select", "index": index})
        self._draft_refs.clear()
        return await self.observe()

    async def act(self, name: str, arguments: dict) -> str:
        self._check_stop()
        self._validate(name, arguments)
        await self._fresh()
        args = dict(arguments)
        if name == "browser_snapshot":
            return await self.observe()
        target = args.get("target")
        node = await self._inspect(target) if target else None
        if name == "browser_press_key" and args["key"] in {"Enter", "Return", "Space", " "}:
            node = await self._inspect()
            if args["key"] in {"Enter", "Return"} and node.get("tag") not in {"input", "textarea", "select", "button", "a"} and node.get("role") not in {"button", "textbox", "searchbox"}:
                raise McpToolError("The active control cannot be classified for Enter; select an inspectable control first.")
        if node and node.get("disabled"):
            raise McpToolError("The selected control is disabled.")
        submit_after_type = name == "browser_type" and args.pop("submit", False)
        implicit_enter = name == "browser_press_key" and args["key"] in {"Enter", "Return"}
        if node and name in {"browser_click", "browser_press_key"} and self._submission(node, enter=implicit_enter):
            await self._review(node, target)
        fields = args.get("fields", [])
        # Validate and inspect the entire batch before sending its first write.
        for field in fields:
            await self._inspect(field["target"])
        for field in [args, *fields]:
            text = field.get("text") or field.get("value")
            if isinstance(text, str) and text:
                self._secrets.add(text)
        self._check_stop()
        await self._call(name, args)
        await self.observe()
        checks = fields or ([{"target": target, "value": args["text"]}] if name == "browser_type" else [])
        for field in checks:
            current = await self._inspect(field["target"])
            expected = field["value"]
            actual = current.get("value", "")
            kind = field.get("type", "textbox")
            if kind in {"checkbox", "radio"}:
                matches = bool(current.get("checked")) == (expected == "true")
            elif kind == "combobox":
                matches = any(expected in {o.get("value"), o.get("text")} for o in current.get("selected", []))
            elif current.get("sensitive"):
                matches = bool(actual) == bool(expected)
            else:
                matches = str(actual) == expected
            if not matches:
                raise McpToolError("Field read-back did not match; task remains incomplete.")
            self._draft_refs.add(field["target"])
        if name == "browser_select_option":
            current = await self._inspect(target)
            if set(args["values"]) != {v["value"] for v in current.get("selected", [])}:
                raise McpToolError("The selected options did not match the request.")
            self._draft_refs.add(target)
        label = str((node or {}).get("label", "page"))[:80]
        message = f"Verified {name.removeprefix('browser_')} on {urlsplit(self.url).hostname or 'selected tab'}: {label}"
        self.verified_steps.append(message)
        if submit_after_type:
            return await self.act("browser_press_key", {"key": "Enter"})
        return message
