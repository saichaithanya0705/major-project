"""
Chat artifact rendering for JARVIS screen analysis.
"""

from __future__ import annotations

import base64
import textwrap
from io import BytesIO
from typing import Any, Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFont


DEFAULT_OUTLINE_STROKE = "#2D6CDF"
DEFAULT_OUTLINE_WIDTH = 4
MAX_OUTLINE_WIDTH = 16
GEMINI_COORD_MAX = 1000.0
DEFAULT_LABEL_FILL = (245, 248, 252, 255)
DEFAULT_LABEL_BACKGROUND = (8, 10, 13, 224)
DEFAULT_LABEL_OUTLINE = (255, 255, 255, 96)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return min(max(value, minimum), maximum)


def _scale_coord(value: Any, extent: int, default: int = 0) -> int:
    try:
        scaled = round((float(value) / GEMINI_COORD_MAX) * max(extent - 1, 0))
    except (TypeError, ValueError):
        scaled = default
    return _clamp(int(scaled), 0, max(extent - 1, 0))


def _scale_length(value: Any, extent: int, default: int = 0) -> int:
    try:
        scaled = round((float(value) / GEMINI_COORD_MAX) * max(extent, 1))
    except (TypeError, ValueError):
        scaled = default
    return max(int(scaled), 0)


def _parse_color(value: Any, opacity: float) -> tuple[int, int, int, int]:
    color = str(value or DEFAULT_OUTLINE_STROKE).strip()
    try:
        r, g, b = ImageColor.getrgb(color)[:3]
    except Exception:
        r, g, b = ImageColor.getrgb(DEFAULT_OUTLINE_STROKE)
    alpha = _clamp(int(round(_clamp(int(opacity * 255), 0, 255))), 0, 255)
    return r, g, b, alpha


def _parse_solid_color(value: Any, fallback: str = DEFAULT_OUTLINE_STROKE) -> tuple[int, int, int, int]:
    color = str(value or fallback).strip()
    try:
        r, g, b = ImageColor.getrgb(color)[:3]
    except Exception:
        r, g, b = ImageColor.getrgb(fallback)[:3]
    return r, g, b, 255


def _rect_from_bounds(args: dict[str, Any], image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    width, height = image_size
    x_min = _scale_coord(args.get("x_min"), width)
    y_min = _scale_coord(args.get("y_min"), height)
    x_max = _scale_coord(args.get("x_max"), width)
    y_max = _scale_coord(args.get("y_max"), height)
    left, right = sorted((x_min, x_max))
    top, bottom = sorted((y_min, y_max))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _rect_from_box(box: dict[str, Any], image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    width, height = image_size
    left = _scale_coord(box.get("x"), width)
    top = _scale_coord(box.get("y"), height)
    box_width = _scale_length(box.get("width"), width)
    box_height = _scale_length(box.get("height"), height)
    right = _clamp(left + box_width, 0, max(width - 1, 0))
    bottom = _clamp(top + box_height, 0, max(height - 1, 0))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _iter_outline_boxes(tool_calls: Iterable[tuple[str, dict[str, Any]]], image_size: tuple[int, int]):
    for tool_name, args in tool_calls or []:
        if tool_name != "draw_bounding_box" or not isinstance(args, dict):
            continue

        rect = _rect_from_bounds(args, image_size)
        if rect is None:
            continue

        stroke_width = _clamp(_as_int(args.get("stroke_width"), DEFAULT_OUTLINE_WIDTH), 1, MAX_OUTLINE_WIDTH)
        opacity = min(max(_as_float(args.get("opacity"), 1.0), 0.15), 1.0)
        yield {
            "rect": rect,
            "stroke": _parse_color(args.get("stroke"), opacity),
            "stroke_width": stroke_width,
        }


def _load_font(font_size: int) -> ImageFont.ImageFont:
    size = _clamp(_as_int(font_size, 18), 9, 48)
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text or " ", font=font)
    return max(bbox[2] - bbox[0], 1), max(bbox[3] - bbox[1], 1)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    safe_text = " ".join(str(text or "").strip().split())
    if not safe_text:
        return []

    lines: list[str] = []
    for paragraph in safe_text.splitlines() or [safe_text]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and _text_bbox(draw, candidate, font)[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)

    if not lines:
        return []
    wrapped: list[str] = []
    for line in lines[:8]:
        if _text_bbox(draw, line, font)[0] <= max_width:
            wrapped.append(line)
            continue
        char_width = max(_text_bbox(draw, "M", font)[0], 1)
        width_chars = max(max_width // char_width, 4)
        wrapped.extend(textwrap.wrap(line, width=width_chars)[:3])
    return wrapped[:8]


def _anchor_to_label_rect(
    x: int,
    y: int,
    text_width: int,
    text_height: int,
    padding: int,
    align: str | None,
    baseline: str | None,
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    image_width, image_height = image_size
    align = (align or "left").lower()
    baseline = (baseline or "top").lower()

    if align == "center":
        left = x - (text_width // 2) - padding
    elif align == "right":
        left = x - text_width - (padding * 2)
    else:
        left = x

    if baseline in {"middle", "center"}:
        top = y - (text_height // 2) - padding
    elif baseline in {"bottom", "alphabetic"}:
        top = y - text_height - (padding * 2)
    else:
        top = y

    right = left + text_width + (padding * 2)
    bottom = top + text_height + (padding * 2)
    if right > image_width:
        left -= right - image_width
        right = image_width
    if bottom > image_height:
        top -= bottom - image_height
        bottom = image_height
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0

    return (
        _clamp(left, 0, max(image_width - 1, 0)),
        _clamp(top, 0, max(image_height - 1, 0)),
        _clamp(right, 1, max(image_width, 1)),
        _clamp(bottom, 1, max(image_height, 1)),
    )


def _draw_text_label(
    draw: ImageDraw.ImageDraw,
    image_size: tuple[int, int],
    x: int,
    y: int,
    text: Any,
    *,
    font_size: int = 18,
    align: str | None = "left",
    baseline: str | None = "top",
) -> bool:
    font = _load_font(font_size)
    padding = max(4, _as_int(font_size, 18) // 3)
    max_text_width = max(min(image_size[0] - (padding * 4), 420), 24)
    lines = _wrap_text(draw, str(text or "")[:400], font, max_text_width)
    if not lines:
        return False

    line_sizes = [_text_bbox(draw, line, font) for line in lines]
    text_width = max(width for width, _height in line_sizes)
    line_gap = max(2, _as_int(font_size, 18) // 5)
    text_height = sum(height for _width, height in line_sizes) + (line_gap * max(len(lines) - 1, 0))
    left, top, right, bottom = _anchor_to_label_rect(
        x,
        y,
        text_width,
        text_height,
        padding,
        align,
        baseline,
        image_size,
    )
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=6,
        fill=DEFAULT_LABEL_BACKGROUND,
        outline=DEFAULT_LABEL_OUTLINE,
        width=1,
    )

    cursor_y = top + padding
    for line, (_line_width, line_height) in zip(lines, line_sizes):
        draw.text((left + padding, cursor_y), line, fill=DEFAULT_LABEL_FILL, font=font)
        cursor_y += line_height + line_gap
    return True


def _draw_create_text(
    draw: ImageDraw.ImageDraw,
    image_size: tuple[int, int],
    args: dict[str, Any],
) -> int:
    x = _scale_coord(args.get("x"), image_size[0])
    y = _scale_coord(args.get("y"), image_size[1])
    return int(_draw_text_label(
        draw,
        image_size,
        x,
        y,
        args.get("text"),
        font_size=_as_int(args.get("font_size"), 18),
        align=args.get("align") or "left",
        baseline=args.get("baseline") or "top",
    ))


def _draw_text_for_box(
    draw: ImageDraw.ImageDraw,
    image_size: tuple[int, int],
    args: dict[str, Any],
) -> int:
    raw_box = args.get("box")
    if not isinstance(raw_box, dict):
        return 0
    rect = _rect_from_box(raw_box, image_size)
    if rect is None:
        return 0

    left, top, right, bottom = rect
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    padding = _as_int(args.get("padding"), 6)
    position = str(args.get("position") or "top").lower()
    align = args.get("align")
    if position == "bottom":
        anchor_x, anchor_y, baseline, default_align = center_x, bottom + padding, "top", "center"
    elif position == "left":
        anchor_x, anchor_y, baseline, default_align = left - padding, center_y, "middle", "right"
    elif position == "right":
        anchor_x, anchor_y, baseline, default_align = right + padding, center_y, "middle", "left"
    else:
        anchor_x, anchor_y, baseline, default_align = center_x, top - padding, "bottom", "center"

    return int(_draw_text_label(
        draw,
        image_size,
        anchor_x,
        anchor_y,
        args.get("text"),
        font_size=_as_int(args.get("font_size"), 18),
        align=align or default_align,
        baseline=baseline,
    ))


def _draw_pointer(
    draw: ImageDraw.ImageDraw,
    image_size: tuple[int, int],
    args: dict[str, Any],
) -> int:
    x = _scale_coord(args.get("x_pos"), image_size[0])
    y = _scale_coord(args.get("y_pos"), image_size[1])
    text_x = _scale_coord(args.get("text_x"), image_size[0])
    text_y = _scale_coord(args.get("text_y"), image_size[1])
    radius = _clamp(_as_int(args.get("radius"), 5), 3, 18)
    ring_radius = _clamp(_as_int(args.get("ring_radius"), radius + 5), radius + 2, 32)
    ring_color = _parse_solid_color(args.get("ring_color"), DEFAULT_OUTLINE_STROKE)
    dot_color = _parse_solid_color(args.get("dot_color"), "#ffffff")

    draw.line((x, y, text_x, text_y), fill=(255, 255, 255, 196), width=2)
    draw.ellipse((x - ring_radius, y - ring_radius, x + ring_radius, y + ring_radius), outline=ring_color, width=3)
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=dot_color)
    count = 1
    if _draw_text_label(
        draw,
        image_size,
        text_x,
        text_y,
        args.get("text"),
        font_size=_as_int(args.get("font_size"), 18),
        align="left",
        baseline="top",
    ):
        count += 1
    return count


def _image_to_png_data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_jarvis_visual_artifact(
    screenshot: Image.Image | None,
    tool_calls: Iterable[tuple[str, dict[str, Any]]] | None,
) -> dict[str, Any] | None:
    """Return a chat-safe screenshot artifact with JARVIS component outlines."""
    if screenshot is None:
        return None

    base = screenshot.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    outline_count = 0
    annotation_count = 0
    for box in _iter_outline_boxes(tool_calls or [], base.size):
        draw.rectangle(box["rect"], outline=box["stroke"], width=box["stroke_width"])
        outline_count += 1
        annotation_count += 1

    for tool_name, args in tool_calls or []:
        if not isinstance(args, dict):
            continue
        if tool_name == "create_text":
            annotation_count += _draw_create_text(draw, base.size, args)
        elif tool_name == "create_text_for_box":
            annotation_count += _draw_text_for_box(draw, base.size, args)
        elif tool_name == "draw_pointer_to_object":
            annotation_count += _draw_pointer(draw, base.size, args)

    if annotation_count == 0:
        return None

    annotated = Image.alpha_composite(base, overlay).convert("RGB")
    width, height = annotated.size
    return {
        "kind": "vision_screenshot",
        "title": "Analyzed screen",
        "imageDataUrl": _image_to_png_data_url(annotated),
        "width": width,
        "height": height,
        "outlineCount": outline_count,
        "annotationCount": annotation_count,
    }
