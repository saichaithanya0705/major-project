# AI Slop Audit

## 2026-05-15 Hook Pass - CUA Slop Recheck

Scope: current uncommitted CUA implementation plus directly connected model-policy, provider-selection, criticizer, backend/controller, and routed-completion tests. This pass did not expand into unrelated repo-wide browser/tooling hotspots because source evidence did not connect them to the current CUA root cause.

**Verdict**

Score after this recheck: 6/100, Minimal slop risk for the scoped CUA implementation.

Confidence: High for the scoped implementation. Graphify remains dated 2026-04-27 and misses the newest CUA files, but it still identified the relevant CUA action/capture island (`Community 32`) and routed-agent bridge (`Community 6`). Current source, diffs, and tests were inspected directly after the required Graphify triage.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown` once for this hook pass.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The severe source-augmented result remains repo-wide and is dominated by old/vendor/browser/tooling surfaces. This pass used it only as triage for the CUA slice and direct provider/routing boundaries.

**Findings**

No new confirmed AI-slop finding was found in the scoped CUA implementation during this pass.

| Area | Evidence Checked | Result |
|---|---|---|
| Strong/weak model path | `agents/cua_vision/model_policy.py` validates `CUA_VISION_*_REASONING` env values and emits provider purposes such as `cua_planner_low` and `cua_planner_strong`; `agents/cua_vision/single_call.py` calls `self._model_policy.provider_purpose(...)`; `models/openrouter_fallback.py` resolves role/strength-specific NVIDIA/OpenRouter env keys. | Accepted. The policy is live in the provider path instead of being detached configuration. |
| Completion correctness | `agents/cua_vision/criticizer.py` requires semantic, accessibility, structural, or visible goal-state evidence; `agents/cua_vision/single_call.py` treats inconclusive visual checks as unknown and counts rejected completion claims for escalation. | Accepted. A low-reasoning planner cannot complete solely from a pixel change or self-claim. |
| Boundary exception handling | `agents/cua_vision/accessibility.py`, `agents/cua_vision/computer_backend.py`, and `agents/cua_vision/controller.py` convert external/UI failures into explicit unavailable snapshots or incomplete `ActionResult`/run results. | Accepted. Broad catches are at integration boundaries and preserve typed failure state. |
| Provider env indirection | `models/openrouter_fallback.py` centralizes OpenRouter/NVIDIA CUA env order maps and defaults at the provider boundary. | Accepted. This removes caller duplication and is covered by provider-selection tests. |

**No Repair Applied In This Pass**

The prior confirmed issue, "reasoning policy config existed but the live provider path ignored it," remains fixed: the live step-response path now routes through `CuaModelPolicy.provider_purpose()`, and focused tests prove rejected completion uses the strong CUA planner purpose. Because no new confirmed root-cause defect was found, this pass updated the audit report only.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_model_policy.py tests/test_cua_vision_loop_guard.py tests/test_router_backends_boundary.py -q` -> 26 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_router_backends_boundary.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q` -> 132 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m compileall -q agents\\cua_vision models\\openrouter_fallback.py models\\agent_step_runner.py`.
- Passed: `git diff --check` with CRLF normalization warnings only.

**Residual Risk**

- Live desktop validation was not run because it would manipulate the user's active Windows session.
- Repo-wide scanner risk outside CUA remains high and should be handled as a separate broad repository audit.
- Existing `cmd`/`node` processes were observed before finishing, but they were pre-existing desktop/Codex activity rather than foreground validation processes created by this pass.

---

## 2026-05-15 Hook Pass - Current CUA Implementation Full Check

Scope: all current uncommitted CUA implementation work plus directly connected model-provider and router boundaries. Inspected `agents/cua_vision/*`, `models/openrouter_fallback.py`, `models/agent_step_runner.py`, focused CUA tests, and provider-selection tests.

**Verdict**

Score after this repair: 7/100, Minimal slop risk for the scoped CUA implementation.

Confidence: High for the scoped implementation. Graphify is dated 2026-04-27 and does not include the newest CUA files, but it still points to the relevant CUA action/capture cluster (`Community 32`) and routed-agent bridge (`Community 6`). Current source and tests were inspected directly after Graphify triage.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The severe scanner result remains repo-wide and is dominated by old/vendor/browser/tooling surfaces. This pass only used it as triage for the scoped CUA implementation and directly connected provider/routing code.

**Confirmed Finding Fixed**

| Signal | Graph Evidence | Source Evidence | Classification | Permanent Fix |
|---|---|---|---|---|
| Reasoning policy config existed but the live provider path ignored it. | Community 32 covers CUA action/capture behavior and Community 6 covers routed-agent execution, so model-selection policy must connect to those boundaries rather than sit as an isolated helper. | `agents/cua_vision/model_policy.py` exposed `CuaModelPolicy.from_env()`, but `agents/cua_vision/single_call.py` still called `get_nvidia_models("vision")` and `get_openrouter_models("vision")` for every step. The audit report even listed provider wiring as residual risk. | Confirmed slop signal: apparently complete configuration without runtime effect. | `CuaModelPolicy` now owns provider purposes such as `cua_planner_low` and `cua_planner_strong`; `SingleCallVisionEngine` uses policy context to select the provider purpose; `models/openrouter_fallback.py` resolves role/strength-specific NVIDIA/OpenRouter env model lists with safe vision defaults. |

**Additional Source Checks**

- Completion remains gated by explicit goal evidence rather than pixel change.
- `tts_speak` remains non-terminal feedback.
- Inconclusive visual comparison remains unknown, not success.
- Accessibility provider validation rejects non-finite confidence and malformed bounds.
- Backend/controller failure paths return honest incomplete results instead of escaping typed boundaries.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_model_policy.py tests/test_cua_vision_loop_guard.py tests/test_router_backends_boundary.py -q` -> 26 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_router_backends_boundary.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q` -> 132 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m compileall -q agents\\cua_vision models\\openrouter_fallback.py`.

**Residual Risk**

- Live desktop validation was not run because it would manipulate the user's active Windows session.
- Repo-wide scanner risk outside CUA remains high and should be handled as a separate broad repository audit.

---

## 2026-05-15 Hook Pass - CUA Reasoning Policy Env Configuration

Scope: the user's proposed CUA reasoning-strength configuration plus directly connected `agents/cua_vision/model_policy.py` and `tests/test_cua_vision_model_policy.py`.

**Verdict**

Score after this repair: 9/100, Minimal slop risk for the scoped reasoning-policy configuration boundary.

Confidence: High for the scoped code. Graphify remains stale for the latest CUA files, but it still identifies CUA capture/action (`Community 32`) and routed-agent (`Community 6`) as relevant review areas. Source inspection confirmed the current reasoning policy was cohesive but hard-coded.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The severe scanner score is repo-wide and dominated by old/vendor/browser/tooling surfaces; this pass stayed scoped to the CUA reasoning-policy question.

**Confirmed Finding Fixed**

| Signal | Graph Evidence | Source Evidence | Classification | Permanent Fix |
|---|---|---|---|---|
| Reasoning strength was policy-owned but not configurable. | Community 32 and Community 6 make CUA action/completion and router boundaries the relevant places to avoid path duplication. | `agents/cua_vision/model_policy.py` had a clean `CuaModelPolicy`, but defaults were hard-coded. Adding ad hoc env checks in callers would duplicate model-strength decisions across planner, grounder, and critic paths. | Confirmed slop-prevention signal. | Added `CuaModelPolicy.from_env()` with validated env variables for planner, grounder, critic, and low-confidence threshold. Invalid or non-finite values now fail loudly instead of silently selecting the wrong path. |

**Design Decision**

- Environment config is appropriate, but it should select role strength through one policy boundary, not fork the CUA into separate strong/weak pipelines.
- Strong reasoning can be the default for critic/completion and escalation cases; weak/low reasoning can remain valid for simple planner steps when action normalization, grounding, and completion criticism still enforce correctness.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_model_policy.py -q` -> 6 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q` -> 131 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m compileall -q agents\\cua_vision\\model_policy.py`.
- Passed: `git diff --check` with CRLF normalization warnings only.

**Residual Risk**

- Superseded by the 2026-05-15 full implementation check above, which wires provider/model-call selection through `CuaModelPolicy`.

---

## 2026-05-15 Subagent Critique - CUA Completion and Validation Hardening

Scope: current CUA implementation changed in this prompt plus directly connected architecture. A read-only explorer subagent (`Ohm`, status `returned`) criticized `agents/cua_vision/agent.py`, `agents/cua_vision/single_call.py`, `agents/cua_vision/criticizer.py`, `agents/cua_vision/accessibility.py`, `models/agent_step_runner.py`, and focused CUA tests. The main agent reviewed and integrated the confirmed findings.

**Verdict**

Score after this repair: 8/100, Minimal slop risk for the scoped CUA completion and validation boundary.

Confidence: High for the scoped code. Graphify is still stale for the new CUA files, but the required report and scanner were used first, then source and tests confirmed the actual defects.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown` once before repair.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- The scanner was not rerun after repairs, per the hook completion gate. The severe source-augmented result remains repo-wide and is not evidence that the scoped CUA files are still slop-heavy.

**Confirmed Findings Fixed**

| Signal | Source Evidence | Classification | Permanent Fix |
|---|---|---|---|
| `VisionAgent` discarded the real `CuaRunResult`. | `_call_interaction_loop()` and `_interact_with_screen()` awaited the interaction engine without returning it, so a false/incomplete result could fall through to `complete=True`. | Confirmed slop signal. | Both boundaries now return the awaited result. `tests/test_cua_vision_agent_boundary.py` covers the real engine path, not only a mocked `_call_interaction_loop()`. |
| Pixel change was treated as goal completion evidence. | `single_call.py` used visible change as `completion_evidence`; `criticizer.py` accepted generic `completion_evidence=True`. A low-reasoning model could click the wrong thing, see pixels change, then claim success. | Confirmed slop signal. | Visual change is now only telemetry (`visual_change_since_last_action`). The criticizer accepts completion only from explicit goal-state evidence (`visible_goal_satisfied`, `accessibility_goal_satisfied`, `semantic_goal_satisfied`) or a sourced compatibility metric. A configured semantic judge can make the completion decision directly. |
| Inconclusive visual comparison counted as visible effect. | `global_similarity is None` made `globally_unchanged=False`, which set `_last_action_had_visible_effect=True`. | Confirmed slop signal. | Inconclusive visual verification now records an observation and leaves the effect state unknown, which cannot satisfy completion. |
| `tts_speak` was terminal like `task_is_complete`. | `_handle_function_call()` grouped `tts_speak` with `task_is_complete`, so speech/status feedback could end a run. | Confirmed slop signal. | `tts_speak` now executes as non-terminal feedback and does not increment desktop action evidence. |
| Accessibility payloads accepted non-finite confidence and malformed bounds. | `float(math.nan)` bypassed range checks, and bounds were passed through unvalidated to grounding consumers. | Confirmed slop signal. | `WindowsAccessibilityProvider` now normalizes bounds to finite positive rectangles, rejects non-finite confidence/bounds, skips invalid elements, and reports normalization errors. |

**Also Preserved From This Hook Repair**

- `PyAutoGuiComputerBackend.execute()` now returns explicit failed `ActionResult` on pre-observation failure instead of escaping the typed backend contract.
- `type_string` execution now prevents stale raw arguments from overriding the normalized text payload.
- `CuaController` now replaces immutable result values when adding unexpected-window metrics and returns honest incomplete results when post-action re-observation fails.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_agent_boundary.py tests/test_cua_vision_loop_guard.py tests/test_cua_vision_criticizer.py tests/test_cua_vision_accessibility_provider.py tests/test_cua_vision_controller.py tests/test_cua_vision_end_to_end_fake_backend.py tests/test_agent_step_runner_cua_completion.py -q` -> 40 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q` -> 129 passed.
- Passed: `.\\.venv\\Scripts\\python.exe -m compileall -q agents\\cua_vision models\\agent_step_runner.py`.
- Passed: `git diff --check` with CRLF normalization warnings only.

**Residual Risk**

- Live desktop validation was not run because it would manipulate the user's active Windows session.
- Strong reasoning can improve judgment only when wired as an independent critic/semantic judge over the observed state. A stronger planner alone does not fix completion correctness if the runtime still accepts unsourced completion claims; this repair makes that boundary explicit.
- Repo-wide scanner risk remains outside this scoped pass, mainly old/vendor/browser/tooling surfaces.

---

## 2026-05-14 Hook Pass - Current CUA Implementation Re-Audit

Scope: current merged `main` CUA runtime implementation plus directly connected routing/completion boundaries. Inspected source included `agents/cua_vision/single_call.py`, `agents/cua_vision/computer_backend.py`, `agents/cua_vision/controller.py`, `agents/cua_vision/criticizer.py`, `agents/cua_vision/action_normalizer.py`, `agents/cua_vision/grounding.py`, `agents/cua_vision/accessibility.py`, `agents/cua_vision/session_state.py`, `agents/cua_vision/trajectory.py`, `agents/cua_vision/agent.py`, `models/agent_step_runner.py`, and the focused CUA/router tests.

**Verdict**

Score after this repair: 11/100, Minimal slop risk for the scoped current CUA implementation.

Confidence: Medium-high. Graphify is dated 2026-04-27 and does not include the new CUA files, but it still identified the relevant older CUA community (`Community 32`) and routed-agent bridge (`Community 6`). Current source and tests were inspected directly.

**Required Triage**

- Read `graphify-out/GRAPH_REPORT.md` before raw source inspection.
- Inventoried Graphify outputs with `rg --files graphify-out`.
- Ran `python C:/Users/SAI/.codex/skills/audit-ai-slop/scripts/graphify_slop_scan.py --graphify-out graphify-out --source-root . --format markdown`.
- Graph-only triage score: 51/100, Moderate.
- Source-augmented triage score: 96/100, Severe.
- Repo-wide scanner severity remains dominated by old/vendor/browser/tooling surfaces. This pass did not expand into those unrelated hotspots because source evidence did not connect them to the CUA implementation changed in this prompt.

**Confirmed Findings Fixed**

| Signal | Graph Evidence | Source Evidence | Classification | Permanent Fix |
|---|---|---|---|---|
| Legacy completion evidence accepted unknown visual effect. | Community 32 centers CUA capture/visual helpers and completion-sensitive action loops. | `agents/cua_vision/single_call.py` treated `_last_action_had_visible_effect is None` as enough evidence after any executed action. That could let a low-reasoning model claim completion after an unverified action. | Confirmed slop signal. | Completion claims now require `_last_action_had_visible_effect is True` or equivalent explicit evidence before `CuaCriticizer` accepts them. Added `tests/test_cua_vision_loop_guard.py` coverage for unknown vs verified visual evidence. |
| Backend could escape the typed `ActionResult` boundary before action execution. | Community 32 includes active-window capture and action execution helpers. | `PyAutoGuiComputerBackend.execute()` called `observe()` before its try/return boundary. A capture failure could raise instead of returning an explicit failed `ActionResult`, contradicting the backend contract. | Confirmed slop signal. | Backend now uses one `_safe_observe()` path for before/after observations; pre-observation failure returns `executed=False` without performing the action. Added `tests/test_cua_vision_pyautogui_backend.py` coverage. |
| Frozen result contract was being mutated through a nested metrics dict. | Graphify is stale for `controller.py`, but Community 6/32 routing/action bridge made controller state mutation a direct review target. | `CuaController.run()` mutated `result.metrics["unexpected_window_change"]` after `ActionResult` creation. | Confirmed slop signal. | Controller now uses `dataclasses.replace()` to create a new `ActionResult` with merged metrics, keeping result handling value-oriented. Existing controller and trajectory tests cover behavior. |

**Healthy Signals**

- New CUA modules are narrow contract boundaries rather than reference-shaped packages: normalization, backend, session state, grounding, accessibility, criticizer, controller, trajectory, and model policy each own one decision boundary.
- Low-reasoning model output is normalized and policy-checked before execution.
- Completion semantics are now explicit: `success` means the agent ran; `complete` means the user goal has evidence-backed completion.
- Tests include failure paths: false completion, low-confidence grounding, blocked hotkeys, pre-observation capture failure, invalid actions, and incomplete routed CUA steps.

**Validation**

- Passed: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_cua_vision_loop_guard.py tests/test_cua_vision_pyautogui_backend.py tests/test_cua_vision_controller.py tests/test_cua_vision_criticizer.py -q` -> 35 passed.
- Passed: `$files = Get-ChildItem -Path tests -Filter 'test_cua_vision_*.py' | ForEach-Object { $_.FullName }; .\\.venv\\Scripts\\python.exe -m pytest @files tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q` -> 121 passed.

**Residual Risk**

- Live desktop validation was not run in this hook pass because it would manipulate the user's active Windows session.
- Repo-wide Graphify/source-scan risk remains high outside this scoped CUA pass, especially vendored `browser_use`, lockfiles, and broad non-CUA agent/tooling surfaces.

---

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
