"""
Regression checks for JARVIS screen-analysis chat artifacts.
"""

from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image


def test_jarvis_visual_artifact_draws_outlines_on_full_screenshot() -> None:
    from agents.jarvis.artifact import build_jarvis_visual_artifact

    screenshot = Image.new("RGB", (200, 100), "white")
    artifact = build_jarvis_visual_artifact(
        screenshot,
        [
            (
                "draw_bounding_box",
                {
                    "time": 0.1,
                    "y_min": 100,
                    "x_min": 100,
                    "y_max": 500,
                    "x_max": 500,
                    "stroke": "#ff0000",
                    "stroke_width": 4,
                    "opacity": 1.0,
                },
            )
        ],
    )

    assert artifact is not None
    assert artifact["kind"] == "vision_screenshot"
    assert artifact["width"] == 200
    assert artifact["height"] == 100
    assert artifact["outlineCount"] == 1
    assert artifact["imageDataUrl"].startswith("data:image/png;base64,")

    encoded = artifact["imageDataUrl"].split(",", 1)[1]
    outlined = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")
    assert outlined.size == (200, 100)
    assert outlined.getpixel((20, 10)) != (255, 255, 255)


def test_jarvis_visual_artifact_scales_gemini_coordinates_to_screenshot_edges() -> None:
    from agents.jarvis.artifact import build_jarvis_visual_artifact

    screenshot = Image.new("RGB", (200, 100), "white")
    artifact = build_jarvis_visual_artifact(
        screenshot,
        [
            (
                "draw_bounding_box",
                {
                    "time": 0.1,
                    "y_min": 250,
                    "x_min": 500,
                    "y_max": 750,
                    "x_max": 1000,
                    "stroke": "#0055ff",
                    "stroke_width": 3,
                    "opacity": 1.0,
                },
            )
        ],
    )

    assert artifact is not None
    encoded = artifact["imageDataUrl"].split(",", 1)[1]
    outlined = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")

    assert outlined.getpixel((100, 25)) != (255, 255, 255)
    assert outlined.getpixel((199, 50)) != (255, 255, 255)


def test_jarvis_visual_artifact_renders_text_and_pointer_annotations() -> None:
    from agents.jarvis.artifact import build_jarvis_visual_artifact

    screenshot = Image.new("RGB", (240, 140), "white")
    artifact = build_jarvis_visual_artifact(
        screenshot,
        [
            (
                "create_text",
                {
                    "time": 0.1,
                    "x": 500,
                    "y": 500,
                    "text": "Terminal",
                    "font_size": 16,
                    "align": "center",
                    "baseline": "middle",
                },
            ),
            (
                "draw_pointer_to_object",
                {
                    "time": 0.2,
                    "x_pos": 250,
                    "y_pos": 250,
                    "text": "Explorer",
                    "text_x": 520,
                    "text_y": 300,
                    "dot_color": "#ff0000",
                    "ring_color": "#0055ff",
                },
            ),
            (
                "create_text_for_box",
                {
                    "time": 0.3,
                    "box": {"x": 100, "y": 100, "width": 250, "height": 250},
                    "text": "File list",
                    "position": "bottom",
                    "font_size": 14,
                    "padding": 8,
                },
            ),
        ],
    )

    assert artifact is not None
    assert artifact["outlineCount"] == 0
    assert artifact["annotationCount"] == 4

    encoded = artifact["imageDataUrl"].split(",", 1)[1]
    annotated = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGB")
    changed_pixels = sum(
        1
        for y in range(annotated.height)
        for x in range(annotated.width)
        if annotated.getpixel((x, y)) != (255, 255, 255)
    )
    assert changed_pixels > 250


def test_jarvis_box_cleanup_waits_until_after_final_annotation() -> None:
    import agents.jarvis.tools as tools

    tools.stop_all_actions()
    try:
        tools.draw_bounding_box(
            time=0.2,
            y_min=10,
            x_min=20,
            y_max=50,
            x_max=70,
            box_id="first_component_box",
        )
        tools.destroy_box(time=1.0, box_id="first_component_box")
        tools.draw_bounding_box(
            time=0.4,
            y_min=55,
            x_min=20,
            y_max=75,
            x_max=70,
            box_id="final_component_box",
        )
        tools.clear_screen(time=4.0)

        queued = list(tools.ACTION_QUEUE)
        draw_actions = [
            item
            for item in queued
            if getattr(item[1], "__name__", "") == "_draw_bounding_box"
        ]
        assert len(draw_actions) == 2
        assert abs(draw_actions[0][0] - 0.2) < 0.001
        assert abs(draw_actions[1][0] - 2.2) < 0.001

        destroy_actions = [
            item
            for item in queued
            if getattr(item[1], "__name__", "") == "_destroy_box"
            and item[2] == ("first_component_box",)
        ]
        assert destroy_actions, queued
        assert abs(destroy_actions[0][0] - 9.2) < 0.001

        clear_actions = [
            item
            for item in queued
            if getattr(item[1], "__name__", "") == "_clear_screen_with_layout_reset"
        ]
        assert clear_actions, queued
        assert abs(clear_actions[0][0] - 9.2) < 0.001
    finally:
        tools.stop_all_actions()


def test_jarvis_clear_annotation_actions_cancels_pending_visuals() -> None:
    import agents.jarvis.tools as tools

    tools.stop_all_actions()
    try:
        tools.draw_bounding_box(
            time=0.2,
            y_min=10,
            x_min=20,
            y_max=50,
            x_max=70,
            box_id="component_box",
        )
        tools.create_text(time=2.0, x=100, y=100, text="Component")

        tools.clear_annotation_actions()

        assert list(tools.ACTION_QUEUE) == []
    finally:
        tools.stop_all_actions()


def test_jarvis_initial_clear_stays_immediate_and_annotations_auto_clear() -> None:
    import agents.jarvis.tools as tools

    tools.stop_all_actions()
    try:
        tools.clear_screen(time=0.0)
        tools.draw_bounding_box(
            time=0.2,
            y_min=10,
            x_min=20,
            y_max=50,
            x_max=70,
            box_id="component_box",
        )

        queued = list(tools.ACTION_QUEUE)
        clear_actions = [
            item
            for item in queued
            if getattr(item[1], "__name__", "") == "_clear_screen_with_layout_reset"
        ]
        assert len(clear_actions) == 2
        assert abs(clear_actions[0][0] - 0.0) < 0.001
        assert abs(clear_actions[1][0] - 7.2) < 0.001
        assert clear_actions[1][3].get("restore_chat") is True
    finally:
        tools.stop_all_actions()
