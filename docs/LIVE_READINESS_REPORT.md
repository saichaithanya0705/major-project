# Live readiness report - 2026-10-29

## What I did

Tested the configured providers on this machine, replaced the NVIDIA credential
in the ignored local `.env`, repaired reproduced runtime failures, and exercised
the real backend through its authenticated WebSocket protocol. Recorded the
user's consented microphone phrase, transcribed it, submitted that command to
the app, generated ElevenLabs speech, and replayed it with user confirmation
that it was clearly audible. Browser and screen-agent tests followed.

| Live path | Observed result | Measured time |
| --- | --- | --- |
| NVIDIA Bolt arithmetic | Correct answer, `42` | 1.05 s direct API |
| NVIDIA Lightning arithmetic | Correct answer, `42` | 1.08 s direct API; 1.66 s app adapter |
| NVIDIA routing | Valid routing object through the actual adapter | 4.16 s initial; 1.16 s in app |
| NVIDIA router follow-up | Lightning returned valid browser routes after strict tool-name normalization | 1.39-1.75 s live routes |
| Connected Chrome browser agent | Official extension paired, explicitly selected an owned local test tab, inspected it through the NVIDIA planner, and verified a two-field edit with zero submissions | 3.6 s pairing; 7.8 s read; 16.3 s verified edit |
| Physical microphone capture | Recognizable user speech in a 9.98 s clip | Capture and transcription passed |
| Microphone transcription through the app | `Jarvis what is seventeen plus twenty five?` | 2.17 s on the final app run |
| Submitted voice command | `Seventeen plus twenty five is forty-two.` | 1.97 s after submission |
| Normal chat through the app | Relevant explanation from NVIDIA | 1.95 s |
| Sourced web answer through the app | Tavily results and clickable Python.org sources | 7.77 s warm; 22.08 s earlier |
| ElevenLabs speech generation | HTTP 200; 85,724-byte MP3 | 23.14 s including initial playback |
| Speaker playback | Player returned success; user confirmed hearing it clearly | 13.41 s replay including player startup |
| Managed browser navigation | Real headed browser at `https://example.com/`, title verified | 4.33 s |
| Managed browser search | Searched and opened `https://www.python.org/doc/`, title verified | 5.94 s |
| Screen context extraction | Correctly identified Search, Settings, and Connected | 4.4-9.2 s across trials |
| Screen annotation generation | Validated tool calls for three boxes and three explanations; Electron renderer received them | 3.1-3.3 s model time on successful trials |
| Gemini 3.1 Flash-Lite vision | Correct annotation tool calls in direct and app-renderer tests | 8.31 s direct; 3.33 s app model call |
| App authentication | Missing-token connection rejected with code 1008 | Passed |

**Visible native annotation placement remains unqualified.** Electron loaded
both renderers and received the drawing commands, but captured desktop frames
did not show the annotation layer. The user was away during those runs and
could not confirm it. Model/tool success is not proof that the labels were
visible and aligned on the user's interactive desktop.

## Why this approach

The presentation configuration uses models that actually accepted this
account's requests, followed by independent device and app-protocol checks.
NVIDIA chat and routing are the primary demonstrated model path; Gemini is
retained for screen explanation, with a live-tested Flash-Lite backup.

The local, ignored configuration now selects:

```dotenv
ROUTER_PROVIDER=nvidia
NVIDIA_ROUTER_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
NVIDIA_BRAIN_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
JARVIS_BRAIN_PRIMARY=nvidia
JARVIS_BRAIN_ESCALATION=gemini,openrouter
GEMINI_BACKUP_MODEL=gemini-3.1-flash-lite
OLLAMA_ROUTER_MODEL=qwen3.5:4b-fast
JARVIS_BRAIN_MODEL=qwen3.5:4b-fast
```

The NVIDIA key is not included in this report or committed to Git. Voice uses
the existing ElevenLabs key through the app's automatic provider selection.

## Why not the alternative

Credential presence, a model catalog entry, mocked tests, and successful
renderer messages each prove only part of the path. The retired OpenRouter
model was not silently changed to its paid version. Optional CLI providers
that timed out are excluded from this machine's presentation chat fallback
order instead of adding minutes of waiting before an answer.

## What was the issue / root cause

| Reproduced issue | Repair or qualification |
| --- | --- |
| Local-first default referenced absent Nemotron; Ollama was stopped | Selected tested NVIDIA models in local configuration; recorded local mode as unavailable |
| Old NVIDIA credential failed authorization; the prior model then returned account-specific 404 with the new key | Read back the replacement credential and selected models that passed inference |
| NVIDIA router spent its small token budget on reasoning and returned no final content | Disable thinking for NVIDIA routing and text-brain requests |
| NVIDIA Lightning returned declared tool names such as `invoke_cua_cli` in the `agent` field | Map only the six declared router tool names to their validated internal route names; unknown tool-like values still fail closed |
| NVIDIA was not a selectable chat-brain provider | Added it to the existing provider interface and configuration validation |
| Structured brain output was accepted without parsing | Require a JSON object and fall through to another provider on malformed output |
| Software names such as Python and Node caused factual source questions to be treated as shell tasks | Distinguish software subjects from execution/local-state intent; preserve execution routing |
| Provider fallback helper still resolved `.env` relative to the old module layout | Resolve the project root correctly after the move to `models/shared` |
| Gemini backup `gemini-2.0-flash` returned retirement 404 | Replaced it with live-tested `gemini-3.1-flash-lite`; 3.8 and 3.6 timed out in vision probes |
| Annotation executor treated time zero as an uninitialized clock and shortened cleanup delays | Use a separate initial-state sentinel and preserve annotation cleanup reading time |
| Installed Copilot rejected `--disable-client-telemetry`; piped runs also needed explicit prompt mode | Removed the obsolete flag and added a fixed noninteractive instruction; live Copilot inference still timed out |
| Renderer socket logs included the authentication query | Log the endpoint without its query string for connection, error, and close events |

Gemini model support was checked against the account's live model list and the
[official model documentation](https://ai.google.dev/gemini-api/docs/models).
The NVIDIA requests use the documented
[chat-completions endpoint](https://docs.api.nvidia.com/nim/docs/models).

## Why this works best

The changes preserve the current runtime boundaries and keep provider logic,
action validation, and annotation scheduling independently testable. New
regressions were first observed failing, then passed after their root-cause
changes. The current router compatibility regression passed alongside the
provider and parser suites; the current project-interpreter sweep completed
**765 passing tests with two environmental skips**. One requires Windows native
symlink privilege and the other requires the optional Python Playwright package
for a rendered UI test; neither skip covers the installed-extension checks.
JavaScript syntax and Git whitespace checks also passed.

Live responses and private voice/screenshot evidence are kept locally under
ignored `evals/results/live-readiness-20261028/`. They are test evidence, not
public repository assets. Search source freshness and model factual accuracy
still require evaluation; returned citations alone do not establish correctness.

## Other valid patterns

- A fully local demo needs a running Ollama service and a verified installed
  model; offline Whisper and Piper packages/voice files are currently absent.
- The separate ChatGPT-plan integration is signed out. Codex CLI sign-in does
  not establish that integration's authorization.
- Claude Code, Codex CLI, and Copilot CLI did not produce answers within the
  50-second probe budget. They are not qualified as presentation fallbacks.
- OpenRouter's old free model returned 404; its free router produced an empty
  short reply, and another free model was rate-limited. Free-provider
  availability is not guaranteed by an API key or catalog listing.
- Managed browser open/search passed. The follow-on extension operator has now
  qualified the installed Chrome session, verified form entry/submission review,
  and NVIDIA-backed multipage research; the current Lightning router follow-up
  also paired the live extension, selected an owned tab, inspected it, and
  verified a local two-field edit with no submission. See
  [the browser implementation report](BROWSER_IMPLEMENTATION_REPORT.md).
  Brave/Comet and arbitrary websites remain unqualified.
- For the demo, launch with `./start-dev.ps1`, rehearse the exact prompts on
  the presentation network, and qualify native annotation visibility before
  relying on that part of the presentation.
