import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_generating_indicator_eval(body: str):
    if shutil.which("node") is None:
        raise RuntimeError("Node.js is required to validate ui/generating_indicator.mjs")

    script = (
        "const path = require('path');\n"
        "const { pathToFileURL } = require('url');\n"
        "(async () => {\n"
        "  const modulePath = pathToFileURL(path.join(process.cwd(), 'ui', 'generating_indicator.mjs')).href;\n"
        "  const indicator = await import(modulePath);\n"
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


def test_generating_indicator_uses_public_phrases_and_three_dots() -> None:
    result = _run_generating_indicator_eval(
        (
            "const initial = indicator.buildGeneratingIndicatorView({ elapsedMs: 0, statusText: '' });\n"
            "const routing = indicator.buildGeneratingIndicatorView({ elapsedMs: 1600, statusText: 'Routing request…' });\n"
            "const custom = indicator.buildGeneratingIndicatorView({ elapsedMs: 3200, statusText: 'Checking result…' });\n"
            "process.stdout.write(JSON.stringify({\n"
            "  initial,\n"
            "  routing,\n"
            "  custom,\n"
            "  placeholders: ['Thinking', 'Preparing the response', 'Waiting for model response…'].map((text) => indicator.isGeneratingPlaceholderText(text)),\n"
            "}));"
        ),
    )

    assert result["initial"]["label"] == "Thinking"
    assert result["initial"]["dotCount"] == 3
    assert result["routing"]["label"] == "Choosing the right agent"
    assert result["custom"]["label"] == "Checking result"
    assert result["custom"]["ariaLabel"] == "Checking result..."
    assert result["placeholders"] == [True, True, True]


def test_chat_pending_assistant_messages_use_generating_indicator_markup() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert "buildGeneratingIndicatorView" in input_window_js
    assert "renderGeneratingIndicatorContent" in input_window_js
    assert "chat-msg-generating" in input_window_js
    assert ".chat-generating-indicator" in input_window_css
    assert ".chat-generating-dot" in input_window_css
    assert "prefers-reduced-motion: reduce" in input_window_css


if __name__ == "__main__":
    test_generating_indicator_uses_public_phrases_and_three_dots()
    test_chat_pending_assistant_messages_use_generating_indicator_markup()
    print("[test_ui_generating_indicator] All checks passed.")
