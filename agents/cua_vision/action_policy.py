"""
Security policy for CUA Vision desktop actions.

The model can propose tool calls, but this module is the code-level boundary
that decides whether those calls are safe enough to execute.
"""

from __future__ import annotations

import os
import math
from typing import Mapping


MAX_TYPED_TEXT_CHARS = 4000
MAX_REMEMBER_TEXT_CHARS = 2000
MAX_TTS_TEXT_CHARS = 800
MAX_TARGET_DESCRIPTION_CHARS = 240
MAX_KEY_HOLD_SECONDS = 2.0
MAX_HOTKEY_PARTS = 4
VISION_BBOX_FIELDS = ("ymin", "xmin", "ymax", "xmax")
ALLOWED_CLICK_TYPES = {"left click", "double left click", "right click"}
ALLOWED_HELD_KEYS = {"w", "a", "s", "d"}
MODIFIER_KEY_ALIASES = {
    "control": "ctrl",
    "cmd": "win",
    "command": "win",
    "windows": "win",
    "option": "alt",
}
MODIFIER_KEYS = {"ctrl", "alt", "shift", "win"}
BLOCKED_CTRL_HOTKEYS = {
    "backspace",
    "delete",
    "enter",
    "esc",
    "escape",
    "f4",
    "q",
    "r",
    "tab",
    "w",
}
BLOCKED_ALT_HOTKEYS = {"enter", "esc", "escape", "f4", "tab"}
SENSITIVE_WINDOW_MARKERS = (
    "password",
    "credential",
    "secret",
    "api key",
    "token",
    "payment",
    "checkout",
    "bank",
    "admin",
)
SENSITIVE_INPUT_TOOLS = {
    "type_string",
    "press_ctrl_hotkey",
    "press_alt_hotkey",
    "press_key_for_duration",
    "hold_down_key",
}


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_key(key: object) -> str:
    value = str(key or "").strip().lower()
    if not value:
        raise ValueError("Key value is required.")
    if len(value) > 24:
        raise ValueError("Key value is too long.")
    return value


def validate_text(value: object, *, max_chars: int, field_name: str) -> str:
    text = str(value or "")
    if len(text) > max_chars:
        raise ValueError(f"{field_name} is too long; maximum is {max_chars} characters.")
    return text


def validate_key_hold_args(key: object, seconds: object) -> tuple[str, float]:
    normalized_key = normalize_key(key)
    if normalized_key not in ALLOWED_HELD_KEYS:
        allowed = ", ".join(sorted(ALLOWED_HELD_KEYS))
        raise ValueError(f"Key '{normalized_key}' is not allowed for timed key-hold actions. Allowed: {allowed}.")
    try:
        duration = float(seconds)
    except (TypeError, ValueError):
        raise ValueError("Key hold duration must be a number.") from None
    if duration < 0:
        raise ValueError("Key hold duration cannot be negative.")
    if duration > MAX_KEY_HOLD_SECONDS:
        raise ValueError(
            f"Key hold duration is too long; maximum is {MAX_KEY_HOLD_SECONDS:.1f}s."
        )
    return normalized_key, duration


def validate_held_key(key: object) -> str:
    normalized_key = normalize_key(key)
    if normalized_key not in ALLOWED_HELD_KEYS:
        allowed = ", ".join(sorted(ALLOWED_HELD_KEYS))
        raise ValueError(f"Key '{normalized_key}' is not allowed for held-key actions. Allowed: {allowed}.")
    return normalized_key


def validate_hotkey(tool_name: str, key: object) -> str:
    normalized_key = normalize_key(key)
    blocked = BLOCKED_CTRL_HOTKEYS if tool_name == "press_ctrl_hotkey" else BLOCKED_ALT_HOTKEYS
    if normalized_key in blocked and not _truthy_env("CUA_VISION_ALLOW_DANGEROUS_HOTKEYS"):
        raise ValueError(f"{tool_name}({normalized_key}) is blocked by the CUA Vision action policy.")
    return normalized_key


def normalize_hotkey_keys(keys: object) -> tuple[str, ...]:
    """
    Validate a generic hotkey sequence while preserving existing ctrl/alt policy.

    Generic computer-use providers often emit hotkeys as ["ctrl", "l"] or
    "ctrl+l". Keep that normalization in the policy boundary so callers do not
    reimplement blocked-key checks.
    """
    if isinstance(keys, str):
        raw_parts = [part.strip() for part in keys.replace(",", "+").split("+")]
    elif isinstance(keys, (list, tuple)):
        raw_parts = [str(part).strip() for part in keys]
    else:
        raise ValueError("Hotkey keys must be a string or list.")

    normalized = tuple(
        MODIFIER_KEY_ALIASES.get(part.lower(), part.lower())
        for part in raw_parts
        if part
    )
    if not normalized:
        raise ValueError("Hotkey keys are required.")
    if len(normalized) > MAX_HOTKEY_PARTS:
        raise ValueError(
            f"Hotkey has too many keys; maximum is {MAX_HOTKEY_PARTS}."
        )

    key_set = set(normalized)
    non_modifiers = [key for key in normalized if key not in MODIFIER_KEYS]
    if not non_modifiers:
        raise ValueError("Hotkey must include a non-modifier key.")
    if len(non_modifiers) > 1:
        raise ValueError("Hotkey must include exactly one non-modifier key.")

    primary_key = non_modifiers[0]
    if "ctrl" in key_set:
        validate_hotkey("press_ctrl_hotkey", primary_key)
    if "alt" in key_set:
        validate_hotkey("press_alt_hotkey", primary_key)
    return normalized


def normalize_click_type(value: object) -> str:
    normalized = str(value or "left click").strip().lower().replace("_", " ")
    aliases = {
        "left": "left click",
        "single": "left click",
        "single click": "left click",
        "double": "double left click",
        "double click": "double left click",
        "double-click": "double left click",
        "right": "right click",
        "context": "right click",
        "context click": "right click",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ALLOWED_CLICK_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CLICK_TYPES))
        raise ValueError(f"Unsupported click type '{value}'. Allowed: {allowed}.")
    return normalized


def validate_bbox_args(args: Mapping[str, object]) -> dict[str, float]:
    bbox: dict[str, float] = {}
    for field in VISION_BBOX_FIELDS:
        if field not in args:
            raise ValueError(f"{field} is required for target bounding boxes.")
        try:
            value = float(args[field])
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number.") from None
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite.")
        bbox[field] = value

    if bbox["ymin"] == bbox["ymax"] or bbox["xmin"] == bbox["xmax"]:
        raise ValueError("Target bounding box must have non-zero width and height.")
    return bbox


def _window_looks_sensitive(active_window: str | None) -> bool:
    title = str(active_window or "").lower()
    return any(marker in title for marker in SENSITIVE_WINDOW_MARKERS)


def validate_vision_tool_call(
    tool_name: str,
    args: Mapping[str, object] | None,
    *,
    active_window: str | None = None,
) -> dict:
    """
    Return sanitized tool arguments or raise ValueError if policy blocks the call.
    """
    sanitized = dict(args or {})

    if _window_looks_sensitive(active_window) and tool_name in SENSITIVE_INPUT_TOOLS:
        raise ValueError(
            f"{tool_name} is blocked because the active window looks sensitive: {active_window}"
        )

    if tool_name == "type_string":
        sanitized["string"] = validate_text(
            sanitized.get("string", ""),
            max_chars=MAX_TYPED_TEXT_CHARS,
            field_name="Typed text",
        )
        sanitized["submit"] = bool(sanitized.get("submit", False))
    elif tool_name in {"press_ctrl_hotkey", "press_alt_hotkey"}:
        sanitized["key"] = validate_hotkey(tool_name, sanitized.get("key"))
    elif tool_name == "press_key_for_duration":
        key, seconds = validate_key_hold_args(
            sanitized.get("key"),
            sanitized.get("seconds"),
        )
        sanitized["key"] = key
        sanitized["seconds"] = seconds
    elif tool_name in {"hold_down_key", "release_held_key"}:
        sanitized["key"] = validate_held_key(sanitized.get("key"))
    elif tool_name == "click_target":
        sanitized.update(validate_bbox_args(sanitized))
        sanitized["type_of_click"] = normalize_click_type(
            sanitized.get("type_of_click", "left click")
        )
        sanitized["target_description"] = validate_text(
            sanitized.get("target_description", ""),
            max_chars=MAX_TARGET_DESCRIPTION_CHARS,
            field_name="Target description",
        ).strip()
        if not sanitized["target_description"]:
            raise ValueError("target_description is required for click_target.")
    elif tool_name == "remember_information":
        sanitized["thing_to_remember"] = validate_text(
            sanitized.get("thing_to_remember", ""),
            max_chars=MAX_REMEMBER_TEXT_CHARS,
            field_name="Memory text",
        )
    elif tool_name in {"tts_speak", "task_is_complete"}:
        if "text" in sanitized:
            sanitized["text"] = validate_text(
                sanitized.get("text", ""),
                max_chars=MAX_TTS_TEXT_CHARS,
                field_name="Spoken text",
            )

    return sanitized
