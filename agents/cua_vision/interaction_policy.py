"""
Interaction policy helpers for CUA vision single-call execution.
"""

from __future__ import annotations

from typing import Mapping

STATUS_TARGET_PREFIXES = (
    "searching for ",
    "looking for ",
    "locating ",
    "clicking ",
    "opening ",
    "selecting ",
)


def resolve_target_description(
    *,
    task: str,
    args: Mapping[str, object],
    last_target_description: str | None,
) -> str:
    target = args.get("target_description")
    if isinstance(target, str) and target.strip():
        return target.strip()

    status_text = args.get("status_text")
    if isinstance(status_text, str) and status_text.strip():
        normalized = status_text.strip().rstrip(".")
        lower = normalized.lower()
        for prefix in STATUS_TARGET_PREFIXES:
            if lower.startswith(prefix):
                candidate = normalized[len(prefix):].strip()
                if candidate:
                    return candidate
        return normalized

    if isinstance(last_target_description, str) and last_target_description.strip():
        return last_target_description.strip()

    return f"best target for task: {task}"


def default_status_text(tool_name: str, click_tool_to_type: Mapping[str, str]) -> str:
    if tool_name == "type_string":
        return "Typing..."
    if tool_name in {"press_ctrl_hotkey", "press_alt_hotkey"}:
        return "Using shortcut..."
    if tool_name == "go_to_element":
        return "Positioning cursor to target..."
    if tool_name in click_tool_to_type:
        return "Clicking target..."
    if tool_name == "crop_and_search":
        return "Zooming in for a precision click..."
    if tool_name == "tts_speak":
        return "Preparing response..."
    if tool_name == "task_is_complete":
        return "Task complete"
    return "Working..."


def describe_action_for_feedback(
    *,
    tool_name: str,
    task: str,
    args: Mapping[str, object],
    click_tool_to_type: Mapping[str, str],
    last_target_description: str | None,
) -> str:
    target = resolve_target_description(
        task=task,
        args=args,
        last_target_description=last_target_description,
    )
    if tool_name in click_tool_to_type:
        return f"{click_tool_to_type[tool_name]} on {target}"
    if tool_name == "type_string":
        return "typing into the current field"
    if tool_name in {"press_ctrl_hotkey", "press_alt_hotkey", "press_key_for_duration"}:
        return f"using {tool_name}"
    return f"using {tool_name}"


def build_fallback_context(
    *,
    task: str,
    click_type: str | None,
    args: Mapping[str, object] | None,
    last_click_context: Mapping[str, object] | None,
    last_target_description: str | None,
) -> dict[str, str] | None:
    context: dict[str, object] | None = None
    if click_type and args is not None:
        context = {
            "type_of_click": click_type,
            "target_description": resolve_target_description(
                task=task,
                args=args,
                last_target_description=last_target_description,
            ),
        }
    elif isinstance(last_click_context, Mapping):
        context = dict(last_click_context)

    if not context:
        return None

    target = context.get("target_description")
    resolved_click_type = context.get("type_of_click")
    if not isinstance(target, str) or not target.strip():
        return None
    if not isinstance(resolved_click_type, str) or not resolved_click_type.strip():
        return None

    return {
        "type_of_click": resolved_click_type.strip(),
        "target_description": target.strip(),
    }
