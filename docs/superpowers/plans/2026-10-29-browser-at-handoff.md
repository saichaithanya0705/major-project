# `@browser` Chat Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start safe browser work from one `@browser` chat message while keeping existing natural-language browser routing.

**Architecture:** A typed parser identifies leading user-authored markers and direct-link/current-tab policy. The connected runner creates a tab only for a direct ordinary user URL, and the input renderer adds a keyboard-first mention suggestion.

**Tech Stack:** Python 3.11, asyncio, Playwright MCP extension, Electron HTML/CSS/ES modules, pytest.

---

### Task 1: Parse and route explicit browser handoffs

**Files:**
- Create: `agents/browser/handoff_intent.py`
- Modify: `agents/browser/connected_control.py`
- Modify: `models/routing/routing_guardrails.py`
- Test: `tests/test_browser_handoff_intent.py`
- Test: `tests/test_routing_policy.py`

- [ ] **Step 1: Add failing tests for marker parsing and deterministic routing.**

```python
def test_explicit_handoff_parses_link():
    intent = parse_browser_handoff("@Browser inspect https://example.test/form")
    assert (intent.task, intent.direct_url, intent.tab_policy) == ("inspect https://example.test/form", "https://example.test/form", "owned_url")

def test_current_tab_disables_owned_tab_policy():
    assert parse_browser_handoff("@browser use current tab https://example.test").tab_policy == "current"

def test_explicit_handoff_beats_ambiguous_route():
    result = apply_routing_guardrails_route("@browser inspect https://example.test", {"agent": "direct", "response_text": "hi"}, None)
    assert result == {"agent": "browser", "task": "inspect https://example.test"}
```

- [ ] **Step 2: Run `& .\.venv-1\Scripts\python.exe -m pytest tests/test_browser_handoff_intent.py tests/test_routing_policy.py -q`; expect parser/routing failure.**

- [ ] **Step 3: Create `BrowserHandoffIntent(task, direct_url, tab_policy)` and `parse_browser_handoff(text)`.**

```python
match = re.match(r"^\s*@browser\b\s*(.+?)\s*$", text or "", re.I | re.S)
if not match:
    return None
task = match.group(1).strip()
url = first_ordinary_http_url(task)
policy = "current" if CURRENT_TAB_RE.search(task) else "owned_url" if url else "selected_or_ask"
return BrowserHandoffIntent(task, url, policy)
```

Accept only credential-free HTTP(S) URLs. Re-export an explicit-request helper from `connected_control.py`. In guardrails, route explicit markers before `connected_session_request()`, strip only the marker, and leave the normal prompt check intact.

- [ ] **Step 4: Run `& .\.venv-1\Scripts\python.exe -m pytest tests/test_browser_handoff_intent.py tests/test_routing_policy.py tests/test_connected_browser_integration.py -q`; expect PASS.**

- [ ] **Step 5: Commit only parser, guardrail, and test files with message `Add explicit browser handoff routing`.**

### Task 2: Bootstrap direct links and load trusted skills

**Files:**
- Modify: `agents/browser/connected_runner.py`
- Modify: `agents/skills/browser_skills.py`
- Create: `tests/test_browser_handoff_runner.py`
- Modify: `tests/test_browser_instruction_skills.py`

- [ ] **Step 1: Add failing runner tests.**

```python
async def test_direct_url_creates_one_selected_tab(client):
    result = await ConnectedBrowserRunner(client, decide=done).execute("@browser inspect https://example.test")
    assert client.tab_new_calls == [{"action": "new", "url": "https://example.test"}]
    assert client.selected_index is not None
    assert result["success"]

async def test_current_tab_request_never_creates_a_tab(client):
    result = await ConnectedBrowserRunner(client, decide=done).execute("@browser use current tab and summarize")
    assert client.tab_new_calls == []
    assert result["result"]["awaiting_input"]
```

- [ ] **Step 2: Run `& .\.venv-1\Scripts\python.exe -m pytest tests/test_browser_handoff_runner.py tests/test_browser_instruction_skills.py -q`; expect missing bootstrap/skill helper failures.**

- [ ] **Step 3: Add `BrowserSkills.activate_for_task(task)` and runner bootstrap.**

```python
def activate_for_task(self, task: str) -> dict[str, str]:
    active = {"browser-operator": self.activate("browser-operator")}
    # Add one trusted relevant specialization and any explicit trusted skill.
    return active
```

For `owned_url`, the runner privately calls `browser_tabs:new`, refreshes listings, finds the exact URL, and invokes existing `select_tab()` before the first observation. For `current` and `selected_or_ask`, never create a tab; retain the objective and request sharing/selection. The planning model never receives pre-selection new-tab capability.

- [ ] **Step 4: Run `& .\.venv-1\Scripts\python.exe -m pytest tests/test_browser_handoff_runner.py tests/test_browser_instruction_skills.py tests/test_browser_personal_inputs.py tests/test_browser_review_regressions.py tests/test_connected_browser_runner.py -q`; expect PASS.**

- [ ] **Step 5: Commit scoped runner, skills, and tests with message `Bootstrap browser links with trusted skills`.**

### Task 3: Add mention discoverability, docs, and evidence

**Files:**
- Modify: `ui/input.html`
- Modify: `ui/input_window.js`
- Modify: `ui/input_window.css`
- Modify: `docs/BROWSER_EXTENSION.md`
- Modify: `docs/BROWSER_IMPLEMENTATION_REPORT.md`
- Modify: `tests/test_ui_input_window_controls.py`
- Modify: `tests/test_ui_discoverability.py`

- [ ] **Step 1: Add failing UI assertions.**

```python
def test_browser_mention_menu_is_accessible():
    assert 'id="browser-mention-menu"' in input_html
    assert 'aria-activedescendant' in input_html
    assert "insertBrowserMention" in input_window_js
```

- [ ] **Step 2: Run `& .\.venv-1\Scripts\python.exe -m pytest tests/test_ui_input_window_controls.py tests/test_ui_discoverability.py -q`; expect mention assertion failure.**

- [ ] **Step 3: Add one hidden listbox option.**

Show `@browser — Control a connected browser` only for current `@`/`@bro…` token. Arrow keys select; Enter/Tab inserts `@browser `; Escape closes; normal Enter sends when closed. Preserve existing voice/send behavior and compact styles. Document both entry points, direct-link owned tabs, shared-current-tab behavior, trusted skills, literal values, and chat-only final submission review.

- [ ] **Step 4: Run focused tests, `node --check ui/input_window.js`, complete suite batches, and `git diff --check`; expect PASS.**

Live-qualify only on the local fixture: one `@browser` direct-link request must select one owned tab, show trusted-skill evidence, read back synthetic draft values, and keep submission count zero before confirmation.

- [ ] **Step 5: Commit scoped UI/docs/tests with message `Add discoverable browser handoff`, then push `main`.**

## Self-review

- Covers both explicit and ordinary entry paths, selected/current/owned tab policy, trusted-skill injection, discoverability, form safety, docs, tests, and live fixture proof.
- Uses the same `BrowserHandoffIntent`, `parse_browser_handoff`, and `owned_url`/`current`/`selected_or_ask` names throughout.
- No automatic access to unrelated tabs, arbitrary skill scripts, or broad new browser tools.
