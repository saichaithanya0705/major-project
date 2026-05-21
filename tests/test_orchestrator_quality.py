from __future__ import annotations

import pytest

from models.orchestrator_contracts import OrchestrationPlan, OrchestratorTask, ResourceLock
from models.orchestrator_quality import validate_plan_quality


def test_validate_plan_quality_normalizes_direct_route_metadata_work_text() -> None:
    plan = OrchestrationPlan(
        request="finish tasks",
        tasks=(
            OrchestratorTask(
                id="direct-finish",
                agent="direct",
                resources=(ResourceLock.MODEL_ROUTER,),
                route={
                    "agent": "direct",
                    "direct_response_args": {"text": "Done.", "variant": "compact"},
                },
            ),
            OrchestratorTask(
                id="cli-patch",
                agent="cua_cli",
                task="Apply the patch",
                resources=(ResourceLock.CLI,),
            ),
        ),
        max_parallel=2,
        metadata={"payload": {"tasks": [{"agent": "direct"}, {"agent": "cua_cli"}]}},
    )

    validate_plan_quality(plan)


def test_validate_plan_quality_detects_duplicate_direct_work_after_normalization() -> None:
    plan = OrchestrationPlan(
        request="finish tasks",
        tasks=(
            OrchestratorTask(
                id="direct-a",
                agent="direct",
                resources=(ResourceLock.MODEL_ROUTER,),
                route={
                    "agent": "direct",
                    "direct_response_args": {"text": "Done.", "variant": "compact"},
                },
            ),
            OrchestratorTask(
                id="direct-b",
                agent="direct",
                resources=(ResourceLock.MODEL_ROUTER,),
                route={
                    "agent": "direct",
                    "response_text": "Done.",
                },
            ),
        ),
        max_parallel=2,
        metadata={"payload": {"tasks": [{"agent": "direct"}, {"agent": "direct"}]}},
    )

    with pytest.raises(ValueError, match="Duplicate plan work"):
        validate_plan_quality(plan)
