# CUA Rearchitecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the current CUA vision path into a reliable computer-use runtime for scoped desktop workflows, with typed actions, grounded targets, explicit completion semantics, independent criticism, trajectory logging, and benchmarked correctness.

**Architecture:** Evolve the current `agents/cua_vision/single_call.py` loop through vertical slices rather than a big-bang rewrite: observe screen -> ask model for intent/action -> normalize action -> ground target -> execute through the existing PyAutoGUI path -> re-observe -> criticize -> continue, retry, fail, or complete. Extract a module only when it owns an enforced contract or replaces duplicated behavior. Keep Windows accessibility/window-state support behind an explicit capability boundary inspired by TryCUA's driver model.

**Tech Stack:** Python 3.11, existing `agents/cua_vision` modules, PIL screenshots, PyAutoGUI keyboard/mouse wrappers, current Nvidia/OpenRouter vision model adapters, pytest boundary tests, and a later Windows UI Automation capability provider for element-aware control.

**Implementation Status (2026-05-14):** The core runtime slices are implemented: contracts, action normalization, backend protocol, session state, grounding, accessibility capability metadata, criticizer, controller, trajectory, model policy, fake-backend benchmarks, and routed `success`/`complete` semantics. The legacy `single_call.py` loop remains as a compatibility adapter, but completion claims and repeated-loop stops now go through the critic/incomplete-result boundary instead of silently becoming success.

---

## Current CUA Critique

The current CUA can move and click, but it relies too much on the same model to decide, act, and declare success.

Known weaknesses to fix:
- `agents/cua_vision/agent.py` returns `"Task completed"` after the loop exits, without an independent semantic proof.
- `agents/cua_vision/single_call.py` accepts `task_is_complete` and some repeated-loop exits as completion, which can produce false success.
- `agents/cua_vision/action_policy.py` validates known tool calls but does not normalize broad computer-use action schemas such as `left_click`, `hotkey`, `coordinates`, `element_description`, or `button`.
- `agents/cua_vision/visual_feedback.py` detects no-op visual changes, but it cannot prove the user's goal is complete.
- `models/rapid_orchestrator.py` and `models/agent_step_runner.py` trust successful agent results unless the agent explicitly marks them incomplete.
- The active-window screenshot and PyAutoGUI action layer is useful but not enough for precise multi-window, DPI, accessibility-tree, or off-focus control.

Reference patterns from [trycua/cua](https://github.com/trycua/cua) to adapt:
- A typed `Computer`/handler interface for screenshot, click, scroll, type, keypress, drag, and wait.
- An operator normalizer that repairs model action schemas before execution.
- A composed grounded loop where a reasoning model may describe an element and a grounding layer maps that description to coordinates.
- Trajectory saving with screenshots, action results, and annotated clicks.
- Budget and image-retention callbacks.
- Windows UI Automation/window-state support with element indexes, screenshots, and action execution targeted to a specific window.

## Design Rule

Do not make model strength the safety mechanism. Strong reasoning models should improve planning and criticism, but code-level contracts must still enforce target grounding, action validity, completion proof, retry limits, and routing truth.

Do not add architecture-shaped layers just because the reference project has them. Every new module below must either consolidate existing duplicated behavior, create a testable boundary around an external system, or make an unsafe state unrepresentable. If a task can be completed by strengthening an existing module without muddying its responsibility, do that first.

Low-reasoning models can be allowed to propose actions only when:
- The action schema is constrained.
- The normalizer repairs or rejects malformed calls.
- The grounder converts semantic targets to verified coordinates or element IDs.
- The criticizer blocks completion unless the goal is visibly or structurally satisfied.
- The controller can retry with a stronger model or fail honestly.

## Task 1: Canonical CUA Contracts

**Files:**
- Create: `agents/cua_vision/contracts.py`
- Test: `tests/test_cua_vision_contracts.py`

- [x] Add canonical data classes for observations, actions, targets, results, and critic verdicts.
- [x] Keep these contracts free of PyAutoGUI, PIL implementation details, and model SDK types.
- [x] Include explicit `complete` and `confidence` fields so success and completion are not collapsed.
- [x] Do not introduce a `core/` package unless a later slice proves multiple cohesive core modules are needed.
- [x] Run `python -m pytest tests/test_cua_vision_contracts.py -q`.

Core contract shape:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE_TEXT = "type_text"
    KEYPRESS = "keypress"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"
    COMPLETE = "complete"
    ABORT = "abort"


class TargetKind(str, Enum):
    NONE = "none"
    COORDINATE = "coordinate"
    BBOX = "bbox"
    ELEMENT_ID = "element_id"
    DESCRIPTION = "description"


@dataclass(frozen=True)
class TargetRef:
    kind: TargetKind
    x: float | None = None
    y: float | None = None
    bbox: tuple[float, float, float, float] | None = None
    element_id: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ComputerAction:
    action_type: ActionType
    target: TargetRef = TargetRef(TargetKind.NONE)
    text: str | None = None
    keys: tuple[str, ...] = ()
    scroll_delta: int | None = None
    duration_seconds: float | None = None
    raw_name: str | None = None
    raw_args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScreenObservation:
    screenshot_png_base64: str | None
    active_window_title: str | None
    capture_context: dict[str, Any]
    accessibility_tree: str | None = None
    elements: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ActionResult:
    executed: bool
    message: str
    before: ScreenObservation | None = None
    after: ScreenObservation | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CriticVerdict:
    complete: bool
    should_continue: bool
    confidence: float
    reason: str
    next_hint: str | None = None
```

## Task 2: Action Normalizer

**Files:**
- Create: `agents/cua_vision/action_normalizer.py`
- Modify: `agents/cua_vision/action_policy.py`
- Test: `tests/test_cua_vision_action_normalizer.py`

- [x] Normalize current internal tool calls into `ComputerAction`.
- [x] Normalize TryCUA/OpenAI-style action names: `left_click`, `right_click`, `double_click`, `move`, `keypress`, `hotkey`, `type`, `scroll`, `wait`, `computer_call_output`.
- [x] Normalize common argument aliases: `coordinate`, `coordinates`, `x`, `y`, `button`, `element_description`, `target_description`, `key`, `keys`, `text`, `string`.
- [x] Reject unsupported or ambiguous actions with a structured error before they reach the backend.
- [x] Preserve existing safety checks from `action_policy.py`.
- [x] Run `python -m pytest tests/test_cua_vision_action_normalizer.py tests/test_cua_vision_security_policy.py tests/test_cua_vision_interaction_policy_boundary.py -q`.

Acceptance examples:
- `{"name": "left_click", "arguments": {"coordinate": [12, 40]}}` becomes `ComputerAction(ActionType.CLICK, TargetKind.COORDINATE)`.
- `{"name": "hotkey", "arguments": {"keys": ["ctrl", "l"]}}` becomes `ComputerAction(ActionType.HOTKEY, keys=("ctrl", "l"))`.
- `{"name": "click_target", "arguments": {"xmin": 1, "ymin": 2, "xmax": 9, "ymax": 12, "target_description": "Save"}}` becomes a bbox-target click.

## Task 3: Backend Protocol and PyAutoGUI Adapter

**Files:**
- Create: `agents/cua_vision/computer_backend.py`
- Modify: `agents/cua_vision/keyboard.py`
- Modify: `agents/cua_vision/screen_context.py`
- Test: `tests/test_cua_vision_backend_protocol.py`
- Test: `tests/test_cua_vision_pyautogui_backend.py`

- [x] Define `ComputerBackend` with `observe()`, `execute(action)`, `get_active_window()`, and `close()`.
- [x] Wrap existing `capture_active_window`, coordinate mapping, `type_string`, hotkeys, mouse clicks, scroll, and waits behind this backend.
- [x] Ensure backend execution returns `ActionResult`, not bare exceptions or strings.
- [x] Add a `FakeComputerBackend` test helper for deterministic controller tests.
- [x] Keep the first implementation in one module; split into a `backends/` package only when a second concrete backend lands.
- [x] Run `python -m pytest tests/test_cua_vision_backend_protocol.py tests/test_cua_vision_pyautogui_backend.py tests/test_cua_vision_windows_launch_policy.py -q`.

Backend protocol:

```python
from typing import Protocol

from agents.cua_vision.contracts import ActionResult, ComputerAction, ScreenObservation


class ComputerBackend(Protocol):
    def observe(self) -> ScreenObservation:
        ...

    def execute(self, action: ComputerAction) -> ActionResult:
        ...

    def get_active_window(self) -> str | None:
        ...

    def close(self) -> None:
        ...
```

## Task 4: Window Targeting and Session State

**Files:**
- Create: `agents/cua_vision/session_state.py`
- Modify: `agents/cua_vision/runtime_state.py`
- Modify: `agents/cua_vision/screen_context.py`
- Test: `tests/test_cua_vision_session_state.py`

- [ ] Track task id, initial active window title, last trusted observation, action count, retry count, and completion status.
- [ ] Add a policy for expected window changes: allow them when the model action implies app launch, browser navigation, file picker, or dialog handling; otherwise warn the criticizer.
- [ ] Store window/capture context in every action result so coordinate transforms can be audited.
- [ ] Run `python -m pytest tests/test_cua_vision_session_state.py tests/test_cua_vision_loop_guard.py -q`.

## Task 5: Grounding Layer

**Files:**
- Create: `agents/cua_vision/grounding.py`
- Modify: `agents/cua_vision/legacy_locator.py`
- Modify: `agents/cua_vision/tools.py`
- Test: `tests/test_cua_vision_grounding.py`

- [ ] Convert bbox targets into screen coordinates using existing active-window capture context.
- [ ] Convert description targets into coordinates by reusing the current crop/search or locator path.
- [ ] Return a `GroundedTarget` with coordinate, confidence, source, and evidence.
- [ ] Require a minimum confidence threshold before clicking a description-grounded target.
- [ ] Add a "needs stronger model" result when grounding confidence is low.
- [ ] Keep bbox and description grounding together until tests show they need independent implementations.
- [ ] Run `python -m pytest tests/test_cua_vision_grounding.py tests/test_cua_vision_visual_feedback_boundary.py -q`.

## Task 6: Windows Accessibility Provider

**Files:**
- Create: `agents/cua_vision/accessibility.py`
- Modify: `agents/cua_vision/computer_backend.py`
- Test: `tests/test_cua_vision_accessibility_provider.py`

- [ ] Add a capability provider interface that returns an accessibility tree and element list when available.
- [ ] On Windows, implement a provider that can enumerate visible UI elements with role/name/bounds/action hints.
- [ ] If provider initialization fails, return explicit capability metadata such as `{"accessibility": "unavailable", "reason": "..."}` and keep screenshot-only mode working without pretending element targeting exists.
- [ ] Feed element summaries into `ScreenObservation.elements` and the model prompt.
- [ ] Allow `TargetKind.ELEMENT_ID` actions when the provider can map element IDs to bounds.
- [ ] Run `python -m pytest tests/test_cua_vision_accessibility_provider.py -q`.

Implementation note:
- The permanent target is a TryCUA-style driver/sidecar for reliable UIA, but this task should first establish the smallest provider contract and a Windows implementation that is testable without live desktop state by injecting a fake enumerator. Split this into an `accessibility/` package only after multiple providers exist.

## Task 7: Independent Criticizer

**Files:**
- Create: `agents/cua_vision/criticizer.py`
- Modify: `agents/cua_vision/visual_feedback.py`
- Test: `tests/test_cua_vision_criticizer.py`

- [ ] Implement a criticizer that consumes task, before/after observations, executed action, visual metrics, window changes, and model completion claims.
- [ ] Block completion when the only evidence is a model `task_is_complete` call.
- [ ] Use deterministic checks first: no-op visual metrics, loop signatures, sensitive windows, failed grounding, action errors, and unexpected window changes.
- [ ] Add configurable strong-model semantic judgment that must return strict JSON matching `CriticVerdict`.
- [ ] Escalate to a stronger model when a low-reasoning model claims completion with weak evidence.
- [ ] Run `python -m pytest tests/test_cua_vision_criticizer.py tests/test_cua_vision_loop_guard.py -q`.

Criticizer prompt contract:

```text
Return only JSON:
{
  "complete": boolean,
  "should_continue": boolean,
  "confidence": number between 0 and 1,
  "reason": string,
  "next_hint": string or null
}

Judge whether the user's original desktop task is actually complete.
Do not trust the previous model's completion claim by itself.
Use the current screen, accessibility summary, action result, and visual-change metrics.
```

## Task 8: New Controller Loop

**Files:**
- Create: `agents/cua_vision/controller.py`
- Modify: `agents/cua_vision/agent.py`
- Modify: `agents/cua_vision/single_call.py`
- Modify: `agents/cua_vision/prompts.py`
- Test: `tests/test_cua_vision_controller.py`
- Test: `tests/test_cua_vision_agent_boundary.py`

- [ ] Move step orchestration out of `single_call.py` into `CuaController`.
- [ ] Keep `single_call.py` as a compatibility adapter until the new controller has full parity.
- [ ] The controller must run: observe -> model step -> normalize -> ground -> execute -> observe -> criticize.
- [ ] The controller must return `{"success": bool, "complete": bool, "result": str, "error": str, "critic": {...}}`.
- [ ] Stop only when the critic says complete, the user stops the task, the budget is exhausted, or recovery fails.
- [ ] Run `python -m pytest tests/test_cua_vision_controller.py tests/test_cua_vision_agent_boundary.py tests/test_agent_step_runner_latency.py -q`.

Controller shape:

```python
class CuaController:
    async def run(self, task: str) -> dict:
        session = CuaSession.start(task)
        observation = self.backend.observe()
        while session.can_continue():
            model_call = await self.model.next_action(task, observation, session)
            action = self.normalizer.normalize(model_call, active_window=observation.active_window_title)
            grounded_action = self.grounder.ground(action, observation)
            result = self.backend.execute(grounded_action)
            verdict = await self.criticizer.review(task, action, result, session)
            self.trajectory.record(session, action, result, verdict)
            if verdict.complete:
                return self._complete(session, verdict)
            if not verdict.should_continue:
                return self._incomplete(session, verdict)
            observation = result.after or self.backend.observe()
        return self._budget_exhausted(session)
```

## Task 9: Trajectory, Image Retention, and Budgeting

**Files:**
- Create: `agents/cua_vision/trajectory.py`
- Modify: `agents/cua_vision/runtime_state.py`
- Modify: `agents/cua_vision/controller.py`
- Test: `tests/test_cua_vision_trajectory.py`

- [ ] Save per-step JSON with observation metadata, normalized action, grounded target, result, critic verdict, and model name.
- [ ] Save only the latest N screenshots in live context, but keep full trajectory artifacts on disk when tracing is enabled.
- [ ] Add cost/action/time budgets with explicit incomplete results when exhausted.
- [ ] Annotate click screenshots when a grounded coordinate is used.
- [ ] Run `python -m pytest tests/test_cua_vision_trajectory.py -q`.

## Task 10: Router and Orchestrator Completion Semantics

**Files:**
- Modify: `models/agent_step_runner.py`
- Modify: `models/rapid_orchestrator.py`
- Modify: `models/contracts.py`
- Test: `tests/test_agent_step_runner_cua_completion.py`
- Test: `tests/test_router_chaining.py`

- [ ] Preserve `success` as "agent ran without infrastructure failure".
- [ ] Treat `complete` as "the user task is finished".
- [ ] Ensure CUA can return `success=True, complete=False` when it acted but needs another step.
- [ ] Ensure orchestrator does not mark a CUA step complete unless `complete` is explicitly true.
- [ ] Include critic reason in the work trace and final result.
- [ ] Run `python -m pytest tests/test_agent_step_runner_cua_completion.py tests/test_router_chaining.py tests/test_rapid_state_boundary.py -q`.

## Task 11: Strong/Low Reasoning Model Policy

**Files:**
- Create: `agents/cua_vision/model_policy.py`
- Modify: `agents/cua_vision/controller.py`
- Modify: `models/runtime_config.py`
- Test: `tests/test_cua_vision_model_policy.py`

- [ ] Add model roles: `planner`, `grounder`, `critic`.
- [ ] Allow low-reasoning models for routine planner steps when action schema confidence is high.
- [ ] Escalate planner or critic to a stronger model for destructive actions, low grounding confidence, unclear screen state, repeated no-op, or completion claims.
- [ ] Make critic model strength configurable independently from planner model strength.
- [ ] Run `python -m pytest tests/test_cua_vision_model_policy.py -q`.

Policy:
- Low-reasoning planner: acceptable for clicking known UI, typing short text, waiting, simple navigation, and following explicit coordinates.
- Strong planner: required for ambiguous UI, multi-app workflows, recovery after failure, or tasks needing interpretation.
- Strong critic: required for final completion, high-risk actions, or any step where the planner and visual evidence disagree.

## Task 12: Benchmarks and Regression Tasks

**Files:**
- Create: `tests/cua_vision_tasks/__init__.py`
- Create: `tests/cua_vision_tasks/fixtures.py`
- Create: `tests/test_cua_vision_benchmark_harness.py`
- Create: `tests/test_cua_vision_end_to_end_fake_backend.py`

- [ ] Add fake-backend tasks for app launch, button click, form fill, menu selection, repeated click, failed grounding, and false completion.
- [ ] Assert that false completion is rejected.
- [ ] Assert that low-reasoning planner output succeeds when normalized and grounded.
- [ ] Assert that ambiguous completion escalates to strong critic.
- [ ] Run `python -m pytest tests/test_cua_vision_benchmark_harness.py tests/test_cua_vision_end_to_end_fake_backend.py -q`.

## Task 13: Migration and Cleanup

**Files:**
- Modify: `agents/cua_vision/single_call.py`
- Modify: `agents/cua_vision/tools.py`
- Modify: `agents/cua_vision/tool_declarations.py`
- Modify: `agents/cua_vision/status_presenter.py`
- Test: existing CUA test suite

- [ ] Remove duplicated coordinate conversion once `grounding.py` owns it.
- [ ] Remove completion shortcuts that bypass the criticizer.
- [ ] Keep legacy tool declarations only as model-facing aliases mapped by the normalizer.
- [ ] Update statuses to show current phase: observing, planning, grounding, executing, criticizing, retrying, complete, incomplete.
- [ ] Run full focused CUA tests:

```powershell
python -m pytest `
  tests/test_cua_vision_security_policy.py `
  tests/test_cua_vision_loop_guard.py `
  tests/test_cua_vision_interaction_policy_boundary.py `
  tests/test_cua_vision_action_guard_boundary.py `
  tests/test_cua_vision_windows_launch_policy.py `
  tests/test_cua_vision_visual_feedback_boundary.py `
  tests/test_status_bubble_cua_vision.py -q
```

## Final Verification

- [ ] Run all new CUA tests:

```powershell
python -m pytest tests/test_cua_vision_*.py tests/test_agent_step_runner_cua_completion.py -q
```

- [ ] Run router and orchestrator regressions:

```powershell
python -m pytest tests/test_router_chaining.py tests/test_rapid_state_boundary.py tests/test_agent_step_runner_latency.py -q
```

- [ ] Manually run three live desktop tasks with tracing enabled:
  - Open an app and stop after the target window is visible.
  - Click a visible UI control by description.
  - Fill a harmless text field and verify the typed value.
- [ ] Confirm no stale `cmd.exe`, `powershell.exe`, `pwsh.exe`, `node.exe`, `npx`, or test helper processes created by the task remain.

## Expected Outcome

After this plan is implemented, the CUA should no longer be "a vision model with tools." It should be a computer-use runtime where models propose work, code normalizes and grounds it, a backend executes it, and an independent critic decides whether the task is truly complete.

A stronger reasoning model will make the CUA better at planning and judging ambiguous tasks, but it will not make the current design correct by itself. Correctness comes from the combination of strong model judgment, typed action boundaries, reliable observation, precise grounding, independent verification, honest incomplete states, and regression benchmarks.
