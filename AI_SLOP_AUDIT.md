# AI Slop Audit

Date: 2026-05-10

Scope: code changed during this prompt and directly connected architecture for the latest `web_qa` failure, router hand-off, chat UI rendering, latest `cua_cli` false-success issue, hook-continuation review of the `cua_cli` tool allowlist fix, rapid session context/artifact enrichment, and the current audit of the assistant file-name memory fix. `docs/audits/ai-slop/` does not exist in this repository, so this report lives at the repository root.

## Scoped Verdict

Score after this hook repair: 22/100, Low slop risk for the scoped rapid hand-off changes.

Confidence: Medium. Graphify is stale from 2026-04-27 and the repository-wide scanner is noisy because it includes vendored browser artifacts and package lockfiles, but the scoped source path was inspected and covered with red/green regression tests.

Why:

- Graphify Community 6 and Community 31 point to the same directly connected areas changed here: CLI execution/results, routing, session history, and context hand-off.
- Source inspection found a real slop-like boundary bug in `models/rapid_state.py`: contextual pronouns and file-operation verbs were matched with raw substring checks.
- Source inspection also found artifact tracking accepted any successful path-bearing tool/message, which could turn a `read_file` path into the next "open the file" target.
- The root-cause repair now uses token/phrase matching and explicit output-file tool evidence instead of broader string guesses.
- Current source inspection found and fixed a fresh boundary smell from this prompt: `models/agent_step_runner.py` briefly imported output-file parsing from `models/rapid_state.py`, making execution depend on session-memory internals.
- Regression tests prove both the original user flow and the newly discovered false-positive cases.

## Required Triage

- Read `graphify-out/GRAPH_REPORT.md` before source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Current hook pass re-ran the same Graphify triage command before source inspection.
- Graph-only score: 51/100, Moderate.
- Source-augmented score: 96/100, Severe.
- The severe source-augmented score is dominated by broad repository signals, including vendored `browser-use` artifacts, package lockfiles, and unrelated high-fanout model/router files. Per the hook scope, this pass audited only code changed in this prompt plus directly connected architecture.

## Confirmed Findings

### 1. Web QA rejected useful Tavily results when MCP returned labeled text

Status: Fixed.

Evidence:

- `logs/assistant_activity.jsonl:6320-6324` shows the latest failed query, `what is the net worth of bill gates`, routed to `web_qa` and failed with `No useful Tavily web results were found for that question.`
- Local reproduction showed Tavily MCP returned useful search data in a `raw_content` text payload containing repeated `Title:`, `URL:`, and `Content:` blocks.
- The parser in `agents/web_qa/agent.py` was the boundary where structured Tavily results and raw text payloads became citations.

Risk:

- A valid web search could be discarded as empty, which stopped the routed agent chain even when Tavily returned enough information to answer.
- Citation rendering also depended on loose source-section detection; any answer that merely mentioned `sources:` could skip the actual citations section.

Root-cause fix:

- `agents/web_qa/agent.py:13` now defines an explicit source heading detector instead of substring matching.
- `agents/web_qa/agent.py:29` centralizes source extraction and HTTP(S) URL validation.
- `agents/web_qa/agent.py:42` parses Tavily labeled text blocks case-insensitively and preserves multiline content.
- `agents/web_qa/agent.py:149` appends citations only when the answer lacks a real `Sources` heading.
- `tests/test_web_qa_agent.py:72`, `tests/test_web_qa_agent.py:117`, and `tests/test_web_qa_agent.py:140` cover the failure payload, unsafe URL rejection, and source-section detection.

### 2. Chat UI reply source policy was embedded in a monolithic UI script

Status: Fixed.

Evidence:

- The hand-off path is: `models/agent_step_runner.py:339` runs `web_qa`; `models/rapid_orchestrator.py:637-644` sends the final routed reply through `direct_response` with `source="rapid_response"`; `ui/input_window.js:3176` handles `complete_status_bubble` updates.
- `web_qa` status events should feed the work trace, not create the final chat bubble. The final chat bubble should come from the router's `rapid_response` source after the route is complete.
- The source allowlist lived inside `ui/input_window.js`, and the test checked it with static substring slicing rather than an executable behavior contract.

Risk:

- A future edit could accidentally let `web_qa` status messages become duplicate chat replies, or block the router's final `rapid_response`, without a clear behavioral test catching the regression.

Root-cause fix:

- Added `ui/chat_reply_policy.mjs:1`, a small executable policy module for chat reply source decisions.
- `ui/input_window.js:17` imports that policy, so status rendering and final reply rendering share the same contract.
- `tests/test_ui_input_window_controls.py:128` executes the policy with Node and verifies `rapid_response` is shown while `web_qa` and trace sources stay trace-only.
- Existing hand-off tests in `tests/test_router_chaining.py:154` and `tests/test_ui_agent_work_trace.py:83` verify the router response and trace behavior.

### 3. CLI agent reported a failed tool call as a successful step

Status: Fixed.

Evidence:

- `logs/assistant_activity.jsonl:6708-6711` shows the latest real `cua_cli` issue: the user asked to write context to a desktop file, Gemini CLI attempted `write_file`, the tool result said `Tool "write_file" not found`, and the final request was still logged as `success=true`.
- `agents/cua_cli/response_parser.py:58-68` previously based stream success on process return code and the final `result` event, while preserving tool-result errors only as metadata.
- `agents/cua_cli/agent.py:701-717` collected tool errors but did not flip a response from success to failure when the last completed tool call failed.

Risk:

- The router and chat UI could tell the user the CLI task succeeded even though the only attempted action failed.
- The failed write was masked as a completed routed step, so downstream orchestration had no reliable failure signal.

Root-cause fix:

- `agents/cua_cli/response_parser.py:11` now extracts deterministic tool error messages.
- `agents/cua_cli/response_parser.py:20` detects whether the last completed tool call failed; if the stream ends successfully after an unrecovered final tool error, parsing returns `success=False`.
- `agents/cua_cli/agent.py:701` now enforces the same invariant during response normalization for any `CLIResponse` object, including tests or future parser paths.
- `tests/test_cli_response_parser_boundary.py:32` reproduces the `write_file` not found shape from the log and verifies it fails.
- `tests/test_cli_response_parser_boundary.py:50` verifies a recovered tool error remains successful when a later tool call succeeds.
- `tests/test_cli_background_manager.py:109` verifies `CLIAgent.execute()` no longer reports zero-exit final tool failures as success.

### 4. CLI non-interactive tool allowlist was embedded in the agent wrapper and underfit task intent

Status: Fixed during hook continuation.

Evidence:

- Graphify Community 6 groups `CLIAgent` and `CLIResponse` into a low-cohesion CLI-agent area, and the required scanner flagged `agents/cua_cli/agent.py` as a severe source-augmented hotspot for agentic tooling blast radius, broad error masking, and policy sprawl.
- Source inspection found the previous allowlist logic inside `CLIAgent`, adjacent to command construction, response normalization, retry handling, and process execution. That made tool policy another responsibility of the agent wrapper instead of a dedicated boundary.
- The previous logic only added `run_shell_command` for terminal wording, explicit shell commands, and server intent. Connected policy in `agents/cua_cli/server_launch_policy.py:100` already treats clone/install/build as setup-oriented task intent, so clone/test and file-system move tasks could still be launched without shell capability in default non-interactive mode.
- The original trust-policy tests covered file-writing and terminal wording, but did not cover common non-terminal CLI work such as "clone this repo and run tests" or "create a folder and move files".

Risk:

- The `write_file` false-success bug was fixed, but the CLI could still fail legitimate clone/test/folder-management tasks from the same root cause: a scoped Gemini run without the tool needed to perform the requested operation.
- Leaving tool selection inside `CLIAgent` increased the class' policy surface and made future fixes more likely to accrete around the process wrapper instead of the intent boundary.

Root-cause fix:

- Added `agents/cua_cli/tool_allowlist_policy.py:15`, a focused policy module with explicit edit and shell capability constants.
- `agents/cua_cli/tool_allowlist_policy.py:39` now centralizes shell-intent detection using existing terminal, explicit-command, and server-intent boundaries plus direct CLI task verbs for clone/test/build/file-system operations.
- `agents/cua_cli/agent.py:56` imports the policy and `agents/cua_cli/agent.py:203` delegates `--allowed-tools` construction to it.
- `agents/cua_cli/agent.py:799`, `agents/cua_cli/agent.py:812`, and `agents/cua_cli/agent.py:825` pass the original user task as tool-policy context when retry prompts wrap or rewrite the text sent to Gemini.
- Added `tests/test_cli_tool_allowlist_policy.py:18` through `tests/test_cli_tool_allowlist_policy.py:37` for file-only, terminal, clone/test, folder-move, and unrestricted approval modes.
- Strengthened `tests/test_cli_trust_policy.py:68` and `tests/test_cli_trust_policy.py:84` so the built Gemini command verifies the exact `--allowed-tools` surface.

### 5. Rapid session context enrichment used substring matching and broad artifact capture

Status: Fixed during this hook continuation.

Evidence:

- The current hand-off fix added session context enrichment in `models/rapid_state.py`, which is directly connected to the graph's low-cohesion CLI/router/session areas: Community 6 (`CLIAgent`, `CLIResponse`) and Community 31/session history.
- Source inspection showed `_task_has_context_reference()` used substring checks against markers including `it`. That meant `write a README file on desktop` was treated as contextual because `write` contains the letters `it`.
- Source inspection also showed `record_step_context()` accepted any path from a successful tool call or message. A successful `read_file` call could overwrite `last_file_path`, causing a later "open the file" request to target the wrong artifact.
- Red test evidence: `tests/test_rapid_state_boundary.py:96` reproduced the false enrichment, and `tests/test_rapid_state_boundary.py:115` reproduced broad `read_file` artifact capture.

Risk:

- Unrelated file-writing tasks could silently receive the previous answer as content, corrupting user-requested file operations.
- A path from a read/list/open operation could be promoted to the created-file ledger, making contextual follow-ups unstable across mixed CLI steps.

Root-cause fix:

- `models/rapid_state.py:56` now tokenizes task text once and matches context references as whole tokens or ordered phrases.
- `models/rapid_state.py:110` now records file paths only from explicit output-file tools (`write_file`, `replace`, `edit`, `edit_file`) with successful status.
- `models/rapid_state.py:274` now falls back to message path extraction only when the message is an actual file-status message such as written/saved/created.
- `tests/test_rapid_state_boundary.py:96` verifies non-contextual writes are not enriched.
- `tests/test_rapid_state_boundary.py:107` verifies contextual writes still receive the prior answer.
- `tests/test_rapid_state_boundary.py:115` and `tests/test_rapid_state_boundary.py:131` verify `read_file` paths are ignored while `write_file` artifacts are captured.

### 6. Output-file artifact parsing briefly lived in rapid session state

Status: Fixed during current hook continuation.

Evidence:

- Latest real log evidence showed `logs/assistant_activity.jsonl` recorded a successful `write_file` tool call for `C:\Users\SAI\Desktop\bill_gates_net_worth.md`, but the persisted chat message was only `CLI task completed.`, so the direct follow-up could not answer "give me the file name."
- The first behavior fix exposed `extract_output_file_path_from_tool_calls()` from `models/rapid_state.py` and imported it in `models/agent_step_runner.py:21`. That solved duplication but made the execution layer depend on the rapid session-memory module.
- Graphify already placed the affected area in low-cohesion connected clusters: Community 6 (`CLIAgent`, routing/execution) and Community 31 (chat/session history), plus thin Community 66 for output-file event creation. That made this ownership boundary an aggressive review target.
- Red test evidence: `tests/test_output_file_artifacts.py` initially failed because no dedicated artifact-boundary module existed.

Risk:

- Keeping artifact parsing inside session state would invite future execution/UI callers to import from a stateful memory module just to parse tool output.
- The output-file concept would remain split between visible completion text and session context, increasing the chance that one path remembers a file while the other path forgets it again.

Root-cause fix:

- Added `models/output_file_artifacts.py:1`, a focused boundary module that owns output-file path parsing from successful tool calls, file-status text detection, and Windows path extraction.
- `models/agent_step_runner.py:21` now imports artifact parsing from `models.output_file_artifacts`, and `models/agent_step_runner.py:87` uses it to turn generic successful CLI output into a visible `Created file: <path>` message.
- `models/rapid_state.py:14` now imports the same artifact-boundary functions, keeping rapid state focused on session history and context enrichment.
- `models/rapid_state.py:289` adds the last created/edited path to the rapid prompt's session-context block so short follow-ups have deterministic context.
- Added `tests/test_output_file_artifacts.py:21` for the parser boundary, `tests/test_agent_step_runner_latency.py:149` for generic CLI output, and `tests/test_rapid_state_boundary.py:152` for the direct follow-up prompt context.

## Reviewed But Not Changed

- Broad `except Exception` and `Any` usage remain in some boundary modules (`agents/web_qa/mcp_client.py`, `models/agent_step_runner.py`, `models/rapid_orchestrator.py`, `ui/server.py`). In the audited call path, these mostly guard subprocess, MCP, websocket, or model boundaries. They are risk areas, but not confirmed slop from this prompt.
- Graphify flagged unrelated vendored code and lockfile content. Those signals were treated as triage noise for this scoped hook pass.

## Validation

- Passed: `.venv\Scripts\python.exe tests\test_web_qa_agent.py`
- Passed: `.venv\Scripts\python.exe -m pytest tests\test_web_qa_agent.py tests\test_agent_step_runner_latency.py tests\test_router_chaining.py tests\test_ui_agent_work_trace.py tests\test_ui_input_window_controls.py tests\test_ui_chat_outcome.py tests\test_ui_server_security.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_response_parser_boundary.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_background_manager.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_background_runtime_boundary.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_server_launch_policy_boundary.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_stream_event_policy_boundary.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_workspace_policy_boundary.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_trust_policy.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_tool_allowlist_policy.py`
- Passed: `.venv\Scripts\python.exe tests\test_cli_direct_command_policy.py`
- Passed: `.venv\Scripts\python.exe -m pytest tests\test_cli_trust_policy.py tests\test_cli_direct_command_policy.py`
- Passed: `.venv\Scripts\python.exe -m pytest tests\test_cli_response_parser_boundary.py tests\test_cli_background_manager.py tests\test_cli_direct_command_policy.py tests\test_cli_stream_event_policy_boundary.py tests\test_cli_workspace_policy_boundary.py tests\test_cli_server_launch_policy_boundary.py tests\test_agent_step_runner_latency.py`
- Focused pytest result: 62 passed.
- Prior full-suite run in this prompt: 192 passed, 20 failed, 3 skipped. The remaining failures were unrelated vendored `browser_use` async tests caused by missing/unknown `pytest.mark.asyncio` handling in the current environment.
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_rapid_state_boundary.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_router_chaining.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_agent_step_runner_latency.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_routing_contracts.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_cli_response_parser_boundary.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_cli_background_manager.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_web_qa_agent.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_routing_policy.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe tests\test_router_backends_boundary.py`
- Passed during current hook continuation: `.venv\Scripts\python.exe -m compileall models tests\test_router_chaining.py tests\test_rapid_state_boundary.py tests\test_agent_step_runner_latency.py`
- Red evidence during latest hook continuation: `.venv\Scripts\python.exe tests\test_output_file_artifacts.py` failed with `ModuleNotFoundError: No module named 'models.output_file_artifacts'` before the boundary module existed.
- Passed during latest hook continuation: `.venv\Scripts\python.exe tests\test_output_file_artifacts.py`
- Passed during latest hook continuation: `.venv\Scripts\python.exe tests\test_agent_step_runner_latency.py`
- Passed during latest hook continuation: `.venv\Scripts\python.exe tests\test_rapid_state_boundary.py`
- Passed during latest hook continuation: `.venv\Scripts\python.exe tests\test_router_chaining.py`
- Passed during latest hook continuation: `.venv\Scripts\python.exe -m pytest tests\test_output_file_artifacts.py tests\test_agent_step_runner_latency.py tests\test_rapid_state_boundary.py tests\test_router_chaining.py` (35 passed)
- Passed during latest hook continuation: `.venv\Scripts\python.exe -m compileall models tests\test_output_file_artifacts.py tests\test_agent_step_runner_latency.py tests\test_rapid_state_boundary.py tests\test_router_chaining.py`
