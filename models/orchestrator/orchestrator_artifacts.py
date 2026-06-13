"""
Artifact and context helpers for orchestration execution.

The executor owns task ordering. This module owns the pure data rules for which
completed task outputs become dependency context for later tasks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from models.orchestrator_contracts import (
    AgentStepOutcome,
    OrchestrationPlan,
    OrchestratorTask,
    TaskArtifact,
    TaskExecutionContext,
)
from models.output_file_artifacts import extract_output_file_path_from_tool_calls


def artifacts_from_outcome(outcome: AgentStepOutcome) -> tuple[TaskArtifact, ...]:
    """Return trusted artifacts produced by a completed task outcome."""
    if not outcome.success or not outcome.complete:
        return ()

    if isinstance(outcome.artifacts, Mapping):
        artifacts: list[TaskArtifact] = []
        for kind, value in outcome.artifacts.items():
            kind_text = str(kind or "").strip()
            if not kind_text:
                continue
            if not _is_trusted_artifact(outcome, kind_text, value):
                continue
            artifacts.append(
                TaskArtifact(
                    id=f"{outcome.task_id}:{kind_text}",
                    task_id=outcome.task_id,
                    agent=outcome.agent,
                    kind=kind_text,
                    value=value,
                    metadata=_artifact_metadata(outcome),
                )
            )
        return tuple(artifacts)

    if isinstance(outcome.artifacts, Sequence) and not isinstance(outcome.artifacts, (str, bytes, bytearray)):
        artifacts = []
        for index, value in enumerate(outcome.artifacts, start=1):
            artifacts.append(_artifact_from_sequence_item(outcome, value, index))
        return tuple(artifact for artifact in artifacts if artifact is not None)

    return ()


def context_for_task(
    plan: OrchestrationPlan,
    task: OrchestratorTask,
    *,
    outcomes_by_task: Mapping[str, AgentStepOutcome],
    artifacts: Sequence[TaskArtifact],
) -> TaskExecutionContext:
    """Build the dependency-scoped context visible to a task runner."""
    dependency_ids = tuple(task.depends_on)
    dependency_id_set = set(dependency_ids)
    dependency_outcomes = tuple(
        outcomes_by_task[dependency_id]
        for dependency_id in dependency_ids
        if dependency_id in outcomes_by_task
    )
    dependency_artifacts = tuple(artifact for artifact in artifacts if artifact.task_id in dependency_id_set)
    return TaskExecutionContext(
        request=plan.request,
        dependency_outcomes=dependency_outcomes,
        artifacts=dependency_artifacts,
        metadata={
            "task_id": task.id,
            "depends_on": dependency_ids,
        },
    )


def _artifact_from_sequence_item(
    outcome: AgentStepOutcome,
    value: object,
    index: int,
) -> TaskArtifact | None:
    if isinstance(value, Mapping):
        kind = str(value.get("kind") or value.get("type") or "artifact").strip()
        artifact_id = str(value.get("id") or f"{outcome.task_id}:{kind}-{index}").strip()
        artifact_value = value.get("value", value.get("data", dict(value)))
        metadata = value.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if not kind or not artifact_id:
            return None
        return TaskArtifact(
            id=artifact_id,
            task_id=outcome.task_id,
            agent=outcome.agent,
            kind=kind,
            value=artifact_value,
            metadata={**_artifact_metadata(outcome), **metadata},
        )

    return TaskArtifact(
        id=f"{outcome.task_id}:artifact-{index}",
        task_id=outcome.task_id,
        agent=outcome.agent,
        kind="artifact",
        value=value,
        metadata=_artifact_metadata(outcome),
    )


def _artifact_metadata(outcome: AgentStepOutcome) -> dict[str, Any]:
    source = outcome.metadata.get("source")
    metadata: dict[str, Any] = {}
    if source:
        metadata["source"] = source
    return metadata


def _is_trusted_artifact(outcome: AgentStepOutcome, kind: str, value: object) -> bool:
    if kind != "output_file_path":
        return True

    value_text = str(value or "").strip()
    if not value_text:
        return False

    raw_step_result = outcome.metadata.get("raw_step_result")
    if not isinstance(raw_step_result, Mapping):
        return True

    if str(raw_step_result.get("output_file_path") or "").strip() == value_text:
        return True

    explicit_artifacts = raw_step_result.get("artifacts")
    if isinstance(explicit_artifacts, Mapping):
        if str(explicit_artifacts.get("output_file_path") or "").strip() == value_text:
            return True

    return extract_output_file_path_from_tool_calls(raw_step_result.get("tool_calls")) == value_text
