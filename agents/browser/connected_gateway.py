"""Narrow, inspected action boundary for the user's connected browser.

The model never receives an evaluation tool. Fixed readers below are runtime
implementation details, and never interpolate model, skill, or page source.
"""
from __future__ import annotations

import hashlib
import copy
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import jsonschema

from agents.browser.mcp_client import McpToolError, McpToolResult


PAGE_INFO = "() => { /* JARVIS_PAGE_INFO */ return {url: location.href, title: document.title}; }"
# Fixed private metadata reader; never catalogued or authored by the model.
# The pinned Playwright Page GUID survives navigation and changes on reconnect.
PAGE_IDENTITY = "async (page) => ({tab_id: page._guid})"
ELEMENT_STATE = r"""async (element) => { /* JARVIS_ELEMENT_STATE */
 const e = element || document.activeElement;
 if (!e || !e.isConnected) return null;
 const scope = e.form || e.closest('form,[role="form"],[role="search"]');
 const sensitive = n => n.type === 'hidden' || /password|otp|one-time|card|cvv|cvc|ssn|aadhaar|passcode|pin\b/i.test(
   [n.type,n.name,n.id,n.autocomplete,n.getAttribute('aria-label')].join(' '));
 const label = n => (n.getAttribute('aria-label') || n.getAttribute('alt') || n.labels?.[0]?.innerText ||
   n.innerText || n.getAttribute('placeholder') || n.name || n.id || n.tagName).slice(0,120);
 const allControls = scope ? Array.from(scope.querySelectorAll('input,textarea,select,button')) : [];
 const controls = allControls.slice(0,100);
 const editable = controls.filter(n => !['hidden','submit','button','reset'].includes(n.type));
 const search = scope ? (scope.getAttribute('role') === 'search' ||
   (String(scope.method || 'get').toLowerCase() === 'get' && editable.length > 0 && editable.every(n =>
     n.type === 'search' || /^(q|query|search|search_query)$/i.test(n.name || n.id)))) :
   (e.type === 'search' || e.getAttribute('role') === 'searchbox');
 const fingerprint = async n => {
   if (!sensitive(n) || !n.value) return null;
   if (!globalThis.crypto?.subtle) return 'unavailable';
   const bytes = new TextEncoder().encode("__JARVIS_APPROVAL_KEY__" + '\0' + String(n.value));
   return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
 };
 const read = async n => ({name:label(n), sensitive:sensitive(n), fingerprint:await fingerprint(n),
   value:sensitive(n) ? (n.value ? '[present]' : '') : String(n.value ?? '').slice(0,4096),
   checked:!!n.checked, selected:n.selectedOptions ? Array.from(n.selectedOptions).map(o=>o.value) : []});
 return {tag:e.tagName.toLowerCase(), type:e.type || '', role:e.getAttribute('role') || '',
   label:label(e), value:sensitive(e) ? (e.value ? '[present]' : '') : String(e.value ?? '').slice(0,4096),
   sensitive:sensitive(e), fingerprint:await fingerprint(e), checked:!!e.checked, disabled:!!e.disabled,
   readOnly:!!e.readOnly, editable:!!e.isContentEditable,
   selected:e.selectedOptions ? Array.from(e.selectedOptions).map(o=>({value:o.value,text:o.text})) : [],
   valid:e.validity ? e.validity.valid : true,
   form:scope ? {id:scope.id || scope.getAttribute('aria-label') || 'form',
     action:scope.action || location.href, method:scope.method || '', search:!!search,
     truncated:allControls.length > controls.length, values:await Promise.all(controls.map(read))} : null,
   submission:scope ? (() => {
     const submitter = ['submit','image'].includes(e.type) ? e : controls.find(n=>['submit','image'].includes(n.type) && !n.disabled);
     const override = (attribute, property, fallback) => submitter?.getAttribute(attribute) != null ? submitter[property] : fallback;
     return {action:override('formaction','formAction',scope.action || location.href),
       method:override('formmethod','formMethod',scope.method || 'get'), target:override('formtarget','formTarget',scope.target || '_self'),
       enctype:override('formenctype','formEnctype',scope.enctype || '')};
   })() : null, search:!!search};
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


class SelectedTabLostError(McpToolError):
    pass


class BrowserInputRequired(McpToolError):
    """A proposed personal value has no source in the human's supplied input."""


class AlreadyVerifiedWrite(McpToolError):
    """A repeated edit still matches a value this task has already verified."""


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    # Strip userinfo as well as query/fragment without changing IPv6 or ports.
    authority = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))


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
    def __init__(self, client, confirm, stopped=lambda: False, *, user_input=""):
        self.client, self.confirm, self.stopped = client, confirm, stopped
        self.user_input = user_input
        self.generation = 0
        self.url = ""
        self.title = ""
        self.verified_steps: list[str] = []
        self.verified_edits: list[str] = []
        self.verified_submissions: list[str] = []
        self.approval_wait = 0.0
        self._schemas: dict[str, dict] = {}
        self._raw_snapshot = ""
        self._refs: set[str] = set()
        self._draft_refs: set[str] = set()
        self._secrets: set[str] = set()
        self._tab_entries: dict[int, tuple[str, str]] = {}
        self._approval_key = secrets.token_hex(32)
        self._tab_identity = None
        self._identity_lost = False

    def _check_stop(self):
        if self.stopped():
            raise McpToolError("Browser task stopped; no further action was sent.")

    async def _call(self, name, args=None) -> McpToolResult:
        self._check_stop()
        if name != "browser_tabs" and self._tab_identity is not None:
            await self._ensure_identity()
        return (await self.client.call_result(name, args or {})).require_success()

    async def _read_identity(self) -> str:
        self._check_stop()
        state = _json_result((await self.client.call_result("browser_run_code_unsafe", {"code":PAGE_IDENTITY})).require_success())
        identity = state.get("tab_id")
        if not isinstance(identity, str) or not identity or len(identity) > 160:
            raise McpToolError("The browser cannot identify the selected tab safely; reconnect and select it explicitly.")
        return identity

    async def _ensure_identity(self):
        identity = await self._read_identity()
        if self._identity_lost or (self._tab_identity is not None and identity != self._tab_identity):
            self._identity_lost = True
            raise SelectedTabLostError("The selected tab closed or the connection changed. Use browser status and explicitly select a tab again; no replacement page was read.")
        self._tab_identity = identity

    async def _page(self) -> dict:
        return _json_result(await self._call("browser_evaluate", {"function": PAGE_INFO}))

    async def _inspect(self, target: str | None = None) -> dict:
        reader = (ELEMENT_STATE if target else ACTIVE_STATE).replace('__JARVIS_APPROVAL_KEY__', self._approval_key)
        args = {"function": reader, "target": target} if target else {"function": reader}
        node = _json_result(await self._call("browser_evaluate", args))
        if not node.get("tag"):
            raise McpToolError("This control is not inspectable; user takeover is needed.")
        return node

    @staticmethod
    def _tree(text: str) -> str:
        return text.split("### Snapshot", 1)[-1].strip()

    async def observe(self) -> str:
        await self._ensure_identity()
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
            if name == "browser_snapshot":
                schema = {"type":"object", "properties":{}, "additionalProperties":False}
            if name == "browser_tabs":
                schema["properties"]["action"]["enum"] = ["list", "new"]
            catalog[name] = schema
        return catalog

    def validate_action(self, name: str, arguments: dict) -> None:
        """Pure preflight: callers may correct this rejection without replaying effects."""
        self._validate(name, self._canonical(arguments))

    @staticmethod
    def _canonical(arguments: dict) -> dict:
        if not isinstance(arguments, dict):
            return arguments
        result = copy.deepcopy(arguments)
        fields = result.get("fields", [])
        if not isinstance(fields, list):
            return result
        for item in [result, *fields]:
            if not isinstance(item, dict):
                continue
            value = item.get("target")
            if isinstance(value, str):
                match = re.fullmatch(r"(?:ref=|\[ref=)((?:f\d+)?e\d+)\]?", value.strip())
                if match:
                    item["target"] = match.group(1)
        return result

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
    def _editable(node: dict, kind="textbox"):
        tag, field_type = node.get("tag"), node.get("type", "text")
        valid = False
        if kind == "textbox":
            valid = tag == "textarea" or bool(node.get("editable")) or (tag == "input" and field_type not in {"checkbox","radio","submit","button","reset","hidden","file","range"})
        elif kind in {"checkbox", "radio"}:
            valid = tag == "input" and field_type == kind
        elif kind == "combobox":
            valid = tag == "select"
        elif kind == "slider":
            valid = tag == "input" and field_type == "range"
        if not valid or node.get("disabled") or node.get("readOnly"):
            raise McpToolError("The target is not an editable field of the requested type; no batch was sent.")

    @staticmethod
    def _submission(node: dict, *, enter=False) -> bool:
        form = node.get("form") or {}
        if form.get("search") or (not form and node.get("search")):
            return False
        if enter and node.get("tag") in {"input", "select", "button"} and form:
            return True
        if node.get("tag") in {"button", "input"} and node.get("type") in {"submit", "image"} and form:
            return True
        return bool(node.get("tag") in {"button", "input", "a"} or node.get("role") == "button") and bool(_SUBMIT.search(str(node.get("label", ""))))

    def _check_personal_value(self, node: dict, value: str):
        if not value or node.get("search") or (node.get("form") or {}).get("search"):
            return
        label = str(node.get("label", "field"))[:80]
        descriptor = re.sub(r"[_-]+", " ", label)
        personal = node.get("sensitive") or node.get("type") in {"email", "tel", "password"} or re.fullmatch(r"\s*name\s*[:*]?\s*", descriptor, re.I) or re.search(
            r"\b(?:e ?mail|phone|mobile|telephone|age|date of birth|birth ?date|dob|full name|first name|last name|given name|family name|address|postcode|zip ?code|ssn|aadhaar|passport|password|passcode|card number|cvv|cvc)\b",
            descriptor, re.I)
        if not personal:
            return
        supplied = " ".join(self.user_input.split())
        literal = " ".join(str(value).split())
        if not re.search(r"(?<!\w)" + re.escape(literal) + r"(?!\w)", supplied, re.I):
            raise BrowserInputRequired(f"What value should I use for “{label}”? I paused before entering an assumed personal value.")

    @staticmethod
    def _field_matches(node: dict, expected: str, kind="textbox") -> bool:
        if kind in {"checkbox", "radio"}:
            return bool(node.get("checked")) == (expected == "true")
        if kind == "combobox":
            return any(expected in {o.get("value"), o.get("text")} for o in node.get("selected", []))
        if node.get("sensitive"):
            return bool(node.get("value")) == bool(expected)
        return str(node.get("value", "")) == expected

    async def _approval_state(self, node: dict) -> str:
        form = node.get("form") or {}
        if form.get("truncated") or any(isinstance(value, dict) and value.get("fingerprint") == "unavailable" for value in [node, *form.get("values", [])]):
            raise McpToolError("This form cannot be fingerprinted completely; user takeover is needed.")
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
        destination = public_url((node.get("submission") or {}).get("action") or form.get("action") or self.url)
        description = f"submit “{node.get('label', 'this form')}” to {destination}"
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

    async def list_tabs(self) -> str:
        result = await self._call("browser_tabs", {"action":"list"})
        entries = {}
        for match in re.finditer(r"(?m)^-\s*(\d+):\s*(?:\(current\)\s*)?\[(.*?)\]\(([^\n]+)\)", result.text):
            entries[int(match.group(1))] = (match.group(2), match.group(3))
        self._tab_entries = entries
        return "\n".join(f"{index}: {title} — {public_url(url)}" for index,(title,url) in entries.items())[:6000]

    async def select_tab(self, index: int) -> str:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise McpToolError("Choose a nonnegative tab index from browser status.")
        # Called only for an explicit user chat command, never from model actions.
        expected = self._tab_entries.get(index)
        await self.list_tabs()
        entry = self._tab_entries.get(index)
        if entry is None or (expected is not None and entry != expected):
            raise StalePageError("The tab list changed; check browser status and choose the tab again.")
        if urlsplit(entry[1]).scheme not in {"http","https"}:
            raise McpToolError("Choose a normal HTTP(S) test tab; browser-internal pages cannot be controlled.")
        await self._call("browser_tabs", {"action": "select", "index": index})
        self._tab_identity = await self._read_identity()
        self._identity_lost = False
        page = await self._page()
        if page.get("url") != entry[1]:
            raise StalePageError("The selected tab changed before inspection; choose it again.")
        self._draft_refs.clear()
        return await self.observe()

    async def open_owned_tab(self, url: str) -> str:
        """Open a user-requested HTTP(S) URL as JARVIS's selected tab.

        This is deliberately not exposed to the model.  It is a deterministic
        consequence of the user's direct-link request, and the tab is selected
        before any page content is inspected.
        """
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise McpToolError("JARVIS can open only a normal HTTP(S) link in a new browser tab.")
        if not self._schemas:
            self._schemas = await self.client.tool_schemas()
        if "browser_tabs" not in self._schemas:
            raise McpToolError("This Playwright connection cannot create a browser tab.")
        await self._call("browser_tabs", {"action": "new", "url": url})
        self._tab_identity = await self._read_identity()
        self._identity_lost = False
        self._draft_refs.clear()
        return await self.observe()

    async def act(self, name: str, arguments: dict) -> str:
        self._check_stop()
        arguments = self._canonical(arguments)
        self._validate(name, arguments)
        await self._fresh()
        args = dict(arguments)
        if name == "browser_snapshot":
            return await self.observe()
        if name == "browser_tabs" and args.get("action") == "list":
            message = "Observed browser tabs:\n" + await self.list_tabs()
            self.verified_steps.append(message)
            return message
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
        submitting = bool(node and name in {"browser_click", "browser_press_key"} and self._submission(node, enter=implicit_enter))
        if submitting:
            await self._review(node, target)
        before_submission = self.observation() if submitting else ""
        fields = args.get("fields", [])
        # Validate and inspect the entire batch before sending its first write.
        inspected_fields = []
        for field in fields:
            field_node = await self._inspect(field["target"])
            self._editable(field_node, field["type"])
            self._check_personal_value(field_node, field["value"])
            inspected_fields.append((field, field_node))
        if name == "browser_type":
            self._editable(node)
            self._check_personal_value(node, args["text"])
            inspected_fields.append(({"target":target,"value":args["text"]}, node))
        if name == "browser_select_option":
            self._editable(node, "combobox")
            for value in args["values"]:
                self._check_personal_value(node, value)
            if target in self._draft_refs and not node.get("sensitive") and set(args["values"]) == {v["value"] for v in node.get("selected", [])}:
                raise AlreadyVerifiedWrite("These options are already selected and verified. Choose an unfinished step or finish using the verified evidence.")
        if inspected_fields and not submit_after_type and all(
            field["target"] in self._draft_refs and not current.get("sensitive") and
            self._field_matches(current, field["value"], field.get("type", "textbox"))
            for field,current in inspected_fields):
            raise AlreadyVerifiedWrite("These fields already match the requested values and are verified. Choose an unfinished step or finish using the verified field evidence; do not repeat the edit.")
        for field in [args, *fields]:
            text = field.get("text") or field.get("value")
            if isinstance(text, str) and text:
                self._secrets.add(text)
        self._check_stop()
        await self._call(name, args)
        if name == "browser_tabs" and args.get("action") == "new":
            self._tab_identity = await self._read_identity()
        await self.observe()
        checks = fields or ([{"target": target, "value": args["text"]}] if name == "browser_type" else [])
        receipts = []
        for field in checks:
            current = await self._inspect(field["target"])
            expected = field["value"]
            kind = field.get("type", "textbox")
            if not self._field_matches(current, expected, kind):
                raise McpToolError("Field read-back did not match; task remains incomplete.")
            self._draft_refs.add(field["target"])
            receipts.append(f'Verified field "{str(current.get("label", "field")).strip()[:80]}": requested value matches read-back.')
        if name == "browser_select_option":
            current = await self._inspect(target)
            if set(args["values"]) != {v["value"] for v in current.get("selected", [])}:
                raise McpToolError("The selected options did not match the request.")
            self._draft_refs.add(target)
        label = str((node or {}).get("label", "page"))[:80]
        message = f"Verified {name.removeprefix('browser_')} on {urlsplit(self.url).hostname or 'selected tab'}: {label}"
        self.verified_steps.append(message)
        self.verified_steps.extend(receipts)
        if checks or name == "browser_select_option":
            self.verified_edits.append(message)
        if submitting:
            observed = self.observation()
            signals = re.findall(r"(?im)^.*\b(?:received successfully|submitted successfully|thank you|receipt|successfully sent|confirmation number|draft received|application received)\b[^\n]*", observed)
            fresh_signals = [signal for signal in signals if signal not in before_submission]
            if not fresh_signals:
                raise McpToolError("Submission was sent, but acceptance could not be verified. Do not resend automatically; inspect the outcome first.")
            proof = "Verified submission outcome: " + fresh_signals[0][:240]
            self.verified_submissions.append(proof)
            self.verified_steps.append(proof)
        if submit_after_type:
            return await self.act("browser_press_key", {"key": "Enter"})
        return message
