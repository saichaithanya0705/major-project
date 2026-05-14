"""
Checks for CUA Vision trajectory recording.

Usage:
    python tests/test_cua_vision_trajectory.py
"""

import os
import sys
import tempfile

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.contracts import ActionResult, ActionType, ComputerAction, CriticVerdict  # noqa: E402
from agents.cua_vision.session_state import CuaSession  # noqa: E402
from agents.cua_vision.trajectory import CuaTrajectoryRecorder  # noqa: E402
from tests.cua_vision_tasks.fixtures import observation  # noqa: E402


def test_trajectory_retains_only_latest_live_screenshots() -> None:
    session = CuaSession.start("Click Save", observation(marker="initial"))
    recorder = CuaTrajectoryRecorder(max_live_screenshots=2)
    verdict = CriticVerdict(False, True, 0.7, "continue")

    for index in range(3):
        after = observation(marker=f"screen-{index}")
        recorder.record(
            session=session,
            action=ComputerAction(ActionType.WAIT),
            result=ActionResult(True, "waited", before=session.last_trusted_observation, after=after),
            verdict=verdict,
        )

    assert list(recorder.live_screenshots) == ["screen-1", "screen-2"]
    assert len(recorder.steps) == 3


def test_enabled_trajectory_writes_json_steps() -> None:
    session = CuaSession.start("Click Save", observation(marker="initial"))
    verdict = CriticVerdict(False, True, 0.7, "continue")
    with tempfile.TemporaryDirectory() as temp_dir:
        recorder = CuaTrajectoryRecorder(enabled=True, directory=temp_dir)
        recorder.record(
            session=session,
            action=ComputerAction(ActionType.WAIT),
            result=ActionResult(True, "waited", before=session.last_trusted_observation, after=observation()),
            verdict=verdict,
        )
        files = os.listdir(temp_dir)

    assert len(files) == 1
    assert files[0].endswith("-001.json")


def run_checks() -> None:
    test_trajectory_retains_only_latest_live_screenshots()
    test_enabled_trajectory_writes_json_steps()


if __name__ == "__main__":
    run_checks()
    print("[test_cua_vision_trajectory] All checks passed.")
