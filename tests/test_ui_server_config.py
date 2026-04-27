import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_server_config_eval(project_root: Path, body: str, env_overrides: dict[str, str] | None = None):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to validate ui/server_config.js")

    script = (
        "const path = require('path');\n"
        "const serverConfig = require(path.join(process.cwd(), 'ui', 'server_config.js'));\n"
        "const projectRoot = process.env.PROJECT_ROOT;\n"
        f"{body}\n"
    )
    env = os.environ.copy()
    env["PROJECT_ROOT"] = str(project_root)
    if env_overrides:
        env.update(env_overrides)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip() or "null")


def test_runtime_state_overrides_settings_values(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "settings.json").write_text(
        json.dumps({"host": "10.10.10.10", "port": 1111}),
        encoding="utf-8",
    )
    runtime_path = project_root / "runtime-state.json"
    runtime_path.write_text(
        json.dumps({"host": "127.0.0.1", "port": 9876}),
        encoding="utf-8",
    )

    result = _run_server_config_eval(
        project_root,
        (
            "const result = serverConfig.getServerConfig({ projectRoot });\n"
            "process.stdout.write(JSON.stringify(result));"
        ),
        {"JARVIS_RUNTIME_STATE_PATH": str(runtime_path)},
    )

    assert result == {"host": "127.0.0.1", "port": 9876}


def test_invalid_runtime_values_fall_back_to_settings(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "settings.json").write_text(
        json.dumps({"host": "192.168.1.25", "port": 8766}),
        encoding="utf-8",
    )
    runtime_path = project_root / "runtime-state.json"
    runtime_path.write_text(
        json.dumps({"host": "   ", "port": "not-a-number"}),
        encoding="utf-8",
    )

    result = _run_server_config_eval(
        project_root,
        (
            "const result = serverConfig.getServerConfig({ projectRoot });\n"
            "process.stdout.write(JSON.stringify(result));"
        ),
        {"JARVIS_RUNTIME_STATE_PATH": str(runtime_path)},
    )

    assert result == {"host": "192.168.1.25", "port": 8766}


def test_missing_files_use_defaults(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)

    result = _run_server_config_eval(
        project_root,
        (
            "const result = serverConfig.getServerConfig({ projectRoot });\n"
            "process.stdout.write(JSON.stringify(result));"
        ),
    )

    assert result == {"host": "127.0.0.1", "port": 8765}


def test_runtime_state_path_honors_explicit_env(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    explicit_runtime_path = str(project_root / "custom-runtime.json")

    resolved_path = _run_server_config_eval(
        project_root,
        (
            "const result = serverConfig.getRuntimeStatePath(projectRoot);\n"
            "process.stdout.write(JSON.stringify(result));"
        ),
        {"JARVIS_RUNTIME_STATE_PATH": f"  {explicit_runtime_path}  "},
    )

    assert resolved_path == explicit_runtime_path
