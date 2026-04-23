# Codebase Documentation

## Overview

This repository is a desktop assistant called `JARVIS`.

At a high level, it combines:

- a Python orchestration layer
- an Electron overlay and input UI
- a lightweight router model
- several specialized execution agents
- a small visualization protocol between Python and the overlay

The system is not a single monolithic agent. It is a routed desktop orchestration loop:

1. the user opens the input UI
2. the app captures screen state
3. the router decides what kind of task this is
4. the request is delegated to a specialized agent
5. results are shown through the overlay, status bubble, chat window, or direct desktop/browser actions


## What Is First-Party vs Bundled

This matters, because the repository contains both product code and embedded upstream runtimes.

### First-party code

These directories define the product itself:

- `app.py`
- `core/`
- `models/`
- `agents/jarvis/`
- `agents/cua_vision/`
- `agents/browser/agent.py`
- `agents/cua_cli/agent.py`
- `integrations/`
- `ui/`
- `tests/`
- `setup.ps1`
- `setup.sh`

### Bundled or vendored code

These are embedded subsystems that the first-party code wraps:

- `agents/browser/browser_use/`
  - bundled browser automation runtime
- `agents/cua_cli/gemini-cli/`
  - bundled Gemini CLI source/build tree used by the CLI agent
- `ui/node_modules/`
  - normal frontend dependency tree

Treat those bundled trees as runtime dependencies, not the main source of truth for app behavior.


## Top-Level Structure

```text
project/
|- app.py
|- settings.json
|- core/
|- models/
|- agents/
|  |- jarvis/
|  |- cua_vision/
|  |- browser/
|  |  `- browser_use/           # vendored
|  `- cua_cli/
|     `- gemini-cli/            # vendored
|- integrations/
|- ui/
|- tests/
|- setup.ps1
|- setup.sh
`- README.md
```


## Core Runtime Architecture

### 1. Application bootstrap

`app.py` is the main entrypoint.

It is responsible for:

- selecting an open websocket host/port through `core/settings.py`
- detecting or falling back to screen dimensions
- loading model names from `settings.json`
- starting `ui.server.VisualizationServer`
- wiring overlay input to `models.models.call_gemini`
- wiring stop/reset hooks for active actions

Important files:

- `app.py`
- `core/settings.py`
- `ui/server.py`

### 2. Settings and persistence

`core/settings.py` reads and rewrites `settings.json` directly.

It manages:

- websocket host and port
- screen size
- viewport size
- rapid response model
- JARVIS model
- TTS enablement
- personalization text

Other lightweight persistence:

- `core/assistant_logging.py`
  - writes JSONL assistant activity logs into `logs/assistant_activity.jsonl`
- `core/registry.py`
  - in-memory registry for drawn boxes/text
- `ui/main.js`
  - persists chat history for the desktop input window

### 3. Router and orchestration

`models/models.py` is the center of the system.

It is responsible for:

- storing or reusing screenshots
- maintaining short rapid-model conversation history
- deciding when to short-circuit into direct visual explanation
- building the router prompt
- running the routing loop
- dispatching to the correct agent
- logging request lifecycle events
- handling fallback behavior such as OpenRouter and retry/guardrail cleanup

`models/function_calls.py` defines the router tool schema for:

- `direct_response`
- `invoke_jarvis`
- `invoke_browser`
- `invoke_cua_cli`
- `invoke_cua_vision`
- `request_screen_context`

`models/prompts.py` provides the router prompt and optional personalization injection.

### 4. Specialized agents

The router delegates into specialized execution paths.

#### JARVIS annotation agent

Directory: `agents/jarvis/`

Purpose:

- explain what is on screen
- annotate UI visually
- draw boxes, labels, and pointers
- present direct overlay responses

Main files:

- `agent.py`
- `tools.py`
- `prompts.py`

Key detail:

`agents/jarvis/tools.py` contains a timed action queue so annotations can appear in sequence rather than all at once.

#### CUA vision agent

Directory: `agents/cua_vision/`

Purpose:

- interact with desktop UI using screen understanding
- locate buttons and elements
- click, type, press keys, drag, and complete tasks
- optionally speak status through TTS

Main files:

- `agent.py`
- `tools.py`
- `single_call.py`
- `agentic_vision.py`
- `legacy_locator.py`
- `keyboard.py`
- `image.py`
- `prompts.py`

Key detail:

This is the main GUI-control path. `single_call.py` contains the real step loop and loop-guard behavior. `agentic_vision.py` adds a more precise crop-and-search flow for smaller targets.

#### Browser agent

Directory: `agents/browser/`

Purpose:

- perform browser automation
- prefer a persistent `browser_use` session
- fall back to Playwright when browser-use is unavailable

Main file:

- `agents/browser/agent.py`

Key detail:

The browser agent is first-party wrapper logic around the vendored `browser_use` subsystem.

#### CLI agent

Directory: `agents/cua_cli/`

Purpose:

- perform shell-based desktop and code tasks
- run commands through the bundled Gemini CLI
- manage long-running/background process promotion

Main file:

- `agents/cua_cli/agent.py`

Key detail:

The first-party wrapper adds environment setup, trusted-folder config, workspace inclusion, subprocess handling, and background lifecycle management around the vendored CLI.


## UI Architecture

The UI is an Electron-based overlay plus a dedicated input window.

### Main Electron process

`ui/main.js` owns:

- app lifecycle
- transparent overlay window creation
- separate focusable input window creation
- global shortcuts
- tray behavior
- cursor polling
- IPC handlers
- chat session persistence

Important shortcuts mentioned in the code and README:

- open input window
- close input window
- stop/clear active actions

### Renderer and overlay composition

`ui/renderer.js` owns the visual overlay runtime:

- drawing dots and connectors
- rendering text bubbles
- rendering box overlays
- direct-response layout
- status bubble and cursor status behavior
- viewport clamping and hit testing

Supporting code is split into:

- `ui/dom_nodes/`
  - DOM factories and element updates
- `ui/animations/`
  - visual behaviors for overlay components

### IPC bridge

`ui/preload.js` exposes a limited bridge to the renderer for:

- toggling interactivity
- receiving cursor position
- showing and hiding the input window
- requesting stop
- loading and saving chat session data
- retrieving model name and server config

### Python websocket bridge

`ui/server.py` is the Python-side websocket server between the orchestration layer and Electron.

It handles:

- client connections
- broadcast of draw/remove/status commands
- screenshot caching
- theme adaptation based on local screen luminance sampling
- overlay input forwarding
- stop-all requests

### Python visualization API

`ui/visualization_api/` contains helper functions for Python code to send overlay commands without knowing the websocket details directly.

This is the interface used by:

- JARVIS annotation tools
- status bubble flows
- several smoke tests


## Request Flow

Here is the practical end-to-end request path.

### Text input path

1. The user opens the input window in Electron.
2. `ui/input_window.js` sends a screenshot capture request before submitting text.
3. `app.py` receives overlay input through `VisualizationServer`.
4. `app.py` calls `models.models.call_gemini(...)`.
5. `models/models.py` builds router context from:
   - current request
   - recent rapid-model history
   - optional chain state
   - optional screen context
6. The router selects one of:
   - direct response
   - JARVIS annotation
   - browser agent
   - CLI agent
   - CUA vision agent
   - one-shot screen-context extraction
7. The delegated agent executes.
8. Results are surfaced by one or more of:
   - overlay text
   - boxes and pointers
   - status bubble
   - TTS
   - browser actions
   - desktop actions

### Visual explanation path

If a request is clearly about understanding or explaining the current screen, the system can skip heavier execution and go directly into the JARVIS annotation flow.

### Multi-step routed path

The router supports chaining. A single user request can trigger multiple delegated steps, for example:

1. inspect visible screen context
2. run a CLI task such as cloning or starting a local server
3. open a browser or local URL
4. finish with a direct response


## Module-by-Module Guide

### `core/`

#### `core/settings.py`

Central helper for reading and mutating `settings.json`.

Use it when changing:

- startup network config
- screen and viewport handling
- model selection
- TTS toggle
- personalization fields

#### `core/assistant_logging.py`

Request/event logging helper. Good starting place for:

- telemetry changes
- debugging request/agent histories
- adding new event types

#### `core/registry.py`

Very small shared state module for overlay objects.

### `models/`

#### `models/models.py`

This is the most important backend file in the repo.

If you want to understand system behavior, read this after `app.py`.

Important responsibilities:

- router lifecycle
- chain execution
- screenshot handling
- guardrails and refusal cleanup
- agent dispatch
- screen-context extraction
- logging

#### `models/function_calls.py`

Router-facing tool declarations and bindings.

Modify this when:

- adding a new routed capability
- renaming router tool contracts
- changing the model-visible schema

#### `models/prompts.py`

Prompt text for the rapid router. Includes optional personality/personalization support.

### `agents/jarvis/`

Best place to work when changing:

- annotation appearance
- direct overlay responses
- pointer drawing
- label placement
- action sequencing timing

### `agents/cua_vision/`

Best place to work when changing:

- GUI automation behavior
- click and type primitives
- target localization
- precision crop/refine logic
- loop prevention
- screen-based verification

### `agents/browser/`

Best place to work when changing:

- browser session reuse
- Playwright fallback policy
- direct URL vs search behavior
- page reuse between tasks

### `agents/cua_cli/`

Best place to work when changing:

- CLI environment setup
- approval and sandbox policy wiring
- subprocess lifecycle
- background server handling
- Gemini CLI integration

### `ui/`

Best place to work when changing:

- overlay visuals
- input window behavior
- shortcut behavior
- chat persistence
- status bubbles
- renderer hit testing
- Electron packaging

### `integrations/audio/`

Currently focused on ElevenLabs TTS and playback.


## Configuration and Environment

### `settings.json`

The runtime config file stores values such as:

- `host`
- `port`
- `screen_width`
- `screen_height`
- `viewport_width`
- `viewport_height`
- `rapid_response_model`
- `jarvis_model`
- `tts`
- `personalization`

### Environment variables used in code

The codebase references these environment families:

- `GEMINI_API_KEY`
- `OLLAMA_*`
- `OPENROUTER_*`
- `JARVIS_THINKING_BUDGET`
- `JARVIS_LOG_DIR`
- `ELEVENLABS_*`

These are loaded mainly through `.env` plus `python-dotenv`.


## Install and Run Surface

The intended setup path is described in:

- `README.md`
- `setup.ps1`
- `setup.sh`

The main moving pieces are:

1. create the Python virtualenv
2. install Python dependencies from `requirements.txt`
3. install Playwright Chromium
4. install `ui/` npm dependencies
5. install and build `agents/cua_cli/gemini-cli`
6. provide required API keys
7. run the Electron UI
8. run `app.py`


## Testing Strategy

The `tests/` directory is mixed in style.

There are:

- regression-style tests with assertions
- smoke tests
- interactive/manual overlay scripts

### Higher-value automated tests

- `tests/test_router_chaining.py`
  - routing and multi-step orchestration behavior
- `tests/test_browser_agent_fallback.py`
  - browser fallback and URL-selection behavior
- `tests/test_cli_background_manager.py`
  - CLI background process management
- `tests/test_cua_vision_loop_guard.py`
  - loop prevention in the vision agent
- `tests/test_assistant_logging.py`
  - assistant event logging behavior

### More smoke/manual leaning tests

- `tests/model_test.py`
- `tests/box_test.py`
- `tests/points_test.py`
- `tests/clear_screen.py`
- `tests/test_all_visuals.py`
- `tests/test_status_bubble_*.py`


## Known Gaps and Sharp Edges

These are grounded in the inspected code and are worth knowing before changing behavior.

1. `README.md` is partially stale.
   - It still describes some agents as stubs even though `agents/browser/agent.py` and `agents/cua_cli/agent.py` now contain substantial logic.

2. `VisionAgent.execute()` accepts a screenshot but currently does not use it.
   - The orchestration layer can pass a screenshot into the vision path, but that snapshot is effectively ignored by the current implementation.

3. `settings.json` writes are direct and unlocked.
   - `core/settings.py` rewrites the file in place without schema validation or write coordination.

4. `core/registry.py` is mutable shared global state.
   - It is simple, but not isolated for concurrent or overlapping flows.

5. Several critical integrations are runtime-only validated.
   - Missing API keys or services are mostly discovered during execution, not through a single upfront validation pass.

6. Browser fallback is partial.
   - The Playwright fallback helps with navigation-oriented work, but it is not a full replacement for the richer `browser_use` path.

7. The CLI path is intentionally permissive.
   - `agents/cua_cli/agent.py` configures a high-access execution environment, which is powerful but sensitive.

8. Some UI verification is still manual.
   - Several overlay/status tests are smoke-style rather than assert-heavy automated coverage.


## Recommended Reading Order

If you are new to the repo, read files in this order:

1. `README.md`
2. `app.py`
3. `core/settings.py`
4. `models/function_calls.py`
5. `models/prompts.py`
6. `models/models.py`
7. `agents/jarvis/agent.py`
8. `agents/jarvis/tools.py`
9. `agents/cua_vision/agent.py`
10. `agents/cua_vision/single_call.py`
11. `agents/cua_vision/tools.py`
12. `ui/main.js`
13. `ui/preload.js`
14. `ui/server.py`
15. `ui/renderer.js`
16. `agents/browser/agent.py`
17. `agents/cua_cli/agent.py`


## Practical Ownership Map

When making changes, this is the fastest mental map:

- change startup/runtime wiring:
  - `app.py`
  - `core/settings.py`

- change routing behavior:
  - `models/models.py`
  - `models/function_calls.py`
  - `models/prompts.py`

- change overlay annotations:
  - `agents/jarvis/*`
  - `ui/visualization_api/*`
  - `ui/renderer.js`

- change GUI desktop automation:
  - `agents/cua_vision/*`

- change browser automation:
  - `agents/browser/agent.py`
  - only descend into `agents/browser/browser_use/` if the wrapper cannot solve the issue

- change CLI automation:
  - `agents/cua_cli/agent.py`
  - only descend into `agents/cua_cli/gemini-cli/` if the wrapper cannot solve the issue

- change desktop shell/input/chat behavior:
  - `ui/main.js`
  - `ui/input_window.js`
  - `ui/preload.js`
  - `ui/renderer.js`


## Summary

This codebase is a desktop agent platform built around a Python router and an Electron overlay.

Its defining structure is:

- Python owns orchestration, routing, agent delegation, and logging
- Electron owns the overlay, input window, and desktop-facing UI shell
- JARVIS handles visual explanation
- CUA Vision handles GUI actioning
- Browser and CLI wrappers integrate heavier embedded runtimes

If you keep the first-party code separate from the bundled subsystems and start from `app.py` plus `models/models.py`, the rest of the repository becomes much easier to reason about.
