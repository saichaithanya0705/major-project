"""
Screen capture and coordinate mapping helpers for CUA Vision tools.
"""

import os
import time

from PIL import Image, ImageDraw, ImageGrab

try:
    import pygetwindow as gw
except ImportError:
    gw = None
    print("pygetwindow dependency is not installed; active-window capture will fallback to full-screen mode.")

try:
    import pyautogui
except ImportError:
    pyautogui = None
    print("pyautogui dependency is not installed; display size fallback uses capture dimensions.")

from agents.cua_vision.runtime_state import (
    get_last_capture_context as _get_last_capture_context,
    get_last_capture_image as _get_last_capture_image,
    set_last_capture_context as _set_last_capture_context,
    set_last_capture_image as _set_last_capture_image,
)

AUTO_FORCE_ZOOM_MIN_SIDE_LOGICAL_PX = 96
AUTO_FORCE_ZOOM_MAX_AREA_LOGICAL_PX2 = 14000


def capture_active_window() -> Image.Image:
    """Capture the currently active window and cache frame context."""
    try:
        bbox = _get_active_window_bbox()
        if bbox:
            image = ImageGrab.grab(bbox=bbox)
            logical_width = max(int(bbox[2] - bbox[0]), 1)
            logical_height = max(int(bbox[3] - bbox[1]), 1)
            scale_x = float(image.size[0]) / float(logical_width)
            scale_y = float(image.size[1]) / float(logical_height)
            _set_last_capture_context(
                width=image.size[0],
                height=image.size[1],
                logical_width=logical_width,
                logical_height=logical_height,
                offset_x=bbox[0],
                offset_y=bbox[1],
                scale_x=scale_x,
                scale_y=scale_y,
                mode="active_window",
            )
            _set_last_capture_image(image)
            return image
    except Exception as e:
        print(f"Error capturing active window: {e}")

    image = ImageGrab.grab()
    try:
        if pyautogui is not None:
            logical_width, logical_height = pyautogui.size()
        else:
            logical_width, logical_height = image.size
    except Exception:
        logical_width, logical_height = image.size
    logical_width = max(int(logical_width), 1)
    logical_height = max(int(logical_height), 1)
    scale_x = float(image.size[0]) / float(logical_width)
    scale_y = float(image.size[1]) / float(logical_height)
    _set_last_capture_context(
        width=image.size[0],
        height=image.size[1],
        logical_width=logical_width,
        logical_height=logical_height,
        offset_x=0.0,
        offset_y=0.0,
        scale_x=scale_x,
        scale_y=scale_y,
        mode="full_screen",
    )
    _set_last_capture_image(image)
    return image


def get_active_window_title() -> str:
    """Get the title of the currently active window."""
    if gw is None:
        return "Unknown"
    try:
        return gw.getActiveWindowTitle() or "Unknown"
    except Exception:
        return "Unknown"


def _get_active_window_bbox():
    """
    Return active window bounds as (left, top, right, bottom), or None.

    Some pygetwindow backends can return a string title from getActiveWindow();
    this helper normalizes that shape and avoids attribute errors.
    """
    if gw is None:
        return None

    try:
        window = gw.getActiveWindow()
    except Exception:
        return None

    def _bounds_from_window(win):
        required = ("left", "top", "width", "height")
        if not all(hasattr(win, key) for key in required):
            return None
        try:
            left = int(win.left)
            top = int(win.top)
            width = int(win.width)
            height = int(win.height)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return (left, top, left + width, top + height)

    bbox = _bounds_from_window(window)
    if bbox:
        return bbox

    if isinstance(window, str) and window:
        try:
            candidates = gw.getWindowsWithTitle(window)
        except Exception:
            return None
        for candidate in candidates:
            bbox = _bounds_from_window(candidate)
            if bbox:
                return bbox

    return None


def _to_pixels(value: float, size: int) -> float:
    """Convert ratio/normalized/pixel coordinate formats to pixels."""
    val = float(value)
    if 0.0 <= val <= 1.0:
        return val * size
    if 0.0 <= val <= 1000.0:
        return (val / 1000.0) * size
    return val


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _bbox_center_to_screen_coords(ymin: float, xmin: float, ymax: float, xmax: float) -> tuple[float, float]:
    """Map a bbox center from the last model frame to absolute screen coordinates."""
    context = _get_last_capture_context()
    if not context:
        capture_active_window()
        context = _get_last_capture_context()
    if not context:
        raise RuntimeError("No capture context available for bbox coordinate mapping")

    width = int(context.get("logical_width") or context["width"])
    height = int(context.get("logical_height") or context["height"])
    offset_x = float(context["offset_x"])
    offset_y = float(context["offset_y"])

    top = _to_pixels(ymin, height)
    left = _to_pixels(xmin, width)
    bottom = _to_pixels(ymax, height)
    right = _to_pixels(xmax, width)

    left, right = sorted((left, right))
    top, bottom = sorted((top, bottom))

    left = _clamp(left, 0, max(width - 1, 0))
    right = _clamp(right, 1, max(width, 1))
    top = _clamp(top, 0, max(height - 1, 0))
    bottom = _clamp(bottom, 1, max(height, 1))

    center_x_window = left + ((right - left) / 2.0)
    center_y_window = top + ((bottom - top) / 2.0)

    return (center_x_window + offset_x, center_y_window + offset_y)


def _bbox_logical_dimensions(ymin: float, xmin: float, ymax: float, xmax: float) -> tuple[float, float]:
    """Return bbox width/height in logical screen pixels."""
    context = _get_last_capture_context()
    if not context:
        capture_active_window()
        context = _get_last_capture_context()
    if not context:
        raise RuntimeError("No capture context available for bbox sizing")

    width = int(context.get("logical_width") or context["width"])
    height = int(context.get("logical_height") or context["height"])

    top = _to_pixels(ymin, height)
    left = _to_pixels(xmin, width)
    bottom = _to_pixels(ymax, height)
    right = _to_pixels(xmax, width)
    return (abs(right - left), abs(bottom - top))


def _should_force_zoom(width_px: float, height_px: float) -> bool:
    """Decide whether to force precision crop refinement for small targets."""
    w = max(float(width_px), 0.0)
    h = max(float(height_px), 0.0)
    area = w * h
    return (
        (w <= AUTO_FORCE_ZOOM_MIN_SIDE_LOGICAL_PX and h <= AUTO_FORCE_ZOOM_MIN_SIDE_LOGICAL_PX)
        or (area <= AUTO_FORCE_ZOOM_MAX_AREA_LOGICAL_PX2)
    )


def _bbox_to_capture_pixel_box(
    ymin: float,
    xmin: float,
    ymax: float,
    xmax: float,
    context: dict | None = None,
) -> tuple[float, float, float, float]:
    """
    Map bbox args to pixel coordinates on the stored capture image.

    Args are interpreted in logical coordinates (0-1000/0-1/logical px),
    then scaled into capture-image pixels.
    """
    context = context or _get_last_capture_context()
    if not context:
        capture_active_window()
        context = _get_last_capture_context()
    if not context:
        raise RuntimeError("No capture context available for bbox pixel mapping")

    logical_width = int(context.get("logical_width") or context["width"])
    logical_height = int(context.get("logical_height") or context["height"])
    scale_x = float(context.get("scale_x", 1.0))
    scale_y = float(context.get("scale_y", 1.0))
    if scale_x <= 0:
        scale_x = 1.0
    if scale_y <= 0:
        scale_y = 1.0

    top = _to_pixels(ymin, logical_height)
    left = _to_pixels(xmin, logical_width)
    bottom = _to_pixels(ymax, logical_height)
    right = _to_pixels(xmax, logical_width)

    left, right = sorted((left, right))
    top, bottom = sorted((top, bottom))

    left = _clamp(left, 0, max(logical_width - 1, 0))
    right = _clamp(right, 1, max(logical_width, 1))
    top = _clamp(top, 0, max(logical_height - 1, 0))
    bottom = _clamp(bottom, 1, max(logical_height, 1))

    return (left * scale_x, top * scale_y, right * scale_x, bottom * scale_y)


def save_go_to_element_debug_snapshot(
    ymin: float,
    xmin: float,
    ymax: float,
    xmax: float,
    target_description: str = "",
) -> str:
    """Save annotated debug image showing the bbox and its computed center."""
    image = _get_last_capture_image()
    if image is None:
        image = capture_active_window()

    context = _get_last_capture_context() or {}
    left_px, top_px, right_px, bottom_px = _bbox_to_capture_pixel_box(ymin, xmin, ymax, xmax)
    center_x = left_px + ((right_px - left_px) / 2.0)
    center_y = top_px + ((bottom_px - top_px) / 2.0)

    draw = ImageDraw.Draw(image)
    border_width = max(3, int(round(min(image.size) * 0.004)))
    draw.rectangle(
        [left_px, top_px, right_px, bottom_px],
        outline=(255, 64, 64),
        width=border_width,
    )
    cross = max(8, int(round(min(image.size) * 0.01)))
    draw.line([(center_x - cross, center_y), (center_x + cross, center_y)], fill=(64, 255, 64), width=border_width)
    draw.line([(center_x, center_y - cross), (center_x, center_y + cross)], fill=(64, 255, 64), width=border_width)

    mode = context.get("mode", "unknown")
    logical_width = context.get("logical_width", image.size[0])
    logical_height = context.get("logical_height", image.size[1])
    scale_x = context.get("scale_x", 1.0)
    scale_y = context.get("scale_y", 1.0)
    target = target_description.strip() if isinstance(target_description, str) and target_description.strip() else "target"
    text = (
        f"target={target} bbox=[{ymin},{xmin},{ymax},{xmax}] "
        f"mode={mode} logical={logical_width}x{logical_height} "
        f"image={image.size[0]}x{image.size[1]} scale=({scale_x:.2f},{scale_y:.2f})"
    )
    text_x = max(8, int(left_px))
    text_y = max(8, int(top_px) - 26)
    draw.rectangle([text_x - 4, text_y - 2, text_x + min(len(text) * 7, image.size[0] - text_x - 4), text_y + 18], fill=(0, 0, 0))
    draw.text((text_x, text_y), text, fill=(255, 255, 0))

    path = os.path.join("/tmp", f"cua_vision_bbox_debug_{int(time.time() * 1000)}.png")
    image.save(path)
    try:
        image.save("/tmp/cua_vision_bbox_debug_latest.png")
    except Exception:
        pass
    return path
