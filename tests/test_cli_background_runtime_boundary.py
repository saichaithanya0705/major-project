"""
Checks for extracted CLI background runtime helpers.

Usage:
    python tests/test_cli_background_runtime_boundary.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_cli.background_manager import (
    list_background_processes,
    register_foreground_process,
    resolve_background_shell,
    stop_all_background_processes,
    stop_background_process,
    unregister_foreground_process,
    wait_for_any_port,
)


async def run_checks() -> None:
    foreground_store: dict[str, dict] = {}
    process = SimpleNamespace(pid=12345)
    metadata = register_foreground_process(
        store=foreground_store,
        session_id="sess1",
        process=process,
        task="echo hello",
    )
    assert metadata["id"] == "sess1", metadata
    assert metadata["pid"] == 12345, metadata
    assert "sess1" in foreground_store, foreground_store

    unregister_foreground_process(store=foreground_store, session_id="sess1")
    assert "sess1" not in foreground_store, foreground_store

    async def _fake_port_check(port: int) -> bool:
        return port == 31337

    opened = await wait_for_any_port(
        ports=[1111, 31337, 4444],
        timeout_seconds=0.2,
        port_check=_fake_port_check,
    )
    assert opened == 31337, opened

    managed_store = {
        "p1": {
            "pid": 0,
            "command": "npm run dev",
            "log_path": "/tmp/fake.log",
            "started_at": 1.0,
            "active_port": 3000,
        }
    }
    rows = list_background_processes(managed_store=managed_store)
    assert len(rows) == 1, rows
    assert rows[0]["id"] == "p1", rows
    assert rows[0]["active_port"] == 3000, rows

    stopped = await stop_background_process(managed_store=managed_store, process_id="p1")
    assert stopped is True, managed_store
    assert managed_store == {}, managed_store

    managed_store = {
        "p2": {"pid": 0, "started_at": 1.0},
        "p3": {"pid": 0, "started_at": 1.0},
    }
    count = await stop_all_background_processes(managed_store=managed_store)
    assert count == 2, count
    assert managed_store == {}, managed_store

    shell_args, spawn_kwargs = resolve_background_shell()
    assert isinstance(shell_args, list) and shell_args, shell_args
    assert isinstance(spawn_kwargs, dict), spawn_kwargs


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("[test_cli_background_runtime_boundary] All checks passed.")
