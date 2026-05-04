import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_chat_outcome_eval(body: str):
    if shutil.which("node") is None:
        raise RuntimeError("Node.js is required to validate ui/chat_outcome.mjs")

    script = (
        "const path = require('path');\n"
        "const { pathToFileURL } = require('url');\n"
        "(async () => {\n"
        "  const modulePath = pathToFileURL(path.join(process.cwd(), 'ui', 'chat_outcome.mjs')).href;\n"
        "  const outcome = await import(modulePath);\n"
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


def test_failed_agent_trace_keeps_chat_lifecycle_in_needs_attention() -> None:
    result = _run_chat_outcome_eval(
        (
            "const failed = outcome.getAssistantLifecycleOutcome({\n"
            "  text: 'Stopping chained execution because cua_vision failed: quota exceeded',\n"
            "  agentTrace: { status: 'failed', summary: 'Vision model quota exceeded' },\n"
            "});\n"
            "const completed = outcome.getAssistantLifecycleOutcome({\n"
            "  text: 'Opened WhatsApp Web successfully.',\n"
            "  agentTrace: { status: 'completed', summary: 'Browser task completed.' },\n"
            "});\n"
            "process.stdout.write(JSON.stringify({ failed, completed }));"
        ),
    )

    assert result["failed"]["phase"] == "stopped"
    assert result["failed"]["text"] == "Needs attention"
    assert "failed" in result["failed"]["detail"].lower()
    assert result["completed"]["phase"] == "completed"
    assert result["completed"]["text"] == "Completed"


def test_chat_uses_failure_aware_lifecycle_for_final_router_reply() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")

    assert "getAssistantLifecycleOutcome" in input_window_js
    assert "applyFinalAssistantLifecycle" in input_window_js
    assert "Latest response is ready." not in input_window_js.split(
        "payload.command === 'draw_text' && payload.id === 'direct_response'",
        1,
    )[1].split("return;", 1)[0]


if __name__ == "__main__":
    test_failed_agent_trace_keeps_chat_lifecycle_in_needs_attention()
    test_chat_uses_failure_aware_lifecycle_for_final_router_reply()
    print("[test_ui_chat_outcome] All checks passed.")
