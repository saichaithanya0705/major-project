"""
Hard policy for JARVIS screen annotation tool calls.

JARVIS may explain and annotate the screen. It must not impersonate trusted
system UI or smuggle policy decisions through model-provided tool arguments.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping


MAX_JARVIS_TOOL_CALLS = 12
MAX_JARVIS_TIMELINE_SECONDS = 8.0
MAX_JARVIS_TEXT_CHARS = 1000
MODEL_CONTROLLED_ARGS = {
    "direct_response": {"source"},
}
SPOOFING_TEXT_MARKERS = (
    "system security warning",
    "security warning:",
    "paste your password",
    "enter your password",
    "share your password",
    "paste your api key",
    "enter your api key",
    "share your api key",
    "paste your token",
    "enter your token",
    "disable antivirus",
)


def _function_name(function_call) -> str:
    return str(getattr(function_call, "name", "") or "").strip()


def _function_args(function_call) -> dict:
    args = getattr(function_call, "args", None)
    return dict(args or {}) if isinstance(args, Mapping) else {}


def _contains_spoofing_text(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(marker in normalized for marker in SPOOFING_TEXT_MARKERS)


def _sanitize_args(tool_name: str, args: dict, tool_map: Mapping[str, object]) -> dict:
    tool = tool_map.get(tool_name)
    if tool is None:
        raise ValueError(f"Unknown JARVIS tool: {tool_name}")

    blocked_args = MODEL_CONTROLLED_ARGS.get(tool_name, set())
    signature = inspect.signature(tool)
    parameters = signature.parameters
    accepts_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    allowed = set(parameters.keys())
    sanitized = {}
    for key, value in args.items():
        if key in blocked_args:
            continue
        if accepts_var_keyword or key in allowed:
            sanitized[key] = value

    raw_text = sanitized.get("text", args.get("text"))
    if raw_text is not None:
        text = str(raw_text or "")
        if len(text) > MAX_JARVIS_TEXT_CHARS:
            raise ValueError(
                f"JARVIS text is too long; maximum is {MAX_JARVIS_TEXT_CHARS} characters."
            )
        if _contains_spoofing_text(text):
            raise ValueError("JARVIS overlay text was blocked as a possible UI spoof.")
        if "text" in sanitized:
            sanitized["text"] = text

    if "time" in sanitized:
        try:
            time_s = float(sanitized["time"])
        except (TypeError, ValueError):
            raise ValueError("JARVIS action time must be a number.") from None
        if time_s < 0:
            raise ValueError("JARVIS action time cannot be negative.")
        if time_s > MAX_JARVIS_TIMELINE_SECONDS:
            raise ValueError(
                f"JARVIS action time exceeds {MAX_JARVIS_TIMELINE_SECONDS:.1f}s."
            )
        sanitized["time"] = time_s

    return sanitized


def validate_jarvis_function_calls(function_calls: list, tool_map: Mapping[str, object]) -> list[tuple[str, dict]]:
    if len(function_calls) > MAX_JARVIS_TOOL_CALLS:
        raise ValueError(f"JARVIS returned too many tool calls; maximum is {MAX_JARVIS_TOOL_CALLS}.")

    direct_response_indexes = [
        index
        for index, function_call in enumerate(function_calls)
        if _function_name(function_call) == "direct_response"
    ]
    if direct_response_indexes and direct_response_indexes[0] != 0:
        raise ValueError("direct_response must be the first JARVIS tool call.")

    validated = []
    for function_call in function_calls:
        tool_name = _function_name(function_call)
        args = _function_args(function_call)
        validated.append((tool_name, _sanitize_args(tool_name, args, tool_map)))
    return validated
