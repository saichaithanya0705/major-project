# Browser control through the Playwright extension and Agent Skills

Date: 2026-10-28
Status: Approved for implementation by the user on 2026-10-28, including the multipurpose operator and submission-only clarification.

Revision: User clarified that the browser agent must be multipurpose, with chat-UI
confirmation specifically before form submission, not before routine interactions
or field entry. This revised behavior supersedes the broader confirmation policy
in the first draft.

## Intent and decisions

JARVIS should act in the user's existing browser session: inspect a page, search,
navigate, click controls, fill forms, check values, and complete authorized tasks.
Procedures belong in portable Agent Skills files so adding a workflow does not
require rebuilding the application when existing tools are sufficient. This is a
general browser operator: a task-specific skill is helpful but not required. The
base observation/action/verification loop must handle unfamiliar ordinary web
tasks using available tools rather than reject them because no named skill exists.

The user uses Comet, Chrome, and Brave interchangeably and selected **the official
Playwright extension first**, rather than a custom JARVIS extension. The initial
release targets Chrome. Brave and Comet are compatibility candidates, not promised
supported browsers: upstream documents extension mode for Chrome/Edge only.
Failure in either candidate must not delay the Chrome presentation path.

This is a moderate feature spanning browser execution, skill loading, and
validation, not just an extension installation. Calls below that were not explicitly
selected by the user are design recommendations for approval.

## Goals, constraints, and exclusions

- Control a browser/profile and tab deliberately selected by the user, retaining
  that browser's existing login state without exporting cookies or credentials.
- Support general browser tasks: research, comparisons, extraction, navigation,
  multi-page workflows, web-app controls, and form filling, with reliable
  read-back and meaningful evidence; distinguish progress from completion.
- Add skills as folders containing standard `SKILL.md`; load relevant instructions
  on demand instead of embedding website procedures in application code.
- Keep the existing managed browser available as a separately selected mode.
- Reading, navigation, searching, clicking ordinary controls, selecting options,
  and entering user-supplied values proceed autonomously within the requested task.
  Ask for confirmation in the existing JARVIS chat UI before form submission;
  field sensitivity alone does not add an action-confirmation prompt.
- Missing information may still require a question; browser permission prompts,
  login/2FA challenges, CAPTCHAs, inaccessible controls, and unavailable tools may
  require user assistance. General purpose does not mean guaranteed success on
  every website or arbitrary tasks outside browser capabilities.
- No custom extension, stealth configuration, CAPTCHA bypass, automated credential
  discovery, model-supplied page JavaScript, or background unattended purchases in v1.
- Instruction skills and references are supported for browser tasks; executing
  skill scripts is excluded from this first browser release.
- The existing screen/voice implementations and unrelated CLI skill behavior are
  outside this enhancement.

## Approaches considered

| Approach | Benefit | Cost or limitation | Decision |
| --- | --- | --- | --- |
| Official Playwright extension plus shared skills | Reuses upstream connection and existing sessions; smallest extension maintenance burden | Browser/version compatibility still needs live qualification | User selected |
| Custom JARVIS Chromium extension plus shared skills | More control over connection and browser selection UX | Extension lifecycle, authentication, updates, and permissions become project responsibilities | Deferred |
| Managed browser only plus skills | Existing isolated browser remains easy to test | Does not satisfy acting in the user's current logged-in browser | Retain as explicit alternative mode |

## Current code and root gaps

- `agents/browser/agent.py` chooses managed Playwright or browser-use, with
  navigation fast paths and a separate MCP snapshot path; browser-use has an
  interactive loop, but it does not consume the existing skill registry.
- `agents/browser/mcp_client.py` launches the local MCP executable with no
  extension arguments. It returns text only, losing MCP error/result structure,
  and health checks establish tool availability rather than a connected user tab.
- `integrations/playwright_mcp/package.json` pins `@playwright/mcp` to `0.0.73`;
  its `node_modules` is absent in this checkout. Current upstream documentation
  is not proof that this older pin has every currently documented option.
- `agents/skills/registry.py` discovers bundled `skills/` and
  `JARVIS_SKILLS_DIR` (default `~/.jarvis/skills`). CLI agents already use this;
  project/user `.agents/skills` discovery is not currently implemented.
- `agents/skills/manifest.py` reads YAML and Markdown, but supports legacy nested
  `metadata.jarvis` and does not enforce every standard authoring constraint.
  `allowed-tools` is not currently an operational permission boundary.
- `agents/browser/action_guard.py` covers browser-use actions; it is not a guard
  for MCP tools, and unresolved click targets currently pass its classification.
  Connected-mode actions must not inherit that failure-open behavior.

## Architecture and ownership

### 1. Connection adapter and lifecycle

Extend `PlaywrightMcpClient` with an explicit connection configuration rather than
launching a second independent browser agent. New connected tasks select the
extension adapter before existing managed-browser heuristics run.

Use the locally installed, pinned official MCP executable in `--extension` mode.
During implementation, inspect the chosen pin's CLI/schema and extension protocol;
retain `0.0.73` if compatible or update package and lockfile together to a verified
stable release. No runtime `@latest` downloads. Use upstream's installation and
pairing flow; optional pairing credentials, if needed by that exact version, stay
in ignored local configuration and are redacted from logs.

Recommend `JARVIS_BROWSER_MODE=managed|extension`, default `managed` to preserve
existing installations; the presentation's local configuration selects `extension`.
Profile/channel or executable options are exposed only when the selected upstream
version actually supports them. Do not infer browser or profile identity from a
model response. Show the configured browser label as configuration, and the
observed selected tab's title and origin as live connection evidence.

Only one connected task owns the session at a time. Connection states are
disconnected, connecting, awaiting user pairing, ready, running, awaiting approval,
stopped, or failed. Readiness requires a successful snapshot of the selected tab,
not just `list_tools`. Bound connection and action timeouts and show actionable
missing-extension, denied-pairing, stale-tab, and disconnected errors.

The user explicitly selects/authorizes the browser through upstream's connection
flow. Multiple possible tabs require a choice; do not guess from the active window
or switch to another browser because a task failed. Tab selection is bound to the
session generation; indices are re-resolved from fresh tab listings before use.
Navigation is allowed within the selected tab, and user-requested new tabs may be
opened. Unrelated tab content is not added to model context.

Disconnect stops JARVIS-owned MCP processes and invalidates references/approvals;
it does not close the user's browser, delete a profile, or close user tabs.
Closing tabs is not exposed in v1. Reconnection requires fresh tab selection and
snapshot. There is no automatic fallback from extension mode to a managed browser.

### 2. Validated browser action loop

Add a focused connected runner under `agents/browser/`, called from
`BrowserAgent.execute`, rather than growing its existing orchestration methods.
Reuse `models.brain.generate_brain_reply` for provider selection, including the
live-tested NVIDIA primary. The model proposes one action at a time; runtime
validation and policy run before every tool call.

The initial tool set is snapshots and page-content extraction, tab
listing/selection/new-tab, HTTP(S) navigation/back, link/control clicks, typing,
form filling, option selection, scrolling, bounded key presses, and waiting for
observable page changes. This common tool set supports new tasks without a
website-specific script or skill; skills add guidance and recovery knowledge.
Map to the exact
MCP tool schemas returned by the installed server. No raw `evaluate`, run-code,
shell, filesystem, upload, browser-wide close, or unrecognized tools are exposed.

Accessibility text alone is not authoritative for input type, submit behavior, or
current values. Add a private runtime-owned DOM inspector for these facts, using
the verified server's element-targeted evaluation capability with fixed source
code checked into the adapter. It reads only the resolved element's tag, relevant
attributes, value, selected options, checked state, and validation state. It must
not mutate DOM, dispatch events, submit, fetch, access storage/cookies, enumerate
unrelated fields, or write output files. No model/page/skill text is interpolated
into executable source or selectors; targets come from current snapshot refs.
Password/OTP/payment fields expose classification and presence only, not their
contents. Other values stay in runtime for masked verification where possible.

This inspector is an internal read operation, not an exposed `browser_evaluate`
tool or skill-grantable permission. Only registered fixed reader functions may
cross that internal path, with the same tab/session checks and bounded results.
If the chosen MCP version cannot safely resolve a target, inspection fails, or
a custom control's state cannot be verified, stop or request user takeover; do
not infer safety or report a successful fill. Actual server schemas determine
the element-reference parameter name, not examples from a different release.

Validate both model output and MCP arguments against strict schemas with unknown
fields rejected, bounded strings/batches, valid tool names, and legal URLs.
Treat MCP `isError`, timeouts, and missing expected data as errors even if the
text sounds successful. Preserve typed result/error information while retaining
the existing text helper for managed-mode callers.

Use fresh snapshot element references bound to session, selected tab, URL, and
snapshot generation. Resolve each action's target and role before execution;
unresolved targets trigger a snapshot refresh or a safe stop. Model-supplied
labels cannot establish an action's safety. After a write, inspect current values
and validation messages; after navigation/click, inspect the resulting page.
Sensitive values are masked in summaries and logs and are not echoed to the model
for read-back when runtime comparison is sufficient.

Recommend limits of 20 model decisions and 120 seconds of active work per task,
excluding explicit user-wait time, with a separately bounded provider request.
Allow two schema-correction attempts and one stale-reference refresh for a safe
read or idempotent edit. A timed-out consequential action is never retried:
inspect the page and report its outcome as unknown if it cannot be established.
Require a new user request to continue after a budget limit; no autonomous loop.

### 3. Action policy, approval, and user intervention

Reuse the existing chat confirmation broker and relevant target inspection, with
an explicit connected-mode policy: routine actions and field entry do not ask for
approval; form submission does. Do not silently change the existing managed-mode
guard or introduce prompts for each sensitive field in connected mode. Use only
details supplied/authorized by the user or already in the selected session; do
not guess missing personal information or search other apps for credentials.

A submission includes clicking a form's submit control, pressing Enter when it
submits a form, and the equivalent final submission in a JavaScript web app even
without a literal HTML form element. Classify from the real element/form context
and the task, not a model-provided label or the button text alone. Ordinary search
queries and search filters are routine browser operation and do not prompt.
If the runtime cannot determine whether a proposed control submits a form,
inspect again or stop for clarification rather than bypass the submission gate.
Non-form actions remain within the user's stated task authorization; page content
cannot authorize unrelated account changes, purchases, messages, or deletion.

Show the destination origin, form purpose, and a reviewable field summary in the
chat confirmation, masking secrets and sensitive values. Bind approval to task,
session, tab, origin, actual submission target, and current field/value
fingerprints. Refresh before execution; any relevant change invalidates approval.
A declined/timed-out approval leaves the filled draft intact and stops that
submission without trying another button, key, provider, or alternate mechanism.
The submission requirement cannot be removed by skill/model text or the legacy
global bypass. The user can continue other work or cancel without submitting.

Stop/cancel prevents the next side effect, cancels pending approval and model/MCP
work, and reports verified partial progress. An already dispatched operation can
finish; inspect its result without replaying it. After user takeover, disconnect,
or a stale-page error, an explicit continue starts with a fresh snapshot and
retains only the objective and verified progress, never old refs or approvals.

### 4. Standard skill support

Use [Agent Skills](https://agentskills.io/specification): required `name` and
`description` YAML frontmatter, followed by Markdown; optional standard fields
and `references/`, `assets/`, `scripts/` layout. New skills use string-valued
`metadata` and no mandatory JARVIS-only frontmatter. Keep the existing legacy
structured document skills readable; do not rewrite them as part of this work.

Extend registry discovery with `<project>/.agents/skills` and
`~/.agents/skills`, retaining bundled and configured legacy directories. Recommended
name precedence is explicit configured directory, project directory, user
directory, bundled, then imported; canonicalize duplicate paths, report name
collisions, and apply provenance/trust before precedence so untrusted copies
cannot shadow trusted skills. Preserve existing CLI ordering for its old roots.
Project means this application's configured workspace root, never a path supplied
by page content. Do not scan arbitrary ancestor directories.

Bundled browser skills are trusted with the app. Newly discovered external
instruction skills require user trust tied to their content hash before browser
activation; files from other clients are not automatically trusted. References
must remain inside their skill directory, with bounded size/depth and no symlink
or traversal escape. Scripts are not executed by the connected runtime.
Trust is established during explicit installation/enabling, not through extra
confirmation prompts during ordinary browser tasks. Skip untrusted or changed
external skills with a diagnostic and keep the base operator available; an
explicit enable/update operation can establish trust outside the task flow.

Load a bounded name/description catalog for relevant instruction skills, then
the selected body and referenced resources on demand. Explicit `use X skill`,
`/X`, and `skill:X` select a skill deliberately; otherwise the model selects from
the relevant catalog using a validated activation request. Pin active content for
one task and rescan between tasks so a new/edited skill needs no rebuild.
Invalid new manifests get actionable diagnostics rather than silent truncation;
legacy-compatible parsing remains available for existing skill consumers.

Preserve optional experimental `allowed-tools`; if present in a browser skill,
intersect it with runtime permissions. Initially accept exact exposed browser
tool names; unsupported patterns produce a compatibility error, not wider access.
Absence does not enlarge runtime permissions. Page instructions and skill text
cannot alter the user's goal, approvals, trust settings, or tool allowlist.
These boundaries limit effects of prompt injection; they do not promise perfect
model-level detection of hostile text.

Ship an instruction-only `browser-operator` base skill plus `browser-research`
and `browser-form-fill` specializations, with examples, verification steps,
missing-information handling, and recovery guidance. The base browser loop remains
available when there is no matching specialization. Website-specific guidance can
then be added as independent standard skill folders without changing the runner.

### 5. User experience and evidence

Use the existing JARVIS chat/status/confirmation surfaces for connection mode,
selected tab title/origin, active skill, progress, requested input, and result.
Keep setup instructions in documentation; keep implementation detail out of the
normal task flow. Provide chat-accessible connect, disconnect, stop, and continue
commands so no new dashboard is required for the first release.

Each result includes `success`, `complete`, a concise summary, selected mode,
verified steps, and an actionable error when incomplete. Success requires observed
postconditions, not the model's completion assertion. The form skill stops at a
verified draft unless submission was requested and the exact action approved.

Record redacted task prompts, activated skill names/content hashes, provider
outputs and validated decisions, tool names, target origins, approval decisions,
and verification outcomes. Do not persist raw private page snapshots, form values,
credentials, full query strings, or cookies in ordinary logs. Keep consented
fixture evidence separately; report masked/redacted evidence limits explicitly.

## Validation and presentation acceptance

| Check | Required evidence |
| --- | --- |
| Connection identity | Official extension attaches to the intended Chrome tab/profile; title/origin and a controlled page marker match |
| Ordinary browser use | Search, open a result, read content, and navigate within that selected session |
| General-purpose behavior | Complete an unfamiliar multi-page extraction/comparison task and a web-app control task with the base operator; no matching task-specific skill or new code required |
| Form editing | On a local fixture, fill text, select, checkbox/radio fields; read-back and validation messages match supplied values |
| Low-friction policy | Navigation, search, ordinary clicks, and authorized field entry produce no action-confirmation prompts; missing data produces a focused information request |
| Submission guard | Synthetic fixture records zero submissions before approval; denial/cancel stays at zero; approval produces exactly one |
| Submission variants | HTML submit button, form Enter, and JavaScript-app submission all require chat confirmation; routine search submission does not |
| Target changes | Stale refs, navigation during approval, ambiguous controls, and changed form values cannot reuse approval |
| Malformed output | Unknown tools, wrong types, invalid JSON, MCP error blocks, and oversized batches do not cause side effects |
| DOM inspection | Omitted snapshot attributes are recovered by the fixed reader; custom/unreadable controls stop safely; model-supplied scripts never execute |
| Hostile page/skill | Injected requests cannot enable tools, switch tabs, trust skills, or bypass final approval |
| Skill extensibility | Add a new instruction skill between tasks, activate it without restart/rebuild, and complete its fixture workflow |
| Skill compatibility | Standard examples load; legacy document/CLI skills still work; collisions, untrusted edits, and reference escapes are handled |
| Lifecycle | Stop during a pending action, disconnect/reconnect, two overlapping tasks, and MCP death leave user tabs/browser intact |
| UI and provider path | Typed and voice-originated browser requests reach the runner through the normal app protocol; confirmations appear and are consumed correctly |
| Browser candidates | Attempt equivalent non-sensitive tests in Brave/Comet only if official extension setup is supported; record exact version and result, otherwise mark unsupported/unverified |

Use focused deterministic tests for policy/schema/lifecycle failures, a real MCP
plus synthetic page integration test, then a real Chrome extension rehearsal on
this device. Inspect a fixture request log for effects; a successful model/tool
response alone is insufficient. Run the existing browser, skills, router, and UI
regressions, followed by the full suite after integration. Do not submit public
forms or use real accounts/payments to qualify behavior. Previously passing 651
tests describe the baseline, not this feature's completion.

## Delivery order and builder decisions

1. Verify/pin the official MCP and extension combination and document manual setup.
2. Implement the typed adapter, session identity, lifecycle, and narrow tool gateway.
3. Add the validated action loop, approvals, and observed postconditions.
4. Extend standard skill discovery/activation and add the base and two specialized browser skills.
5. Connect app commands/status, qualify the Chrome path, and record candidate results.

The builder may choose module names, exact schemas derived from the verified
server, timeout plumbing, and test fixture organization. Changes to provider
defaults, wider tool permissions, automatic mode switching, script execution,
or supported-browser promises require a design update.

## Change transparency

### What I did

Documented the selected extension approach, reusable skill format, execution
boundaries, current gaps, and measurable acceptance criteria; revised it to require
general-purpose operation and submission-only action confirmation after the user's
clarification. No product code or dependencies are changed by this document.

### Why this approach

It meets the existing-browser requirement while reusing upstream connection work
and this repository's provider, skill, and confirmation interfaces.

### Why not the alternative

A custom extension adds an independent maintenance surface before the presentation;
managed-only automation does not reach the user's existing session.

### What was the issue / root cause

Browser execution and skills are currently separate, and MCP is only a snapshot
adapter; installing an extension alone would not create validated task execution.
The initial draft also emphasized two workflows and inherited broader confirmation
rules than the user requested; the revised design makes the general operator and
submission-only policy explicit.

### Why this works best

Workflow instructions can evolve independently while a small, testable gateway
retains control over browser side effects and verifies actual outcomes.

### Other valid patterns

A custom extension remains a future option if candidate browser compatibility or
upstream connection UX is inadequate; managed mode remains useful for isolated
automation. Neither requires changing the standard skill format.

## Sources checked

- [Official Playwright MCP](https://github.com/microsoft/playwright-mcp), including
  its extension flag and linked extension setup; Context7 `/microsoft/playwright-mcp`
  was consulted for extension mode and tool contracts on 2026-10-28.
- [Upstream extension setup](https://github.com/microsoft/playwright/tree/main/packages/extension).
- [Agent Skills specification](https://agentskills.io/specification).
- [Skill client integration guidance](https://agentskills.io/client-implementation/adding-skills-support).

Live support of the selected package/extension/browser versions remains an
implementation acceptance check, not a conclusion drawn from these documents.

## Builder check resolution

A fresh read-only reviewer identified one consequential ambiguity: how field
classification/read-back can be authoritative when accessibility snapshots omit
DOM details and arbitrary evaluation is excluded. The design now permits the
private fixed DOM reader above while keeping arbitrary/model-authored evaluation
outside the tool gateway. This is an engineering recommendation, not a request
to broaden user-facing browser permissions. Uninspectable controls remain
unsupported rather than being treated as safe or successfully edited.

The user's later clarification broadens the acceptance examples to general tasks
and narrows confirmation to form submission in chat. The runtime-owned inspector
still provides the evidence needed to identify submission paths and verify fields;
it does not introduce extra field-entry approval prompts.
