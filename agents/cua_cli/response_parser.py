"""
CLI output parsing helpers for CLIAgent.
"""

from __future__ import annotations

import json
from typing import Any


def parse_stream_json_response(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    """Parse stream-json format output (newline-delimited JSON events)."""
    output_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    error: str | dict[str, Any] | None = None

    for line in stdout.strip().split("\n"):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line, might be debug output.
            continue

        event_type = event.get("type")

        if event_type == "message" and event.get("role") == "assistant":
            content = event.get("content", "")
            if content:
                output_parts.append(content)

        elif event_type == "tool_use":
            tool_calls.append(
                {
                    "tool_name": event.get("tool_name"),
                    "tool_id": event.get("tool_id"),
                    "parameters": event.get("parameters"),
                }
            )

        elif event_type == "tool_result":
            tool_id = event.get("tool_id")
            for tc in tool_calls:
                if tc.get("tool_id") == tool_id:
                    tc["result"] = event.get("output")
                    tc["status"] = event.get("status")
                    tc["error"] = event.get("error")

        elif event_type == "error":
            error = event.get("message", "Unknown error")

        elif event_type == "result":
            # Final result event.
            if event.get("status") != "success":
                error = event.get("error", "Task failed")

    output = "".join(output_parts)
    return {
        "success": returncode == 0 and error is None,
        "output": output,
        "error": error or (stderr if returncode != 0 else None),
        "tool_calls": tool_calls if tool_calls else None,
    }


def parse_json_response(
    *,
    stdout: str,
    stderr: str,
    returncode: int,
) -> dict[str, Any]:
    """Parse single JSON output format."""
    try:
        data = json.loads(stdout)
        return {
            "success": returncode == 0,
            "output": data.get("response", stdout),
            "error": data.get("error"),
            "tool_calls": None,
        }
    except json.JSONDecodeError:
        return {
            "success": returncode == 0,
            "output": stdout,
            "error": stderr if returncode != 0 else None,
            "tool_calls": None,
        }
