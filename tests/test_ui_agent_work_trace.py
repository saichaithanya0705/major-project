import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_agent_trace_eval(body: str):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to validate ui/agent_work_trace.mjs")

    script = (
        "const path = require('path');\n"
        "const { pathToFileURL } = require('url');\n"
        "(async () => {\n"
        "  const modulePath = pathToFileURL(path.join(process.cwd(), 'ui', 'agent_work_trace.mjs')).href;\n"
        "  const traceModule = await import(modulePath);\n"
        f"{body}\n"
        "})().catch((error) => {\n"
        "  console.error(error && error.stack ? error.stack : error);\n"
        "  process.exit(1);\n"
        "});\n"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip() or "null")


def test_agent_trace_sources_exclude_router_replies() -> None:
    result = _run_agent_trace_eval(
        (
            "process.stdout.write(JSON.stringify({\n"
            "  rapid: traceModule.isAgentTraceSource('rapid_response'),\n"
            "  cli: traceModule.isAgentTraceSource('cua_cli'),\n"
            "  browserLabel: traceModule.getAgentTraceSourceLabel('browser_use'),\n"
            "}));"
        ),
    )

    assert result == {
        "rapid": False,
        "cli": True,
        "browserLabel": "Browser",
    }


def test_agent_trace_opens_while_running_and_collapses_after_success() -> None:
    result = _run_agent_trace_eval(
        (
            "const trace = traceModule.createAgentWorkTraceState();\n"
            "const first = trace.applyEvent({ command: 'show_status_bubble', source: 'cua_cli', text: 'Running CLI task...' });\n"
            "const second = trace.applyEvent({ command: 'update_status_bubble', source: 'cua_cli', text: 'Checking files' });\n"
            "const done = trace.applyEvent({ command: 'complete_status_bubble', source: 'cua_cli', doneText: 'Task done', responseText: 'CLI task completed.' });\n"
            "process.stdout.write(JSON.stringify({ first, second, done }));"
        ),
    )

    assert result["first"]["isOpen"] is True
    assert result["first"]["status"] == "running"
    assert result["second"]["isOpen"] is True
    assert result["second"]["summary"] == "Checking files"
    assert result["second"]["entries"][-1]["label"] == "CLI"
    assert result["done"]["isOpen"] is False
    assert result["done"]["status"] == "completed"
    assert result["done"]["summary"] == "CLI task completed."


def test_agent_trace_stays_open_after_failure() -> None:
    result = _run_agent_trace_eval(
        (
            "const trace = traceModule.createAgentWorkTraceState();\n"
            "trace.applyEvent({ command: 'show_status_bubble', source: 'browser_use', text: 'Running browser task...' });\n"
            "const failed = trace.applyEvent({ command: 'complete_status_bubble', source: 'browser_use', doneText: 'Task failed', responseText: 'Browser task failed.' });\n"
            "process.stdout.write(JSON.stringify(failed));"
        ),
    )

    assert result["isOpen"] is True
    assert result["status"] == "failed"
    assert result["summary"] == "Browser task failed."
    assert result["entries"][-1]["status"] == "failed"


def test_agent_trace_is_thread_width_not_nested_inside_assistant_bubble() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert "pendingAssistantEl.after(section)" in input_window_js
    assert "parentEl.after(section)" in input_window_js
    assert ".agent-work-trace {" in input_window_css
    agent_trace_block = input_window_css.split(".agent-work-trace {", 1)[1].split("}", 1)[0]
    assert "align-self: stretch;" in agent_trace_block
    assert "width: 100%;" in agent_trace_block
    assert "max-width: 100%;" in agent_trace_block
