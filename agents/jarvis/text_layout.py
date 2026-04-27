"""
Text layout helpers for JARVIS overlay labels.
"""

from __future__ import annotations

_TEXT_PANEL_MAX_WIDTH_PX = 320
_TEXT_PANEL_MIN_WIDTH_PX = 96
_TEXT_PANEL_MIN_HEIGHT_PX = 44
_TEXT_HORIZONTAL_PADDING_PX = 40  # 20px left + 20px right
_TEXT_VERTICAL_PADDING_PX = 32  # 16px top + 16px bottom
_TEXT_LINE_HEIGHT_MULTIPLIER = 1.6
_TEXT_CHAR_WIDTH_MULTIPLIER = 0.56
_TEXT_SIZE_SAFETY_WIDTH_PX = 8
_TEXT_SIZE_SAFETY_HEIGHT_PX = 16
_TEXT_VIEWPORT_MARGIN_PX = 8
_TEXT_LAYOUT_STEP_PX = 28
_TEXT_LAYOUT_MAX_RINGS = 10
_TEXT_OVERLAP_BUFFER_PX = 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_align(align: str | None) -> str:
    value = str(align or "left").strip().lower()
    if value not in {"left", "center", "right"}:
        return "left"
    return value


def _normalize_baseline(baseline: str | None) -> str:
    value = str(baseline or "top").strip().lower()
    if value in {"middle", "center"}:
        return "middle"
    if value == "bottom":
        return "bottom"
    return "top"


def _wrap_line_to_width(raw_line: str, max_chars: int) -> list[str]:
    if max_chars <= 1:
        return list(raw_line) if raw_line else [""]

    words = raw_line.split(" ")
    lines = []
    current = ""

    def _append_long_word(word: str, existing: str):
        current_local = existing
        for idx in range(0, len(word), max_chars):
            chunk = word[idx:idx + max_chars]
            if idx == 0:
                current_local = chunk
            else:
                lines.append(current_local)
                current_local = chunk
        return current_local

    for word in words:
        if not current:
            if len(word) <= max_chars:
                current = word
            else:
                current = _append_long_word(word, current)
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        lines.append(current)
        if len(word) <= max_chars:
            current = word
        else:
            current = _append_long_word(word, "")

    lines.append(current if current else "")
    return lines


def _estimate_text_panel_size(text: str, font_size: int) -> tuple[int, int]:
    safe_text = str(text or "")
    safe_font_size = max(int(font_size or 18), 10)

    content_max_width = max(_TEXT_PANEL_MAX_WIDTH_PX - _TEXT_HORIZONTAL_PADDING_PX, 40)
    char_width = max(safe_font_size * _TEXT_CHAR_WIDTH_MULTIPLIER, 4.5)
    max_chars_per_line = max(1, int(content_max_width // char_width))

    wrapped_lines = []
    for raw_line in (safe_text.splitlines() or [""]):
        wrapped_lines.extend(_wrap_line_to_width(raw_line, max_chars_per_line))
    wrapped_lines = wrapped_lines or [""]

    line_count = max(len(wrapped_lines), 1)
    longest_line_chars = max((len(line) for line in wrapped_lines), default=1)

    content_width = min(
        content_max_width,
        max(char_width * max(longest_line_chars, 2), 24),
    )
    line_height = max(safe_font_size * _TEXT_LINE_HEIGHT_MULTIPLIER, safe_font_size + 4)
    content_height = max(line_count * line_height, line_height)

    panel_width = int(round(_clamp(
        content_width + _TEXT_HORIZONTAL_PADDING_PX + _TEXT_SIZE_SAFETY_WIDTH_PX,
        _TEXT_PANEL_MIN_WIDTH_PX,
        _TEXT_PANEL_MAX_WIDTH_PX,
    )))
    panel_height = int(round(max(
        content_height + _TEXT_VERTICAL_PADDING_PX + _TEXT_SIZE_SAFETY_HEIGHT_PX,
        _TEXT_PANEL_MIN_HEIGHT_PX,
    )))
    return panel_width, panel_height


def _anchor_to_rect(
    anchor_x: float,
    anchor_y: float,
    panel_width: int,
    panel_height: int,
    align: str,
    baseline: str,
    viewport_width: int,
    viewport_height: int,
) -> tuple[int, int, tuple[float, float, float, float]]:
    if align == "center":
        left = anchor_x - (panel_width / 2.0)
    elif align == "right":
        left = anchor_x - panel_width
    else:
        left = anchor_x

    if baseline == "middle":
        top = anchor_y - (panel_height / 2.0)
    elif baseline == "bottom":
        top = anchor_y - panel_height
    else:
        top = anchor_y

    horizontal_margin = _TEXT_VIEWPORT_MARGIN_PX
    vertical_margin = _TEXT_VIEWPORT_MARGIN_PX
    if panel_width + (2 * horizontal_margin) > viewport_width:
        horizontal_margin = 0
    if panel_height + (2 * vertical_margin) > viewport_height:
        vertical_margin = 0

    min_left = horizontal_margin
    min_top = vertical_margin
    max_left = max(viewport_width - panel_width - horizontal_margin, min_left)
    max_top = max(viewport_height - panel_height - vertical_margin, min_top)
    clamped_left = _clamp(left, min_left, max_left)
    clamped_top = _clamp(top, min_top, max_top)

    if align == "center":
        resolved_x = clamped_left + (panel_width / 2.0)
    elif align == "right":
        resolved_x = clamped_left + panel_width
    else:
        resolved_x = clamped_left

    if baseline == "middle":
        resolved_y = clamped_top + (panel_height / 2.0)
    elif baseline == "bottom":
        resolved_y = clamped_top + panel_height
    else:
        resolved_y = clamped_top

    rect = (
        float(clamped_left),
        float(clamped_top),
        float(clamped_left + panel_width),
        float(clamped_top + panel_height),
    )
    return int(round(resolved_x)), int(round(resolved_y)), rect


def _rects_overlap(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
    buffer: int = 0,
) -> bool:
    a_left, a_top, a_right, a_bottom = rect_a
    b_left, b_top, b_right, b_bottom = rect_b
    return (
        a_left < (b_right - buffer)
        and a_right > (b_left + buffer)
        and a_top < (b_bottom - buffer)
        and a_bottom > (b_top + buffer)
    )


def _intersection_area(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
) -> float:
    a_left, a_top, a_right, a_bottom = rect_a
    b_left, b_top, b_right, b_bottom = rect_b
    width = max(0.0, min(a_right, b_right) - max(a_left, b_left))
    height = max(0.0, min(a_bottom, b_bottom) - max(a_top, b_top))
    return width * height


def _has_text_overlap(
    rect: tuple[float, float, float, float],
    active_text_rects: dict[str, tuple[float, float, float, float]],
    ignore_text_id: str | None = None,
) -> bool:
    for other_id, other_rect in active_text_rects.items():
        if ignore_text_id and other_id == ignore_text_id:
            continue
        if _rects_overlap(rect, other_rect, _TEXT_OVERLAP_BUFFER_PX):
            return True
    return False


def _overlap_score(
    rect: tuple[float, float, float, float],
    active_text_rects: dict[str, tuple[float, float, float, float]],
    ignore_text_id: str | None = None,
) -> float:
    score = 0.0
    for other_id, other_rect in active_text_rects.items():
        if ignore_text_id and other_id == ignore_text_id:
            continue
        score += _intersection_area(rect, other_rect)
    return score


def resolve_non_overlapping_anchor(
    anchor_x: int,
    anchor_y: int,
    text: str,
    font_size: int,
    align: str | None,
    baseline: str | None,
    text_id: str | None,
    viewport_width: int,
    viewport_height: int,
    active_text_rects: dict[str, tuple[float, float, float, float]],
) -> tuple[int, int, tuple[float, float, float, float]]:
    norm_align = _normalize_align(align)
    norm_baseline = _normalize_baseline(baseline)
    panel_width, panel_height = _estimate_text_panel_size(text, font_size)

    resolved_x, resolved_y, base_rect = _anchor_to_rect(
        anchor_x,
        anchor_y,
        panel_width,
        panel_height,
        norm_align,
        norm_baseline,
        viewport_width,
        viewport_height,
    )
    if not _has_text_overlap(base_rect, active_text_rects, ignore_text_id=text_id):
        return resolved_x, resolved_y, base_rect

    best = (resolved_x, resolved_y, base_rect)
    best_score = _overlap_score(base_rect, active_text_rects, ignore_text_id=text_id)
    best_distance = 0

    for ring in range(1, _TEXT_LAYOUT_MAX_RINGS + 1):
        delta = ring * _TEXT_LAYOUT_STEP_PX
        offsets = (
            (0, -delta),
            (0, delta),
            (delta, 0),
            (-delta, 0),
            (delta, -delta),
            (-delta, -delta),
            (delta, delta),
            (-delta, delta),
            (2 * delta, 0),
            (-2 * delta, 0),
            (0, 2 * delta),
            (0, -2 * delta),
        )
        for dx, dy in offsets:
            cand_x, cand_y, cand_rect = _anchor_to_rect(
                anchor_x + dx,
                anchor_y + dy,
                panel_width,
                panel_height,
                norm_align,
                norm_baseline,
                viewport_width,
                viewport_height,
            )
            if not _has_text_overlap(cand_rect, active_text_rects, ignore_text_id=text_id):
                return cand_x, cand_y, cand_rect

            score = _overlap_score(cand_rect, active_text_rects, ignore_text_id=text_id)
            distance = abs(dx) + abs(dy)
            if score < best_score or (score == best_score and distance < best_distance):
                best = (cand_x, cand_y, cand_rect)
                best_score = score
                best_distance = distance

    return best
