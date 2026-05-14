"""
Normalize model/operator CUA actions into typed computer-use contracts.

The model-facing tool names are allowed to be messy and provider-specific. This
module is the narrow intake boundary that repairs known aliases, validates
arguments through the existing action policy, and returns a `ComputerAction`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from agents.cua_vision.action_policy import (
    MAX_TARGET_DESCRIPTION_CHARS,
    normalize_click_type,
    normalize_hotkey_keys,
    normalize_key,
    validate_bbox_args,
    validate_held_key,
    validate_hotkey,
    validate_key_hold_args,
    validate_text,
    validate_vision_tool_call,
)
from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef


class ActionNormalizationError(ValueError):
    """Raised when a proposed CUA action cannot be safely normalized."""


CLICK_TYPE_TO_ACTION = {
    "left click": ActionType.CLICK,
    "double left click": ActionType.DOUBLE_CLICK,
    "right click": ActionType.RIGHT_CLICK,
}

NAME_ALIASES = {
    "click_left_click": "left_click",
    "click_target": "click",
    "left_click": "left_click",
    "left-click": "left_click",
    "click": "click",
    "click_double_left_click": "double_click",
    "double_click": "double_click",
    "double-click": "double_click",
    "click_right_click": "right_click",
    "right_click": "right_click",
    "right-click": "right_click",
    "go_to_element": "move",
    "move_cursor": "move",
    "mouse_move": "move",
    "move": "move",
    "crop_and_search": "move",
    "type_string": "type_text",
    "type": "type_text",
    "type_text": "type_text",
    "input_text": "type_text",
    "write": "type_text",
    "press_ctrl_hotkey": "ctrl_hotkey",
    "press_alt_hotkey": "alt_hotkey",
    "hotkey": "hotkey",
    "keypress": "keypress",
    "key_press": "keypress",
    "press_key": "keypress",
    "press": "keypress",
    "key": "keypress",
    "press_key_for_duration": "key_for_duration",
    "hold_down_key": "hold_key",
    "release_held_key": "release_key",
    "scroll": "scroll",
    "mouse_scroll": "scroll",
    "wait": "wait",
    "sleep": "wait",
    "task_is_complete": "complete",
    "tts_speak": "complete",
    "complete": "complete",
    "abort": "abort",
    "stop": "abort",
}


def normalize_action_payload(
    payload: Mapping[str, Any] | object,
    *,
    active_window: str | None = None,
) -> ComputerAction:
    """Normalize a dict-like or SDK-like action/function-call payload."""
    if isinstance(payload, Mapping):
        if isinstance(payload.get("action"), Mapping):
            action_payload = payload["action"]
            name = action_payload.get("type") or action_payload.get("name")
            args = {key: value for key, value in action_payload.items() if key not in {"type", "name"}}
            return normalize_action_call(str(name or ""), args, active_window=active_window)

        name = payload.get("name") or payload.get("type") or payload.get("action_type")
        args = payload.get("arguments", payload.get("args", payload))
        if isinstance(args, Mapping):
            args = {key: value for key, value in args.items() if key not in {"name", "type", "action_type"}}
        return normalize_action_call(str(name or ""), args, active_window=active_window)

    name = getattr(payload, "name", None) or getattr(payload, "type", None)
    args = getattr(payload, "args", None) or getattr(payload, "arguments", None) or {}
    return normalize_action_call(str(name or ""), args, active_window=active_window)


def normalize_action_call(
    tool_name: str,
    args: Mapping[str, Any] | None = None,
    *,
    active_window: str | None = None,
) -> ComputerAction:
    """Return a validated `ComputerAction` for a model/tool action proposal."""
    raw_name = str(tool_name or "").strip()
    if not raw_name:
        raise ActionNormalizationError("Action name is required.")

    raw_args = _coerce_args(args)
    normalized_name = NAME_ALIASES.get(raw_name.strip().lower().replace(" ", "_"), raw_name)

    try:
        return _normalize_known_action(
            normalized_name,
            raw_name=raw_name,
            raw_args=raw_args,
            active_window=active_window,
        )
    except ActionNormalizationError:
        raise
    except ValueError as exc:
        raise ActionNormalizationError(str(exc)) from None


def _normalize_known_action(
    normalized_name: str,
    *,
    raw_name: str,
    raw_args: dict[str, Any],
    active_window: str | None,
) -> ComputerAction:
    if normalized_name == "computer_call":
        action = raw_args.get("action")
        if not isinstance(action, Mapping):
            raise ActionNormalizationError("computer_call requires an action object.")
        return normalize_action_payload(action, active_window=active_window)

    if normalized_name == "computer_call_output":
        raise ActionNormalizationError("computer_call_output is an observation, not an executable action.")

    if normalized_name in {"left_click", "right_click", "double_click", "click"}:
        return _normalize_click(normalized_name, raw_name, raw_args, active_window)

    if normalized_name == "move":
        return _normalize_move(raw_name, raw_args)

    if normalized_name == "type_text":
        return _normalize_type_text(raw_name, raw_args, active_window)

    if normalized_name in {"ctrl_hotkey", "alt_hotkey", "hotkey"}:
        return _normalize_hotkey(normalized_name, raw_name, raw_args, active_window)

    if normalized_name in {"keypress", "key_for_duration", "hold_key", "release_key"}:
        return _normalize_keypress(normalized_name, raw_name, raw_args)

    if normalized_name == "scroll":
        return _normalize_scroll(raw_name, raw_args)

    if normalized_name == "wait":
        return _normalize_wait(raw_name, raw_args)

    if normalized_name == "complete":
        sanitized = validate_vision_tool_call(
            "task_is_complete",
            {"text": _first_present(raw_args, "text", "message", "status_text") or ""},
            active_window=active_window,
        )
        return ComputerAction(
            action_type=ActionType.COMPLETE,
            text=sanitized.get("text") or "",
            raw_name=raw_name,
            raw_args=sanitized,
        )

    if normalized_name == "abort":
        return ComputerAction(
            action_type=ActionType.ABORT,
            text=str(_first_present(raw_args, "text", "message", "reason") or ""),
            raw_name=raw_name,
            raw_args=dict(raw_args),
        )

    raise ActionNormalizationError(f"Unsupported CUA action: {raw_name}")


def _normalize_click(
    normalized_name: str,
    raw_name: str,
    raw_args: dict[str, Any],
    active_window: str | None,
) -> ComputerAction:
    if raw_name == "click_target":
        sanitized = validate_vision_tool_call(
            "click_target",
            raw_args,
            active_window=active_window,
        )
        target = _target_from_args(sanitized)
        click_type = sanitized["type_of_click"]
        return ComputerAction(
            action_type=CLICK_TYPE_TO_ACTION[click_type],
            target=target,
            raw_name=raw_name,
            raw_args=sanitized,
        )

    click_type = {
        "left_click": "left click",
        "double_click": "double left click",
        "right_click": "right click",
    }.get(normalized_name)
    if click_type is None:
        click_type = normalize_click_type(
            _first_present(raw_args, "type_of_click", "button", "click_type") or "left click"
        )

    target = _target_from_args(raw_args)
    return ComputerAction(
        action_type=CLICK_TYPE_TO_ACTION[click_type],
        target=target,
        raw_name=raw_name,
        raw_args=dict(raw_args),
    )


def _normalize_move(raw_name: str, raw_args: dict[str, Any]) -> ComputerAction:
    if raw_name in {"go_to_element", "crop_and_search"}:
        bbox = validate_bbox_args(raw_args)
        description = _description_from_args(raw_args)
        target = TargetRef(
            TargetKind.BBOX,
            bbox=(bbox["ymin"], bbox["xmin"], bbox["ymax"], bbox["xmax"]),
            description=description,
        )
    else:
        target = _target_from_args(raw_args)
        if target.kind == TargetKind.NONE:
            raise ActionNormalizationError("Move actions require coordinates, bbox, element_id, or description.")

    return ComputerAction(
        action_type=ActionType.MOVE,
        target=target,
        raw_name=raw_name,
        raw_args=dict(raw_args),
    )


def _normalize_type_text(
    raw_name: str,
    raw_args: dict[str, Any],
    active_window: str | None,
) -> ComputerAction:
    text = _first_present(raw_args, "string", "text", "value", "input")
    sanitized = validate_vision_tool_call(
        "type_string",
        {"string": text or "", "submit": bool(raw_args.get("submit", False))},
        active_window=active_window,
    )
    return ComputerAction(
        action_type=ActionType.TYPE_TEXT,
        text=sanitized["string"],
        raw_name=raw_name,
        raw_args=sanitized,
    )


def _normalize_hotkey(
    normalized_name: str,
    raw_name: str,
    raw_args: dict[str, Any],
    active_window: str | None,
) -> ComputerAction:
    if normalized_name == "ctrl_hotkey":
        sanitized = validate_vision_tool_call(
            "press_ctrl_hotkey",
            {"key": raw_args.get("key")},
            active_window=active_window,
        )
        keys = ("ctrl", sanitized["key"])
    elif normalized_name == "alt_hotkey":
        sanitized = validate_vision_tool_call(
            "press_alt_hotkey",
            {"key": raw_args.get("key")},
            active_window=active_window,
        )
        keys = ("alt", sanitized["key"])
    else:
        keys = normalize_hotkey_keys(_first_present(raw_args, "keys", "key", "hotkey"))
        _validate_sensitive_hotkey_alias(keys, active_window)
        sanitized = {"keys": keys}

    return ComputerAction(
        action_type=ActionType.HOTKEY,
        keys=tuple(keys),
        raw_name=raw_name,
        raw_args=sanitized,
    )


def _normalize_keypress(
    normalized_name: str,
    raw_name: str,
    raw_args: dict[str, Any],
) -> ComputerAction:
    if normalized_name == "key_for_duration":
        key, seconds = validate_key_hold_args(
            raw_args.get("key"),
            _first_present(raw_args, "seconds", "duration", "duration_seconds"),
        )
        return ComputerAction(
            action_type=ActionType.KEYPRESS,
            keys=(key,),
            duration_seconds=seconds,
            raw_name=raw_name,
            raw_args={"key": key, "seconds": seconds},
        )

    if normalized_name in {"hold_key", "release_key"}:
        key = validate_held_key(raw_args.get("key"))
    else:
        keys = _first_present(raw_args, "keys", "key")
        if isinstance(keys, (list, tuple)):
            if len(keys) != 1:
                raise ActionNormalizationError("keypress requires exactly one key.")
            key = keys[0]
        else:
            key = keys
        key = normalize_key(key)

    return ComputerAction(
        action_type=ActionType.KEYPRESS,
        keys=(key,),
        raw_name=raw_name,
        raw_args={"key": key},
    )


def _normalize_scroll(raw_name: str, raw_args: dict[str, Any]) -> ComputerAction:
    delta = _first_present(
        raw_args,
        "scroll_delta",
        "delta_y",
        "dy",
        "scroll_y",
        "amount",
    )
    direction = str(raw_args.get("direction", "")).strip().lower()
    if delta is None and direction:
        delta = 1 if direction in {"up", "backward"} else -1
    if delta is None:
        raise ActionNormalizationError("Scroll actions require scroll_delta, delta_y, amount, or direction.")

    scroll_delta = _finite_int(delta, "scroll_delta")
    return ComputerAction(
        action_type=ActionType.SCROLL,
        target=_target_from_args(raw_args),
        scroll_delta=scroll_delta,
        raw_name=raw_name,
        raw_args=dict(raw_args),
    )


def _normalize_wait(raw_name: str, raw_args: dict[str, Any]) -> ComputerAction:
    seconds = _first_present(raw_args, "seconds", "duration", "duration_seconds", "time")
    if seconds is None:
        seconds = 1.0
    duration = _finite_float(seconds, "duration")
    if duration < 0.0 or duration > 60.0:
        raise ActionNormalizationError("Wait duration must be between 0 and 60 seconds.")
    return ComputerAction(
        action_type=ActionType.WAIT,
        duration_seconds=duration,
        raw_name=raw_name,
        raw_args={"seconds": duration},
    )


def _target_from_args(args: Mapping[str, Any]) -> TargetRef:
    element_id = _first_present(args, "element_id", "element")
    if element_id:
        return TargetRef(TargetKind.ELEMENT_ID, element_id=str(element_id))

    if all(field in args for field in ("ymin", "xmin", "ymax", "xmax")):
        bbox = validate_bbox_args(args)
        return TargetRef(
            TargetKind.BBOX,
            bbox=(bbox["ymin"], bbox["xmin"], bbox["ymax"], bbox["xmax"]),
            description=_description_from_args(args),
        )

    coordinate = _coordinate_from_args(args)
    if coordinate is not None:
        return TargetRef(TargetKind.COORDINATE, x=coordinate[0], y=coordinate[1])

    description = _description_from_args(args)
    if description:
        return TargetRef(TargetKind.DESCRIPTION, description=description)

    return TargetRef(TargetKind.NONE)


def _coordinate_from_args(args: Mapping[str, Any]) -> tuple[float, float] | None:
    value = _first_present(args, "coordinate", "coordinates", "point", "position")
    if value is not None:
        if isinstance(value, Mapping):
            x_value = value.get("x")
            y_value = value.get("y")
        elif _is_non_string_sequence(value) and len(value) >= 2:
            x_value = value[0]
            y_value = value[1]
        else:
            raise ActionNormalizationError("Coordinate must be [x, y] or {'x': x, 'y': y}.")
        return (_finite_float(x_value, "x"), _finite_float(y_value, "y"))

    if "x" in args and "y" in args:
        return (_finite_float(args["x"], "x"), _finite_float(args["y"], "y"))

    return None


def _description_from_args(args: Mapping[str, Any]) -> str | None:
    value = _first_present(args, "target_description", "element_description", "description")
    if value is None:
        return None
    description = validate_text(
        value,
        max_chars=MAX_TARGET_DESCRIPTION_CHARS,
        field_name="Target description",
    ).strip()
    return description or None


def _validate_sensitive_hotkey_alias(keys: tuple[str, ...], active_window: str | None) -> None:
    key_set = set(keys)
    non_modifiers = [key for key in keys if key not in {"ctrl", "alt", "shift", "win"}]
    if not non_modifiers:
        raise ActionNormalizationError("Hotkey must include a non-modifier key.")
    primary_key = non_modifiers[0]
    if "ctrl" in key_set:
        validate_vision_tool_call(
            "press_ctrl_hotkey",
            {"key": primary_key},
            active_window=active_window,
        )
    if "alt" in key_set:
        validate_vision_tool_call(
            "press_alt_hotkey",
            {"key": primary_key},
            active_window=active_window,
        )


def _coerce_args(args: Mapping[str, Any] | None) -> dict[str, Any]:
    if args is None:
        return {}
    if not isinstance(args, Mapping):
        raise ActionNormalizationError("Action arguments must be an object.")
    return dict(args)


def _first_present(args: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in args and args[key] is not None:
            return args[key]
    return None


def _finite_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ActionNormalizationError(f"{field_name} must be a number.") from None
    if not math.isfinite(result):
        raise ActionNormalizationError(f"{field_name} must be finite.")
    return result


def _finite_int(value: Any, field_name: str) -> int:
    result = _finite_float(value, field_name)
    return int(round(result))


def _is_non_string_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
