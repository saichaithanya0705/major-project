import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_node(body: str):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to validate ui/main/safe_logger.js")

    script = (
        "const path = require('path');\n"
        "const { createSafeLogger } = require(path.join(process.cwd(), 'ui', 'main', 'safe_logger.js'));\n"
        f"{body}\n"
    )
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip() or "null")


def test_safe_logger_disables_after_broken_pipe() -> None:
    result = _run_node(
        """
        let calls = 0;
        const target = {
          log: () => {
            calls += 1;
            const error = new Error('broken pipe, write');
            error.code = 'EPIPE';
            throw error;
          }
        };
        const logger = createSafeLogger(target);
        const first = logger.log('first');
        const second = logger.log('second');
        process.stdout.write(JSON.stringify({
          first,
          second,
          calls,
          outputBroken: logger.isOutputBroken()
        }));
        """
    )

    assert result == {
        "first": False,
        "second": False,
        "calls": 1,
        "outputBroken": True,
    }


def test_safe_logger_rethrows_non_pipe_errors() -> None:
    result = _run_node(
        """
        const target = {
          error: () => {
            const error = new Error('formatter failed');
            error.code = 'EINVAL';
            throw error;
          }
        };
        const logger = createSafeLogger(target);
        let message = '';
        try {
          logger.error('boom');
        } catch (error) {
          message = error.message;
        }
        process.stdout.write(JSON.stringify({ message, outputBroken: logger.isOutputBroken() }));
        """
    )

    assert result == {"message": "formatter failed", "outputBroken": False}


def test_electron_main_uses_safe_logger_boundary() -> None:
    main_js = (ROOT_DIR / "ui" / "main.js").read_text(encoding="utf-8")

    assert "createSafeLogger" in main_js
    assert "const logger = createSafeLogger(console)" in main_js
    assert "console.log(" not in main_js
    assert "console.error(" not in main_js
