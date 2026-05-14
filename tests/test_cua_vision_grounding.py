"""
Checks for CUA Vision target grounding.

Usage:
    python tests/test_cua_vision_grounding.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionType, ComputerAction, TargetKind, TargetRef  # noqa: E402
from agents.cua_vision.grounding import (  # noqa: E402
    GROUNDING_GROUNDED,
    GROUNDING_NEEDS_STRONGER_MODEL,
    CuaGrounder,
    GroundedTarget,
)
from tests.cua_vision_tasks.fixtures import observation  # noqa: E402


def test_bbox_target_maps_to_screen_coordinate() -> None:
    action = ComputerAction(
        ActionType.CLICK,
        target=TargetRef(TargetKind.BBOX, bbox=(100, 100, 200, 200), description="Save"),
    )

    result = CuaGrounder().ground(action, observation())

    assert result.status == GROUNDING_GROUNDED
    assert result.action.target.kind == TargetKind.COORDINATE
    assert result.action.target.x == 160.0
    assert result.action.target.y == 170.0


def test_description_target_without_grounder_requests_stronger_model() -> None:
    action = ComputerAction(
        ActionType.CLICK,
        target=TargetRef(TargetKind.DESCRIPTION, description="Save button"),
    )

    result = CuaGrounder().ground(action, observation())

    assert result.status == GROUNDING_NEEDS_STRONGER_MODEL
    assert result.needs_stronger_model


def test_low_confidence_description_grounding_requests_stronger_model() -> None:
    action = ComputerAction(
        ActionType.CLICK,
        target=TargetRef(TargetKind.DESCRIPTION, description="Save button"),
    )
    grounder = CuaGrounder(
        description_grounder=lambda _description, _observation: GroundedTarget(
            x=10,
            y=20,
            confidence=0.2,
            source="fake",
            evidence={},
        )
    )

    result = grounder.ground(action, observation())

    assert result.status == GROUNDING_NEEDS_STRONGER_MODEL
    assert result.target is not None
    assert result.target.confidence == 0.2


def test_element_id_uses_accessibility_bounds() -> None:
    obs = observation()
    obs = type(obs)(
        screenshot_png_base64=obs.screenshot_png_base64,
        active_window_title=obs.active_window_title,
        capture_context=obs.capture_context,
        elements=(
            {
                "id": "save",
                "bounds": {"left": 20, "top": 30, "right": 60, "bottom": 70},
                "confidence": 0.88,
            },
        ),
    )
    action = ComputerAction(
        ActionType.CLICK,
        target=TargetRef(TargetKind.ELEMENT_ID, element_id="save"),
    )

    result = CuaGrounder().ground(action, obs)

    assert result.status == GROUNDING_GROUNDED
    assert result.action.target.x == 40.0
    assert result.action.target.y == 50.0


def run_checks() -> None:
    test_bbox_target_maps_to_screen_coordinate()
    test_description_target_without_grounder_requests_stronger_model()
    test_low_confidence_description_grounding_requests_stronger_model()
    test_element_id_uses_accessibility_bounds()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_grounding] All checks passed.")
