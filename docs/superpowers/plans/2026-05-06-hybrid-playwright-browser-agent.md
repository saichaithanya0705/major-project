# Hybrid Playwright Browser Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hybrid browser backend where Jarvis uses Python Playwright for deterministic browser control and page context extraction, while the official Playwright MCP server is installed locally and used as an LLM-friendly snapshot/tool adapter when a browser task benefits from MCP refs and iterative page reasoning.

**Architecture:** Add a Python-first `BrowserController` that owns persistent Playwright sessions, deterministic navigation, and request-driven page context extraction. Add a local pinned Playwright MCP install plus a Python MCP client adapter that can launch the local MCP server, list tools, call browser tools, and shut it down. Keep `browser_use` available for complex natural-language workflows, but route page reading and deterministic open/read flows through the controller.

**Tech Stack:** Python 3.11+, `playwright==1.58.0`, official Python MCP SDK `mcp==1.26.0` (compatible with `browser-use==0.12.2`), local npm package `@playwright/mcp@0.0.73`, existing Jarvis router and `BrowserAgent`.

---

## File Map

- Create: `agents/browser/page_context.py`
  - Defines `PageContext`, text cleanup, heading extraction, main-content extraction script, extractive summary formatting, and chat response formatting.
- Create: `agents/browser/controller.py`
  - Defines `PlaywrightBrowserController`, a focused wrapper around Python Playwright session lifecycle, navigation, page reuse, and page context extraction.
- Create: `agents/browser/mcp_client.py`
  - Defines `PlaywrightMcpClient`, a focused wrapper around the official Python MCP SDK and local `@playwright/mcp` process.
- Create: `integrations/playwright_mcp/package.json`
  - Pins the local MCP server dependency to `@playwright/mcp@0.0.73`.
- Create: `integrations/playwright_mcp/.gitignore`
  - Keeps `node_modules/` out of git while preserving `package-lock.json`.
- Modify: `requirements.txt`
  - Adds `mcp==1.26.0`, matching the `browser-use==0.12.2` dependency constraint.
- Modify: `setup.ps1`
  - Installs `integrations/playwright_mcp` dependencies during Windows setup.
- Modify: `setup.sh`
  - Installs `integrations/playwright_mcp` dependencies during macOS/Linux setup.
- Modify: `README.md`
  - Documents Playwright MCP as a default installed component and explains Python-first fallback behavior.
- Modify: `agents/browser/task_policy.py`
  - Adds request heuristics for page reading, headings, findings, and MCP snapshot usage.
- Modify: `agents/browser/agent.py`
  - Delegates deterministic Playwright work to `PlaywrightBrowserController`, uses page context responses for chat, and adds MCP health-aware routing.
- Modify: `models/agent_step_runner.py`
  - Ensures structured browser page context payloads surface as user-facing chat messages.
- Test: `tests/test_browser_page_context.py`
  - Unit tests for cleanup, heading extraction, summaries, response formatting.
- Test: `tests/test_browser_controller.py`
  - Unit tests using fake Playwright pages for navigate/read/reuse behavior.
- Test: `tests/test_browser_mcp_client.py`
  - Unit tests for local binary resolution, tool-call response parsing, health failure handling, and close behavior.
- Modify: `tests/test_browser_task_policy_boundary.py`
  - Adds policy coverage for headings, findings, page content, and MCP snapshot routing.
- Modify: `tests/test_browser_agent_fallback.py`
  - Updates integration-style BrowserAgent checks around deterministic reading and backend fallback.
- Create: `tests/test_agent_step_runner_browser_message.py`
  - Adds structured browser payload assertions without staging unrelated Jarvis artifact tests.

---

## Task 1: Add Page Context Extraction Unit

**Files:**
- Create: `agents/browser/page_context.py`
- Create: `tests/test_browser_page_context.py`

- [ ] **Step 1: Write failing tests for page text cleanup and heading response formatting**

Create `tests/test_browser_page_context.py`:

```python
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.page_context import (
    PageContext,
    clean_page_text,
    extractive_summary,
    format_page_context_response,
)


def test_clean_page_text_collapses_spaces_and_blank_runs() -> None:
    raw = "  Heading  \r\n\r\n\r\n  First   paragraph.  \n\tSecond line.  "
    assert clean_page_text(raw) == "Heading\n\nFirst paragraph.\nSecond line."


def test_summary_selects_first_readable_sentences() -> None:
    text = (
        "First sentence explains the page. Second sentence adds detail. "
        "Third sentence adds another detail. Fourth sentence should still fit. "
        "Fifth sentence is enough. Sixth sentence should be clipped."
    )
    summary = extractive_summary(text, max_chars=160, max_sentences=5)
    assert "First sentence explains the page." in summary
    assert "Fifth sentence is enough." in summary
    assert "Sixth sentence should be clipped." not in summary


def test_format_page_context_response_for_headings() -> None:
    context = PageContext(
        title="Example Docs",
        url="https://example.com/docs",
        headings=["Install", "Usage", "Troubleshooting"],
        text="Install\\n\\nUsage\\n\\nTroubleshooting",
    )
    response = format_page_context_response(
        task="read the headings on this page",
        context=context,
    )
    assert response.startswith("Headings from Example Docs (https://example.com/docs):")
    assert "- Install" in response
    assert "- Usage" in response
    assert "- Troubleshooting" in response


def test_format_page_context_response_for_summary() -> None:
    context = PageContext(
        title="World War I - Wikipedia",
        url="https://en.wikipedia.org/wiki/World_War_I",
        headings=["History", "Course of the war"],
        text=(
            "World War I was a global conflict between two coalitions. "
            "The war lasted from 1914 to 1918 and reshaped Europe."
        ),
    )
    response = format_page_context_response(
        task="summarize this page",
        context=context,
    )
    assert response.startswith("Summary of World War I - Wikipedia")
    assert "global conflict between two coalitions" in response
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run:

```powershell
python tests/test_browser_page_context.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.browser.page_context'`.

- [ ] **Step 3: Implement page context helpers**

Create `agents/browser/page_context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import re


MAIN_CONTENT_SCRIPT = """
() => {
  const selectors = [
    '#mw-content-text .mw-parser-output',
    'article',
    'main',
    '[role="main"]',
    'body'
  ];
  const root = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
  if (!root) {
    return { text: document.body ? document.body.innerText : '', headings: [] };
  }
  const clone = root.cloneNode(true);
  clone.querySelectorAll([
    'script',
    'style',
    'noscript',
    'nav',
    'header',
    'footer',
    'aside',
    'form',
    'figure',
    'sup',
    '.mw-editsection',
    '.reference',
    '.reflist',
    '.navbox',
    '.infobox',
    '.sidebar'
  ].join(',')).forEach((element) => element.remove());
  const headings = Array.from(clone.querySelectorAll('h1, h2, h3'))
    .map((element) => (element.innerText || '').replace(/\\s+/g, ' ').trim())
    .filter(Boolean)
    .slice(0, 30);
  const blocks = Array.from(clone.querySelectorAll('p, li'));
  const textBlocks = blocks
    .map((element) => (element.innerText || '').replace(/\\s+/g, ' ').trim())
    .filter((text) => text.length > 40);
  const text = textBlocks.length > 0 ? textBlocks.join('\\n\\n') : (clone.innerText || '');
  return { text, headings };
}
"""


@dataclass(frozen=True)
class PageContext:
    title: str
    url: str
    headings: list[str] = field(default_factory=list)
    text: str = ""


def clean_page_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if cleaned and not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False
    return "\n".join(cleaned).strip()


def truncate_words(value: str, max_chars: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def extractive_summary(
    page_text: str,
    *,
    max_chars: int = 1200,
    max_sentences: int = 5,
) -> str:
    text = clean_page_text(page_text)
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n+", text)
        if paragraph.strip()
    ]
    candidate = " ".join(paragraphs[:4]) if paragraphs else text
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", candidate)
        if sentence.strip()
    ]
    selected: list[str] = []
    for sentence in sentences:
        proposed = " ".join([*selected, sentence]).strip()
        if selected and len(proposed) > max_chars:
            break
        selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    if selected:
        return truncate_words(" ".join(selected), max_chars)
    return truncate_words(candidate, max_chars)


def _source_label(context: PageContext) -> str:
    title = context.title.strip()
    url = context.url.strip()
    if title and url and url not in title:
        return f"{title} ({url})"
    return title or url or "page"


def _wants_headings(task: str) -> bool:
    lowered = " ".join(str(task or "").lower().split())
    return any(marker in lowered for marker in ("heading", "headings", "section list", "sections"))


def _wants_findings(task: str) -> bool:
    lowered = " ".join(str(task or "").lower().split())
    return any(marker in lowered for marker in ("findings", "key findings", "takeaways", "key points"))


def _wants_summary(task: str) -> bool:
    lowered = " ".join(str(task or "").lower().split())
    return any(marker in lowered for marker in ("summary", "summarize", "summarise", "tl;dr", "tldr", "overview"))


def format_page_context_response(task: str, context: PageContext) -> str:
    source = _source_label(context)
    headings = [heading for heading in context.headings if heading.strip()]
    text = clean_page_text(context.text)
    if _wants_headings(task):
        if not headings:
            return f"Headings from {source}:\nNo readable headings were found."
        heading_lines = "\n".join(f"- {heading}" for heading in headings[:20])
        return f"Headings from {source}:\n{heading_lines}"
    if _wants_summary(task) or _wants_findings(task):
        content = extractive_summary(text)
        if not content:
            return f"Summary of {source}:\nNo readable page text was found."
        return f"Summary of {source}:\n{content}"
    content = truncate_words(text, 1800)
    if not content:
        return f"Page content from {source}:\nNo readable page text was found."
    return f"Page content from {source}:\n{content}"
```

- [ ] **Step 4: Run page context tests**

Run:

```powershell
python tests/test_browser_page_context.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add agents/browser/page_context.py tests/test_browser_page_context.py
git commit -m "feat: add browser page context extraction helpers"
```

---

## Task 2: Add Python Playwright Controller

**Files:**
- Create: `agents/browser/controller.py`
- Create: `tests/test_browser_controller.py`
- Modify: `agents/browser/agent.py`

- [ ] **Step 1: Write failing controller tests with fake pages**

Create `tests/test_browser_controller.py`:

```python
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.controller import PlaywrightBrowserController


class _FakePage:
    def __init__(self, url: str = "about:blank", title: str = "Blank") -> None:
        self.url = url
        self._title = title
        self.goto_calls: list[str] = []
        self.closed = False
        self.payload = {
            "text": "Alpha paragraph explains the page. Beta paragraph adds detail.",
            "headings": ["Alpha", "Beta"],
        }

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30000):
        self.goto_calls.append(url)
        self.url = url
        self._title = "Loaded"

    async def title(self) -> str:
        return self._title

    async def evaluate(self, script: str):
        assert "querySelector" in script
        return self.payload

    async def wait_for_timeout(self, ms: int):
        return None

    def is_closed(self) -> bool:
        return self.closed


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    async def new_page(self):
        page = _FakePage()
        self.pages.append(page)
        return page


async def _run_checks() -> None:
    page = _FakePage("about:blank", "Blank")
    context = _FakeContext([page])
    controller = PlaywrightBrowserController()
    controller._page = page
    controller._context = context

    context_result = await controller.navigate_and_extract("https://example.com/docs")
    assert page.goto_calls == ["https://example.com/docs"]
    assert context_result.url == "https://example.com/docs"
    assert context_result.title == "Loaded"
    assert context_result.headings == ["Alpha", "Beta"]
    assert "Alpha paragraph" in context_result.text

    selected = await controller.select_relevant_existing_page("current localhost page", default_page=page)
    assert selected is page


def test_controller_navigation_and_extraction() -> None:
    asyncio.run(_run_checks())
```

- [ ] **Step 2: Run controller tests and confirm missing module**

Run:

```powershell
python tests/test_browser_controller.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.browser.controller'`.

- [ ] **Step 3: Implement controller skeleton and extraction path**

Create `agents/browser/controller.py`:

```python
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from agents.browser.page_context import MAIN_CONTENT_SCRIPT, PageContext, clean_page_text


class PlaywrightBrowserController:
    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._runtime_home: str | None = None
        self._used_headless = False

    async def get_or_create_page(self):
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    return self._page, self._used_headless
            except Exception:
                self._page = None

        from playwright.async_api import async_playwright

        self._runtime_home = tempfile.mkdtemp(prefix="jarvis-playwright-home-")
        launch_env = dict(os.environ)
        launch_env["HOME"] = self._runtime_home
        self._playwright = await async_playwright().start()
        self._browser, self._used_headless = await self._launch_browser(self._playwright, launch_env)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        return self._page, self._used_headless

    async def _launch_browser(self, playwright, launch_env: dict[str, str]):
        launch_args = ["--disable-crashpad", "--disable-crash-reporter"]
        errors: list[str] = []
        for headless in (False, True):
            try:
                browser = await playwright.chromium.launch(
                    headless=headless,
                    env=launch_env,
                    args=launch_args,
                )
                return browser, headless
            except Exception as exc:
                errors.append(f"bundled chromium headless={headless}: {exc}")
        for channel in ("chrome", "msedge"):
            for headless in (False, True):
                try:
                    browser = await playwright.chromium.launch(
                        channel=channel,
                        headless=headless,
                        env=launch_env,
                        args=launch_args,
                    )
                    return browser, headless
                except Exception as exc:
                    errors.append(f"channel {channel} headless={headless}: {exc}")
        for executable_path in self.known_browser_executables():
            for headless in (False, True):
                try:
                    browser = await playwright.chromium.launch(
                        executable_path=executable_path,
                        headless=headless,
                        env=launch_env,
                        args=launch_args,
                    )
                    return browser, headless
                except Exception as exc:
                    errors.append(f"executable {executable_path} headless={headless}: {exc}")
        raise RuntimeError(
            "Could not launch Playwright browser. "
            "Tried bundled Chromium, browser channels, and local browser executables. "
            f"Launch errors: {' | '.join(errors[:6])}"
        )

    @staticmethod
    def known_browser_executables() -> list[str]:
        if sys.platform.startswith("win"):
            candidates = [
                r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
                r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
                r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ]
        else:
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/usr/bin/microsoft-edge",
                "/usr/bin/brave-browser",
            ]
        resolved: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            path = str(Path(os.path.expandvars(candidate)).expanduser())
            if path in seen:
                continue
            seen.add(path)
            if Path(path).exists():
                resolved.append(path)
        return resolved

    async def navigate_and_extract(self, url: str) -> PageContext:
        page, _used_headless = await self.get_or_create_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)
        return await self.extract_context(page)

    async def extract_context(self, page=None) -> PageContext:
        active_page = page or (await self.get_or_create_page())[0]
        title = await active_page.title()
        try:
            payload = await active_page.evaluate(MAIN_CONTENT_SCRIPT)
        except Exception:
            payload = {"text": "", "headings": []}
        if not isinstance(payload, dict):
            payload = {"text": str(payload or ""), "headings": []}
        headings = payload.get("headings") if isinstance(payload.get("headings"), list) else []
        return PageContext(
            title=str(title or ""),
            url=str(getattr(active_page, "url", "") or ""),
            headings=[str(item).strip() for item in headings if str(item).strip()],
            text=clean_page_text(str(payload.get("text") or "")),
        )

    async def select_relevant_existing_page(self, task: str, default_page=None):
        lowered = str(task or "").lower()
        context = self._context
        if context is None:
            return None
        pages = list(getattr(context, "pages", []) or [])
        if not pages:
            return None
        if "localhost" in lowered or "127.0.0.1" in lowered:
            for page in pages:
                url = str(getattr(page, "url", "") or "").lower()
                if "localhost" in url or "127.0.0.1" in url:
                    return page
        if "current" in lowered or "currently open" in lowered or "this page" in lowered:
            return default_page or self._page or pages[-1]
        return None

    async def close(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        if self._runtime_home:
            shutil.rmtree(self._runtime_home, ignore_errors=True)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._runtime_home = None
        self._used_headless = False
```

- [ ] **Step 4: Run controller tests**

Run:

```powershell
python tests/test_browser_controller.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add agents/browser/controller.py tests/test_browser_controller.py
git commit -m "feat: add python playwright browser controller"
```

---

## Task 3: Install Playwright MCP By Default

**Files:**
- Create: `integrations/playwright_mcp/package.json`
- Create: `integrations/playwright_mcp/.gitignore`
- Modify: `requirements.txt`
- Modify: `setup.ps1`
- Modify: `setup.sh`
- Modify: `README.md`

- [ ] **Step 1: Add local Playwright MCP package manifest**

Create `integrations/playwright_mcp/package.json`:

```json
{
  "name": "jarvis-playwright-mcp-runtime",
  "version": "1.0.0",
  "private": true,
  "description": "Pinned local Playwright MCP runtime used by the Jarvis BrowserAgent.",
  "license": "UNLICENSED",
  "dependencies": {
    "@playwright/mcp": "0.0.73"
  }
}
```

Create `integrations/playwright_mcp/.gitignore`:

```gitignore
node_modules/
npm-debug.log*
```

- [ ] **Step 2: Add Python MCP SDK dependency**

Modify `requirements.txt` under the browser dependencies block:

```text
# Browser Agent dependencies
browser-use==0.12.2
playwright==1.58.0
psutil==7.2.2
mcp==1.26.0
```

- [ ] **Step 3: Install MCP dependencies in Windows setup**

Modify `setup.ps1` after the UI dependency install block and before Gemini CLI install:

```powershell
Push-Location (Join-Path $root "integrations\playwright_mcp")
try {
    Invoke-Step "Installing Playwright MCP dependencies..." {
        npm install
    }
}
finally {
    Pop-Location
}
```

- [ ] **Step 4: Install MCP dependencies in macOS/Linux setup**

Modify `setup.sh` after the UI dependency install block and before Gemini CLI install:

```bash
echo "[setup] Installing Playwright MCP dependencies..."
cd "$ROOT_DIR/integrations/playwright_mcp"
npm install
```

- [ ] **Step 5: Run install commands to generate package lock**

Run:

```powershell
Push-Location integrations\playwright_mcp
npm install
Pop-Location
```

Expected: `integrations/playwright_mcp/package-lock.json` is created and `node_modules/` is not staged.

- [ ] **Step 6: Add README dependency note**

Modify `README.md` installation section after Playwright browser install details:

```markdown
The setup scripts also install a local pinned Playwright MCP runtime under `integrations/playwright_mcp/`. Browser tasks use Python Playwright first for deterministic control and can use the local Playwright MCP server for accessibility-snapshot workflows. Runtime browser tasks do not download MCP packages from the network.
```

- [ ] **Step 7: Run setup smoke commands**

Run:

```powershell
python -m pip install -r requirements.txt
Push-Location integrations\playwright_mcp
npm install
npm exec playwright-mcp -- --help
Pop-Location
```

Expected: pip install succeeds, npm install succeeds, and `playwright-mcp --help` prints CLI help.

- [ ] **Step 8: Commit**

```powershell
git add requirements.txt setup.ps1 setup.sh README.md integrations/playwright_mcp/package.json integrations/playwright_mcp/package-lock.json integrations/playwright_mcp/.gitignore
git commit -m "build: install local playwright mcp runtime"
```

---

## Task 4: Add Playwright MCP Client Adapter

**Files:**
- Create: `agents/browser/mcp_client.py`
- Create: `tests/test_browser_mcp_client.py`

- [ ] **Step 1: Write failing tests for MCP binary resolution and response parsing**

Create `tests/test_browser_mcp_client.py`:

```python
import asyncio
import os
import sys
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.browser.mcp_client import PlaywrightMcpClient, parse_mcp_text_response


def test_local_mcp_command_resolves_to_project_install() -> None:
    client = PlaywrightMcpClient(project_root=Path(ROOT_DIR))
    command = client.resolve_command()
    assert command.name in {"playwright-mcp", "playwright-mcp.cmd"}
    assert "integrations" in str(command)
    assert "playwright_mcp" in str(command)


def test_parse_mcp_text_response_handles_text_blocks() -> None:
    response = {
        "content": [
            {"type": "text", "text": "Snapshot line one"},
            {"type": "text", "text": "Snapshot line two"},
        ]
    }
    assert parse_mcp_text_response(response) == "Snapshot line one\nSnapshot line two"


async def _run_unavailable_check() -> None:
    client = PlaywrightMcpClient(project_root=Path(ROOT_DIR) / "missing-root")
    assert await client.health_check() is False


def test_health_check_returns_false_when_mcp_is_not_installed() -> None:
    asyncio.run(_run_unavailable_check())
```

- [ ] **Step 2: Run tests and confirm missing module**

Run:

```powershell
python tests/test_browser_mcp_client.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agents.browser.mcp_client'`.

- [ ] **Step 3: Implement MCP client adapter using official Python SDK**

Create `agents/browser/mcp_client.py`:

```python
from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any


def parse_mcp_text_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, dict):
        content = response.get("content")
    else:
        content = getattr(response, "content", None)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            text = item.get("text") if item.get("type") == "text" else None
        else:
            text = getattr(item, "text", None) if getattr(item, "type", None) == "text" else None
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts).strip()


class PlaywrightMcpClient:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._exit_stack: AsyncExitStack | None = None
        self._session: Any = None

    def resolve_command(self) -> Path:
        base = self.project_root / "integrations" / "playwright_mcp" / "node_modules" / ".bin"
        candidates = [base / "playwright-mcp.cmd", base / "playwright-mcp"]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def is_installed(self) -> bool:
        return self.resolve_command().exists()

    async def connect(self):
        if self._session is not None:
            return self._session
        if not self.is_installed():
            raise RuntimeError(
                "Local Playwright MCP runtime is not installed. Run setup.ps1 or setup.sh."
            )
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._exit_stack = AsyncExitStack()
        command = str(self.resolve_command())
        server_params = StdioServerParameters(
            command=command,
            args=["--headless"],
            env=None,
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return session

    async def health_check(self) -> bool:
        if not self.is_installed():
            return False
        try:
            session = await self.connect()
            tools = await session.list_tools()
        except Exception:
            await self.close()
            return False
        tool_items = getattr(tools, "tools", [])
        return any(getattr(tool, "name", "") == "browser_snapshot" for tool in tool_items)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        session = await self.connect()
        return await session.call_tool(name, arguments or {})

    async def navigate(self, url: str) -> str:
        response = await self.call_tool("browser_navigate", {"url": url})
        return parse_mcp_text_response(response)

    async def snapshot(self) -> str:
        response = await self.call_tool("browser_snapshot", {})
        return parse_mcp_text_response(response)

    async def close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._exit_stack = None
        self._session = None
```

- [ ] **Step 4: Run MCP client tests**

Run:

```powershell
python tests/test_browser_mcp_client.py
```

Expected: PASS. If `test_local_mcp_command_resolves_to_project_install` fails because npm install has not run, run Task 3 Step 5 first.

- [ ] **Step 5: Run process hygiene check**

Run:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(node|npx|cmd|powershell|pwsh|python|python.exe)$' -and ($_.CommandLine -match 'playwright-mcp|D:\\projects\\major\\project') } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | Format-List
```

Expected: no stale `playwright-mcp` or `node.exe` process remains after tests.

- [ ] **Step 6: Commit**

```powershell
git add agents/browser/mcp_client.py tests/test_browser_mcp_client.py
git commit -m "feat: add playwright mcp client adapter"
```

---

## Task 5: Extend Browser Task Policy

**Files:**
- Modify: `agents/browser/task_policy.py`
- Modify: `tests/test_browser_task_policy_boundary.py`

- [ ] **Step 1: Add failing policy assertions**

Modify `tests/test_browser_task_policy_boundary.py` by adding these assertions to the existing policy test function:

```python
    assert should_extract_page_content("read the headings on the current page")
    assert should_extract_page_content("show me the key findings from this article")
    assert should_extract_page_content("what are the sections on this website")
    assert should_use_mcp_snapshot("click the submit button based on the current page")
    assert should_use_mcp_snapshot("use the page controls to filter the results")
    assert not should_use_mcp_snapshot("open https://example.com")
    assert not should_use_mcp_snapshot("summarize https://example.com")
```

Also update the import block:

```python
from agents.browser.task_policy import (
    extract_direct_url,
    has_browser_interaction_intent,
    should_extract_page_content,
    should_fallback_to_playwright,
    should_search_before_direct_navigation,
    should_use_mcp_snapshot,
    should_use_playwright_fast_path,
)
```

- [ ] **Step 2: Run policy tests and confirm missing function**

Run:

```powershell
python tests/test_browser_task_policy_boundary.py
```

Expected: FAIL with `ImportError` or `NameError` for `should_use_mcp_snapshot`.

- [ ] **Step 3: Implement policy changes**

Modify `agents/browser/task_policy.py`:

```python
PAGE_STRUCTURE_MARKERS = (
    "heading",
    "headings",
    "section",
    "sections",
    "findings",
    "key findings",
    "takeaways",
    "key takeaways",
)


MCP_SNAPSHOT_MARKERS = (
    "based on the current page",
    "page controls",
    "use the page controls",
    "click the",
    "press the",
    "choose",
    "select",
    "filter",
)
```

Update `should_extract_page_content` before `content_patterns`:

```python
    for marker in PAGE_STRUCTURE_MARKERS:
        if " " in marker:
            if marker in lowered:
                return True
        elif re.search(rf"\b{re.escape(marker)}\b", lowered):
            return True
```

Add:

```python
def should_use_mcp_snapshot(task: str) -> bool:
    lowered = " ".join((task or "").lower().split())
    if not lowered:
        return False
    if should_extract_page_content(lowered) and not has_browser_interaction_intent(lowered):
        return False
    if extract_direct_url(task) and not has_browser_interaction_intent(task):
        return False
    return any(marker in lowered for marker in MCP_SNAPSHOT_MARKERS)
```

- [ ] **Step 4: Add BrowserAgent static wrapper**

Modify `agents/browser/agent.py` import list:

```python
    should_use_mcp_snapshot,
```

Add to `BrowserAgent` static helper section:

```python
    @staticmethod
    def _should_use_mcp_snapshot(task: str) -> bool:
        return should_use_mcp_snapshot(task)
```

- [ ] **Step 5: Run policy and browser fallback tests**

Run:

```powershell
python tests/test_browser_task_policy_boundary.py
python tests/test_browser_agent_fallback.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add agents/browser/task_policy.py agents/browser/agent.py tests/test_browser_task_policy_boundary.py
git commit -m "feat: route browser tasks by page context intent"
```

---

## Task 6: Integrate Controller Into BrowserAgent

**Files:**
- Modify: `agents/browser/agent.py`
- Modify: `tests/test_browser_agent_fallback.py`

- [ ] **Step 1: Add failing BrowserAgent page content integration test**

Add this test helper to `tests/test_browser_agent_fallback.py` before `run_checks()`:

```python
async def _run_controller_page_context_result_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_backend = cls._shared_backend
    original_controller = cls._shared_playwright_controller

    class _FakeController:
        async def navigate_and_extract(self, url: str):
            from agents.browser.page_context import PageContext

            return PageContext(
                title="Example Docs",
                url=url,
                headings=["Install", "Usage"],
                text="Install instructions explain setup. Usage explains day to day work.",
            )

        async def extract_context(self, page=None):
            from agents.browser.page_context import PageContext

            return PageContext(
                title="Current Page",
                url="http://localhost:3000",
                headings=["Dashboard", "Results"],
                text="Dashboard shows the current local app results.",
            )

    try:
        cls._shared_backend = None
        cls._shared_playwright_controller = _FakeController()
        result = await agent.execute("summarize https://example.com/docs")
        assert result["success"], result
        assert result["complete"] is True, result
        summary = result["result"]["summary"]
        assert "Summary of Example Docs" in summary, summary
        assert "Install instructions explain setup" in summary, summary
    finally:
        cls._shared_backend = original_backend
        cls._shared_playwright_controller = original_controller
```

Call it inside `run_checks()`:

```python
    asyncio.run(_run_controller_page_context_result_check())
```

- [ ] **Step 2: Run browser fallback tests and confirm missing controller field**

Run:

```powershell
python tests/test_browser_agent_fallback.py
```

Expected: FAIL with `AttributeError` for `_shared_playwright_controller` or a routing mismatch.

- [ ] **Step 3: Add shared controller field and helper**

Modify `agents/browser/agent.py` imports:

```python
from agents.browser.controller import PlaywrightBrowserController
from agents.browser.page_context import format_page_context_response
```

Add class field near existing Playwright fields:

```python
    _shared_playwright_controller: Any = None
```

Add helper:

```python
    @classmethod
    def _get_or_create_playwright_controller(cls) -> PlaywrightBrowserController:
        controller = cls._shared_playwright_controller
        if controller is None:
            controller = PlaywrightBrowserController()
            cls._shared_playwright_controller = controller
        return controller
```

- [ ] **Step 4: Add deterministic page context execution path**

Add method to `BrowserAgent`:

```python
    async def _execute_with_controller_page_context(
        self,
        task: str,
        *,
        pre_extracted_url: str | None,
    ) -> dict[str, Any]:
        controller = type(self)._get_or_create_playwright_controller()
        if pre_extracted_url:
            context = await controller.navigate_and_extract(pre_extracted_url)
        else:
            page, _used_headless = await controller.get_or_create_page()
            selected = await controller.select_relevant_existing_page(task, default_page=page)
            context = await controller.extract_context(selected or page)
        summary = format_page_context_response(task, context)
        return {
            "success": True,
            "result": {
                "summary": summary,
                "mode": "playwright_controller",
                "task": task,
                "url": context.url,
                "title": context.title,
                "headings": context.headings,
                "complete": True,
            },
            "error": None,
            "complete": True,
        }
```

- [ ] **Step 5: Route page content requests to controller before browser_use**

Modify `execute()` after `close_when_done = False` and before backend reuse:

```python
        if self._should_extract_page_content(task):
            return await self._execute_with_controller_page_context(
                task,
                pre_extracted_url=original_direct_url,
            )
```

- [ ] **Step 6: Ensure shared resource cleanup closes controller**

Modify `_close_shared_resources` to close the controller before backend-specific cleanup:

```python
        controller = cls._shared_playwright_controller
        if controller is not None:
            try:
                await controller.close()
            except Exception:
                pass
            cls._shared_playwright_controller = None
```

- [ ] **Step 7: Run BrowserAgent tests**

Run:

```powershell
python tests/test_browser_agent_fallback.py
python tests/test_browser_task_policy_boundary.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add agents/browser/agent.py tests/test_browser_agent_fallback.py
git commit -m "feat: use playwright controller for page reading tasks"
```

---

## Task 7: Add MCP Snapshot Backend Routing

**Files:**
- Modify: `agents/browser/agent.py`
- Modify: `tests/test_browser_agent_fallback.py`

- [ ] **Step 1: Add failing test for MCP snapshot path**

Add this helper to `tests/test_browser_agent_fallback.py`:

```python
async def _run_mcp_snapshot_backend_check() -> None:
    agent = BrowserAgent(model_name="test-model")
    cls = BrowserAgent

    original_client = cls._shared_playwright_mcp_client
    original_execute_browser_use = agent._execute_with_browser_use

    calls: list[str] = []

    class _FakeMcpClient:
        async def health_check(self) -> bool:
            return True

        async def snapshot(self) -> str:
            calls.append("snapshot")
            return '- button "Submit" [ref=e12]\\n- textbox "Search" [ref=e5]'

    async def _fail_browser_use(task: str, close_when_done: bool):
        raise AssertionError("browser_use should not run for MCP snapshot probe")

    try:
        cls._shared_playwright_mcp_client = _FakeMcpClient()
        agent._execute_with_browser_use = _fail_browser_use
        result = await agent.execute("click the submit button based on the current page")
        assert result["success"], result
        assert result["complete"] is False, result
        assert calls == ["snapshot"], calls
        assert "Submit" in result["result"]["summary"], result
    finally:
        cls._shared_playwright_mcp_client = original_client
        agent._execute_with_browser_use = original_execute_browser_use
```

Call it inside `run_checks()`:

```python
    asyncio.run(_run_mcp_snapshot_backend_check())
```

- [ ] **Step 2: Run tests and confirm missing MCP client field**

Run:

```powershell
python tests/test_browser_agent_fallback.py
```

Expected: FAIL with `AttributeError` for `_shared_playwright_mcp_client`.

- [ ] **Step 3: Add MCP client fields and helper**

Modify `agents/browser/agent.py` imports:

```python
from agents.browser.mcp_client import PlaywrightMcpClient
```

Add class field:

```python
    _shared_playwright_mcp_client: Any = None
```

Add helper:

```python
    @classmethod
    def _get_or_create_playwright_mcp_client(cls) -> PlaywrightMcpClient:
        client = cls._shared_playwright_mcp_client
        if client is None:
            client = PlaywrightMcpClient()
            cls._shared_playwright_mcp_client = client
        return client
```

- [ ] **Step 4: Add MCP snapshot execution method**

Add method:

```python
    async def _execute_with_playwright_mcp_snapshot(self, task: str) -> dict[str, Any]:
        client = type(self)._get_or_create_playwright_mcp_client()
        if not await client.health_check():
            return {
                "success": False,
                "result": None,
                "error": "Playwright MCP is unavailable.",
                "complete": False,
            }
        snapshot = await client.snapshot()
        summary = (
            "Playwright MCP captured the current page structure, but an additional "
            f"action is needed to complete the request. Snapshot:\n{snapshot}"
        )
        return {
            "success": True,
            "result": {
                "summary": summary,
                "mode": "playwright_mcp_snapshot",
                "task": task,
                "complete": False,
            },
            "error": None,
            "complete": False,
        }
```

- [ ] **Step 5: Route MCP snapshot requests before browser_use**

Modify `execute()` after the page-context request branch:

```python
        if self._should_use_mcp_snapshot(task):
            mcp_result = await self._execute_with_playwright_mcp_snapshot(task)
            if mcp_result.get("success"):
                return mcp_result
```

- [ ] **Step 6: Cleanup MCP client on stop**

Modify `_close_shared_resources` near controller cleanup:

```python
        mcp_client = cls._shared_playwright_mcp_client
        if mcp_client is not None:
            close = getattr(mcp_client, "close", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    pass
            cls._shared_playwright_mcp_client = None
```

- [ ] **Step 7: Run BrowserAgent tests and process hygiene check**

Run:

```powershell
python tests/test_browser_agent_fallback.py
python tests/test_browser_mcp_client.py
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(node|npx|cmd|powershell|pwsh|python|python.exe)$' -and ($_.CommandLine -match 'playwright-mcp|D:\\projects\\major\\project') } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | Format-List
```

Expected: tests PASS and no stale `playwright-mcp` process remains.

- [ ] **Step 8: Commit**

```powershell
git add agents/browser/agent.py tests/test_browser_agent_fallback.py
git commit -m "feat: add playwright mcp snapshot backend"
```

---

## Task 8: Surface Structured Browser Context In Chat

**Files:**
- Modify: `models/agent_step_runner.py`
- Create: `tests/test_agent_step_runner_browser_message.py`

- [ ] **Step 1: Add failing message extraction assertion**

Add this test to `tests/test_agent_step_runner_browser_message.py`:

```python
def test_browser_message_prefers_nested_page_context_summary() -> None:
    from models.agent_step_runner import _browser_completion_message

    result = {
        "success": True,
        "result": {
            "page_context": {
                "summary": "Summary of Example Docs:\nInstall instructions explain setup."
            },
            "summary": "",
        },
    }
    assert _browser_completion_message(result) == (
        "Summary of Example Docs:\nInstall instructions explain setup."
    )
```

- [ ] **Step 2: Run test and confirm extraction does not read nested page context**

Run:

```powershell
python tests/test_agent_step_runner_browser_message.py
```

Expected: FAIL because `_browser_completion_message` returns `Browser task completed.` or an empty fallback.

- [ ] **Step 3: Extend browser message extraction**

Modify `_extract_browser_message` in `models/agent_step_runner.py` inside the `isinstance(history, dict)` block:

```python
        page_context = history.get("page_context")
        if isinstance(page_context, dict):
            value = page_context.get("summary") or page_context.get("content")
            if isinstance(value, str) and value.strip():
                return _clean_text(value, "")
```

Keep the existing direct key loop below this new block.

- [ ] **Step 4: Run message extraction test**

Run:

```powershell
python tests/test_agent_step_runner_browser_message.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add models/agent_step_runner.py tests/test_agent_step_runner_browser_message.py
git commit -m "feat: surface browser page context in chat"
```

---

## Task 9: End-to-End Validation And Cleanup

**Files:**
- Modify only files that fail validation from earlier tasks.

- [ ] **Step 1: Run focused backend tests**

Run:

```powershell
python tests/test_browser_page_context.py
python tests/test_browser_controller.py
python tests/test_browser_mcp_client.py
python tests/test_browser_task_policy_boundary.py
python tests/test_browser_agent_fallback.py
python tests/test_agent_step_runner_browser_message.py
```

Expected: all PASS.

- [ ] **Step 2: Run router regression tests affected by browser completion**

Run:

```powershell
python tests/test_router_chaining.py
python tests/test_routing_policy.py
python tests/test_routing_contracts.py
```

Expected: all PASS.

- [ ] **Step 3: Run dependency install smoke tests**

Run:

```powershell
python -m pip install -r requirements.txt
Push-Location integrations\playwright_mcp
npm install
npm exec playwright-mcp -- --help
Pop-Location
```

Expected: pip install succeeds, npm install succeeds, and the MCP CLI help is printed.

- [ ] **Step 4: Run process hygiene check**

Run:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(cmd|powershell|pwsh|node|npx|python|python.exe)$' -and ($_.CommandLine -match 'D:\\projects\\major\\project|browser|mcp|playwright') } | Select-Object ProcessId,ParentProcessId,Name,CommandLine | Format-List
```

Expected: no stale task-owned `node.exe`, `npx`, `powershell.exe`, `cmd.exe`, `python.exe`, or `playwright-mcp` process remains.

- [ ] **Step 5: Run manual smoke through BrowserAgent**

Run:

```powershell
@'
import asyncio
from agents.browser.agent import BrowserAgent

async def main():
    agent = BrowserAgent(model_name="test-model")
    result = await agent.execute("summarize https://example.com")
    print(result["success"])
    print(result["complete"])
    print(result["result"]["summary"])
    await agent.stop()

asyncio.run(main())
'@ | python -
```

Expected: prints `True`, prints `True`, and prints a summary that includes `Example Domain` or readable page text.

- [ ] **Step 6: Commit validation fixes**

If validation required code changes:

```powershell
git add agents/browser models tests requirements.txt setup.ps1 setup.sh README.md integrations/playwright_mcp
git commit -m "test: validate hybrid playwright browser backend"
```

If validation required no code changes, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan covers Python-first Playwright control, request-driven summaries/headings/findings, default local Playwright MCP installation, MCP adapter usage, BrowserAgent routing, chat surfacing, tests, setup scripts, and process hygiene.
- Red-flag scan: The plan contains concrete file paths, commands, expected outcomes, and implementation snippets.
- Type consistency: `PageContext`, `PlaywrightBrowserController`, `PlaywrightMcpClient`, `format_page_context_response`, and `should_use_mcp_snapshot` are defined before later tasks use them.
- Scope check: The plan keeps one feature boundary: hybrid browser backend for BrowserAgent. It does not include custom Jarvis MCP server creation or unrelated browser-use replacement.
