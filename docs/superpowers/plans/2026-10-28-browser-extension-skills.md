# Extension Browser Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute general browser tasks in a user-selected Chrome session through the official extension, with portable skills and chat confirmation only before form submission.

**Architecture:** Extend the pinned MCP transport with typed results and an extension connection mode. A narrow action gateway owns DOM inspection, form-submission review, and verification; a bounded model loop uses that gateway and the shared provider brain. Browser skills extend the loop without granting permissions or requiring a matching specialization.

**Tech Stack:** Python 3.11, asyncio, MCP SDK 1.26.0, jsonschema 4.26.0, pinned official Playwright MCP, existing NVIDIA/Gemini brain and Electron chat UI.

**Spec:** `docs/superpowers/specs/2026-10-28-browser-extension-skills-design.md` (approved 2026-10-28 after submission-only clarification).

## Global Constraints

- Chrome first; Brave and Comet are compatibility candidates, not promised supported browsers.
- No automatic fallback from extension mode to a managed browser.
- Routine browser actions and user-authorized field entry proceed automatically; form submission requires chat review, including Enter/SPA equivalents; search does not prompt.
- No model-authored JavaScript, shell, uploads, browser-wide close, or skill-script execution.
- Fixed private DOM readers only; actual target inspection, stale-reference checks, value read-back, masked secrets, and bounded results.
- Standard SKILL.md YAML/Markdown; trusted activation, resource containment, optional specialization, and legacy CLI compatibility.
- Disconnect/stop leaves the user's browser and tabs intact; completion requires observed evidence.
- Keep keys and private browser evidence out of Git and ordinary logs.

## Review Focus

- A tool can return an error as text or MCP `isError`; neither counts as success (Task 1).
- Real form submission includes default buttons, Enter, and SPA controls, while search remains automatic (Task 2).
- The page can change while the user reviews; old approval must not execute on changed state (Task 2).
- Skill collisions, edited trust hashes, references outside the skill directory, and a missing specialized skill must not widen tools or disable the base operator (Task 3).
- Existing routing still sends “my browser” to desktop vision; extension mode must route selected-session tasks correctly without claiming arbitrary profiles/windows (Task 4).

## File map

- Modify `agents/browser/mcp_client.py`: explicit connection configuration, persistent transport ownership, typed responses, schemas, bounded calls.
- Create `agents/browser/connected_gateway.py`: allowed tools, fixed DOM readers, snapshot identity, policy and postconditions.
- Create `agents/browser/connected_runner.py`: bounded observe/act/verify loop, cancellation, incomplete results, shared brain integration.
- Create `agents/skills/browser_skills.py`: browser-only standard discovery/trust/activation/resources; preserve the old registry consumers.
- Modify `agents/skills/__main__.py`: explicit browser-skill trust command.
- Create `skills/browser-operator/SKILL.md`, `skills/browser-research/SKILL.md`, `skills/browser-form-fill/SKILL.md`.
- Modify `core/confirmations.py`: required submission review and explicit cancellation while preserving legacy callers.
- Modify `agents/browser/agent.py`, `models/routing/routing_guardrails.py`, `models/routing/prompts.py`, `app.py`: connected routing/lifecycle and deterministic chat commands.
- Create focused test modules for each unit plus a local browser fixture and live probe.
- Add `docs/BROWSER_EXTENSION.md` and implementation/readiness evidence to the design delivery report.

---

### Task 1: Typed MCP connection

**Files:** `agents/browser/mcp_client.py`, `tests/test_browser_mcp_client.py`, `tests/test_connected_browser_transport.py`, integration package/lock only if compatibility requires a pin change.

**Interfaces:**
- Produce `McpToolResult(text: str, is_error: bool, structured: dict | None)` and `McpToolError`.
- `PlaywrightMcpClient(project_root=None, *, extension=False, browser='chrome', executable_path=None)`.
- `await call_result(name, arguments=None) -> McpToolResult`; keep `call_tool(...) -> str` for existing consumers.
- `await tool_schemas() -> dict[str, dict]`; tool argument validation remains the gateway's responsibility.
- Session protocol operations run on one owner asyncio task, because MCP stdio cleanup uses AnyIO cancellation scopes.

- [ ] Write `test_extension_launch_is_explicit_and_local`, `test_error_result_is_preserved`, `test_schema_catalog_is_exposed`, and `test_cross_task_calls_close_owner_cleanly`; assert no `npx`, extension/channel flags, errors retained, schemas usable, owned process ends.
- [ ] Run `python -m pytest -q tests/test_connected_browser_transport.py`; expect missing interfaces/failed assertions.
- [ ] Implement typed transport, validated config, bounded requests, clean ownership; install the existing local lockfile with `npm ci`, inspect actual CLI/tools, and record pin compatibility.
- [ ] Run `python -m pytest -q tests/test_connected_browser_transport.py tests/test_browser_mcp_client.py`; expect all passing.
- [ ] Commit the exact transport/tests and record Task 1 evidence in the ledger.

### Task 2: Inspected actions and submission review

**Files:** create `agents/browser/connected_gateway.py`, `tests/test_connected_browser_gateway.py`; modify `core/confirmations.py` and its existing tests only as needed.

**Interfaces:**
- Consume `PlaywrightMcpClient.call_result/tool_schemas`.
- Produce `ConnectedGateway(client, confirm, stopped)` with `await observe() -> str`, `await act(name: str, arguments: dict) -> str`, and `tool_catalog() -> dict`.
- Gateway owns `generation`, current URL/title, selected-tab state, verified progress, and safe result summaries.
- `ConfirmationBroker.request(action, *, required=False) -> bool`; `cancel()` declines pending review.

- [ ] Write tests for automatic input/search, HTML/default/SPA submission and Enter, mandatory approval despite legacy bypass, refusal, changed state during approval, batched fields, read-back mismatch, unknown refs/tools, invalid URLs/arguments, MCP errors, and no raw model evaluation.
- [ ] Run `python -m pytest -q tests/test_connected_browser_gateway.py`; expect missing gateway/failing new required-review contracts.
- [ ] Implement a strict allowlist and installed-schema validation, fixed targeted and active-element DOM readers, form state fingerprints, fresh observations, masking and one-shot submission approval; uninspectable targets stop safely.
- [ ] Run gateway tests plus existing `tests/test_browser_action_guard.py`; expect passing without managed-mode policy changes.
- [ ] Commit the gateway/review contracts and ledger Task 2 evidence.

### Task 3: Portable browser skills and bounded execution

**Files:** create `agents/skills/browser_skills.py`, three browser skill folders, `agents/browser/connected_runner.py`, `tests/test_browser_instruction_skills.py`, `tests/test_connected_browser_runner.py`; modify skill CLI.

**Interfaces:**
- `BrowserSkills(project_root, *, home=None)` with `catalog(task)->str`, `activate(name)->str`, `resource(name, relative_path)->str`, and `trust(path)->str` (content digest).
- `ConnectedBrowserRunner(client, *, decide=None, confirm=None, status=None)` with `await execute(task)->dict`, `request_stop()`, `await disconnect()`, and remembered objective/verified progress only.
- `decide(system: str, user: str) -> awaitable[str]` returns strict JSON `{tool, arguments}` or `{done, summary, evidence}`; default calls the shared brain in JSON mode.
- Limits: 20 decisions, 120 active seconds excluding confirmation wait, two invalid-output corrections, no automatic consequential replay.

- [ ] Write skill tests for standard validation, browser-only discovery across roots, trusted-hash changes, collision precedence, resource escape, exact allowed-tools intersection, and no-specialization fallback; write runner tests for novel task execution, invalid output/no side effect, false completion, stop/resume and failed provider.
- [ ] Run both new modules; expect missing interfaces.
- [ ] Implement standard instruction-only loading and explicit CLI trust; ship general/research/form skills; implement the bounded loop with schema correction, activation/resource reads, redacted decisions, verified/incomplete results, and cancellation cleanup.
- [ ] Run `python -m pytest -q tests/test_browser_instruction_skills.py tests/test_connected_browser_runner.py tests/test_skills.py`; expect passing.
- [ ] Commit the skills/runner and ledger Task 3 evidence.

### Task 4: App integration and live qualification

**Files:** modify BrowserAgent, routing guardrails/prompts and app lifecycle; create `tests/test_connected_browser_integration.py`, `tests/fixtures/browser_operator.html`, `evals/browser_extension_probe.py`, and `docs/BROWSER_EXTENSION.md`; update README/design/readiness record.

**Interfaces:**
- BrowserAgent owns a process-lifetime connected runner in extension mode before any managed heuristics; `request_stop_all`, resume and cleanup delegate to it.
- Deterministic chat commands: `connect browser`, `disconnect browser`, `browser status`, and `use browser tab N`; Stop is consumed before a pending confirmation answer.
- Extension route rewrites apply to browser-session tasks only; native window management remains desktop vision and arbitrary profile switching is not implied.
- Existing step result contract surfaces connected summary, `complete`, and error through normal text/voice app input.

- [ ] Write integration tests for mode isolation/no fallback, chat control routing, selected-session vs native window routing, confirmation delivery/cancel, and result completeness.
- [ ] Run `python -m pytest -q tests/test_connected_browser_integration.py`; expect missing integration behavior.
- [ ] Wire lifecycle/routing/chat commands, add synthetic research/form fixture and repeatable real-MCP probe; document extension installation, skill authoring/trust, stop/resume, limitations and exact tested versions.
- [ ] Run all focused browser/skills/routing/UI tests, then full suite; inspect all failures and compare against baseline.
- [ ] Run a real MCP fixture probe and NVIDIA-backed generic task; attempt the official extension connection on this device, using user pairing when required, and explicitly distinguish installed/session evidence from fixture-only results.
- [ ] Commit implementation/docs and record Task 4 evidence; obtain one fresh whole-branch review, fix consequential findings with failing regressions, run final checks, then integrate into main and clean only owned temporary resources.

## Self-review and execution

Each spec boundary maps to Tasks 1-4; transport/result and gateway/runner signatures
above are shared exactly. The approved request explicitly authorizes implementation;
execute natively in this session rather than request another workflow approval.
The main agent owns planning, integration, tests and final decisions; one fresh
reviewer checks the complete change after implementation under executing-plans.
