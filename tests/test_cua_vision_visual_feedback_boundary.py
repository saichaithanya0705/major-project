"""
Checks for extracted CUA vision visual-feedback helpers.

Usage:
    python tests/test_cua_vision_visual_feedback_boundary.py
"""

import os
import sys

from PIL import Image

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.visual_feedback import visual_similarity_metrics


def run_checks() -> None:
    before = Image.new("RGB", (500, 500), color="white")
    after = Image.new("RGB", (500, 500), color="white")
    for x in range(98, 103):
        for y in range(98, 103):
            after.putpixel((x, y), (0, 0, 0))

    context = {
        "width": 500,
        "height": 500,
        "logical_width": 500,
        "logical_height": 500,
        "offset_x": 0.0,
        "offset_y": 0.0,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "mode": "active_window",
    }

    metrics = visual_similarity_metrics(
        tool_name="click_left_click",
        args={"target_description": "Save"},
        before_frame=before,
        before_context=context,
        after_frame=after,
        after_context=context,
        click_tool_to_type={
            "click_left_click": "left click",
            "click_double_left_click": "double left click",
            "click_right_click": "right click",
        },
        last_position_bbox_args={
            "ymin": 190.0,
            "xmin": 190.0,
            "ymax": 210.0,
            "xmax": 210.0,
        },
        target_region_padding_px=24,
        target_region_min_side_px=48,
    )

    assert metrics["global_similarity"] is not None, metrics
    assert metrics["target_similarity"] is not None, metrics
    assert metrics["target_similarity"] < 1.0, metrics


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_visual_feedback_boundary] All checks passed.")
