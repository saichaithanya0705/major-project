# MAS Orchestrator LLD

Date: 2026-05-15

## Goal

Move the current router-backed agent selection toward a true multi-agent system without turning the router into a loop that calls every agent one by one. The router should only propose separable work. The orchestration layer should own typed tasks, dependencies, resource safety, execution, artifacts, and traceability.

## Importance Scale

- Critical: required before live multi-agent execution can be trusted.
- High: required before the system is operable and debuggable for real users.
- Medium: improves UX, coverage, or future extensibility after the core safety model is in place.

## Level 1 - Resource Contract Hardening

Importance: Critical

Problem: The MAS scheduler already has resource locks, but planner-provided `resources` can override task defaults. If a router/model payload assigns a browser task only `model_router`, the scheduler can be tricked into running browser work concurrently with other browser work.

Design:

- `resources_for_agent(agent)` remains the canonical required-lock source.
- `OrchestratorTask` accepts extra locks, but rejects any resource override that omits required locks for the task agent.
- `normalize_orchestration_plan_payload()` continues parsing model plans, but task construction enforces the same invariant for provider-generated payloads.
- Tests cover both direct contract construction and router plan normalization.

Validation:

- Focused planner and scheduler contract tests.
- Full orchestrator/router test slice.

## Level 2 - Artifact And Context Bus

Importance: Critical

Problem: Current chained execution mostly passes state through history/log metadata. A true MAS needs typed task outputs so dependent agents can consume exact artifacts instead of re-reading or guessing from chat text.

Design:

- Add `TaskExecutionContext` with dependency outcomes and typed artifacts.
- Add an `ArtifactStore` that records artifacts by producing task, artifact type, and stable id.
- Pass dependency-scoped artifacts into each task runner.
- Reject ambiguous or unsafe path artifacts unless the producing agent marks them as usable output.

Validation:

- Unit tests for artifact extraction, dependency filtering, and unsafe artifact rejection.
- Executor tests proving dependent tasks receive only completed dependency artifacts.

## Level 3 - Plan Trace And Observability

Importance: High

Problem: Users and developers need to see what the MAS planned, what ran in parallel, what waited on locks, and why tasks failed or skipped.

Design:

- Emit structured plan events: planned, queued, running, completed, failed, skipped, retried.
- Attach per-task status and final outcome to the existing request log.
- Keep trace construction in the orchestrator boundary, not inside individual agents.

Validation:

- Unit tests for trace events.
- Router chaining tests asserting failed dependencies surface clear skip reasons.

## Level 4 - Session And Resource Ownership

Importance: Critical

Problem: Browser, desktop, screenshot, CLI, and model resources have different concurrency limits. The current per-plan scheduler is necessary but not sufficient for app-level concurrent user requests.

Design:

- Introduce a process-wide resource coordinator for shared live resources.
- Keep per-plan scheduling pure, then acquire live resource leases only at execution time.
- Make lease acquisition explicit and release leases in finally blocks around agent execution.

Validation:

- Unit tests for lease conflicts and release on exceptions.
- Integration tests using fake browser/desktop/CLI resources.

## Level 5 - Router Plan Quality Gate

Importance: High

Problem: A model can still produce plans that are technically valid but strategically poor, such as unnecessary serial tasks or agent parades.

Design:

- Add deterministic plan scoring before execution.
- Reject plans with redundant adjacent agents, empty work, unsupported dependency shapes, or tasks that do not contribute to the user request.
- Fall back to a single route when work is not clearly separable.

Validation:

- Policy tests for valid two-agent plans, rejected agent parades, and fallback behavior.

## Level 6 - UI Plan Surface

Importance: Medium

Problem: Without a plan surface, MAS behavior is hard to trust. Users need a compact trace, not internal implementation prose.

Design:

- Render task cards or rows with agent, status, dependencies, and result summary.
- Show lock-waiting and skipped states.
- Link artifacts or output files only when verified usable.

Validation:

- UI tests for plan rendering and status updates.
- Accessibility checks for status text and controls.

## Level 7 - Live End-To-End Validation

Importance: High

Problem: Pure unit tests prove orchestration rules, but live agents can fail because of external resources, MCP state, browser sessions, or desktop state.

Design:

- Add fake-agent integration tests as the default CI path.
- Add opt-in live smoke tests for web QA plus CLI, browser plus direct, and screen-context plus CUA vision.
- Keep live desktop tests opt-in because they touch the user's active session.

Validation:

- CI-safe fake-agent suite.
- Manual or opt-in live suite with recorded trace artifacts.

## Current Implementation Order

1. Level 1 complete: required resource locks cannot be weakened by planner payloads or manual task construction.
2. Level 2 complete: typed artifacts and execution context are passed to dependent tasks.
3. Level 3 complete: executor trace events are emitted and runtime plan execution attaches trace metadata to request logs.
4. Level 4 complete: shared resource leases can serialize live resources across concurrent plans.
5. Level 5 complete: model-emitted plan payloads are quality-gated for size, empty work, and duplicate agent work.
6. Level 6 complete: the UI trace model can render orchestration plan snapshots with waiting/running/completed/skipped states.
7. Level 7 complete for CI-safe validation: fake-agent smoke coverage exercises plan normalization, leases, trace events, artifacts, and dependency context. Live desktop/browser smoke remains opt-in because it can manipulate the user's active session.
