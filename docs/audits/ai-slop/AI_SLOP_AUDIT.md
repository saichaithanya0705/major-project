# AI Slop Audit

## 2026-05-14 Hook Pass - CUA Runtime Implementation

Scope: code written in this prompt for the CUA runtime implementation plus directly connected CUA/router boundaries. Inspected paths include `agents/cua_vision/contracts.py`, `agents/cua_vision/action_normalizer.py`, `agents/cua_vision/computer_backend.py`, `agents/cua_vision/session_state.py`, `agents/cua_vision/grounding.py`, `agents/cua_vision/accessibility.py`, `agents/cua_vision/criticizer.py`, `agents/cua_vision/controller.py`, `agents/cua_vision/model_policy.py`, `agents/cua_vision/trajectory.py`, `agents/cua_vision/single_call.py`, `agents/cua_vision/agent.py`, `models/agent_step_runner.py`, and the new focused CUA regression tests.

**Verdict**

Score after this implementation repair: 14/100, Minimal slop risk for the scoped CUA runtime slice.

Confidence: Medium-high. The required Graphify report and scanner were run once for this hook pass before implementation inspection. The repo-wide scanner remains noisy, but the fresh CUA code has focused tests for action normalization, backend execution, grounding, accessibility capability metadata, completion criticism, controller behavior, trajectory recording, model policy, fake-backend benchmark tasks, and routed completion semantics.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The severe source-augmented score is still repository-wide and dominated by vendored/browser-use files, lockfiles, broad exception handling, high-fanout model/router modules, and agentic tooling surfaces. This pass used those signals only to inspect code written in the CUA implementation slice and directly connected completion/router boundaries.

**Confirmed Findings Fixed**

| Signal | Evidence | Root-Cause Fix | Validation |
|---|---|---|---|
| Provider action IDs could be mistaken for UI element IDs. | The first `action_normalizer.py` slice accepted generic `id` in `_target_from_args`, which could convert an OpenAI/TryCUA call id into `TargetKind.ELEMENT_ID`. | `action_normalizer.py` now only accepts explicit `element_id` or `element` for element targets. A provider/call `id` is ignored unless it is inside a real target field. | `tests/test_cua_vision_action_normalizer.py::test_ignores_provider_call_id_as_element_target`. |
| Backend hotkeys could bypass the policy boundary. | `PyAutoGuiComputerBackend._execute_hotkey()` sent generic multi-key hotkeys straight to `pyautogui.hotkey`. | Backend hotkeys now go through `normalize_hotkey_keys()`, preserving the same blocked ctrl/alt policy enforced by the normalizer. | `tests/test_cua_vision_pyautogui_backend.py::test_execute_generic_hotkey_uses_policy_boundary`. |
| Completion was still conflated with successful execution. | Existing `VisionAgent.execute()` returned `"Task completed"` when the loop exited, and `models/agent_step_runner.py` did not propagate a CUA `complete` flag. | CUA now returns explicit `success` and `complete`; the router propagates `complete=False` for honest incomplete CUA steps and uses the critic reason in the routed message. | `tests/test_cua_vision_agent_boundary.py`; `tests/test_agent_step_runner_cua_completion.py`; `tests/test_router_chaining.py`. |
| Model completion claims could bypass independent criticism. | `single_call.py` accepted `task_is_complete` directly and repeated loop exits returned as completion. | `single_call.py` now sends completion claims through `CuaCriticizer`; repeated click/no-op stop paths return success with `complete=False` unless independent evidence exists. | `tests/test_cua_vision_loop_guard.py`; `tests/test_cua_vision_criticizer.py`; `tests/test_cua_vision_controller.py`. |
| Reference-shaped architecture risk. | The implementation could have copied TryCUA layers without enforced local contracts. | New modules are narrow boundaries: typed contracts, action normalizer, backend protocol, session state, grounder, accessibility provider, criticizer, model policy, trajectory, and controller. Each has targeted tests and no speculative package split. | `84 passed` for all `tests/test_cua_vision_*.py` plus CUA routed completion. |

**Architecture Added**

- `contracts.py`: SDK-free typed action, observation, result, critic, and run-result contracts.
- `action_normalizer.py`: provider/internal tool-call normalization with policy validation and alias repair.
- `computer_backend.py`: typed PyAutoGUI backend adapter with explicit `ActionResult`.
- `session_state.py`: task/session progress and expected window-change policy.
- `grounding.py`: coordinate, bbox, element-id, and description-target grounding outcomes with confidence.
- `accessibility.py`: optional Windows accessibility provider contract with explicit unavailable metadata.
- `criticizer.py`: deterministic completion/recovery critic with optional strict-JSON semantic judge.
- `controller.py`: observe -> plan -> normalize -> ground -> execute -> criticize loop for testable CUA execution.
- `trajectory.py`: per-step trajectory recording and bounded live screenshot retention.
- `model_policy.py`: low/strong reasoning role policy for planner, grounder, and critic.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_contracts.py tests/test_cua_vision_action_normalizer.py tests/test_cua_vision_backend_protocol.py tests/test_cua_vision_pyautogui_backend.py tests/test_cua_vision_session_state.py tests/test_cua_vision_grounding.py tests/test_cua_vision_accessibility_provider.py tests/test_cua_vision_criticizer.py tests/test_cua_vision_controller.py tests/test_cua_vision_model_policy.py tests/test_cua_vision_trajectory.py tests/test_cua_vision_benchmark_harness.py tests/test_cua_vision_end_to_end_fake_backend.py tests/test_cua_vision_agent_boundary.py tests/test_agent_step_runner_cua_completion.py -q` -> 56 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_security_policy.py tests/test_cua_vision_loop_guard.py tests/test_cua_vision_interaction_policy_boundary.py tests/test_cua_vision_action_guard_boundary.py tests/test_cua_vision_windows_launch_policy.py tests/test_cua_vision_visual_feedback_boundary.py tests/test_status_bubble_cua_vision.py tests/test_router_chaining.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py tests/test_output_file_artifacts.py -q` -> 63 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py -q` -> 84 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m compileall -q agents\\cua_vision models\\agent_step_runner.py`.
- Passed: `git diff --check` with CRLF normalization warnings only.

**Residual Risk**

- Live desktop validation was not run in this audit pass because it would manipulate the user's active Windows session. Coverage is through fake backend, boundary, and router regressions.
- The legacy `single_call.py` path is now guarded by the criticizer for completion, but it remains a compatibility adapter while the new `CuaController` becomes the preferred orchestrator.
- Repo-wide Graphify/source-scan risk remains outside this scope, especially vendored browser-use files, lockfiles, and broad non-CUA agent surfaces.

---

## 2026-05-14 Hook Pass - CUA Rearchitecture Plan

Scope: code and architecture artifacts changed in this prompt, plus directly connected CUA Vision architecture needed to verify the claim. The fresh edit was `docs/superpowers/plans/2026-05-14-cua-rearchitecture.md`; connected source inspection covered `agents/cua_vision/agent.py`, `agents/cua_vision/single_call.py`, `agents/cua_vision/action_guard.py`, and `agents/cua_vision/visual_feedback.py`. This pass intentionally did not expand into repo-wide browser-use, lockfile, MCP, or package-manager hotspots because the fresh source evidence did not connect those areas to the changed artifact.

**Verdict**

Score after this hook repair: 16/100, Minimal slop risk for the scoped CUA plan edit.

Confidence: Medium. Graphify is from 2026-04-27 and the scanner is intentionally noisy at repository scale, but the fresh edit and connected CUA modules were inspected directly.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before searching raw files.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- Repo-wide severe triage was dominated by vendored browser-use files, lockfiles, broad exception handling, high-fanout model/router modules, and agentic tooling surfaces. For this hook pass, those signals were used only to inspect the fresh CUA plan and its directly connected CUA modules.

**Evidence**

| Signal | Graph Evidence | Source Evidence | Classification | Impact |
|---|---|---|---|---|
| Reference-driven indirection inflation in the fresh CUA plan | Community 32 is the CUA Vision island around capture, bbox conversion, stop state, and visual helpers; Graphify does not show it as a natural multi-package runtime yet. | The first plan version proposed `core/`, `backends/`, `grounding/`, and `accessibility/` packages before implementation evidence showed multiple concrete variants. Connected source already has focused owners: `agents/cua_vision/action_guard.py` owns repeat/loop policy and `agents/cua_vision/visual_feedback.py` owns visual metrics. | Confirmed slop signal, fixed in this pass. | A big-bang rewrite could create architecture-shaped wrappers before the code had real boundaries, increasing blast radius and making the future CUA harder to validate. |
| False-success CUA behavior remains the correct root target | Community 32 contains CUA vision capture/coordinate helpers; router/community bridge risk is outside this scoped doc edit but relevant to completion semantics. | `agents/cua_vision/agent.py` still returns `"Task completed"` after the loop exits, and `agents/cua_vision/single_call.py` still owns model-step orchestration. | Aggressive review target, not modified in this doc-only hook pass. | The implementation plan correctly keeps independent completion proof as the first architectural outcome; runtime code should be changed under that implementation phase, not opportunistically in this hook. |

**Permanent Fixes**

- `docs/superpowers/plans/2026-05-14-cua-rearchitecture.md` now requires vertical slices over big-bang replacement.
- The plan now says to extract modules only when they enforce a contract, consolidate duplicated behavior, wrap an external system, or make an unsafe state unrepresentable.
- The planned files were reduced from speculative package trees to single cohesive modules first: `contracts.py`, `action_normalizer.py`, `computer_backend.py`, `session_state.py`, `grounding.py`, and `accessibility.py`.
- Backend, grounding, and accessibility package splits are now deferred until a second concrete implementation exists.
- Accessibility fallback is now explicit capability metadata, not a silent "screenshot-only still works" fallback that could pretend element targeting exists.

**Validation**

- Passed: Graphify report read before raw source inspection.
- Passed: `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Pending at write time: Markdown/diff validation after this report update.
- No runtime code was changed in this hook pass, so no CUA runtime tests were necessary for the repair.

**Residual Risk**

- Repo-wide triage remains high and should be handled as a separate audit, especially browser-use/vendor code, lockfiles, broad exception handling, and agentic tool surfaces.
- The CUA runtime still needs the planned implementation work: explicit `complete` semantics, independent criticizer, typed action normalization, and tests that reject false completion.

---

Date: 2026-05-11

Scope: code changed in this prompt plus directly connected architecture for the router nudge, contextual file-open handoff, CUA Vision Windows launcher policy, and CUA Vision visual no-op loop guard. This pass intentionally did not expand into the repo-wide browser-use/vendor/package-lock hotspots unless source evidence connected them to the changed paths.

## Scoped Verdict

Score after this audit repair: 18/100, Low slop risk for the scoped changes.

Confidence: Medium-high. The Graphify report is from 2026-04-27 and the repository-wide source scan is noisy, but the changed routing and CUA Vision boundaries were inspected in source and covered by focused regression tests.

## Required Triage

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The severe source-augmented score is repository-wide and dominated by broad signals in vendored browser code, lockfiles, high-fanout model/router files, broad exception handling, and agentic tooling surfaces. For this hook pass, those signals were used only to prioritize inspection around the changed CUA Vision action-handler and routing boundaries.

## Confirmed Finding

### 1. Non-click visual no-op guard bypassed repeated-action intent policy

Status: Fixed in this audit pass.

Evidence:

- `agents/cua_vision/single_call.py:103` introduced a stop threshold for repeated non-click actions such as `type_string`, `press_alt_hotkey`, and `press_key_for_duration`.
- `agents/cua_vision/single_call.py:1090` raised after two unchanged frames for those non-click actions, but the first version did not check whether the user explicitly asked to repeat a keyboard action.
- `agents/cua_vision/action_guard.py:171` already protected click loops with a repeated-action intent check, so the new non-click stop had duplicated the loop policy outside the action-guard boundary.

Risk:

- The launcher loop fix would stop the real failing pattern, but it could also abort valid tasks like "Press Down 3 times" when each keypress leaves the screenshot visually unchanged.
- That is a classic slop-like patch shape: useful symptom control, but not integrated with the existing policy owner.

Root-cause fix:

- `agents/cua_vision/action_guard.py:102` now owns generic `task_expects_repeated_actions()`.
- `agents/cua_vision/action_guard.py:129` keeps `task_expects_repeated_clicks()` as the click-loop compatibility wrapper, so click and keyboard repeat intent share one policy.
- `agents/cua_vision/single_call.py:1091` now consults `task_expects_repeated_actions(task)` before stopping repeated non-click visual no-ops.
- `tests/test_cua_vision_action_guard_boundary.py:94` covers repeated keyboard intent and the false-positive word case `sometimes`.
- `tests/test_cua_vision_loop_guard.py:530` proves the launcher Alt+Space no-op still stops early, while `tests/test_cua_vision_loop_guard.py:574` proves an intentional repeated keyboard task is allowed.

## Audited Without New Repair

### Router and session-context nudge

Status: Accepted as scoped and tested.

Evidence:

- `models/prompts.py:77` and `models/prompts.py:153` nudge the router toward CLI for known local paths and follow-up editor opens instead of forcing every editor-related request.
- `models/rapid_state.py:270` injects the known file path only when session context has a last file path and the follow-up task is a contextual file open without an explicit path.
- `models/rapid_state.py:305` adds session-context guidance that still leaves visible UI clicks with `cua_vision`.
- `tests/test_rapid_state_boundary.py:162` verifies a contextual "open the file in vscode" route moves from `cua_vision` to `cua_cli`, and `tests/test_rapid_state_boundary.py:172` verifies an explicit VS Code UI click remains `cua_vision`.
- `tests/test_router_chaining.py:879` simulates the real failure shape by having the router choose `cua_vision` for a follow-up file open; the enriched route executed as `cua_cli`.

Verdict:

- This is a bounded guardrail rather than broad agent forcing. It is acceptable because it applies only when the session owns a concrete file path and the task is a contextual file-open request. It does not override visual UI manipulation.

### CUA Vision Windows launcher policy

Status: Accepted as scoped and tested.

Evidence:

- `agents/cua_vision/prompts.py:8` still acknowledges the Google app launcher dependency.
- `agents/cua_vision/prompts.py:11` tells the agent to use an already visible/open app directly.
- `agents/cua_vision/prompts.py:14` requires confirming the launcher/search input is visible and focused before typing.
- `agents/cua_vision/prompts.py:19` instructs the agent to report the app as unavailable when search cannot find/open it after a reasonable search.
- `tests/test_cua_vision_windows_launch_policy.py:43` verifies the prompt contains those constraints.

Verdict:

- The prompt is no longer "Google launcher first for everything." It nudges app opening through Windows app availability and visible-screen evidence while preserving the launcher as an available search surface.

## Validation

- Passed: `.\\.venv\\Scripts\\python.exe tests/test_cua_vision_action_guard_boundary.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_cua_vision_loop_guard.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_cua_vision_windows_launch_policy.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_rapid_state_boundary.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_router_chaining.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_agent_step_runner_latency.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_output_file_artifacts.py`
- Passed: `.\\.venv\\Scripts\\python.exe tests/test_routing_policy.py`

## Residual Risk

- Repo-wide Graphify/source-scan risk remains high outside this scoped hook pass. The largest hotspots include vendored browser-use files, lockfiles, broad exception handling, and high-fanout routing/model modules. Those should be handled in a separate broader audit so this prompt does not sprawl past the changed architecture.
- The Google app launcher dependency still needs a product decision. Current code treats it as an available Windows app search surface, not as the only path for app opening.
