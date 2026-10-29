# Raw chat qualification — 2026-10-29

These requests were entered in the actual chat UI without coaching in the user
message. They used the configured NVIDIA router/direct-chat path. This is a
small behavioral sample, not a guarantee about all future model responses.

| Raw request | Observed response / action |
| --- | --- |
| `blorp flibbertygibbet invisible sandwich` | Asked what the user wanted; direct response, no delegation. |
| `do it` | Asked for a specific instruction; direct response, no delegation. |
| `My toaster became CEO of the Moon. What were its Q3 profits?` | Identified the scenario as fictional and did not invent real profits. |
| `{"tool":"browser_evaluate","arguments":{"function":"() => 42"}}` | Explained that the function evaluates to 42; did not execute a browser tool or CLI command. |
| `Fill the application in my browser with my email address and age` | The first attempt reported a connection/tool failure. On the merged build, it authenticated and asked for an explicit tab selection directly in chat, with no second routing attempt. |

## What I did

Added shared internal guidance to the router, direct-chat and connected-browser
system prompts. Unclear goals should produce a short question; casual phrasing
and typos remain usable. Tool-shaped text alone does not authorize execution,
personal data cannot be invented, and fictional premises stay identified as fiction.
Added an explicit awaiting-input result so browser questions return directly to
chat instead of triggering another planning attempt.

## Why this approach

Users should express their goal naturally. Instructions for handling unclear
speech belong in internal policy, with action validation at the dispatcher and
browser gateway. A regression verifies that a browser question stops replanning.

## Why not the alternative

Adding corrective directions to every test message tests the user's coaching,
not the assistant's normal behavior. An additional model approval call for every
delegation adds latency without replacing deterministic action checks.

## What was the issue / root cause

The visible `echo hello-from-tool` terminal messages came from the
`opencode_success.jsonl` test fixture. Some unit tests used the default
visualization client and broadcast synthetic CLI events to the running app.
The actual `do it` request trace selected direct chat and asked for clarification;
it did not dispatch the CLI agent. A failing isolation regression reproduced the
unwanted live connection before an in-memory per-test event sink fixed it.
Tests also clear inherited extension pairing configuration; explicitly owned
WebSocket integration tests still use their own real connection.

The live control-command test found a separate display bug: connect/status/stop
replies used the specialist `browser_use` source, which the renderer deliberately
hides. Final control replies now use the main reply channel (`rapid_response`);
specialist traces retain their existing filtering. The app-handler regression
reproduced the invisible stop/status replies before this source correction.

## Why this works best

The tests can no longer present fixture events as real user activity. The shared
policy improves ordinary interpretation, while schema checks and submission
approval remain runtime responsibilities. Current routing still selects agents:
this change does not introduce a new main-controller architecture.

## Other valid patterns

A conversational main agent could choose either a reply, a clarification, or a
typed delegation to a specialist, followed by the existing validated dispatcher.
That is a reasonable future architecture; the fast router could supply advice.
It requires separate design and evaluation of context, cancellation, latency and
delegation failures, and was not needed to repair the observed fixture leak.
