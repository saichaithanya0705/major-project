"""Local launcher contracts without starting the real desktop or provider clients."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from core import app_runtime_lifecycle
from core.process_lifecycle import ManagedProcessSpec, ProcessStartError, ProcessSupervisor


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launch_context(tmp_path, monkeypatch):
    for name in (
        "JARVIS_AUTO_LAUNCH_ELECTRON",
        "JARVIS_UI_EXECUTABLE",
        "JARVIS_ELECTRON_BINARY",
        "ELECTRON_RUN_AS_NODE",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "ui").mkdir()
    specs = []

    def start(spec):
        specs.append(spec)
        return SimpleNamespace(pid=5151)

    return tmp_path, specs, SimpleNamespace(start=start)


@pytest.mark.parametrize("relative", [False, True])
def test_packaged_ui_bypasses_npm_and_inherits_shared_runtime(launch_context, monkeypatch, relative):
    root, specs, supervisor = launch_context
    executable = root / "ui" / "Approved Build" / "JARVIS.exe"
    executable.parent.mkdir()
    executable.touch()
    override = str(executable.relative_to(root / "ui") if relative else executable)
    monkeypatch.setenv("JARVIS_UI_EXECUTABLE", f"  {override}  ")
    monkeypatch.setenv("JARVIS_ELECTRON_BINARY", "unselected-electron.exe")
    monkeypatch.setenv("ELECTRON_RUN_AS_NODE", "1")

    def unexpected_npm_lookup(_name):
        pytest.fail("Packaged UI must not require npm")

    monkeypatch.setattr(app_runtime_lifecycle.shutil, "which", unexpected_npm_lookup)
    outcome = app_runtime_lifecycle.launch_electron_ui(str(root), supervisor=supervisor)

    assert outcome.launched
    assert specs[0].command == [str(executable.resolve())]
    assert specs[0].cwd == root / "ui"
    assert specs[0].env["JARVIS_PROJECT_ROOT"] == str(root.resolve())
    assert specs[0].env["JARVIS_RUNTIME_STATE_PATH"] == app_runtime_lifecycle.get_runtime_state_path(
        str(root / "settings.json")
    )
    assert "ELECTRON_RUN_AS_NODE" not in specs[0].env
    assert os.environ["ELECTRON_RUN_AS_NODE"] == "1"
    assert specs[0].stop_process_tree == (os.name == "nt")


@pytest.mark.parametrize("is_directory", [False, True])
def test_invalid_explicit_ui_fails_without_fallback(launch_context, monkeypatch, is_directory):
    root, specs, supervisor = launch_context
    executable = root / "ui" / "invalid.exe"
    if is_directory:
        executable.mkdir()
    monkeypatch.setenv("JARVIS_UI_EXECUTABLE", str(executable))
    with pytest.raises(ProcessStartError, match="JARVIS_UI_EXECUTABLE is not a file"):
        app_runtime_lifecycle.launch_electron_ui(str(root), supervisor=supervisor)
    assert not specs


def test_packaged_ui_spawn_failure_is_fatal(launch_context, monkeypatch):
    root, specs, _ = launch_context
    executable = root / "ui" / "blocked.exe"
    executable.touch()
    monkeypatch.setenv("JARVIS_UI_EXECUTABLE", str(executable))

    def fail(_spec):
        raise ProcessStartError("blocked by policy")

    with pytest.raises(ProcessStartError, match="blocked by policy"):
        app_runtime_lifecycle.launch_electron_ui(str(root), supervisor=SimpleNamespace(start=fail))
    assert not specs


def test_unset_packaged_ui_uses_existing_npm_dev_flow(launch_context, monkeypatch):
    root, specs, supervisor = launch_context
    monkeypatch.setenv("JARVIS_UI_EXECUTABLE", "   ")
    monkeypatch.setenv("JARVIS_ELECTRON_BINARY", "approved-electron.exe")
    monkeypatch.setattr(app_runtime_lifecycle.shutil, "which", lambda _name: "npm.cmd")
    outcome = app_runtime_lifecycle.launch_electron_ui(str(root), supervisor=supervisor)
    assert outcome.launched
    assert specs[0].command == ["npm.cmd", "run", "dev"]
    assert specs[0].env["JARVIS_ELECTRON_BINARY"] == "approved-electron.exe"
    assert specs[0].stop_process_tree == (os.name == "nt")


def test_backend_only_opt_out_still_works(launch_context, monkeypatch):
    root, specs, supervisor = launch_context
    monkeypatch.setenv("JARVIS_AUTO_LAUNCH_ELECTRON", "0")
    outcome = app_runtime_lifecycle.launch_electron_ui(str(root), supervisor=supervisor)
    assert not outcome.launched
    assert not specs


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell entry point")
@pytest.mark.parametrize("exit_code", [0, 17])
def test_powershell_launcher_uses_repo_root_and_preserves_app_exit(tmp_path, exit_code):
    project = tmp_path / "Project With Spaces"
    project.mkdir()
    shutil.copyfile(ROOT / "start-dev.ps1", project / "start-dev.ps1")
    (project / "app.py").write_text(
        "import json, os, sys\n"
        "print(json.dumps({'cwd': os.getcwd(), 'auto': os.getenv('JARVIS_AUTO_LAUNCH_ELECTRON'), "
        "'ui': os.getenv('JARVIS_UI_EXECUTABLE')}))\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    env = dict(os.environ, JARVIS_AUTO_LAUNCH_ELECTRON="0", JARVIS_UI_EXECUTABLE="Approved UI.exe")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(project / "start-dev.ps1"),
         "-PythonCommand", sys.executable],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    payload = json.loads(next(line for line in result.stdout.splitlines() if line.startswith("{")))
    assert Path(payload["cwd"]) == project
    assert payload["auto"] == "1"
    assert payload["ui"] == "Approved UI.exe"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell entry point")
def test_powershell_missing_default_venv_reports_setup(tmp_path):
    shutil.copyfile(ROOT / "start-dev.ps1", tmp_path / "start-dev.ps1")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(tmp_path / "start-dev.ps1")],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "setup.ps1" in result.stderr
    assert "-PythonCommand" in result.stderr


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell entry point")
@pytest.mark.parametrize("environments", [(".venv",), (".venv-1",), (".venv", ".venv-1")])
def test_powershell_selects_project_environment(tmp_path, environments):
    shutil.copyfile(ROOT / "start-dev.ps1", tmp_path / "start-dev.ps1")
    (tmp_path / "app.py").write_text("import sys; print('PREFIX=' + sys.prefix)\n", encoding="utf-8")
    for name in environments:
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(tmp_path / name)],
            capture_output=True, text=True, check=True, timeout=30,
        )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(tmp_path / "start-dev.ps1")],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = next(line.removeprefix("PREFIX=") for line in result.stdout.splitlines() if line.startswith("PREFIX="))
    assert Path(prefix) == tmp_path / environments[0]


@pytest.mark.skipif(os.name != "nt", reason="Windows process tree cleanup")
def test_owned_windows_ui_tree_is_stopped_before_wrapper_is_lost(tmp_path):
    pid_file = tmp_path / "child.pid"
    parent_script = tmp_path / "ui-wrapper.py"
    parent_script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    supervisor = ProcessSupervisor(stop_timeout_seconds=3)
    handle = supervisor.start(ManagedProcessSpec(
        label="fake-ui", command=[sys.executable, str(parent_script), str(pid_file)],
        cwd=tmp_path, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, stop_process_tree=True,
    ))
    child_pid = None
    try:
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        child_pid = int(pid_file.read_text())
        assert psutil.pid_exists(child_pid)
        result = supervisor.stop(handle)
        assert result.returncode is not None
        deadline = time.monotonic() + 5
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(handle.pid)
        assert not psutil.pid_exists(child_pid)
    finally:
        supervisor.stop_all()
        if child_pid and psutil.pid_exists(child_pid):
            psutil.Process(child_pid).kill()


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required for UI launcher")
@pytest.mark.parametrize("target", ["packaged", "missing", "directory", "electron", "default"])
def test_ui_only_launcher_obeys_override_precedence(tmp_path, target):
    executable = tmp_path / "Approved UI.exe"
    executable.touch()
    runtime = tmp_path / "Approved Electron.exe"
    runtime.touch()
    harness = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const [script, root, target] = process.argv.slice(1);
const env = { ELECTRON_RUN_AS_NODE: '1' };
if (target === 'packaged') env.JARVIS_UI_EXECUTABLE = 'Approved UI.exe';
if (target === 'missing') env.JARVIS_UI_EXECUTABLE = 'missing.exe';
if (target === 'directory') env.JARVIS_UI_EXECUTABLE = root;
if (target !== 'default') env.JARVIS_ELECTRON_BINARY = 'Approved Electron.exe';
const result = { errors: [] };
const context = {
  require(name) {
    if (name === 'node:child_process') return { spawn(command, args, options) {
      result.spawn = { command, args, cwd: options.cwd, env: options.env };
      return { on() {} };
    } };
    if (name === 'electron') return 'default-electron';
    return require(name);
  },
  process: { env, cwd: () => root, exit(code) { throw { exitCode: code }; } },
  console: { warn() {}, error(...args) { result.errors.push(args.join(' ')); } },
};
try { vm.runInNewContext(fs.readFileSync(script, 'utf8'), context); }
catch (error) { result.exitCode = error.exitCode; }
console.log(JSON.stringify(result));
'''
    result = subprocess.run(
        ["node", "-e", harness, str(ROOT / "ui/scripts/start-electron.js"), str(tmp_path), target],
        capture_output=True, text=True, timeout=15, check=True,
    )
    payload = json.loads(result.stdout)
    if target in {"missing", "directory"}:
        assert payload["exitCode"] == 1
        assert "JARVIS_UI_EXECUTABLE is not a file" in payload["errors"][0]
        assert "spawn" not in payload
    else:
        expected = str(executable if target == "packaged" else runtime) if target != "default" else "default-electron"
        assert payload["spawn"]["command"] == expected
        assert payload["spawn"]["args"] == ([] if target == "packaged" else ["."])
        assert "ELECTRON_RUN_AS_NODE" not in payload["spawn"]["env"]
