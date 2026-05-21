import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.vendor_guard import (  # noqa: E402
    GeminiCliVendorError,
    validate_gemini_cli_vendor,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_vendor_tree(
    tmp_path: Path,
    *,
    package_dependency: str = "^1.0.0",
    lock_dependency: str | None = None,
) -> Path:
    vendor_root = tmp_path / "gemini-cli"
    (vendor_root / "bundle").mkdir(parents=True)
    (vendor_root / "bundle" / "gemini.js").write_text(
        "#!/usr/bin/env node\n",
        encoding="utf-8",
    )

    package_json = {
        "name": "@google/gemini-cli",
        "version": "0.29.0",
        "license": "Apache-2.0",
        "workspaces": ["packages/*"],
        "bin": {"gemini": "bundle/gemini.js"},
        "engines": {"node": ">=20.0.0"},
        "dependencies": {"dep-a": package_dependency},
        "devDependencies": {"typescript": "^5.3.3"},
        "optionalDependencies": {"node-pty": "^1.0.0"},
    }
    root_package = {
        "name": package_json["name"],
        "version": package_json["version"],
        "license": package_json["license"],
        "workspaces": package_json["workspaces"],
        "dependencies": {"dep-a": lock_dependency or package_dependency},
        "bin": package_json["bin"],
        "devDependencies": package_json["devDependencies"],
        "engines": package_json["engines"],
        "optionalDependencies": package_json["optionalDependencies"],
    }
    package_lock = {
        "name": package_json["name"],
        "version": package_json["version"],
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": root_package},
    }

    _write_json(vendor_root / "package.json", package_json)
    _write_json(vendor_root / "package-lock.json", package_lock)

    manifest = {
        "schema_version": 1,
        "vendor_root": "gemini-cli",
        "package_name": package_json["name"],
        "package_version": package_json["version"],
        "lockfile_version": package_lock["lockfileVersion"],
        "cli_entrypoint": "bundle/gemini.js",
        "cli_entrypoint_sha256": _sha256(vendor_root / "bundle" / "gemini.js"),
        "package_json_sha256": _sha256(vendor_root / "package.json"),
        "package_lock_sha256": _sha256(vendor_root / "package-lock.json"),
    }
    _write_json(vendor_root.parent / "gemini_cli_vendor_manifest.json", manifest)
    return vendor_root


def test_current_manifest_matches_vendored_gemini_cli() -> None:
    vendor_root = Path(ROOT_DIR) / "agents" / "cua_cli" / "gemini-cli"

    result = validate_gemini_cli_vendor(vendor_root)

    assert result.package_name == "@google/gemini-cli"
    assert result.package_version == "0.29.0"
    assert result.lockfile_version == 3
    assert result.cli_entrypoint == "bundle/gemini.js"
    assert result.entrypoint_path == vendor_root / "bundle" / "gemini.js"


def test_vendor_validation_rejects_package_lock_hash_drift(tmp_path: Path) -> None:
    vendor_root = _write_vendor_tree(tmp_path)
    package_lock_path = vendor_root / "package-lock.json"
    package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
    package_lock["packages"][""]["dependencies"]["dep-a"] = "^2.0.0"
    _write_json(package_lock_path, package_lock)

    with pytest.raises(GeminiCliVendorError) as exc_info:
        validate_gemini_cli_vendor(vendor_root)

    message = str(exc_info.value)
    assert "Gemini CLI vendor validation failed" in message
    assert "package-lock.json sha256 mismatch" in message


def test_vendor_validation_rejects_package_json_lock_dependency_drift(tmp_path: Path) -> None:
    vendor_root = _write_vendor_tree(
        tmp_path,
        package_dependency="^1.0.0",
        lock_dependency="^2.0.0",
    )

    with pytest.raises(GeminiCliVendorError) as exc_info:
        validate_gemini_cli_vendor(vendor_root)

    message = str(exc_info.value)
    assert "package-lock.json root package dependencies does not match package.json" in message


def test_vendor_validation_rejects_cli_entrypoint_hash_drift(tmp_path: Path) -> None:
    vendor_root = _write_vendor_tree(tmp_path)
    entrypoint_path = vendor_root / "bundle" / "gemini.js"
    entrypoint_path.write_text("#!/usr/bin/env node\nconsole.log('drift');\n", encoding="utf-8")

    with pytest.raises(GeminiCliVendorError) as exc_info:
        validate_gemini_cli_vendor(vendor_root)

    message = str(exc_info.value)
    assert "bundle/gemini.js sha256 mismatch" in message


def test_cli_agent_blocks_runtime_if_vendor_changes_after_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vendor_root = _write_vendor_tree(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    from agents.cua_cli.agent import CLIAgent

    agent = CLIAgent(gemini_cli_path=str(vendor_root))
    package_lock_path = vendor_root / "package-lock.json"
    package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
    package_lock["packages"][""]["dependencies"]["dep-a"] = "^2.0.0"
    _write_json(package_lock_path, package_lock)

    subprocess_started = False

    async def _forbid_runtime_start(*args: Any, **kwargs: Any) -> None:
        nonlocal subprocess_started
        subprocess_started = True
        raise AssertionError("Gemini CLI runtime should not start with an invalid vendor tree")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _forbid_runtime_start)

    result = asyncio.run(agent.execute("summarize the current directory", timeout=1))

    assert result["success"] is False
    assert "Gemini CLI vendor validation failed" in str(result["error"])
    assert "package-lock.json sha256 mismatch" in str(result["error"])
    assert subprocess_started is False


def test_cli_agent_keeps_runtime_home_outside_vendor_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vendor_root = _write_vendor_tree(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    from agents.cua_cli.agent import CLIAgent

    agent = CLIAgent(gemini_cli_path=str(vendor_root))

    runtime_home = Path(agent._gemini_cli_home).resolve()
    resolved_vendor = vendor_root.resolve()
    assert resolved_vendor not in [runtime_home, *runtime_home.parents]
