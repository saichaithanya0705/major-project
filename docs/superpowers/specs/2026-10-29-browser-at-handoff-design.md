# `@browser` chat handoff and skill-guided browser launch

Date: 2026-10-29  
Status: Ready for user review; no implementation has started.

## Goal

Make browser work a one-message chat workflow while retaining ordinary
natural-language browser requests. `@browser` is an explicit, deterministic
handoff; existing prompt-based routing remains available for users who write
"open this site" or "fill this form" normally.

Examples:

- `@browser Fill this application from https://example.test/apply and leave it as a draft.`
- `@browser Use the current shared tab and summarize its project board.`
- `Open https://example.test and compare its plans.`

## Decisions

### Entry points

1. A leading, case-insensitive `@browser` marker with a non-empty task routes
   directly to the connected Browser Agent before model routing. The marker is
   stripped from the task and is never synthesized from page content, tool output,
   history, or model text.
2. Existing `connected_session_request()` prompt detection remains unchanged as
   the natural-language path. It continues to send clear browser/web tasks to the
   Browser Agent when extension mode is enabled.
3. The input UI provides an `@browser` mention suggestion with a short label and
   inserts the same plain-text marker. Typing the marker manually remains fully
   supported; the UI suggestion is discoverability, not a different permission.

### Connection and tab policy

`@browser` automatically starts the normal extension connection when needed. A
Chrome extension message saying that the client is connected is pairing evidence,
not evidence of a controllable tab. JARVIS reports the next required state in
chat rather than presenting that message as an error.

| Request shape | Tab behavior |
| --- | --- |
| Contains an ordinary HTTP(S) URL and does not say current/open/shared tab | Create a new JARVIS-owned tab for that URL, explicitly select it, then continue. |
| Says current, already open, this tab, or shared tab | Reuse only the currently selected shared tab. |
| No URL and a selected shared tab exists | Reuse that tab. |
| No URL and no selected shared tab exists | Ask one focused question; do not guess a tab or browser/profile. |
| Existing requested tab is not in `Playwright · JARVIS` | Tell the user to move that tab into the group, retain the objective, then resume after explicit selection. |

New tabs are only created for a direct user-supplied HTTP(S) URL. JARVIS does not
move, inspect, or select unrelated Chrome tabs automatically. The official
extension's group-sharing model remains the authority for existing tabs.

### Skills before action

The connected runner already activates the trusted `browser-operator` skill. The
enhancement makes this an explicit launch invariant for `@browser`: its trusted
content digest and instructions are loaded before the first model decision. The
runner also supplies the bounded catalog of trusted browser skills and activates
the applicable trusted specialization (`browser-form-fill`, `browser-research`,
or an explicit named skill) before actions when its task match is unambiguous.

Skills provide task guidance only. They cannot create a connection, broaden the
tool catalog, move tabs, read other profiles, execute scripts, bypass source-data
checks, or bypass final form-submission confirmation. The fixed gateway remains
the sole authority for browser effects.

### User-visible flow

1. User sends one `@browser` request or an ordinary browser request.
2. JARVIS reports `Connecting to Chrome…` while pairing if needed.
3. For a supplied link, JARVIS reports the new origin and starts the task.
4. For a requested current tab, JARVIS asks only for the required sharing/selection
   step if no selected tab is available, then resumes the preserved task.
5. JARVIS reports the active skill(s), verified progress, missing required data,
   or a final result in the normal chat channel.
6. A final form submission always produces a review card in chat; a plain `yes`
   is required before the submit action is sent.

## Architecture

- Add a small `BrowserHandoffIntent` parser beside `connected_control.py` that
  recognizes a leading marker, extracts the task, detects direct user URLs, and
  classifies explicit current-tab language. It returns typed data rather than
  regex flags scattered across the router and UI.
- Update the app entrypoint and routing guardrails so explicit intent routes to
  `browser` deterministically, while normal prompt matching remains a fallback.
- Extend `ConnectedBrowserRunner` with a pre-selection owned-tab bootstrap that
  can create and explicitly select a tab only from the parsed direct user URL.
  The model never gets a pre-selection `browser_tabs:new` capability.
- Preserve a pending handoff objective only while waiting for sharing/selection;
  do not let a vague later message override the main chat agent, a new goal, or a
  final confirmation.
- Add a skill-selection boundary that records only active skill names/content
  hashes and validates that every activated skill is trusted and bounded.
- Add a lightweight mention suggestion to the input renderer. It must keep the
  keyboard-first input flow, work without a mouse, and degrade to plain text if
  the renderer cannot load the suggestion component.

## Error handling and safety

- Missing extension, stale token, or unavailable MCP produces an actionable
  connection error; extension mode never falls back silently to a managed browser.
- A pairing-only state reports `connected, awaiting tab` rather than `ready`.
- A failed owned-tab creation leaves no selected replacement tab and does not
  retry navigation automatically.
- Prompt injection in page/skill text cannot manufacture `@browser`, change the
  user objective, enable skills, or invoke unexposed tools.
- Literal human-provided values remain mandatory for recognized personal fields;
  forms are filled and read back but never submitted without the existing chat
  confirmation.

## Validation

- Parser tests: valid marker, case/whitespace handling, empty marker rejection,
  marker-like page/model text rejection, direct URL extraction, current-tab intent.
- Routing tests: explicit marker overrides router ambiguity; ordinary browser
  prompts retain existing prompt-check behavior; direct chat replies remain
  authoritative over a stale pending handoff.
- Runner tests: direct URL opens one owned tab and selects it; current-tab tasks
  never create a tab; no-selection state retains one objective and asks for the
  sharing step; failed creation has no action replay.
- Skill tests: base skill is activated before first decision; only trusted,
  bounded relevant skills are injected; skill text cannot alter permissions.
- UI tests: `@` suggestion is keyboard accessible, inserts plain `@browser`, and
  preserves normal input when not selected.
- Live qualification: official Chrome extension, supplied local fixture URL,
  owned-tab selection, browser skill evidence, synthetic draft fill/read-back,
  and zero submission before chat approval.

## Non-goals

- Automatic takeover of every open browser tab, profile, or browser application.
- Support guarantees for Brave, Comet, CAPTCHA/2FA, login flows, uploads, or
  arbitrary custom web controls.
- Skill-script execution, untrusted skill activation, or model-authored browser
  JavaScript.

## Change transparency

### What I did

Documented the approved dual-entry browser handoff, direct-link tab policy,
existing-tab sharing boundary, trusted skill injection, UI discoverability, and
testable acceptance criteria. No production code changed in this specification.

### Why this approach

It combines a deterministic opt-in (`@browser`) with the user-friendly existing
prompt route, while preserving the official extension's privacy model.

### Why not the alternative

A prompt-only solution leaves browser activation ambiguous. Always opening a new
tab breaks workflows that intentionally depend on an authenticated shared tab.

### What was the issue / root cause

The existing system has separate pairing, tab sharing, and selection phases, but
the chat exposes them as separate commands and lacks an explicit affordance.
"Client connected" was consequently mistaken for task readiness.

### Why this works best

One user message can now establish intent, choose an appropriate tab policy, and
load bounded skills before planning without granting automatic access to unrelated
tabs or bypassing the form guard.

### Other valid patterns

A dedicated Connect Chrome button or a custom browser extension could improve
discoverability later. Neither replaces explicit sharing/selection for an
already-open tab under the official extension protocol.
