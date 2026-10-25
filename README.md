# JARVIS
## Computer Linked Overlay Vision Interface System
> This is a public checkpoint. This is a limited version of the full code. Please do not expect production ready performance. Best experience with a NVIDIA API key for CUA vision and OpenRouter as fallback.

## Installation

1. Clone GitHub repository
```
git clone https://github.com/JonOuyang/Jayu
```

2. Create your project-local environment and install dependencies

Windows (PowerShell):
```powershell
.\setup.ps1
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:
```bash
./setup.sh
source .venv/bin/activate
```

Manual setup:
```bash
python -m venv .venv
```

Windows:
```powershell
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
cd ui; npm install
cd ../integrations/playwright_mcp; npm install
cd ../opencode; npm ci
```

macOS / Linux:
```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cd ui && npm install
cd ../integrations/playwright_mcp && npm install
cd ../opencode && npm ci
```

The setup scripts install a pinned local Playwright MCP package under `integrations/playwright_mcp` (`@playwright/mcp` 0.0.73). Runtime browser tasks should use that local install instead of downloading MCP dynamically with `npx` or `latest`.

3. Create your .env file for your keys. Every key is optional: with none set, Jarvis routes and answers chat on the local model, and only screen/vision features need a cloud key.
```
# Optional: screen explanations (JARVIS overlay) and a strong-model escalation target.
GEMINI_API_KEY = "YOUR_API_KEY"

# CUA vision uses NVIDIA first, then OpenRouter. Gemini is not used for CUA vision.
NVIDIA_API_KEY = "YOUR_NVIDIA_API_KEY"
# Optional NVIDIA vision overrides:
# NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# NVIDIA_VISION_MODEL = "mistralai/mistral-small-4-119b-2603"

# The router runs on local Ollama by default and falls back to NVIDIA, then
# OpenRouter, when those keys are set. Set ROUTER_PROVIDER to make a cloud router primary.
# ROUTER_PROVIDER = "ollama"
OPENROUTER_API_KEY = "YOUR_OPENROUTER_API_KEY"
OPENROUTER_ROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
# Optional overrides:
# OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# OPENROUTER_SITE_URL = "https://your-app-url.example"
# OPENROUTER_SITE_NAME = "JARVIS"
# OPENROUTER_TIMEOUT_SECONDS = "45"

# Local model (router + brain). Defaults shown.
# OLLAMA_ROUTER_MODEL = "nemotron-3.5-bolt"
# OLLAMA_BASE_URL = "http://127.0.0.1:11434"
# OLLAMA_ROUTER_TIMEOUT_SECONDS = "90"
# OLLAMA_KEEP_ALIVE = "10m"
# OLLAMA_ROUTER_NUM_CTX = "8192"
# OLLAMA_ROUTER_NUM_PREDICT = "240"
# OLLAMA_ROUTER_THINK = "false"

# Optional source-grounded Web QA via Tavily MCP.
TAVILY_API_KEY = "YOUR_TAVILY_API_KEY"

ELEVENLABS_API_KEY = "YOUR_API_KEY"
ELEVENLABS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"   # Optional
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2" # Optional
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"     # Optional
# Optional full URL override (legacy/advanced):
# ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/<voice_id>"
```

## Local brain and escalation

Chat answers (direct Q&A and web Q&A) come from the local model first: NVIDIA Nemotron 3.5 Bolt E4B 4GB through Ollama, the same model that routes requests. One model plays both roles because two models do not fit in 4 GB of VRAM. Jarvis escalates to a stronger model when:

- the local model errors, times out, or returns nothing,
- the local model decides it cannot answer reliably and replies `ESCALATE` (direct Q&A only),
- you ask for it: "think harder", "use the stronger model", "ask codex", "ask claude", "ask ChatGPT".

Escalation targets are tried in order and skipped when not configured: Gemini (`GEMINI_API_KEY`), OpenRouter (`OPENROUTER_API_KEY`), then your signed-in Claude Code, Codex CLI, and Copilot CLI in answer-only mode (no shell, file-writing, or MCP tools). Codex CLI signed in with ChatGPT is how a ChatGPT subscription is used here; Jarvis never reads the CLIs' credentials. The chat shows which model answered.

```
# .env (all optional)
# JARVIS_BRAIN_PRIMARY = "local"        # or gemini/openrouter/claude/codex/copilot
# JARVIS_BRAIN_ESCALATION = "gemini,openrouter,claude,codex,copilot"
# JARVIS_BRAIN_MODEL = "nemotron-3.5-bolt"   # defaults to the router model
# JARVIS_BRAIN_NUM_CTX = "8192"
# JARVIS_BRAIN_TIMEOUT_SECONDS = "120"
# JARVIS_BRAIN_CLI_TIMEOUT_SECONDS = "180"
# JARVIS_BRAIN_SELF_ESCALATE = "true"
```

On a 4 GB GPU the Q4 model (about 6–8 GB on disk) runs partly on the CPU, so first replies can take several seconds. Screen explanations and the vision agent need an image-capable model and still use Gemini or NVIDIA/OpenRouter vision.

## Skills

Skills use the open [agentskills.io](https://agentskills.io) `SKILL.md` format, the same one used by OpenJarvis, Hermes Agent, OpenClaw, Claude Code, and opencode, so skills from those ecosystems work here.

**Built-in document skills** (`skills/`): `pptx`, `docx`, `pdf`, `xlsx`. Ask for a file ("make a 6 slide presentation on solar energy", "create an excel budget for October and save it on my desktop") and the CLI agent runs the matching skill: the local model writes only a JSON outline that the skill's schema checks, and a tested Python script builds the file. Invalid JSON is retried once with the errors, then handed to a stronger model. Files go to the folder you name, your Desktop/Downloads/Documents if mentioned, or `JARVIS_OUTPUT_DIR` (default `~/Documents/Jarvis`).

**Other skills** give instructions instead of code. When a request matches one, the CLI agent's coding CLI is pointed at its `SKILL.md`; say "use the <name> skill" to force one.

```
python -m agents.skills list
python -m agents.skills import openjarvis                 # skills from your OpenJarvis install
python -m agents.skills import hermes:arxiv               # NousResearch/hermes-agent
python -m agents.skills import openclaw:<owner>/<name>    # openclaw/skills
python -m agents.skills import github:owner/repo/path --name some-skill
python -m agents.skills import C:\path\to\skill-folder
python -m agents.skills show arxiv
python -m agents.skills remove arxiv
```

Imports go to `JARVIS_SKILLS_DIR/imported` (default `~/.jarvis/skills/imported`). As in OpenJarvis, a skill's scripts are not copied until you review them and re-import with `--with-scripts`, symlinks are rejected, and skills declaring `shell:execute`, `network:listen`, or `filesystem:write` need `--yes-dangerous`. Folders you create directly in `JARVIS_SKILLS_DIR` are treated as your own and can run their scripts; when names collide, your skills win over built-in ones, which win over imported ones.

## Forms and confirmations

The browser agent fills forms on its own but stops to ask before anything you cannot take back. The question appears in the chat; reply **yes** (typed or spoken) to allow it. Any other reply, or no reply within 2 minutes, cancels the action and the agent stops and reports what is left for you.

It asks before:
- clicking a button that submits, pays, places an order, sends, posts, deletes, books, subscribes, or signs up (or any submit button),
- typing into a password, card, CVV, OTP, PIN, UPI, Aadhaar/PAN, or bank-account field,
- uploading a file, running custom JavaScript on a page, or pressing Enter after typing into a form (not a search box).

`JARVIS_CONFIRM_RISKY_ACTIONS=off` turns the questions off.

The browser agent's model is chosen from `JARVIS_BROWSER_LLM_ORDER` (default `gemini,openrouter,ollama`), skipping any without a key, so it works with only a local Ollama model (`JARVIS_BROWSER_OLLAMA_MODEL`, default the router model). A 4B local model is noticeably weaker at multi-step browsing than Gemini.

## CLI agent and coding delegation

The CLI agent runs shell and desktop tasks on [opencode](https://opencode.ai) with a local model, and hands coding tasks (bugs, refactors, tests, features) to a stronger coding CLI you are already signed in to. Each CLI uses its own login; Jarvis never reads or reuses their credentials.

| Backend | Install | Used for |
| --- | --- | --- |
| opencode (pinned, installed by setup) | `integrations/opencode` | shell/desktop tasks, last-resort coding |
| Claude Code | `npm install -g @anthropic-ai/claude-code`, then `claude` to sign in | coding (1st choice) |
| Codex CLI | `npm install -g @openai/codex`, then `codex login` (ChatGPT sign-in works) | coding (2nd choice) |
| GitHub Copilot CLI | `npm install -g @github/copilot`, then `copilot` → `/login` | coding (3rd choice) |

Jarvis tries coding backends in order and skips one only if it is not installed or not signed in; once a backend has run a tool it never re-runs the task elsewhere. Prompts are passed on stdin, never as command-line arguments.

Every backend gets the same deny rules: `rm -rf`/`rm -r`, `Remove-Item`, `git push`, `git reset --hard`, `git clean`, `sudo`, `format`, `shutdown` and similar. Codex has no per-command rules, so it runs in its `workspace-write` sandbox with network access off. `JARVIS_CLI_FULL_TRUST=1` keeps only the machine-destroying rules and allows network for Codex.

```
# .env (all optional)
JARVIS_OPENCODE_MODEL = "ollama/nemotron-3.5-bolt"   # provider/model for opencode
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
JARVIS_CODING_BACKENDS = "claude,codex,copilot,opencode"
JARVIS_CODING_DELEGATION = "auto"   # "off" runs coding tasks on opencode too
JARVIS_CODING_TIMEOUT_SECONDS = "900"
JARVIS_CLI_TIMEOUT_SECONDS = "300"
# JARVIS_CLAUDE_MODEL / JARVIS_CODEX_MODEL / JARVIS_COPILOT_MODEL pick models per CLI.
# JARVIS_<NAME>_BIN points at a specific executable (OPENCODE, CLAUDE, CODEX, COPILOT).
```

Google's Antigravity CLI (`agy`) is not wired in: its print mode is reported to hang when it is run without a terminal ([antigravity-cli#318](https://github.com/google-antigravity/antigravity-cli/issues/318)), which is how Jarvis runs CLIs.

## Running Jarvis

1. Start the local model
```
ollama serve
ollama pull nemotron-3.5-bolt
ollama run nemotron-3.5-bolt "ready"
```

2. Run the frontend visualization
```
cd ui
npm run dev
```

3. Run the main app from the project root with the project venv

Windows:
```powershell
.\.venv\Scripts\python.exe app.py
```

macOS / Linux:
```bash
.venv/bin/python app.py
```

## Jarvis Commands

* `Cmd + Shift + Space` opens the JARVIS input bar
* `Cmd + Shift + X` closes the JARVIS input bar
* `Cmd + Shift + C` stops active actions and clears overlay state

---

## System Architecture

### Overview

JARVIS uses a **two-tier routing architecture** where a lightweight router model decides how to handle requests, then delegates to specialized agents for execution.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INPUT                                      │
│                         (Cmd + Shift + Space)                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SCREENSHOT CAPTURE                                 │
│              (Captured BEFORE overlay appears for clean image)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OVERLAY UI APPEARS                                   │
│                    (Electron transparent overlay)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ROUTER MODEL                                        │
│          (OpenRouter Nemotron 3 free, with Ollama fallback support)         │
│                                                                              │
│  Analyzes user request (NO screenshot) and decides routing:                 │
│  ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌──────────────────┐ │
│  │direct_response │ │ invoke_jarvis  │ │ invoke_browser │ │invoke_cua_vision │ │
│  │ Simple Q&A     │ │Screen annotate │ │ Web automation │ │GUI-based control │ │
│  └───────┬────────┘ └───────┬────────┘ └───────┬────────┘ └────────┬─────────┘ │
└──────────┼──────────────────┼──────────────────┼───────────────────┼───────────┘
           │                  │                  │                   │
           ▼                  ▼                  ▼                   ▼
┌──────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌───────────────────┐
│  DIRECT RESPONSE │ │  JARVIS AGENT   │ │  BROWSER AGENT  │ │  CUA VISION AGENT │
│                  │ │                 │ │                 │ │                   │
│ Immediate text   │ │ + Screenshot    │ │ Playwright-     │ │ + Screenshot      │
│ response in      │ │ + Vision model  │ │ based web       │ │ + Element finding │
│ overlay bubble   │ │ + Draw boxes,   │ │ automation      │ │ + Mouse clicks    │
│                  │ │   text, pointers│ │                 │ │ + Keyboard input  │
│                  │ │ + Timed         │ │ (Coming Soon)   │ │ + TTS feedback    │
│                  │ │   sequences     │ │                 │ │                   │
└──────────────────┘ └─────────────────┘ └─────────────────┘ └───────────────────┘
```

### Directory Structure

```
JARVIS/
├── app.py                      # Entry point - starts server and handles input
├── settings.json               # Runtime configuration (port, models, screen size)
│
├── core/                       # Shared utilities
│   ├── settings.py             # Settings management (read/write settings.json)
│   └── registry.py             # Element registry (tracks drawn boxes/text)
│
├── models/                     # LLM integration and routing
│   ├── models.py               # GeminiModel class, call_gemini(), routing logic
│   ├── function_calls.py       # Router tool declarations (invoke_*)
│   └── prompts.py              # Router system prompt
│
├── agents/                     # Execution backends
│   ├── jarvis/                 # Screen annotation agent
│   │   ├── agent.py            # JarvisAgent class
│   │   ├── tools.py            # Drawing tools (boxes, text, pointers)
│   │   └── prompts.py          # JARVIS system prompt
│   │
│   ├── browser/                # Web automation agent (Playwright)
│   │   └── agent.py            # BrowserAgent class (stub)
│   │
│   ├── cua_cli/                # Shell control and coding via coding-agent CLIs
│   │   ├── agent.py            # CLIAgent class
│   │   └── backends/           # opencode, Claude Code, Codex CLI, Copilot CLI
│   │
│   └── cua_vision/             # Desktop control via screen + mouse/keyboard
│       ├── agent.py            # VisionAgent class
│       ├── tools.py            # Tool declarations and functions
│       ├── keyboard.py         # Keyboard and mouse input functions
│       ├── image.py            # Image comparison utilities
│       └── prompts.py          # System prompts
│
├── ui/                         # Electron overlay application
│   ├── main.js                 # Electron main process
│   ├── renderer.js             # Canvas rendering logic
│   ├── preload.js              # IPC bridge
│   ├── index.html              # Overlay HTML
│   ├── server.py               # WebSocket server (Python ↔ Electron)
│   │
│   ├── animations/             # UI animations
│   │   ├── command_overlay.js  # Input bar animation
│   │   ├── overlay_image.js    # Background effects
│   │   └── screen_glow.js      # Glow effects
│   │
│   ├── dom_nodes/              # DOM element factories
│   │   ├── overlay_box.js      # Bounding box elements
│   │   └── overlay_text.js     # Text bubble elements
│   │
│   └── visualization_api/      # Python → Electron drawing API
│       ├── client.py           # WebSocket client singleton
│       ├── draw_bounding_box.py
│       ├── draw_dot.py
│       ├── create_text.py
│       ├── destroy_box.py
│       ├── destroy_text.py
│       └── clear_screen.py
│
├── integrations/               # External service integrations
│   ├── audio/                  # TTS/STT via ElevenLabs
│   │   ├── __init__.py         # Exports tts_speak, stop_speaking
│   │   └── tts.py              # Text-to-speech implementation
│   ├── google-drive/           # Cloud storage (planned)
│   └── messaging/              # Slack, Discord, etc. (planned)
│
└── tests/                      # Test files
```

### Data Flow

#### 1. User Triggers JARVIS (`Cmd + Shift + Space`)

```
main.js (Electron)
    │
    ├── Sends 'capture_screenshot' event via WebSocket
    │       │
    │       ▼
    │   server.py → models.py: store_screenshot()
    │       (PIL ImageGrab captures screen BEFORE overlay)
    │
    └── Sends 'show-overlay-image' to renderer
            │
            ▼
        command_overlay.js shows input UI
```

#### 2. User Submits Query

```
command_overlay.js
    │
    ├── Sends { event: 'overlay_input', text: '...' }
    │       │
    │       ▼
    │   server.py: on_overlay_input callback
    │       │
    │       ▼
    │   models.py: call_gemini(user_prompt)
    │       │
    │       ▼
    │   ┌─────────────────────────────────┐
    │   │         ROUTER MODEL            │
    │   │   (No screenshot - fast)        │
    │   │                                 │
    │   │   Decides: direct_response,     │
    │   │   invoke_jarvis, invoke_browser,│
    │   │   invoke_cua_cli, or            │
    │   │   invoke_cua_vision             │
    │   └─────────────────────────────────┘
    │               │
    │               ▼
    │   ┌─────────────────────────────────┐
    │   │    JARVIS AGENT (if invoked)    │
    │   │   + Stored screenshot           │
    │   │   + Full vision model           │
    │   │   + Returns tool calls:         │
    │   │     draw_bounding_box(),        │
    │   │     create_text(), etc.         │
    │   └─────────────────────────────────┘
    │               │
    │               ▼
    │   ┌─────────────────────────────────┐
    │   │        ACTION QUEUE             │
    │   │   Processes tool calls with     │
    │   │   time delays for animations    │
    │   └─────────────────────────────────┘
    │               │
    │               ▼
    │   visualization_api/client.py
    │       │
    │       ▼
    └── WebSocket to renderer.js
            │
            ▼
        Canvas draws boxes/text/dots
```

### Key Components

#### Router Model (models/function_calls.py)

The router is a lightweight model that classifies requests without seeing the screen:

| Tool | When to Use |
|------|-------------|
| `direct_response` | Simple facts, math, greetings |
| `invoke_jarvis` | Screen questions, "what's this?", visual explanation |
| `invoke_browser` | Web tasks, searches, online services |
| `invoke_cua_cli` | Shell commands, file ops, scripts |
| `invoke_cua_vision` | GUI interactions, clicking buttons |

#### JARVIS Agent (agents/jarvis/)

Screen annotation agent with timed visual elements:

| Tool | Description |
|------|-------------|
| `draw_bounding_box` | Rectangle around UI elements |
| `draw_pointer_to_object` | Dot + text + connecting line |
| `create_text` | Text label at coordinates |
| `create_text_for_box` | Text positioned relative to a box |
| `destroy_box` / `destroy_text` | Remove elements by ID |
| `clear_screen` | Remove all annotations |
| `direct_response` | Text in center overlay bubble |

All tools accept a `time` parameter (seconds from start) enabling animated sequences.

#### CUA Vision Agent (agents/cua_vision/)

Vision-based computer use agent that can see and interact with the screen:

| Tool | Description |
|------|-------------|
| `type_string` | Types out a string using the keyboard |
| `click_left_click` | Left click at coordinates |
| `click_double_left_click` | Double click at coordinates |
| `click_right_click` | Right click at coordinates |
| `press_ctrl_hotkey` | Press Ctrl+key (e.g., Ctrl+C) |
| `press_alt_hotkey` | Press Alt+key |
| `find_and_click_element` | Find element by description and click it |
| `remember_information` | Store information in memory |
| `tts_speak` | Speak to user via TTS |

The agent operates in a loop: capture screen → analyze → execute action → repeat until task complete.

#### Action Queue (agents/jarvis/tools.py)

The action queue handles timed execution:

```python
ACTION_QUEUE = deque()  # [(time, func, args, kwargs), ...]

# Example sequence:
draw_bounding_box(time=0.0, ...)   # Show immediately
create_text(time=0.5, ...)         # Show after 0.5s
destroy_box(time=3.0, ...)         # Remove after 3s
```

#### WebSocket Communication

```
Python Server (server.py:8765)
        │
        │  JSON messages
        │
        ▼
Electron Renderer (renderer.js)

Commands (Python → Electron):
  { command: "draw_box", id, x, y, width, height, stroke, ... }
  { command: "draw_text", id, x, y, text, color, fontSize, ... }
  { command: "draw_dot", id, x, y, radius, lineToId, ... }
  { command: "remove_box", id }
  { command: "clear" }
  { command: "set_model_name", name }

Events (Electron → Python):
  { event: "viewport", width, height }
  { event: "overlay_input", text }
  { event: "capture_screenshot" }
  { event: "click", id }
```

### Configuration (settings.json)

```json
{
    "host": "127.0.0.1",
    "port": 8765,
    "screen_width": 1920,
    "screen_height": 1080,
    "viewport_width": 1920,
    "viewport_height": 1080,
    "rapid_response_model": "nemotron-3.5-bolt",
    "jarvis_model": "gemini-2.5-flash-preview-04-17"
}
```

### Adding a New Agent

1. Create directory: `agents/my_agent/`
2. Create your agent class:
   ```python
   class MyAgent:
       def __init__(self):
           pass

       async def execute(self, task: str) -> dict:
           # Do the work
           return {"success": True, "result": ..., "error": None}
   ```
3. Add routing tool declaration in `models/function_calls.py`:
   ```python
   invoke_my_agent_declaration = {
       "name": "invoke_my_agent",
       "description": "When to use this agent...",
       "parameters": { ... }
   }
   ```
4. Add routing logic in `models/models.py` to handle the new tool
5. Update router prompt in `models/prompts.py` to tell router when to use it
