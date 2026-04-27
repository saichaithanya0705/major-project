"""
Function-calling declarations for CUA vision tools.
"""


def _with_status_text(properties: dict) -> dict:
    enriched = dict(properties)
    enriched["status_text"] = {
        "type": "string",
        "description": "Short user-facing progress text to show while this action runs.",
    }
    return enriched


def _with_click_metadata(properties: dict) -> dict:
    enriched = _with_status_text(properties)
    enriched["target_description"] = {
        "type": "string",
        "description": "Short description of the click target (for retry fallback).",
    }
    return enriched


type_string_declaration = {
    "name": "type_string",
    "description": "Types out a string in the currently focused input. Optionally submit with Enter.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "string": {"type": "string", "description": "The string to type out."},
            "submit": {
                "type": "boolean",
                "description": "Set true to press Enter once after typing.",
            },
        }),
        "required": ["string"],
    },
}

press_ctrl_hotkey_declaration = {
    "name": "press_ctrl_hotkey",
    "description": "Press a control-style hotkey. On macOS this maps to Command automatically; on other OSes it uses Control.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "key": {"type": "string", "description": "The key to press with control."},
        }),
        "required": ["key"],
    },
}

press_alt_hotkey_declaration = {
    "name": "press_alt_hotkey",
    "description": "Press a key along with the alt key to emulate a hotkey.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "key": {"type": "string", "description": "The key to press with alt."},
        }),
        "required": ["key"],
    },
}

click_left_click_declaration = {
    "name": "click_left_click",
    "description": "Emulates a mouse left click at the current cursor position.",
    "parameters": {
        "type": "object",
        "properties": _with_click_metadata({}),
    },
}

click_double_left_click_declaration = {
    "name": "click_double_left_click",
    "description": "Emulates a mouse double left click at the current cursor position.",
    "parameters": {
        "type": "object",
        "properties": _with_click_metadata({}),
    },
}

click_right_click_declaration = {
    "name": "click_right_click",
    "description": "Emulates a mouse right click at the current cursor position.",
    "parameters": {
        "type": "object",
        "properties": _with_click_metadata({}),
    },
}

go_to_element_declaration = {
    "name": "go_to_element",
    "description": (
        "Move cursor to the center of a target bounding box."
    ),
    "parameters": {
        "type": "object",
        "properties": _with_click_metadata({
            "ymin": {
                "type": "number",
                "description": "Top edge of target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "xmin": {
                "type": "number",
                "description": "Left edge of target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "ymax": {
                "type": "number",
                "description": "Bottom edge of target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "xmax": {
                "type": "number",
                "description": "Right edge of target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
        }),
        "required": [
            "target_description",
            "ymin",
            "xmin",
            "ymax",
            "xmax",
        ],
    },
}

crop_and_search_declaration = {
    "name": "crop_and_search",
    "description": (
        "Optional precision cursor positioning helper. Provide a best-effort bounding box around a likely target; "
        "the tool pads the box, runs a second localization pass inside the crop, and moves cursor to the refined center."
    ),
    "parameters": {
        "type": "object",
        "properties": _with_click_metadata({
            "ymin": {
                "type": "number",
                "description": "Top edge of a best-effort target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "xmin": {
                "type": "number",
                "description": "Left edge of a best-effort target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "ymax": {
                "type": "number",
                "description": "Bottom edge of a best-effort target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
            "xmax": {
                "type": "number",
                "description": "Right edge of a best-effort target bounding box, normalized 0-1000 (or ratio 0-1).",
            },
        }),
        "required": [
            "target_description",
            "ymin",
            "xmin",
            "ymax",
            "xmax",
        ],
    },
}

hold_down_left_click_declaration = {
    "name": "hold_down_left_click",
    "description": "Emulates holding down the left mouse button.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "x": {"type": "number", "description": "X coordinate on screen."},
            "y": {"type": "number", "description": "Y coordinate on screen."},
        }),
        "required": ["x", "y"],
    },
}

release_left_click_declaration = {
    "name": "release_left_click",
    "description": "Emulates releasing the left mouse button.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "x": {"type": "number", "description": "X coordinate on screen."},
            "y": {"type": "number", "description": "Y coordinate on screen."},
        }),
        "required": ["x", "y"],
    },
}

press_key_for_duration_declaration = {
    "name": "press_key_for_duration",
    "description": "Holds down a key for a specified duration.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "key": {"type": "string", "description": "The key to press."},
            "seconds": {"type": "number", "description": "Duration in seconds."},
        }),
        "required": ["key", "seconds"],
    },
}

hold_down_key_declaration = {
    "name": "hold_down_key",
    "description": "Press down a key indefinitely until release_held_key is called.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "key": {"type": "string", "description": "The key to hold down."},
        }),
        "required": ["key"],
    },
}

release_held_key_declaration = {
    "name": "release_held_key",
    "description": "Release a previously held down key.",
    "parameters": {
        "type": "object",
        "properties": _with_status_text({
            "key": {"type": "string", "description": "The key to release."},
        }),
        "required": ["key"],
    },
}

remember_information_declaration = {
    "name": "remember_information",
    "description": "Remember/memorize information for later use. Use this when the user asks you to remember something.",
    "parameters": {
        "type": "object",
        "properties": {
            "thing_to_remember": {
                "type": "string",
                "description": "The information to remember, detailed enough to reproduce later.",
            },
        },
        "required": ["thing_to_remember"],
    },
}

tts_speak_declaration = {
    "name": "tts_speak",
    "description": "Verbally speak to the user. Use this to give feedback or confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to speak to the user."},
        },
        "required": ["text"],
    },
}

task_is_complete_declaration = {
    "name": "task_is_complete",
    "description": "Signal that the task is complete. This should be the final action.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Optional short completion message to speak.",
            },
        },
    },
}


def _collect_declared_tool_names(function_declarations: list[dict]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()

    for declaration in function_declarations:
        name = declaration.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Each vision declaration must define a non-empty string name: {declaration!r}")
        normalized_name = name.strip()
        names.append(normalized_name)
        if normalized_name in seen:
            duplicates.add(normalized_name)
        seen.add(normalized_name)

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate vision declaration names detected: {duplicate_list}")
    return tuple(names)


VISION_FUNCTION_DECLARATIONS = [
    type_string_declaration,
    press_ctrl_hotkey_declaration,
    press_alt_hotkey_declaration,
    go_to_element_declaration,
    click_left_click_declaration,
    click_double_left_click_declaration,
    click_right_click_declaration,
    crop_and_search_declaration,
    hold_down_left_click_declaration,
    release_left_click_declaration,
    press_key_for_duration_declaration,
    hold_down_key_declaration,
    release_held_key_declaration,
    remember_information_declaration,
    task_is_complete_declaration,
    tts_speak_declaration,
]

VISION_DECLARED_TOOL_NAMES = _collect_declared_tool_names(VISION_FUNCTION_DECLARATIONS)
