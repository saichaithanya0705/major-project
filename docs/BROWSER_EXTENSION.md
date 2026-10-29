# Use JARVIS in your browser

The browser operator can inspect pages, navigate, search, compare sources, work
with web-app controls, and fill forms in an explicitly selected existing session
or a new JARVIS-owned tab for a supplied link, named website, or fresh search.
Standard Agent Skills provide additional workflows; a dedicated skill is not
required for an unfamiliar task. Chrome is the initial supported target for
qualification. Brave and Comet remain compatibility candidates until tested.

## Connect Chrome

1. Install the official [Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm)
   from Microsoft in the Chrome profile you want to use.
2. Using Node.js 20 or newer, install this project's pinned MCP dependency once:

   ```powershell
   npm ci --prefix integrations/playwright_mcp
   ```

3. Start JARVIS normally and say/type **connect browser**. Complete the extension's
   connection prompt in Chrome, selecting the browser tab you intend to share.
4. Choose the intended tab with **use browser tab N**, using the returned list.
   Verify JARVIS's reported tab title and URL, then give your task.

You do not need to select an old tab when the request itself contains a normal
HTTP(S) link. JARVIS opens that exact link in a new **Playwright · JARVIS** tab
and starts work there. Existing/current-tab wording intentionally keeps the
selection requirement: move that tab into the group, then choose its listed
index before JARVIS reads it.

For a named destination such as `@browser open the ChatGPT website`, JARVIS
creates its own blank tab and navigates from there. A fresh research/search
request can start the same way. You do not need to share an unrelated old tab
or supply the full URL. Requests to use the current tab or fill an unspecified
existing form still require deliberate tab selection.

The current extension isolates clients into separate tab groups. JARVIS can see
only tabs in **Playwright · JARVIS**. To share an existing tab, move/drag it into
that group in Chrome, say **browser status**, then select its listed index.
If only Welcome appears, add the intended HTTP(S) tab to the group first.
A tab belongs to one client group at a time; move it out to remove access.
This is the [official extension's sharing model](https://github.com/microsoft/playwright/blob/main/packages/extension/README.md#multiple-clients).

`connect browser` selects extension mode for the running app. To retain that
choice after restart, put `JARVIS_BROWSER_MODE=extension` in the local `.env`.
The default remains `managed`, which uses the existing separate browser.
Extension mode reports a connection failure rather than silently opening a
different browser. Use `JARVIS_BROWSER_CHANNEL=msedge` only for an intentional
Edge setup. `JARVIS_BROWSER_EXECUTABLE` is an optional explicit executable path;
it does not establish compatibility with another browser or arbitrary profiles.

Upstream MCP and extension versions must be compatible. This integration pins
`@playwright/mcp@0.0.83`, using extension protocol 2 with the installed 0.4.0
extension. The previous 0.0.73 client used protocol 1 and produced the unsupported
protocol error. Reinstall the lockfile after updating this project.

The extension's status page provides `PLAYWRIGHT_MCP_EXTENSION_TOKEN` for local
pairing. Copy the exact value into the ignored local `.env`; do not put it in a
skill or commit it. After pairing, JARVIS first lists tab titles and URLs,
then waits for **use browser tab N** before reading page contents. Browser-internal
pages cannot be selected. `browser status` refreshes the tab indices.

For this device's qualified browser planner, set these browser-only overrides:

```dotenv
JARVIS_BROWSER_BRAIN_PRIMARY=nvidia
JARVIS_BROWSER_NVIDIA_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b
```

These settings preserve the normal chat model. Live NVIDIA availability and
latency can vary; consult [the implementation report](BROWSER_IMPLEMENTATION_REPORT.md)
for measured tests and remaining limits.

## Work through chat

| Message | Behavior |
| --- | --- |
| `connect browser` | Authenticate through the official extension and list tabs for explicit selection |
| `browser status` | Show connection state and selected tab title/URL, excluding URL query data |
| `use browser tab 0` | Deliberately select a tab by the index shown by the browser tools |
| `@browser …` | Explicitly assign the request to the connected-browser operator; type `@` to choose it in chat or use the compact **@ Browser** control |
| `https://… Open this sheet and count its rows` | Open the user-supplied link in a new JARVIS-owned tab, then perform the task |
| `@browser open the ChatGPT website and draft a question` | Start an owned tab, navigate to the named site, and compose the draft; final submission still requires review |
| `disconnect browser` | End JARVIS's connection while leaving your browser/tabs open |
| `stop` / `cancel` / `stop browser` | Cancel active work and pending submission review |
| `continue` | Inspect the current page and resume the retained objective |

Examples:

- `@browser https://docs.google.com/spreadsheets/d/... Open this sheet and count the used rows.`
- `https://example.com/form Fill the visible draft with the details I provide; do not submit.`
- `@browser read the current browser tab and summarize it.`
- “Read the current tab, extract its main points, and give me the source URL.”
- “Compare these products using their specifications and linked reports.”
- “Fill this application with the details I provide and leave it as a draft.”
- “Fill and submit this form.”
- “Show the details in this web app and summarize the milestone.”

Navigation, searching, ordinary controls, option selection, and authorized field
entry run without repeated action approvals. Missing details produce a focused
question. Final form submission asks for review **in JARVIS's chat UI**; reply yes
to submit or decline/cancel to keep the filled draft. This includes form Enter
and recognized JavaScript-app submission controls. Routine search submissions
remain automatic. Changing the page/form during review invalidates that approval.

Provide personal form values explicitly in your request or a follow-up. For
recognized name, email, phone, age, address and sensitive fields, the runtime
checks proposed values against the human's supplied text before any write,
including whole batches and dropdown selection. Missing values ask a question;
model-generated task text cannot authorize them. Automatic profile retrieval,
derived/normalized personal values, and unfamiliar field labels need additional
qualification; provide the desired literal value when asked.

The operator verifies fields after writing and checks the resulting page after
actions. A completion statement needs observed evidence. If an operation times
out, its outcome may be uncertain; the operator stops rather than automatically
repeating a potentially submitted form. Stop cannot undo an operation already
sent to a website. Resume uses fresh references and fresh approval where needed.

## Add a workflow using SKILL.md

Use the [Agent Skills standard](https://agentskills.io/specification): a folder
containing `SKILL.md`, required YAML `name`/`description`, and Markdown instructions.
The name must match the folder. Optional metadata values are strings. Supporting
text may live in `references/` or `assets/`; browser skill scripts are not executed.

```markdown
---
name: browser-project-review
description: Review a project dashboard and extract milestones and blockers.
metadata:
  version: "1.0"
---
# Review a project dashboard

Inspect the selected dashboard, open relevant details, and collect milestones
and blockers. Verify the findings against visible page content and return source
links. Follow the user's scope and the runtime's form-submission review.
```

Discoverable locations are the configured `JARVIS_SKILLS_DIR` (default
`~/.jarvis/skills`), this project's `.agents/skills`, the user's `.agents/skills`,
and bundled `skills/`. External skills require explicit enabling after review:

```powershell
python -m agents.skills trust-browser .agents/skills/browser-project-review
```

Enabling records the skill tree's content digest in
`~/.jarvis/browser-skill-trust.json`; it does not permit scripts or new tools.
Edits require re-enabling for subsequent tasks. An active task keeps pinned
content. Untrusted/changed skills are skipped with diagnostics, while the base
operator remains usable. Existing CLI/document skill behavior is preserved.

The browser always activates the vetted `browser-operator` instructions and,
when relevant, one trusted specialized workflow before the model plans actions.
It retains a small relevant skill catalog for later activation; the explicit forms `use browser-project-review skill`,
`/browser-project-review`, and `skill:browser-project-review` are supported.
New workflows using existing primitives need no app rebuild or restart between
tasks. A new low-level capability still needs code and validation.

Optional experimental `allowed-tools` restricts a skill to exact exposed browser
tool names, separated by spaces. Unsupported patterns are rejected; the field
cannot grant evaluation, uploads, filesystem access, or wider permissions.
Reference traversal, symlinks/junctions, oversized trees, and script reads are
rejected. Unknown tools and malformed model arguments cannot execute directly.

## Rehearse and verify

Use synthetic local pages rather than public forms or real payments:

```powershell
python evals/browser_extension_probe.py --mode fixture
python evals/browser_extension_probe.py --mode research
python evals/browser_extension_probe.py --mode extension
python evals/browser_extension_probe.py --mode extension --open-test-tab
python evals/browser_extension_probe.py --mode fixture --connected-fixture --llm
```

The fixture checks read-back, denial without a POST, one approved POST, ordinary
web-app controls, and JavaScript-app submission. Research uses the actual
configured provider against multiple local source pages. Extension mode checks
the live selected tab through the official connection. Evidence is written under
ignored `evals/results/browser-extension/`; `--connected-fixture` opens an owned
local fixture tab in installed Chrome, performs synthetic submissions, then closes
that test tab. Fixture success alone does not prove
an existing Chrome profile is connected. Production decisions log metadata with
argument values omitted; raw page snapshots are not written as ordinary logs.

The first release has a 20-decision/120-active-second task budget (review waiting
time excluded), bounded corrections, and one safe stale-page refresh. Login/2FA,
CAPTCHAs, native browser permissions, inaccessible/custom controls, downloads and
uploads can require user takeover or additional capabilities. Native window
management and choosing another installed browser/profile still use the desktop
agent. These limits are reported as incomplete work, not silent success.
