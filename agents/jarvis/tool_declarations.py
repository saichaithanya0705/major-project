"""
Function-calling declarations for JARVIS visualization tools.
"""

draw_bounding_box_declaration = {
    "name": "draw_bounding_box",
    "description": "Draw a bounding box using Gemini-style coordinates (y_min, x_min, y_max, x_max).",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "y_min": {"type": "integer", "description": "Top edge coordinate in pixels."},
            "x_min": {"type": "integer", "description": "Left edge coordinate in pixels."},
            "y_max": {"type": "integer", "description": "Bottom edge coordinate in pixels."},
            "x_max": {"type": "integer", "description": "Right edge coordinate in pixels."},
            "box_id": {"type": "string", "description": "Optional unique ID for the box."},
            "stroke": {"type": "string", "description": "Stroke color hex code.", "default": "#AEB4BF"},
            "stroke_width": {"type": "integer", "description": "Border width in pixels.", "default": 5},
            "opacity": {"type": "number", "description": "Opacity from 0 to 1.", "default": 0.8},
            "auto_contrast": {"type": "boolean", "description": "Choose stroke color based on background contrast.", "default": False},
            "fill": {"type": "string", "description": "Optional fill color (CSS color string)."},
        },
        "required": ["time", "y_min", "x_min", "y_max", "x_max"],
    },
}

draw_point_declaration = {
    "name": "draw_pointer_to_object",
    "description": "Draw a dot at (x_pos, y_pos) pointing to an object, with a text label at (text_x, text_y). A thin white line automatically connects the dot to the text bubble center.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "x_pos": {"type": "integer", "description": "X position of the dot in pixels."},
            "y_pos": {"type": "integer", "description": "Y position of the dot in pixels."},
            "text": {"type": "string", "description": "The label text to display."},
            "text_x": {"type": "integer", "description": "X position of the text label in pixels."},
            "text_y": {"type": "integer", "description": "Y position of the text label in pixels."},
            "point_id": {"type": "string", "description": "Optional unique ID for the pointer."},
            "dot_color": {"type": "string", "description": "Dot fill color.", "default": "#ffffff"},
            "ring_color": {"type": "string", "description": "Ring color.", "default": "#AEB4BF"},
            "ring_radius": {"type": "integer", "description": "Optional ring radius in pixels."},
        },
        "required": ["time", "x_pos", "y_pos", "text", "text_x", "text_y"],
    },
}

create_text_declaration = {
    "name": "create_text",
    "description": "Draw a text label at an (x, y) anchor point.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "x": {"type": "integer", "description": "X coordinate in pixels."},
            "y": {"type": "integer", "description": "Y coordinate in pixels."},
            "text": {"type": "string", "description": "Label text to render."},
            "font_size": {"type": "integer", "description": "Font size in pixels.", "default": 18},
            "font_family": {"type": "string", "description": "Font family name.", "default": "Helvetica"},
            "align": {"type": "string", "description": "Canvas textAlign value.", "default": "left"},
            "baseline": {"type": "string", "description": "Canvas textBaseline value.", "default": "top"},
            "text_id": {"type": "string", "description": "Optional unique ID for the text label."},
        },
        "required": ["time", "x", "y", "text"],
    },
}

create_text_for_box_declaration = {
    "name": "create_text_for_box",
    "description": "Draw a text label relative to a bounding box.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "box": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Box left edge."},
                    "y": {"type": "integer", "description": "Box top edge."},
                    "width": {"type": "integer", "description": "Box width."},
                    "height": {"type": "integer", "description": "Box height."},
                },
                "required": ["x", "y", "width", "height"],
            },
            "text": {"type": "string", "description": "Label text to render."},
            "position": {
                "type": "string",
                "enum": ["top", "bottom", "left", "right"],
                "description": "Placement relative to the box.",
                "default": "top",
            },
            "font_size": {"type": "integer", "description": "Font size in pixels.", "default": 18},
            "font_family": {"type": "string", "description": "Font family name.", "default": "Helvetica"},
            "align": {"type": "string", "description": "Canvas textAlign value."},
            "padding": {"type": "integer", "description": "Pixels between text and box.", "default": 6},
        },
        "required": ["time", "box", "text"],
    },
}

direct_response_declaration = {
    "name": "direct_response",
    "description": "Respond directly to the user, without any fancy UI display. Meant for queries that do not involve screen annotations.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Response text to render."},
            "font_size": {"type": "integer", "description": "Font size in pixels.", "default": 18},
            "font_family": {"type": "string", "description": "Font family name.", "default": "Helvetica"},
        },
        "required": ["text"],
    },
}

clear_screen_declaration = {
    "name": "clear_screen",
    "description": "Clear all visual elements on screen.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
        },
        "required": ["time"],
    },
}

destroy_box_declaration = {
    "name": "destroy_box",
    "description": "Remove a bounding box by ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "box_id": {"type": "string", "description": "ID of the box to remove."},
        },
        "required": ["time", "box_id"],
    },
}

destroy_text_declaration = {
    "name": "destroy_text",
    "description": "Remove a text label by ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "time": {"type": "number", "description": "Time offset in seconds for when to run this action."},
            "text_id": {"type": "string", "description": "ID of the text to remove."},
        },
        "required": ["time", "text_id"],
    },
}


def _collect_declared_tool_names(function_declarations: list[dict]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()

    for declaration in function_declarations:
        name = declaration.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Each JARVIS declaration must define a non-empty string name: {declaration!r}")
        normalized_name = name.strip()
        names.append(normalized_name)
        if normalized_name in seen:
            duplicates.add(normalized_name)
        seen.add(normalized_name)

    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate JARVIS declaration names detected: {duplicate_list}")
    return tuple(names)


JARVIS_FUNCTION_DECLARATIONS = [
    draw_bounding_box_declaration,
    draw_point_declaration,
    create_text_declaration,
    direct_response_declaration,
    create_text_for_box_declaration,
    clear_screen_declaration,
    destroy_box_declaration,
    destroy_text_declaration,
]

JARVIS_DECLARED_TOOL_NAMES = _collect_declared_tool_names(JARVIS_FUNCTION_DECLARATIONS)
