"""
CUA Vision Agent - Tool Declarations and Functions

Contains all tool declarations for the vision-based computer use agent,
including screen interaction, memory, and input functions.
"""

import inspect

from dotenv import load_dotenv
from PIL import ImageGrab

class _FunctionCallingConfig:
    def __init__(self, mode: str):
        self.mode = mode


class _ToolConfig:
    def __init__(self, function_calling_config):
        self.function_calling_config = function_calling_config


class _Tool:
    def __init__(self, function_declarations):
        self.function_declarations = function_declarations


class _VisionToolTypes:
    Tool = _Tool
    ToolConfig = _ToolConfig
    FunctionCallingConfig = _FunctionCallingConfig


types = _VisionToolTypes()

from agents.cua_vision.keyboard import (
    move_cursor,
    type_string,
    press_ctrl_hotkey,
    press_alt_hotkey,
    click_left_click,
    hold_down_left_click,
    hold_down_right_click,
    release_left_click,
    release_right_click,
    click_right_click,
    click_double_left_click,
    press_key_for_duration,
    hold_down_key,
    release_held_key,
)
from agents.cua_vision.screen_context import (
    _bbox_center_to_screen_coords,
    _bbox_logical_dimensions,
    _bbox_to_capture_pixel_box,
    _get_active_window_bbox,
    _should_force_zoom,
    capture_active_window,
    get_active_window_title,
    save_go_to_element_debug_snapshot,
)
from agents.cua_vision.tool_declarations import (
    VISION_DECLARED_TOOL_NAMES,
    VISION_FUNCTION_DECLARATIONS,
)
from core.settings import get_jarvis_model
from agents.cua_vision.agentic_vision import crop_and_search_click
from agents.cua_vision.legacy_locator import legacy_find_and_click_element
from agents.cua_vision.runtime_state import (
    clear_stop_request,
    get_last_capture_context as _get_last_capture_context,
    get_last_capture_image as _get_last_capture_image,
    get_memory,
    is_stop_requested,
    remember_image as _remember_image,
    remember_text as _remember_text,
    request_stop,
    reset_state,
)
from integrations.audio import tts_speak

load_dotenv()


# ================================================================================
# GLOBAL STATE
# ================================================================================

TOOL_METADATA_KEYS = {"status_text", "target_description"}

FORCED_ZOOM_PAD_PX = 400


# ================================================================================
# MEMORY FUNCTIONS
# ================================================================================

def remember_information(thing_to_remember: str):
    """Remember information for later use."""
    _remember_text(thing_to_remember)
    try:
        bbox = _get_active_window_bbox()
        if bbox:
            _remember_image(ImageGrab.grab(bbox=bbox))
        else:
            _remember_image(ImageGrab.grab())
    except Exception as e:
        print(f"Could not capture memory image: {e}")
    print(f"Remembered: {thing_to_remember}")


def task_is_complete(text: str = "Done."):
    """Signal task completion and provide concise spoken confirmation."""
    message = str(text or "").strip()
    if not message:
        message = "Done."
    tts_speak(message)


# ================================================================================
# SCREEN CAPTURE UTILITIES
# ================================================================================

def go_to_element(
    ymin: float,
    xmin: float,
    ymax: float,
    xmax: float,
    target_description: str = "",
):
    """
    Move cursor to the center of a target bounding box.

    The bbox should be in active-window coordinates (0-1000, 0-1, or pixels).
    """
    context = _get_last_capture_context()
    if not context:
        capture_active_window()
        context = _get_last_capture_context() or {}

    bbox_w, bbox_h = _bbox_logical_dimensions(ymin, xmin, ymax, xmax)
    target = target_description.strip() if isinstance(target_description, str) else "target"
    auto_zoom = _should_force_zoom(bbox_w, bbox_h)

    if auto_zoom:
        screenshot = _get_last_capture_image()
        if screenshot is None:
            screenshot = capture_active_window()
            context = _get_last_capture_context() or context
        offset = (
            float(context.get("offset_x", 0.0)),
            float(context.get("offset_y", 0.0)),
        )
        window_scale = (
            float(context.get("scale_x", 1.0)),
            float(context.get("scale_y", 1.0)),
        )
        result = crop_and_search_click(
            screenshot=screenshot,
            crop_bounds=(ymin, xmin, ymax, xmax),
            target_description=target,
            window_offset=offset,
            window_scale=window_scale,
            model_name=_get_precision_locator_model_name(),
            should_stop=is_stop_requested,
            perform_click=False,
            pad_pixels=FORCED_ZOOM_PAD_PX,
            rebalance_edges=True,
        )
        x, y = result["x"], result["y"]
    else:
        x, y = _bbox_center_to_screen_coords(ymin, xmin, ymax, xmax)

    context = _get_last_capture_context() or {}
    mode = context.get("mode", "unknown")
    logical_w = context.get("logical_width", context.get("width", "?"))
    logical_h = context.get("logical_height", context.get("height", "?"))
    scale_x = float(context.get("scale_x", 1.0))
    scale_y = float(context.get("scale_y", 1.0))
    move_cursor(x, y, duration=0.2)
    print(f"[VisionAgent] go_to_element centered on {target} at ({x:.1f}, {y:.1f})")
    print(
        "[VisionAgent] go_to_element context "
        f"mode={mode} logical={logical_w}x{logical_h} scale=({scale_x:.2f},{scale_y:.2f})"
    )
    print(
        "[VisionAgent] go_to_element bbox "
        f"size=({bbox_w:.1f}x{bbox_h:.1f}) auto_zoom={'on' if auto_zoom else 'off'}"
    )


# ================================================================================
# LEGACY FALLBACK LOCATOR
# ================================================================================

def find_and_click_element(type_of_click: str, element_description: str):
    """Backward-compatible wrapper for legacy element localization."""
    legacy_find_and_click_element(
        type_of_click,
        element_description,
        should_stop=is_stop_requested,
    )


def run_legacy_locator_fallback(type_of_click: str, element_description: str) -> bool:
    """Run legacy two-call locator as an internal fallback."""
    try:
        return bool(legacy_find_and_click_element(
            type_of_click,
            element_description,
            should_stop=is_stop_requested,
        ))
    except Exception as e:
        print(f"[LegacyLocator] Fallback failed: {e}")
        return False


def _get_precision_locator_model_name() -> str:
    """Get the model name used by the crop-and-search precision locator."""
    try:
        model_name = get_jarvis_model()
        if (
            isinstance(model_name, str)
            and model_name.strip()
            and "gemini" not in model_name.strip().lower()
        ):
            return model_name.strip()
    except Exception:
        pass
    return ""


def crop_and_search(
    target_description: str,
    ymin: float,
    xmin: float,
    ymax: float,
    xmax: float,
):
    """
    Agentic vision precision tool.

    Crops a coarse region, runs second-pass target localization in that crop,
    and moves the cursor to the refined center.
    """
    if not isinstance(target_description, str) or not target_description.strip():
        raise ValueError("target_description is required for crop_and_search")

    screenshot = capture_active_window()
    context = _get_last_capture_context() or {}
    offset = (
        float(context.get("offset_x", 0.0)),
        float(context.get("offset_y", 0.0)),
    )
    window_scale = (
        float(context.get("scale_x", 1.0)),
        float(context.get("scale_y", 1.0)),
    )

    result = crop_and_search_click(
        screenshot=screenshot,
        crop_bounds=(ymin, xmin, ymax, xmax),
        target_description=target_description.strip(),
        window_offset=offset,
        window_scale=window_scale,
        model_name=_get_precision_locator_model_name(),
        should_stop=is_stop_requested,
        perform_click=False,
        pad_pixels=FORCED_ZOOM_PAD_PX,
        rebalance_edges=True,
    )
    move_cursor(result["x"], result["y"], duration=0.2)
    print(
        "[AgenticVision] crop_and_search positioned cursor for "
        f"{result['target_description']} at ({result['x']:.1f}, {result['y']:.1f})"
    )


# ================================================================================
# TOOL EXECUTION HELPERS
# ================================================================================

def _filter_tool_args(tool_name: str, args: dict) -> dict:
    tool = VISION_TOOL_MAP.get(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    signature = inspect.signature(tool)
    allowed = set(signature.parameters.keys())
    filtered = {}
    for key, value in (args or {}).items():
        if key in TOOL_METADATA_KEYS and key not in allowed:
            continue
        if key in allowed:
            filtered[key] = value
    return filtered


def execute_tool_call(tool_name: str, args: dict):
    """Execute a tool call while dropping UI metadata-only arguments."""
    tool = VISION_TOOL_MAP.get(tool_name)
    if tool is None:
        raise ValueError(f"Unknown tool: {tool_name}")

    filtered_args = _filter_tool_args(tool_name, args)
    tool(**filtered_args)


# ================================================================================
# TOOL SETS
# ================================================================================

VISION_TOOLS = [types.Tool(function_declarations=VISION_FUNCTION_DECLARATIONS)]

VISION_TOOL_MAP = {
    "type_string": type_string,
    "press_ctrl_hotkey": press_ctrl_hotkey,
    "press_alt_hotkey": press_alt_hotkey,
    "go_to_element": go_to_element,
    "click_left_click": click_left_click,
    "click_double_left_click": click_double_left_click,
    "click_right_click": click_right_click,
    "crop_and_search": crop_and_search,
    "hold_down_left_click": hold_down_left_click,
    "hold_down_right_click": hold_down_right_click,
    "release_left_click": release_left_click,
    "release_right_click": release_right_click,
    "press_key_for_duration": press_key_for_duration,
    "hold_down_key": hold_down_key,
    "release_held_key": release_held_key,
    "remember_information": remember_information,
    "task_is_complete": task_is_complete,
    "tts_speak": tts_speak,
    "find_and_click_element": find_and_click_element,
}


def _validate_vision_tool_contract() -> None:
    missing = [name for name in VISION_DECLARED_TOOL_NAMES if name not in VISION_TOOL_MAP]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RuntimeError(
            "Vision function declarations include missing implementations: "
            f"{missing_list}"
        )

    not_callable = [
        name for name in VISION_DECLARED_TOOL_NAMES
        if not callable(VISION_TOOL_MAP.get(name))
    ]
    if not_callable:
        bad_list = ", ".join(sorted(not_callable))
        raise TypeError(
            "Vision tool map contains non-callable implementations for: "
            f"{bad_list}"
        )


_validate_vision_tool_contract()

TOOL_CONFIG = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(
        mode="ANY",
    )
)
