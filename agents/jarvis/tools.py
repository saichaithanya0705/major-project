"""
JARVIS Agent Tools - Screen annotation capabilities.

This module contains all the tool definitions and wrapper functions for
drawing on the user's screen (bounding boxes, text, pointers, etc.).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque

try:
    from google.genai import types as _genai_types
except ImportError:
    _genai_types = None


if _genai_types is None:
    class _FunctionCallingConfig:
        def __init__(self, mode: str):
            self.mode = mode


    class _ToolConfig:
        def __init__(self, function_calling_config):
            self.function_calling_config = function_calling_config


    class _Tool:
        def __init__(self, function_declarations):
            self.function_declarations = function_declarations


    class _TypesShim:
        Tool = _Tool
        ToolConfig = _ToolConfig
        FunctionCallingConfig = _FunctionCallingConfig


    types = _TypesShim()
else:
    types = _genai_types

from core.settings import get_screen_size, get_viewport_size
from ui.visualization_api.clear_screen import _clear_screen
from ui.visualization_api.create_text import _create_text
from ui.visualization_api.client import get_client
from ui.visualization_api.destroy_box import _destroy_box
from ui.visualization_api.destroy_text import _destroy_text
from ui.visualization_api.draw_bounding_box import _draw_bounding_box
from ui.visualization_api.draw_dot import _draw_dot
from agents.jarvis.text_layout import resolve_non_overlapping_anchor
from agents.jarvis.tool_declarations import (
    JARVIS_DECLARED_TOOL_NAMES,
    JARVIS_FUNCTION_DECLARATIONS,
)


# ================================================================================
# ACTION QUEUE - Handles timed execution of visual elements
# ================================================================================

ACTION_QUEUE = deque()
_ACTION_TASK = None
_SCREEN_SIZE = None
_VIEWPORT_SIZE = None
_LAST_DIRECT_RESPONSE = None
_WAITED_AFTER_DIRECT_RESPONSE = True
_ACTIVE_TEXT_RECTS = {}
_MAX_INITIAL_ACTION_DELAY_SECONDS = 0.6
_MAX_INTER_ACTION_DELAY_SECONDS = 2.0


def _get_sizes():
    global _SCREEN_SIZE, _VIEWPORT_SIZE
    if not _SCREEN_SIZE or not _VIEWPORT_SIZE:
        _SCREEN_SIZE = get_screen_size()
        _VIEWPORT_SIZE = get_viewport_size()
    return _SCREEN_SIZE, _VIEWPORT_SIZE


def denormalize(norm_x, norm_y):
    """Convert normalized coordinates (0-1000) to pixel values."""
    screen_size, viewport_size = _get_sizes()
    viewport_width, viewport_height = viewport_size
    screen_width, screen_height = screen_size

    width = viewport_width or screen_width
    height = viewport_height or screen_height

    if not width or not height:
        raise RuntimeError("Missing viewport/screen size; cannot denormalize coordinates.")
    denorm_x, denorm_y = norm_x, norm_y

    if 0 <= norm_x <= 1000:
        denorm_x = int(norm_x / 1000 * width)
    if 0 <= norm_y <= 1000:
        denorm_y = int(norm_y / 1000 * height)
    return denorm_x, denorm_y


def _get_command_anchor():
    """Get the anchor position for direct response text."""
    screen_size, viewport_size = _get_sizes()
    viewport_width, viewport_height = viewport_size
    screen_width, screen_height = screen_size

    width = viewport_width or screen_width
    height = viewport_height or screen_height
    if not width or not height:
        raise RuntimeError("Missing viewport/screen size; cannot place direct response.")

    center_x = int(width * 0.5)
    base_y = int(height * 0.5) - 20
    response_y = base_y + 60
    return center_x, response_y


async def _hide_command_overlay():
    client = await get_client()
    await client.send({"command": "overlay_hide", "id": "direct_response"})


async def set_model_name(name: str):
    """Set the model name displayed in the response bubble."""
    client = await get_client()
    await client.send({"command": "set_model_name", "name": name})


# ================================================================================
# ACTION QUEUE HANDLERS
# ================================================================================

def queue_action(time: float, func, args, kwargs=None):
    ACTION_QUEUE.append((time, func, args, kwargs or {}))
    _ensure_queue_processor()


def _ensure_queue_processor():
    """Start the queue processor task if not already running."""
    global _ACTION_TASK

    if _ACTION_TASK is not None and not _ACTION_TASK.done():
        return

    try:
        loop = asyncio.get_running_loop()
        _ACTION_TASK = loop.create_task(_run_queue_async())
    except RuntimeError:
        pass


async def _run_queue_async():
    """Process queued actions with their time delays."""
    global _LAST_DIRECT_RESPONSE, _WAITED_AFTER_DIRECT_RESPONSE
    last_time = 0.0

    while True:
        if not ACTION_QUEUE:
            last_time = 0.0
            await asyncio.sleep(0.05)
            continue

        time_s, func, args, kwargs = ACTION_QUEUE.popleft()
        action_time_s = float(time_s)

        # Handle direct_response delay
        if _LAST_DIRECT_RESPONSE and not _WAITED_AFTER_DIRECT_RESPONSE:
            elapsed = time.monotonic() - _LAST_DIRECT_RESPONSE
            if elapsed < 4.0:
                await asyncio.sleep(4.0 - elapsed)
            await _hide_command_overlay()
            _WAITED_AFTER_DIRECT_RESPONSE = True

        if last_time == 0.0 and action_time_s > _MAX_INITIAL_ACTION_DELAY_SECONDS:
            print(
                f"[JARVIS][queue] clamping initial action time from "
                f"{action_time_s:.2f}s to {_MAX_INITIAL_ACTION_DELAY_SECONDS:.2f}s"
            )
            action_time_s = _MAX_INITIAL_ACTION_DELAY_SECONDS

        delay = max(0.0, action_time_s - last_time)
        if delay > _MAX_INTER_ACTION_DELAY_SECONDS:
            print(
                f"[JARVIS][queue] clamping inter-action delay from "
                f"{delay:.2f}s to {_MAX_INTER_ACTION_DELAY_SECONDS:.2f}s"
            )
            delay = _MAX_INTER_ACTION_DELAY_SECONDS
        if delay:
            await asyncio.sleep(delay)
        await func(*args, **kwargs)
        last_time = action_time_s


def _dispatch_now(coro):
    """Schedule a coroutine to run immediately on the current event loop."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        pass


def _viewport_dimensions() -> tuple[int, int]:
    """Return overlay viewport dimensions in pixels."""
    screen_size, viewport_size = _get_sizes()
    viewport_width, viewport_height = viewport_size
    screen_width, screen_height = screen_size
    width = int(viewport_width or screen_width or 1)
    height = int(viewport_height or screen_height or 1)
    return max(width, 1), max(height, 1)


async def _create_text_non_overlapping(
    x: int,
    y: int,
    text: str,
    text_id: str | None,
    font_size: int,
    font_family: str,
    align: str | None,
    baseline: str | None,
    source: str = "jarvis",
):
    resolved_text_id = text_id or f"text_{uuid.uuid4().hex[:8]}"
    viewport_width, viewport_height = _viewport_dimensions()
    resolved_x, resolved_y, rect = resolve_non_overlapping_anchor(
        int(x),
        int(y),
        text,
        int(font_size or 18),
        align,
        baseline,
        resolved_text_id,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        active_text_rects=_ACTIVE_TEXT_RECTS,
    )
    if resolved_x != int(x) or resolved_y != int(y):
        print(
            "[JARVIS][layout] nudged text "
            f"{resolved_text_id} from ({int(x)},{int(y)}) to ({resolved_x},{resolved_y})"
        )

    created_id = await _create_text(
        resolved_x,
        resolved_y,
        text,
        resolved_text_id,
        font_size,
        font_family,
        align,
        baseline,
        source,
    )
    _ACTIVE_TEXT_RECTS[created_id] = rect
    return created_id


async def _clear_screen_with_layout_reset():
    _ACTIVE_TEXT_RECTS.clear()
    await _clear_screen()


async def _destroy_text_with_layout_reset(text_id: str):
    _ACTIVE_TEXT_RECTS.pop(text_id, None)
    await _destroy_text(text_id)


def stop_all_actions():
    """Immediately stop and clear queued overlay actions."""
    global _ACTION_TASK, _LAST_DIRECT_RESPONSE, _WAITED_AFTER_DIRECT_RESPONSE
    ACTION_QUEUE.clear()
    if _ACTION_TASK is not None and not _ACTION_TASK.done():
        _ACTION_TASK.cancel()
    _ACTION_TASK = None
    _LAST_DIRECT_RESPONSE = None
    _WAITED_AFTER_DIRECT_RESPONSE = True
    _ACTIVE_TEXT_RECTS.clear()


# ================================================================================
# TOOL WRAPPER FUNCTIONS
# ================================================================================

def clear_screen(time: float):
    queue_action(time, _clear_screen_with_layout_reset, (), {})


def create_text(
    time: float,
    x: int,
    y: int,
    text: str,
    font_size: int = 18,
    font_family: str = "Helvetica",
    align: str = "left",
    baseline: str = "top",
    text_id: str = None,
):
    x, y = denormalize(x, y)
    queue_action(
        time,
        _create_text_non_overlapping,
        (x, y, text, text_id, font_size, font_family, align, baseline, "jarvis"),
        {}
    )


def direct_response(
    text: str,
    font_size: int = 18,
    font_family: str = "Helvetica",
    source: str = "jarvis",
):
    global _LAST_DIRECT_RESPONSE, _WAITED_AFTER_DIRECT_RESPONSE
    _LAST_DIRECT_RESPONSE = time.monotonic()
    _WAITED_AFTER_DIRECT_RESPONSE = False
    x, y = _get_command_anchor()
    _dispatch_now(_create_text(
        x,
        y,
        text,
        "direct_response",
        font_size,
        font_family,
        "left",
        "top",
        source,
    ))


def create_text_for_box(
    time: float,
    box: dict,
    text: str,
    position: str = "top",
    font_size: int = 18,
    font_family: str = "Helvetica",
    align: str = None,
    padding: int = 6,
):
    box_x, box_y = denormalize(box["x"], box["y"])
    box_w, box_h = denormalize(box["width"], box["height"])
    box = {"x": box_x, "y": box_y, "width": box_w, "height": box_h}
    center_x = box["x"] + (box["width"] / 2)
    center_y = box["y"] + (box["height"] / 2)

    if position == "top":
        anchor_x = center_x
        anchor_y = box["y"] - padding
        baseline = "bottom"
        default_align = "center"
    elif position == "bottom":
        anchor_x = center_x
        anchor_y = box["y"] + box["height"] + padding
        baseline = "top"
        default_align = "center"
    elif position == "left":
        anchor_x = box["x"] - padding
        anchor_y = center_y
        baseline = "middle"
        default_align = "right"
    elif position == "right":
        anchor_x = box["x"] + box["width"] + padding
        anchor_y = center_y
        baseline = "middle"
        default_align = "left"
    else:
        raise ValueError("position must be one of: top, bottom, left, right")

    anchor_align = align or default_align
    queue_action(
        time,
        _create_text_non_overlapping,
        (
            int(anchor_x),
            int(anchor_y),
            text,
            None,
            font_size,
            font_family,
            anchor_align,
            baseline,
            "jarvis",
        ),
        {},
    )


def destroy_box(time: float, box_id: str):
    queue_action(time, _destroy_box, (box_id,), {})


def destroy_text(time: float, text_id: str):
    queue_action(time, _destroy_text_with_layout_reset, (text_id,), {})


def draw_bounding_box(
    time: float,
    y_min: int,
    x_min: int,
    y_max: int,
    x_max: int,
    box_id: str = None,
    stroke: str | None = "#AEB4BF",
    stroke_width: int = 5,
    opacity: float = 0.8,
    auto_contrast: bool = False,
    fill: str | None = None,
):
    x_min, y_min = denormalize(x_min, y_min)
    x_max, y_max = denormalize(x_max, y_max)
    queue_action(
        time,
        _draw_bounding_box,
        (y_min, x_min, y_max, x_max, box_id, stroke, stroke_width, opacity, auto_contrast, fill),
        {},
    )


def draw_pointer_to_object(
    time: float,
    x_pos: int,
    y_pos: int,
    text: str,
    text_x: int,
    text_y: int,
    point_id: str = None,
    dot_color: str = "#ffffff",
    ring_color: str = "#AEB4BF",
    ring_radius: int = None,
):
    """
    Draw a pointer dot at (x_pos, y_pos) with a text label at (text_x, text_y).
    A thin white line automatically connects the dot to the center of the text bubble.
    """
    link_id = point_id or f"ptr_{uuid.uuid4().hex[:8]}"
    text_id = f"{link_id}_text"

    x_pos, y_pos = denormalize(x_pos, y_pos)
    text_x, text_y = denormalize(text_x, text_y)

    queue_action(
        time,
        _draw_dot,
        (x_pos, y_pos, link_id, 6, dot_color, ring_color, text_id, ring_radius),
        {},
    )
    queue_action(
        time,
        _create_text_non_overlapping,
        (text_x, text_y, text, text_id, 18, "Helvetica", "left", "top", "jarvis"),
        {},
    )


# ================================================================================
# TOOL SETS
# ================================================================================

JARVIS_TOOLS = [types.Tool(function_declarations=JARVIS_FUNCTION_DECLARATIONS)]

JARVIS_TOOL_MAP = {
    "draw_bounding_box": draw_bounding_box,
    "draw_pointer_to_object": draw_pointer_to_object,
    "create_text": create_text,
    "direct_response": direct_response,
    "create_text_for_box": create_text_for_box,
    "clear_screen": clear_screen,
    "destroy_box": destroy_box,
    "destroy_text": destroy_text,
}


def _validate_jarvis_tool_contract() -> None:
    missing = [name for name in JARVIS_DECLARED_TOOL_NAMES if name not in JARVIS_TOOL_MAP]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(
            "JARVIS function declarations include missing implementations: "
            f"{missing_list}"
        )

    not_callable = [
        name for name in JARVIS_DECLARED_TOOL_NAMES
        if not callable(JARVIS_TOOL_MAP.get(name))
    ]
    if not_callable:
        bad_list = ", ".join(sorted(not_callable))
        raise TypeError(
            "JARVIS tool map contains non-callable implementations for: "
            f"{bad_list}"
        )


_validate_jarvis_tool_contract()
