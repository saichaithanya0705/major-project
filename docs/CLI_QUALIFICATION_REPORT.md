# CLI repair and qualification — 2026-10-29

## What I did

Added NVIDIA model selection to opencode when its API key is configured and no
explicit CLI model override is set. Kept credentials as environment references.
Raised the subprocess JSONL line limit to a bounded 4 MiB, enabled process-tree
cleanup on reader/normalizer errors, and isolated Claude tasks from inherited MCP
servers. Simple version queries use the safe direct-command path. Terminal tasks
without tool evidence are retried once and then rejected instead of accepting
an invented answer.
Completion checks recognize successful safe-command receipts and ignore routing
boilerplate when comparing a completed task with the original goal. Requested
additional actions remain part of coverage and cannot be silently dropped.

## Why this approach

The CLI now uses the configured cloud provider rather than requiring an unrelated
local inference service. Existing CLI backends, action policies, and explicit
model choices remain authoritative. The stream and cleanup changes apply to all
CLI backends.

## Why not the alternative

Starting Ollama would still require a compatible downloaded local model. An
unbounded stream reader could consume arbitrary memory; ignoring reader errors
would hide execution failures and strand subprocesses.

## What was the issue / root cause

Routine tasks used `ollama/nemotron-3.5-bolt` even though the working app was
configured for NVIDIA. Ollama was not reachable. A separate coding task launched
Claude with inherited MCP server configuration; its initialization event exceeded
asyncio's default 64 KiB line limit. The exception path unregistered the process
without terminating it or its descendants.

## Why this works best

Provider configuration follows existing account configuration without persisting
credentials. Large valid events are supported, while oversized events fail and
the process tree is reaped. Regressions exercise both cases using real children,
alongside explicit-model precedence and error cleanup.

## Other valid patterns

A dedicated local model remains available through `JARVIS_OPENCODE_MODEL`.
Installed coding CLIs can still be selected using `JARVIS_CLI_BACKEND`; their own
logins and availability determine whether they can execute.

## Qualification

The final suite passed **795 tests with 2 skipped**. A live chat request to run
`git --version` completed with one CLI execution and returned the actual installed
version, `2.56.0.windows.3`, without router repetition. The NVIDIA-backed opencode
path separately executed that command and produced a successful tool receipt.
Its first cloud run took about 55 seconds, so latency remains a presentation limit.
A separate live fixture run read the exact JSON file and returned read receipts;
its earlier completion loop informed the final coverage regressions. The fixture
workflow was not replayed end to end after the final correction.

The installed Claude CLI did not complete a separate 65-second probe. A repair
to event transport does not prove that every installed backend is authenticated,
available, or responsive. Synthetic fixture files and test subprocesses were
removed after qualification.
