# Codebase AI-Slop Remediation Tasks

Scope: remaining codebase-level AI-slop-like issues after the recent router/model, CLI foreground-runtime, browser fallback, app lifecycle, and async subprocess-boundary repairs.

Source basis:
- `graphify-out/GRAPH_REPORT.md`
- fresh `graphify_slop_scan.py` triage output on 2026-05-17
- `docs/audits/ai-slop/AI_SLOP_AUDIT.md`
- direct source inspection of the strongest remaining first-party and vendored hotspot clusters

Status legend:
- `pending`: identified but not yet assigned
- `assigned`: handed to a subagent
- `running`: subagent actively working
- `returned`: subagent finished; main-agent review pending
- `integrated`: reviewed and merged into the main line
- `rejected`: returned work not accepted
- `closed`: no longer needed because another fix eliminated the seam

## Subagent Board

| Agent | Scope | Ownership | Status | Merge Point |
|---|---|---|---|---|
| `Noether` | BrowserAgent shared-state/lifecycle cleanup | `agents/browser/agent.py`, `agents/browser/browser_use_boundary.py`, `agents/browser/playwright_boundary.py`, focused browser boundary tests | `integrated` | recovered from worker exit and validated locally |
| `Copernicus` | CLIAgent execute/response-promotion cleanup | `agents/cua_cli/agent.py`, `agents/cua_cli/background_manager.py`, optional new helper module(s), focused CLI tests | `integrated` | recovered from worker exit and validated locally |
| `Huygens` | Agent-step runner contract hardening | `models/agent_step_runner.py`, `models/agent_step_execution_runtime.py`, focused routing/runtime tests | `integrated` | recovered from worker exit and validated locally |
| `Carver` | Rapid orchestrator failure-path/direct-response cleanup | `models/rapid_orchestrator.py`, focused rapid/chaining/bridge tests | `integrated` | worker hit usage limit; recovered locally, fixed one compatibility regression, and validated |
| `Epicurus` | Browser-use vendored containment survey | read-only survey of `agents/browser/browser_use/**` and current first-party browser boundaries | `returned` | next task recommendation captured locally |
| `Carson` | Browser-use containment bypass survey | read-only survey of first-party browser-use agent/session creation paths after recovery | `closed` | helper timed out during recovery; main agent completed the containment slices locally |
| `Dalton` | Gemini CLI vendored governance survey | read-only survey of `agents/cua_cli/gemini-cli/**`, `vendor_guard.py`, manifest, and boundary tests | `integrated` | survey confirmed the unpinned `bundle/gemini.js` seam; main agent landed entrypoint hash governance locally |
| `Mill` | Router/orchestrator typed-contract survey | read-only survey of remaining `models/**` dict-shaped routing payload seams | `integrated` | survey confirmed the route-carrier seam; main agent landed typed `OrchestratorTask.route` ownership locally |
| `Bernoulli` | Gemini CLI vendored containment survey | read-only survey of `agents/cua_cli/gemini-cli/**`, `vendor_guard.py`, manifest, and current integration touchpoints | `rejected` | worker hit usage limit before returning results |

## Canonical Task List

| ID | Priority | Module | Issue | Permanent Fix Direction | Focused Validation | Status |
|---|---|---|---|---|---|---|
| `CB-BR-01` | P0 | `agents/browser/agent.py` | BrowserAgent still mixes shared mutable browser-use/playwright state, fallback policy, lifecycle cleanup, and execution orchestration in one oversized shell. | Move shared resource lifecycle and resume-state bookkeeping behind explicit boundaries, shrink `BrowserAgent` to coordination logic, and remove broad shell-level catches where typed boundary errors can be used instead. | `tests/test_browser_agent_fallback.py`, `tests/test_browser_playwright_boundary.py`, `tests/test_browser_use_dependency_boundary.py` | `integrated` |
| `CB-BR-02` | P1 | `agents/browser/browser_use/**` + first-party boundaries | Vendored browser-use code dominates hotspot counts with heavy `Any`, broad catches, and low cohesion. | Do not hand-edit the whole vendor tree blindly; contain it behind first-party boundary modules, tighten integration points, and identify the smallest high-value patches needed for correctness/safety. Landed slices now include first-party tool policy blocking `write_file` / `replace_file`, explicit browser-use session policy ownership, lifecycle-backed session reuse, and removal of dead retained-handle/double-cleanup stop logic. | focused browser boundary tests + any new containment tests | `running` |
| `CB-CLI-01` | P0 | `agents/cua_cli/agent.py` | `CLIAgent.execute()` still mixes subprocess orchestration, response normalization, tool-call interpretation, and server-promotion policy. | Extract response/promotion/runtime boundaries so `execute()` becomes a thin coordinator over explicit helper modules and typed result paths. | `tests/test_cli_*`, `tests/test_cua_cli_vendor_boundary.py` | `integrated` |
| `CB-CLI-02` | P1 | `agents/cua_cli/gemini-cli/**` + vendor guard | Vendored Gemini CLI contributes large raw-score noise and runtime blast radius if drift is unchecked. | Keep vendored governance explicit through manifest validation and boundary enforcement; strengthen runtime integration so drift fails closed. Landed slice: the guard now pins the reviewed runtime entrypoint `bundle/gemini.js`, and `CLIAgent` executes the validated entrypoint path rather than reconstructing it ad hoc. | `tests/test_cua_cli_vendor_boundary.py`, focused CLI runtime slice | `running` |
| `CB-MR-01` | P0 | `models/agent_step_runner.py` | Agent-step runner still has broad exception mapping and soft payload handling at a central orchestration boundary. | Tighten failure mapping, reduce `Any` leakage, and move remaining normalization into owning runtime helpers with typed step-result flow. | `tests/test_agent_step_execution_runtime.py`, `tests/test_routing_contracts.py`, focused chaining slice | `integrated` |
| `CB-MR-02` | P0 | `models/rapid_orchestrator.py` | Rapid orchestrator still carries broad error paths and soft direct-response/tool-emission coordination. | Continue decomposing orchestration flow into typed helper boundaries and narrow exception handling to structural failure types. | `tests/test_router_chaining.py`, `tests/test_rapid_orchestrator_contracts.py`, `tests/test_models_bridge_boundaries.py` | `integrated` |
| `CB-MR-03` | P1 | `models/**` cross-cutting routing contracts | Remaining `MR-17` / `MR-18` debt: routing payload contracts are improved but still not uniformly hard across all router/orchestrator layers. | Finish shared typed routing contracts and add missing ownership tests so new seams stop regressing into dict-shaped payload drift. Landed slices: `OrchestratorTask` now carries a first-class typed `route`, route semantics no longer live in task metadata for adapter/planner/quality round-trips, and plan-task payloads are now copied/normalized before orchestration so plan metadata no longer aliases caller-owned nested route dictionaries. | `tests/test_routing_contracts.py`, connected router/model boundary tests | `running` |
| `CB-ME-01` | P2 | audit/measurement hygiene | Raw slop score is materially inflated by vendored trees, lockfiles, generated graph artifacts, and audit docs. | Keep this separate from product fixes: define an explicit audit-scope policy so future whole-codebase ratings distinguish product debt from vendor/generated noise. | audit docs only | `pending` |

## Execution Order

1. `CB-BR-01`, `CB-CLI-01`, `CB-MR-01` in parallel (disjoint write scopes)
2. `CB-BR-02` active containment pass: tool/session policy slices are integrated; next sub-slice is broader boundary-owned persistence/session leasing beyond the removed dead retained-handle path
3. `CB-CLI-02` active pass: executable entrypoint pin landed; next sub-slice is trusted-scope/runtime path governance
4. `CB-MR-03` active pass: plan-payload normalization landed; next sub-slice is remaining outcome/metadata dict tightening
5. `CB-ME-01` after product fixes stabilize

## Notes

- This board is the codebase-level tracker. The detailed model/router seam inventory remains in `docs/audits/ai-slop/MODEL_ROUTER_REMEDIATION_TASKS.md`.
- Vendored code is a major contributor to the raw scanner score, but containment is preferred over indiscriminate rewrites.
- Status changes are authoritative only after main-agent review and validation.
