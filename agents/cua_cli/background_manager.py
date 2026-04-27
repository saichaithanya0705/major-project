"""
Background and process lifecycle helpers for CLIAgent.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from typing import Any, Awaitable, Callable


def register_foreground_process(
    *,
    store: dict[str, dict[str, Any]],
    session_id: str,
    process: asyncio.subprocess.Process,
    task: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "id": session_id,
        "pid": process.pid,
        "pgid": None,
        "task": task,
        "started_at": time.time(),
    }
    if os.name != "nt":
        try:
            metadata["pgid"] = os.getpgid(process.pid)
        except Exception:
            metadata["pgid"] = process.pid

    store[session_id] = metadata
    return metadata


def unregister_foreground_process(
    *,
    store: dict[str, dict[str, Any]],
    session_id: str,
) -> None:
    store.pop(session_id, None)


async def is_local_port_open(port: int, timeout_seconds: float = 0.6) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=timeout_seconds,
        )
        del reader
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def wait_for_any_port(
    *,
    ports: list[int],
    timeout_seconds: float = 8.0,
    port_check: Callable[[int], Awaitable[bool]] | None = None,
) -> int | None:
    if not ports:
        return None
    check = port_check or is_local_port_open
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for port in ports:
            if await check(port):
                return port
        await asyncio.sleep(0.35)
    return None


def resolve_background_shell() -> tuple[list[str], dict[str, Any]]:
    if os.name == "nt":
        shell_path = (
            shutil.which("pwsh")
            or shutil.which("powershell")
            or os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe",
            )
        )
        creationflags = 0
        for flag_name in (
            "CREATE_NEW_PROCESS_GROUP",
            "DETACHED_PROCESS",
            "CREATE_NO_WINDOW",
        ):
            creationflags |= int(getattr(subprocess, flag_name, 0))
        return (
            [
                shell_path,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
            ],
            {"creationflags": creationflags},
        )

    shell_path = shutil.which("zsh") or shutil.which("bash") or shutil.which("sh")
    if not shell_path:
        raise RuntimeError("No supported POSIX shell found for background execution.")
    return ([shell_path, "-lc"], {"start_new_session": True})


def terminate_process_tree_sync(metadata: dict[str, Any]) -> None:
    pid = int(metadata.get("pid") or 0)
    pgid = int(metadata.get("pgid") or 0)

    if os.name == "nt":
        if pid <= 0:
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass
        return

    try:
        if pgid > 0:
            os.killpg(pgid, signal.SIGTERM)
        elif pid > 0:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


async def start_background_process(
    *,
    managed_store: dict[str, dict[str, Any]],
    command: str,
    env: dict[str, str],
    working_dir: str,
    task: str,
    extract_port_candidates: Callable[[str], list[int]],
    wait_for_port: Callable[..., Awaitable[int | None]] | None = None,
) -> dict[str, Any]:
    process_id = uuid.uuid4().hex[:8]
    log_path = os.path.join(tempfile.gettempdir(), f"jarvis_cli_bg_{process_id}.log")
    shell_args, spawn_kwargs = resolve_background_shell()
    with open(log_path, "ab") as log_file:
        process = await asyncio.create_subprocess_exec(
            *shell_args,
            command,
            cwd=working_dir,
            env=env,
            stdout=log_file,
            stderr=log_file,
            **spawn_kwargs,
        )

    pid = process.pid
    pgid: int | None
    if os.name == "nt":
        pgid = None
    else:
        try:
            pgid = os.getpgid(pid)
        except Exception:
            pgid = pid

    metadata: dict[str, Any] = {
        "id": process_id,
        "pid": pid,
        "pgid": pgid,
        "command": command,
        "cwd": working_dir,
        "log_path": log_path,
        "started_at": time.time(),
        "task": task,
    }

    ports = extract_port_candidates(task + "\n" + command)
    if ports:
        metadata["ports"] = ports
        waiter = wait_for_port or wait_for_any_port
        opened = await waiter(ports=ports, timeout_seconds=20.0)
        if opened is not None:
            metadata["active_port"] = opened
        else:
            metadata["health_warning"] = (
                f"Started process {pid}, but no expected port became reachable: {ports}"
            )

    managed_store[process_id] = metadata

    summary_parts = [
        f"Started background process {process_id}",
        f"(pid {pid})",
        f"command: {command}",
        f"log: {log_path}",
    ]
    if metadata.get("active_port"):
        summary_parts.append(f"verified on http://127.0.0.1:{metadata['active_port']}")
    elif metadata.get("ports"):
        summary_parts.append(f"expected ports: {metadata['ports']}")
        summary_parts.append("health-check did not confirm readiness yet")

    return {
        "success": True,
        "result": " | ".join(summary_parts),
        "error": None,
        "tool_calls": [
            {
                "tool_name": "background_process_manager",
                "tool_id": process_id,
                "parameters": {
                    "command": command,
                    "pid": pid,
                    "log_path": log_path,
                },
            }
        ],
    }


def cleanup_background_processes_sync(
    *,
    managed_store: dict[str, dict[str, Any]],
) -> None:
    for proc_id in list(managed_store.keys()):
        meta = managed_store.get(proc_id) or {}
        terminate_process_tree_sync(meta)
        managed_store.pop(proc_id, None)


async def stop_background_process(
    *,
    managed_store: dict[str, dict[str, Any]],
    process_id: str,
) -> bool:
    meta = managed_store.get(process_id)
    if not meta:
        return False
    terminate_process_tree_sync(meta)
    managed_store.pop(process_id, None)
    return True


async def stop_all_background_processes(
    *,
    managed_store: dict[str, dict[str, Any]],
) -> int:
    ids = list(managed_store.keys())
    stopped = 0
    for proc_id in ids:
        if await stop_background_process(managed_store=managed_store, process_id=proc_id):
            stopped += 1
    return stopped


def list_background_processes(
    *,
    managed_store: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = time.time()
    for proc_id, meta in managed_store.items():
        row = {
            "id": proc_id,
            "pid": meta.get("pid"),
            "command": meta.get("command"),
            "log_path": meta.get("log_path"),
            "uptime_seconds": int(max(0, now - float(meta.get("started_at", now)))),
        }
        if meta.get("active_port"):
            row["active_port"] = meta["active_port"]
        rows.append(row)
    return rows
