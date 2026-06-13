"""
Shared typed payloads for rapid step results and orchestration context handoff.
"""

from __future__ import annotations

from typing import TypeAlias, TypedDict

from models.router_backend_types import JsonObject, JsonValue


class RapidToolCallRecord(TypedDict, total=False):
    tool_name: str
    name: str
    status: str
    parameters: JsonObject
    arguments: JsonObject
    result: JsonValue
    error: str


class RapidSourceRecord(TypedDict, total=False):
    title: str
    url: str
    snippet: str
    source: str


class RapidStepMetadataPayload(TypedDict, total=False):
    traceback: str
    result: JsonValue | None
    tool_calls: list[RapidToolCallRecord]
    complete: bool
    critic: JsonObject


class RapidStepArtifactsPayload(TypedDict, total=False):
    output_file_path: str
    sources: list[RapidSourceRecord]


RapidStepArtifactCollection: TypeAlias = RapidStepArtifactsPayload | tuple[object, ...]


class RapidTaskArtifactPayload(TypedDict):
    id: str
    task_id: str
    agent: str
    kind: str
    value: object
    metadata: dict[str, object]


class RapidLegacyOutcomePayload(TypedDict):
    task_id: str
    agent: str
    success: bool
    complete: bool
    message: str
    artifacts: dict[str, object] | tuple[object, ...]
    metadata: dict[str, object]
    needs_followup: bool


class RapidTaskExecutionContextPayload(TypedDict):
    request: str
    dependency_outcomes: tuple[RapidLegacyOutcomePayload, ...]
    artifacts: tuple[RapidTaskArtifactPayload, ...]
    metadata: dict[str, object]


__all__ = [
    "RapidLegacyOutcomePayload",
    "RapidSourceRecord",
    "RapidStepArtifactCollection",
    "RapidStepArtifactsPayload",
    "RapidStepMetadataPayload",
    "RapidTaskArtifactPayload",
    "RapidTaskExecutionContextPayload",
    "RapidToolCallRecord",
]
