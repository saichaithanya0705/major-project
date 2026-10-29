# Browser implementation and qualification — 2026-10-29

## What I did

Implemented a general browser operator using the official Playwright extension,
standard Agent Skills, inspected actions, verified field entry, and chat review
before form submission. Connected the installed Chrome profile with its locally
configured extension token. Added deterministic chat commands, cancellation,
resume, explicit tab selection, and browser-only provider/model configuration.

The runtime remains useful without a specialized skill. Bundled workflows cover
general operation, research, and forms; external workflows require content-hash
trust and cannot grant additional tools or execute scripts.

The final whole-branch review identified seven consequential issues. Regression
fixes cover image submitters, application search inputs, changed sensitive values
and submitter destinations during approval, replacement-tab isolation, verified
completion, cancellation during connection, native browser launches, and the
active task deadline. Node's advertised minimum now matches the locked runtime
dependencies (20). Browser questions return to chat without another planning step.
See [raw chat qualification](ADVERSARIAL_CHAT_REPORT.md) for internal system-policy
changes and the test-event leak that explained unexpected visible CLI messages.

A final chat rehearsal caught invisible deterministic connection/status/stop
replies: they used a specialist trace source filtered by the renderer. Those final
replies now use the main chat response channel, covered by an app-handler
regression that failed before the correction. Broadening the renderer's source
allowlist would also expose routine specialist traces, so the fix is at the
final-response producer.

Existing tabs use the official extension's per-client sharing group. A live
check initially saw only Welcome because the form was outside JARVIS's group.
Moving only that owned synthetic form into **Playwright · JARVIS** made it appear
immediately in `browser status`; explicit index selection remained mandatory.
The connection response and setup guide now explain this required sharing step,
verified by a failing-then-passing connection-message regression. No discovery
shim or automatic access to unrelated browser tabs was added.

The same chat rehearsal exposed model-invented personal values on the synthetic
form even with the internal clarification policy. The gateway now checks
recognized personal fields against original human-supplied text before typing,
batch filling or dropdown selection, and returns a question on missing input.
The public request entrypoint carries raw input in a scoped context independently
of the router's rewritten task; the connected runner keeps a bounded source
history per chat and clears it on disconnect. This keeps routine supplied-data
entry automatic while preventing the demonstrated placeholders from being typed.
Tests reproduced writes before the fix and verify zero writes afterward.

The supplied-data model rehearsal exposed a second issue: field values were
correctly read back, but the batch receipt said only “fill_form on page.” With
values hidden from observations, the model repeated the same completed batch
until its deadline. Progress now names each verified field without repeating
its value. The gateway rechecks and rejects an unchanged, already-verified edit;
the runner gives a bounded correction instead of sending another write. Changed
fields can still be restored, and a new explicit task obtains fresh references.

## Why this approach

An owned MCP session supplies browser primitives while the gateway validates
arguments and checks the actual selected control. The model plans one action at
a time; fixed runtime readers handle identity, submission classification and
field verification. Portable instructions extend workflows without app changes.

The existing chat confirmation channel carries required submission reviews;
legacy confirmation bypass settings cannot disable them. Token pairing first
lists metadata and waits for an explicit tab choice before reading page contents.

Sensitive field values contribute opaque keyed hashes to approval fingerprints;
their raw values do not enter the model observation. The actual form submitter's
destination and method are checked again after review. Stable selected-page
identity is checked before reading or acting, so a closed tab cannot silently
rebind to another page. Explicit tab choice is required for every new extension
session, including pairing without a token.

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

Full-suite qualification also encountered a transient Windows denial of atomic
credential-file replacement. Private writes now retry only Windows access/sharing
denials, at most four attempts over 175 milliseconds of backoff. Persistent errors
still raise, preserve the previous file, and remove the temporary file. Synthetic
transient/permanent-denial regressions failed before the fix and passed afterward.

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
| Review-fix installed Chrome qualification | All 12 checks passed in 193.688 seconds: the original seven, image submitter destination, application search-input Enter, password/destination mutation invalidation, and live NVIDIA multipage research. Owned fixture tabs and MCP session were cleaned up. |
| Final installed personal-form cases | Both live NVIDIA cases passed in 68.375 seconds: missing details left fields empty and returned a question; supplied name/email were filled in one batch, verified, and completed without submission. |

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

The private identity reader uses Playwright's internal Page GUID through a fixed
callback on the pinned runtime; an upstream internal API change requires renewed
qualification. It is absent from the model's action catalog. Submission receipts
currently recognize common English success signals; other outcomes stop as
unverified rather than being reported as accepted. Sensitive approval hashing
requires Web Crypto; unsupported pages or oversized forms require user takeover.

Personal-value source checks cover recognized field types and common labels;
they do not understand every custom widget, language or indirect JavaScript
effect. Literal source matching may request input for legitimate reformatted or
derived values. A future explicit profile/source-data contract could support
those cases with typed provenance and narrower authorization. More prompt text
alone did not prevent the observed invented placeholders.

Required budgets remain 20 decisions and 120 active seconds per task, excluding
review waiting time, with two consecutive output corrections and one safe stale
refresh. Output validation prevents malformed actions and invented evidence;
it does not make the model deterministic. Production decision logs contain task
hashes, tool names and argument keys, excluding page bodies and field values.

### Final validation

The pre-review installed-session rehearsal passed eight checks (62.485 seconds),
and the review-fix rehearsal passed twelve (193.688 seconds). After the live
personal-input and repeated-edit fixes, the complete suite passed **758 tests,
with 1 skip**, in 51.81 seconds, including the rendered UI test using installed
Chrome. The skip is the native Windows symlink test, which requires account
privileges unavailable here. Earlier Windows file-sharing, loopback-connection
and timing failures were retained; launcher/UI deadlines were not relaxed.

The final review is complete; consequential findings have reproducing regression
tests and were fixed in one pass. The deferred minor is surfacing skipped or
changed external-skill diagnostics in chat; trust checks remain enforced.

The expanded fourteen-case run passed thirteen checks, then rejected completion
evidence because the runtime receipt used curly quotes and the model returned
straight quotes. Receipts now use canonical ASCII quotes; evidence matching
remains strict. Both personal-form cases were rerun through the installed
extension and live NVIDIA provider and passed in **68.375 seconds**, with exactly
one fill call and zero form submissions. Thus the twelve browser/research checks
and two personal-form cases are qualified across separate runs, not a claimed
single fourteen-pass run. Failed runs remain in the local evidence directory.

Live extension/provider availability still requires rehearsal before the
presentation. A timed-out or potentially submitted request is never replayed
automatically to obtain a passing result.
