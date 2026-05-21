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
            "  webQa: traceModule.isAgentTraceSource('web_qa'),\n"
            "  webQaLabel: traceModule.getAgentTraceSourceLabel('web_qa'),\n"
            "}));"
        ),
    )

    assert result == {
        "rapid": False,
        "cli": True,
        "browserLabel": "Browser",
        "webQa": True,
        "webQaLabel": "Web QA",
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


def test_web_qa_trace_records_sourced_answer_without_router_reply_source() -> None:
    result = _run_agent_trace_eval(
        (
            "const trace = traceModule.createAgentWorkTraceState();\n"
            "const running = trace.applyEvent({ command: 'show_status_bubble', source: 'web_qa', text: 'Searching the web...' });\n"
            "const done = trace.applyEvent({ command: 'complete_status_bubble', source: 'web_qa', doneText: 'Task done', responseText: 'Sourced answer\\n\\nSources:\\n- [Example](https://example.com)' });\n"
            "const ignored = trace.applyEvent({ command: 'chat_response', source: 'rapid_response', text: 'Sourced answer\\n\\nSources:\\n- [Example](https://example.com)' });\n"
            "process.stdout.write(JSON.stringify({ running, done, ignored }));"
        ),
    )

    assert result["running"]["isOpen"] is True
    assert result["running"]["entries"][-1]["label"] == "Web QA"
    assert result["done"]["isOpen"] is False
    assert result["done"]["status"] == "completed"
    assert result["done"]["entries"][-1]["source"] == "web_qa"
    assert result["done"]["summary"] == "Sourced answer Sources: - [Example](https://example.com)"
    assert result["ignored"] == result["done"]


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


def test_orchestrator_plan_snapshot_normalizes_to_ui_trace_rows() -> None:
    result = _run_agent_trace_eval(
        (
            "const trace = traceModule.createAgentWorkTraceState();\n"
            "const state = trace.applyEvent({ command: 'orchestrator_plan_snapshot', plan: {\n"
            "  tasks: [\n"
            "    { id: 'research', agent: 'web_qa', task: 'Find sources', status: 'completed' },\n"
            "    { id: 'patch', agent: 'cua_cli', task: 'Patch files', status: 'running', depends_on: ['research'] }\n"
            "  ]\n"
            "} });\n"
            "process.stdout.write(JSON.stringify(state));"
        ),
    )

    assert result["isOpen"] is True
    assert result["status"] == "running"
    assert result["entries"] == [
        {
            "id": 1,
            "source": "web_qa",
            "label": "Web QA",
            "status": "completed",
            "text": "research · Find sources",
            "taskId": "research",
            "dependsOn": [],
        },
        {
            "id": 2,
            "source": "cua_cli",
            "label": "CLI",
            "status": "running",
            "text": "patch · Patch files",
            "taskId": "patch",
            "dependsOn": ["research"],
        },
    ]


def test_orchestrator_plan_snapshot_treats_pending_tasks_as_waiting() -> None:
    result = _run_agent_trace_eval(
        (
            "const snapshot = traceModule.normalizeOrchestratorPlanSnapshot({ tasks: [\n"
            "  { id: 'queued', agent: 'browser', task: 'Open docs', status: 'pending' }\n"
            "] });\n"
            "process.stdout.write(JSON.stringify(snapshot));"
        ),
    )

    assert result["isOpen"] is True
    assert result["status"] == "running"
    assert result["entries"][0]["status"] == "waiting"
