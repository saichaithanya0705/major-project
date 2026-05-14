"""
Parsing helpers for file artifacts created by delegated tools.

This module owns the small shared contract between tool execution and session
memory: only successful output-file operations should become follow-up context.
"""

from __future__ import annotations

import re

WINDOWS_PATH_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n`]+\\)*[^\\/:*?\"<>|\r\n`]+"
)
PATH_STRIP_CHARS = " \t\r\n`'\".,;:)]}"
OUTPUT_FILE_TOOL_NAMES = {
    "edit",
    "edit_file",
    "replace",
    "write_file",
}
FILE_PATH_PARAMETER_KEYS = ("file_path", "path", "absolute_path", "target_path")
FILE_STATUS_MARKERS = (
    "written to",
    "saved to",
    "created at",
    "created in",
    "has been written",
    "has been saved",
    "file has been",
)


def extract_path_from_text(text: object) -> str:
    match = WINDOWS_PATH_RE.search(str(text or ""))
    if not match:
        return ""
    return match.group(0).strip(PATH_STRIP_CHARS)


def looks_like_file_status(text: object) -> bool:
    value = str(text or "")
    lowered = " ".join(value.lower().split())
    if not lowered:
        return False
    if not any(marker in lowered for marker in FILE_STATUS_MARKERS):
        return False
    if extract_path_from_text(value):
        return True
    return "desktop" in lowered and bool(re.search(r"\.[a-z0-9]{1,12}\b", lowered))


def extract_output_file_path_from_tool_calls(tool_calls: object) -> str:
    if not isinstance(tool_calls, list):
        return ""

    for tool_call in reversed(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        tool_name = str(tool_call.get("tool_name") or "").strip().lower()
        if tool_name not in OUTPUT_FILE_TOOL_NAMES:
            continue
        status = str(tool_call.get("status") or "").strip().lower()
        if status and status != "success":
            continue
        parameters = tool_call.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in FILE_PATH_PARAMETER_KEYS:
            path = extract_path_from_text(parameters.get(key))
            if path:
                return path
    return ""
