"""
Visual-effect verification helpers for CUA vision single-call execution.
"""

from __future__ import annotations

import numpy as np

from agents.cua_vision.action_guard import extract_position_bbox_args
from agents.cua_vision.image import similarity_score
from agents.cua_vision.screen_context import _bbox_to_capture_pixel_box


def image_similarity(before_frame, after_frame) -> float | None:
    if before_frame is None or after_frame is None:
        return None
    try:
        before_arr = np.array(before_frame)
        after_arr = np.array(after_frame)
        if before_arr.shape != after_arr.shape:
            return None
        return float(similarity_score(before_arr, after_arr))
    except Exception as e:
        print(f"[VisionAgent] Frame similarity failed: {e}")
        return None


def resolve_target_bbox_for_verification(
    *,
    tool_name: str,
    args: dict,
    click_tool_to_type: dict[str, str],
    last_position_bbox_args: dict | None,
) -> dict | None:
    bbox = extract_position_bbox_args(args)
    if bbox:
        return bbox
    if tool_name in click_tool_to_type or tool_name == "type_string":
        return last_position_bbox_args
    return None


def crop_target_region(
    *,
    frame,
    context: dict | None,
    bbox_args: dict | None,
    padding_px: int,
    min_side_px: int,
):
    if frame is None or context is None or bbox_args is None:
        return None
    try:
        left, top, right, bottom = _bbox_to_capture_pixel_box(
            bbox_args["ymin"],
            bbox_args["xmin"],
            bbox_args["ymax"],
            bbox_args["xmax"],
            context=context,
        )
        left = int(round(left))
        top = int(round(top))
        right = int(round(right))
        bottom = int(round(bottom))

        left -= padding_px
        top -= padding_px
        right += padding_px
        bottom += padding_px

        width, height = frame.size
        left = max(0, left)
        top = max(0, top)
        right = min(width, right)
        bottom = min(height, bottom)

        if right - left < min_side_px:
            deficit = min_side_px - (right - left)
            left = max(0, left - (deficit // 2))
            right = min(width, right + (deficit - (deficit // 2)))
        if bottom - top < min_side_px:
            deficit = min_side_px - (bottom - top)
            top = max(0, top - (deficit // 2))
            bottom = min(height, bottom + (deficit - (deficit // 2)))

        if right <= left or bottom <= top:
            return None
        return frame.crop((left, top, right, bottom))
    except Exception as e:
        print(f"[VisionAgent] Target crop failed: {e}")
        return None


def visual_similarity_metrics(
    *,
    tool_name: str,
    args: dict,
    before_frame,
    before_context: dict | None,
    after_frame,
    after_context: dict | None,
    click_tool_to_type: dict[str, str],
    last_position_bbox_args: dict | None,
    target_region_padding_px: int,
    target_region_min_side_px: int,
) -> dict:
    metrics = {
        "global_similarity": image_similarity(before_frame, after_frame),
        "target_similarity": None,
    }

    target_bbox = resolve_target_bbox_for_verification(
        tool_name=tool_name,
        args=args,
        click_tool_to_type=click_tool_to_type,
        last_position_bbox_args=last_position_bbox_args,
    )
    if target_bbox is not None:
        before_crop = crop_target_region(
            frame=before_frame,
            context=before_context,
            bbox_args=target_bbox,
            padding_px=target_region_padding_px,
            min_side_px=target_region_min_side_px,
        )
        after_crop = crop_target_region(
            frame=after_frame,
            context=after_context,
            bbox_args=target_bbox,
            padding_px=target_region_padding_px,
            min_side_px=target_region_min_side_px,
        )
        metrics["target_similarity"] = image_similarity(before_crop, after_crop)

    return metrics
