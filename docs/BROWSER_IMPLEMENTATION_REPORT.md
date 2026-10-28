# Browser implementation and qualification — 2026-10-28

## What I did

Implemented a general browser operator using the official Playwright extension,
standard Agent Skills, inspected actions, verified field entry, and chat review
before form submission. Connected the installed Chrome profile with its locally
configured extension token. Added deterministic chat commands, cancellation,
resume, explicit tab selection, and browser-only provider/model configuration.

The runtime remains useful without a specialized skill. Bundled workflows cover
general operation, research, and forms; external workflows require content-hash
trust and cannot grant additional tools or execute scripts.

## Why this approach

An owned MCP session supplies browser primitives while the gateway validates
arguments and checks the actual selected control. The model plans one action at
a time; fixed runtime readers handle identity, submission classification and
field verification. Portable instructions extend workflows without app changes.

The existing chat confirmation channel carries required submission reviews;
legacy confirmation bypass settings cannot disable them. Token pairing first
lists metadata and waits for an explicit tab choice before reading page contents.

## Why not the alternative

A custom extension would introduce another transport and permission lifecycle to
maintain before the presentation. A fixed workflow per website would not meet the
general-purpose requirement. Model-authored page scripts would bypass the
inspected action boundary, so they are excluded from the model's tool catalog.

## What was the issue / root cause

The former browser path primarily opened a managed session. It lacked a portable
instruction-driven operator for an existing user session and a separate,
mandatory submission boundary.

The installed extension 0.4.0 rejected MCP 0.0.73's protocol 1. The pinned 0.0.83
runtime uses protocol 2. Its removed output-mode option was replaced with an
owned temporary output directory, removed when the MCP connection closes.
AnyIO session scopes now open and close in the same owner task.

Screenshot transcription was insufficient for pairing; the exact user-supplied
token authenticated successfully. It is kept only in ignored local configuration.
Real provider tests also exposed stale reference variants, lost historical source
facts, overly small evidence arrays, and a correction budget consumed by earlier
repaired actions. References are normalized and revalidated; historical facts
exclude old references; bounded evidence remains checked against observations.

## Why this works best

| Qualification | Evidence |
| --- | --- |
| Transport | Typed MCP errors, installed schemas, single-task ownership and temporary-output cleanup have regression tests. |
| Real browser fixture | All seven form/app checks passed with MCP 0.0.83 and real Chrome: five field types read back, decline caused zero POSTs, approval caused exactly one POST, receipt observed, ordinary control needed no review, SPA review occurred once and its result was observed. |
| Installed extension | Exact token authenticated; a dedicated Example Domain tab was opened, explicitly selected and read through the extension. |
| Installed Chrome end to end | Repeated all seven form/app checks through the installed extension, then completed the live NVIDIA multipage comparison in that same session; all eight checks passed in 62.485 seconds. The owned local test tab was closed afterward. |
| Live NVIDIA research | SuperVL completed a multipage comparison in 30.594 seconds, reporting both prices, memory sizes and battery measurements with source links. |
| Chat review transport | A real authenticated local WebSocket carried `confirmation_request`; the request stayed pending until a chat `yes` returned through the server. |
| Regression suite | See final validation entry below. |

Installed browser: Chrome 156.0.8078.48. Runtime pin: `@playwright/mcp@0.0.83`;
installed official extension: 0.4.0. Synthetic evidence is in ignored
`evals/results/browser-extension/`; no private browsing snapshots are committed.

The tested browser planner is `nvidia/nemotron-3.5-super-vl-120b-a12b`. Normal chat
configuration is preserved. Lightning succeeded for chat but did not qualify for
this browser task; Gemini timed out in the browser probe; catalog-listed Kimi
returned an unavailable endpoint for this account. Model availability and latency
are live dependencies. Passing one research scenario does not guarantee every
website or instruction.

## Other valid patterns

Direct CDP could control a deliberately debug-enabled profile but needs separate
launch/session handling. A custom extension may be appropriate for future
browser-specific features. A larger browser-use framework offers wider actions
at the cost of another lifecycle and policy layer. The existing managed mode is
still available for isolated browsing.

Brave and Comet, arbitrary profiles, CAPTCHAs, login/2FA, native permission dialogs,
uploads/downloads and inaccessible/custom controls remain unqualified. Submission
classification supports HTML forms and recognized SPA controls; arbitrary hidden
JavaScript side effects cannot be universally classified. The operator stops on
uninspectable state, declined approval, unverifiable completion or bounded task
failure. Stop cannot undo a request already sent to a website.

Required budgets remain 20 decisions and 120 active seconds per task, excluding
review waiting time, with two consecutive output corrections and one safe stale
refresh. Output validation prevents malformed actions and invented evidence;
it does not make the model deterministic. Production decision logs contain task
hashes, tool names and argument keys, excluding page bodies and field values.

### Final validation

The installed-session rehearsal passed all eight checks (62.485 seconds).
Full suite after the live fixes: **725 passed, 1 skipped** in 89.95 seconds,
including rendered UI tests with installed Chrome. The skipped optional test is
reported by pytest; no failing test was skipped to obtain this result.
Fresh whole-branch review follows this implementation commit.
