# UI Enhancement Plan

## Purpose

This document turns the current UI audit into a concrete enhancement plan for
JARVIS.

The goal is not to make the UI beginner-friendly at the expense of speed. The
goal is to make it feel sharper, clearer, and more trustworthy for technical
users who prefer keyboard-driven workflows and low-friction interfaces.

## Product Lens

- Primary archetype: AI chat / agent console
- Secondary trait: trust-heavy, tool-driven, desktop-first
- Audience: developers, operators, and technical power users
- Density target: medium-high
- Visual direction: restrained, utilitarian, confident
- Stitch usage: skipped
  - Reason: this is an audit and enhancement brief for an existing UI, not a
    net-new shell

## Current Verdict

The UI is directionally good for technical users.

What already works:

- The shortcut-first interaction model matches technical-user expectations.
- The floating chat window is minimal and focused.
- The overlay/status system provides immediate feedback during execution.
- The overall visual tone is coherent and feels closer to a tool than a demo.

What currently holds it back:

- Important behaviors are hidden behind shortcuts, tray interactions, and
  implicit state changes.
- Progress and runtime status copy is too generic for long-running tasks.
- Focus states are missing after `outline: none`, which weakens keyboard trust.
- Some controls and text sizing feel slightly too small for heavy daily use.
- The UI does not yet teach the mental model of "open, submit, inspect, stop,
  resume" inside the product itself.

## Design Goal

Keep the current architecture and interaction model, but make the product feel:

- easier to understand in the first 10 seconds
- more explicit during long-running execution
- more keyboard-legible
- more robust under repeated daily use

Do not add marketing-style decoration or generic "AI glass" styling. This
should remain a fast technical tool.

## Priority 1: Improve Clarity Without Increasing UI Noise

### 1. Add first-run and recall guidance inside the app

Users should not need README access to discover core controls.

Implement:

- a compact help row or inline hint in the input window
- shortcut reminders for:
  - open input
  - stop current actions
  - hide the window
- a one-time first-run helper state, then a quieter persistent hint

Suggested target files:

- `ui/input.html`
- `ui/input_window.css`
- `ui/input_window.js`
- `ui/main.js`

Acceptance criteria:

- A technical user can discover the main controls without opening the README.
- The hints are visible but low-noise.
- The hints can be dismissed or minimized after first use.

### 2. Replace vague status copy with execution-aware feedback

Current messages like `Connected`, `Ready`, and `Planning and executing...` are
too generic for an agent product.

Implement a clearer status model:

- `Ready for command`
- `Capturing screen…`
- `Routing request…`
- `Running browser action…`
- `Running desktop action…`
- `Waiting for model response…`
- `Stopped`
- `Reconnect in progress…`

Suggested target files:

- `ui/input_window.js`
- `ui/renderer.js`
- `ui/animations/status_bubble.js`

Acceptance criteria:

- A user can tell what the system is doing now.
- Status text explains the current phase, not just that "something" is
  happening.
- Long-running tasks do not feel frozen.

### 3. Make stop/control behavior more explicit

Technical users need clear control over automation.

Implement:

- a stronger stop state in the input window
- explicit copy that distinguishes:
  - hide window
  - stop current actions
  - clear overlay state
- optional secondary text under stop events such as
  `All running actions were interrupted.`

Suggested target files:

- `ui/input.html`
- `ui/input_window.js`
- `ui/main.js`

Acceptance criteria:

- Users understand the effect of `Stop` before clicking it.
- Stop feedback appears immediately and consistently.

## Priority 2: Raise Keyboard and Accessibility Quality

### 4. Restore visible focus states

The current UI removes outlines without a visible replacement.

Implement:

- `:focus-visible` styles for:
  - `#command-input`
  - `#command-send`
  - `#chat-stop`
  - `#chat-hide`
  - any dismiss button in status bubbles
- use a subtle but obvious focus ring that fits the dark tool UI

Suggested target files:

- `ui/input_window.css`
- `ui/animations/command_overlay.css`
- `ui/animations/status_bubble.css`

Acceptance criteria:

- Every keyboard-focusable control has a visible focus state.
- Focus treatment is clearer than hover treatment.
- No interactive element depends on browser-default focus styling alone.

### 5. Increase hit target comfort for repeated use

Some controls are usable but slightly tight.

Implement:

- raise important control hit areas toward ~40-44px where possible
- slightly increase padding for `Stop`, close, and send actions
- ensure the composer remains easy to click at the window edge

Suggested target files:

- `ui/input_window.css`
- `ui/animations/command_overlay.css`

Acceptance criteria:

- Repeated use does not feel fiddly.
- Controls remain compact, but not cramped.

### 6. Improve input semantics

The composer is central to the product and should carry stronger semantics.

Implement:

- add an associated visible or programmatic label for the textarea
- consider `spellcheck="false"` for command-style input
- keep placeholder copy concrete and consistent with technical usage

Suggested target files:

- `ui/input.html`
- `ui/index.html`

Acceptance criteria:

- The main command field is clearly identified as the command surface.
- The field behaves like a technical command/chat input, not a generic message
  box.

## Priority 3: Tighten Visual System for a Better Technical Feel

### 7. Move from "nice dark panel" to stronger product identity

The current styling is coherent but a little generic.

Refine the visual system without changing the app's overall structure:

- slightly sharper spacing rhythm
- more intentional typography hierarchy
- a more distinctive accent treatment for active/working states
- better separation between:
  - user messages
  - assistant messages
  - system messages
  - live execution state

Suggested target files:

- `ui/input_window.css`
- `ui/animations/status_bubble.css`
- `ui/animations/overlay_text.css`

Acceptance criteria:

- The interface feels more like a serious desktop tool and less like a styled
  prototype.
- Message roles are distinguishable at a glance.

### 8. Improve conversation scanning

Technical users often skim rather than read sequentially.

Implement:

- slightly stronger visual distinction for user vs assistant bubbles
- more deliberate system-message styling
- optional timestamp or compact metadata treatment if it stays low-noise

Suggested target files:

- `ui/input_window.css`
- `ui/input_window.js`

Acceptance criteria:

- A user can scan the last several interactions quickly.
- Assistant output does not visually blend into system status noise.

### 9. Revisit overlay motion budget

The overlay animations are good, but the product should feel crisp under heavy
 use.

Implement:

- preserve the command reveal animation
- reduce any unnecessary delay before usable input state
- ensure motion remains interruptible
- add reduced-motion handling for non-essential animation

Suggested target files:

- `ui/animations/command_overlay.css`
- `ui/animations/command_overlay.js`
- `ui/animations/status_bubble.css`

Acceptance criteria:

- The UI feels faster, not merely animated.
- Users can type immediately when invoking the input surface.
- Motion never blocks control.

## Priority 4: Make State and Model Behavior Easier To Trust

### 10. Surface a clearer execution lifecycle

The current UI exposes output, but not enough state structure.

Implement a lightweight lifecycle model:

1. idle
2. preparing
3. routing
4. running
5. completed
6. stopped
7. reconnecting

This should appear in both:

- input window status copy
- overlay status bubble

Suggested target files:

- `ui/input_window.js`
- `ui/renderer.js`
- `ui/animations/status_bubble.js`

Acceptance criteria:

- The same task phase is represented consistently across surfaces.
- Completion and interruption states are unambiguous.

### 11. Improve empty and resumed states

Persisted chat history exists, but the UI does not fully frame it.

Implement:

- better empty state when no history exists
- a subtle resumed-session state when prior messages are restored
- optional session divider or "resumed" marker for persisted sessions

Suggested target files:

- `ui/input_window.js`
- `ui/input.html`
- `ui/input_window.css`

Acceptance criteria:

- First-run and resumed-session experiences both feel intentional.

## File-Level Action Map

### `ui/input.html`

Add:

- inline help surface
- stronger command input semantics
- optional empty-state scaffolding

### `ui/input_window.css`

Update:

- focus-visible states
- hit area sizing
- message role styling
- status legibility
- typography and spacing rhythm

### `ui/input_window.js`

Update:

- richer status lifecycle copy
- first-run and resumed-session behaviors
- clearer stop-state feedback
- optional inline help dismissal state

### `ui/index.html`

Add or refine:

- command input semantics
- status/help affordances only if they do not increase overlay noise

### `ui/animations/command_overlay.css`

Update:

- focus-visible states
- motion timing
- reduced-motion support

### `ui/animations/status_bubble.css`

Update:

- focus states
- clearer hierarchy for in-progress vs completed states
- improved readable text sizing and spacing

### `ui/renderer.js`

Update:

- execution-state alignment with input window
- clearer stop/completion behavior
- less hidden behavior where possible

### `ui/main.js`

Update:

- shortcut/help exposure
- optional first-run state plumbing if stored at app level

## Suggested Implementation Order

1. Add focus-visible states and improve control hit targets.
2. Replace generic status copy with a shared execution-state model.
3. Add inline help and first-run shortcut guidance.
4. Improve message-role styling and conversation scanability.
5. Refine overlay motion and reduced-motion handling.
6. Add polished empty/resume states.

## Validation Checklist

Before considering the UI upgrade complete, verify:

- all important controls have visible focus states
- open / stop / hide behavior is discoverable in-product
- status text reflects actual execution phases
- the input field is clearly the primary command surface
- the chat window remains compact and low-noise
- message roles are scannable at a glance
- motion feels fast and interruptible
- the UI still feels optimized for technical users, not generalized for
  non-technical onboarding

## Non-Goals

Do not:

- replace the shortcut-first interaction model
- turn the app into a multi-pane dashboard
- add decorative gradients, oversized glass cards, or consumer-style onboarding
- sacrifice speed and density for broad-market friendliness

## Success Criteria

This enhancement effort is successful if a technical user can:

- open the app and understand the control model immediately
- tell what the agent is doing during execution
- interrupt or hide the system confidently
- scan recent interactions quickly
- trust the UI more after repeated use, not less
