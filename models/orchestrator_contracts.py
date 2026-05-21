"""
Typed contracts for future multi-agent orchestration.

This module is intentionally pure and runtime-agnostic.  It defines the stable
data shapes Level 2 adapters can consume without coupling to execution code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from models.rapid_step_payloads import (
    RapidLegacyOutcomePayload,
    RapidTaskArtifactPayload,
    RapidTaskExecutionContextPayload,
)
from models.routing_payload_parser import RoutePayload

OrchestratorAgent = Literal[
    "direct",
    "jarvis",
    "browser",
    "cua_cli",
    "cua_vision",
    "screen_context",
    "web_qa",
]

KNOWN_ORCHESTRATOR_AGENTS: tuple[str, ...] = (
    "direct",
    "jarvis",
    "browser",
    "cua_cli",
    "cua_vision",
    "screen_context",
    "web_qa",
)


class ResourceLock(str, Enum):
    CLI = "cli"
    BROWSER = "browser"
    DESKTOP = "desktop"
    SCREENSHOT = "screenshot"
    WEB_QA = "web_qa"
    MODEL_ROUTER = "model_router"
    MODEL_VISION = "model_vision"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrchestrationTraceEventType(str, Enum):
    PLANNED = "planned"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRIED = "retried"


def resources_for_agent(agent: str) -> tuple[ResourceLock, ...]:
    """Return conservative default locks for an orchestrator agent."""
    _validate_agent(agent)
    mapping: dict[str, tuple[ResourceLock, ...]] = {
        "direct": (ResourceLock.MODEL_ROUTER,),
        "jarvis": (
            ResourceLock.SCREENSHOT,
            ResourceLock.MODEL_ROUTER,
            ResourceLock.MODEL_VISION,
        ),
        "browser": (ResourceLock.BROWSER, ResourceLock.MODEL_ROUTER),
        "cua_cli": (ResourceLock.CLI,),
        "cua_vision": (
            ResourceLock.DESKTOP,
            ResourceLock.SCREENSHOT,
            ResourceLock.MODEL_VISION,
        ),
        "screen_context": (
            ResourceLock.SCREENSHOT,
            ResourceLock.MODEL_VISION,
        ),
        "web_qa": (ResourceLock.WEB_QA,),
    }
    return mapping[agent]


@dataclass(frozen=True, slots=True)
class OrchestratorTask:
    id: str
    agent: OrchestratorAgent
    task: str = ""
    query: str = ""
    route: RoutePayload = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    resources: tuple[ResourceLock, ...] = ()
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        task_id = self.id.strip() if isinstance(self.id, str) else ""
        if not task_id:
            raise ValueError("OrchestratorTask id must be non-empty.")
        object.__setattr__(self, "id", task_id)

        _validate_agent(self.agent)
        if self.attempts < 0:
            raise ValueError("OrchestratorTask attempts must be non-negative.")
        if self.max_attempts < 1:
            raise ValueError("OrchestratorTask max_attempts must be at least 1.")

        depends_on = tuple(self.depends_on)
        if task_id in depends_on:
            raise ValueError("OrchestratorTask cannot depend on itself.")
        object.__setattr__(self, "depends_on", depends_on)
        object.__setattr__(self, "route", dict(self.route))
        resources = normalize_resource_locks(self.resources or resources_for_agent(self.agent))
        required_resources = resources_for_agent(self.agent)
        missing_resources = tuple(resource for resource in required_resources if resource not in resources)
        if missing_resources:
            missing_list = ", ".join(resource.value for resource in missing_resources)
            raise ValueError(
                f"OrchestratorTask resources for agent {self.agent!r} must include "
                f"required resource lock(s): {missing_list}."
            )
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "status", _coerce_task_status(self.status))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentStepOutcome:
    task_id: str
    agent: OrchestratorAgent
    success: bool
    complete: bool
    message: str = ""
    artifacts: tuple[Any, ...] | dict[str, Any] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    needs_followup: bool = False

    def __post_init__(self) -> None:
        task_id = self.task_id.strip() if isinstance(self.task_id, str) else ""
        if not task_id:
            raise ValueError("AgentStepOutcome task_id must be non-empty.")
        _validate_agent(self.agent)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "metadata", dict(self.metadata))
        if isinstance(self.artifacts, dict):
            object.__setattr__(self, "artifacts", dict(self.artifacts))
        else:
            object.__setattr__(self, "artifacts", tuple(self.artifacts))


@dataclass(frozen=True, slots=True)
class TaskArtifact:
    id: str
    task_id: str
    agent: OrchestratorAgent
    kind: str
    value: Any
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        artifact_id = self.id.strip() if isinstance(self.id, str) else ""
        if not artifact_id:
            raise ValueError("TaskArtifact id must be non-empty.")
        task_id = self.task_id.strip() if isinstance(self.task_id, str) else ""
        if not task_id:
            raise ValueError("TaskArtifact task_id must be non-empty.")
        kind = self.kind.strip() if isinstance(self.kind, str) else ""
        if not kind:
            raise ValueError("TaskArtifact kind must be non-empty.")
        _validate_agent(self.agent)
        object.__setattr__(self, "id", artifact_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class TaskExecutionContext:
    request: str
    dependency_outcomes: tuple[AgentStepOutcome, ...] = ()
    artifacts: tuple[TaskArtifact, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request", str(self.request or ""))
        object.__setattr__(self, "dependency_outcomes", tuple(self.dependency_outcomes))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    request: str
    tasks: tuple[OrchestratorTask, ...]
    max_parallel: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_parallel < 1:
            raise ValueError("OrchestrationPlan max_parallel must be at least 1.")

        tasks = tuple(self.tasks)
        seen: set[str] = set()
        duplicates: set[str] = set()
        for task in tasks:
            if task.id in seen:
                duplicates.add(task.id)
            seen.add(task.id)
        if duplicates:
            duplicate_list = ", ".join(sorted(duplicates))
            raise ValueError(f"Duplicate task id(s): {duplicate_list}")

        unknown_dependencies = sorted(
            {
                dependency
                for task in tasks
                for dependency in task.depends_on
                if dependency not in seen
            }
        )
        if unknown_dependencies:
            dependency_list = ", ".join(unknown_dependencies)
            raise ValueError(f"Unknown task dependency id(s): {dependency_list}")

        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationTraceEvent:
    sequence: int
    event_type: OrchestrationTraceEventType
    task_id: str = ""
    agent: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("OrchestrationTraceEvent sequence must be positive.")
        object.__setattr__(self, "event_type", OrchestrationTraceEventType(self.event_type))
        object.__setattr__(self, "task_id", str(self.task_id or "").strip())
        object.__setattr__(self, "agent", str(self.agent or "").strip())
        object.__setattr__(self, "message", str(self.message or "").strip())
        object.__setattr__(self, "metadata", dict(self.metadata))


def agent_step_outcome_to_dict(outcome: AgentStepOutcome) -> RapidLegacyOutcomePayload:
    """Return a plain metadata-safe representation of an agent step outcome."""
    return {
        "task_id": outcome.task_id,
        "agent": outcome.agent,
        "success": outcome.success,
        "complete": outcome.complete,
        "message": outcome.message,
        "artifacts": dict(outcome.artifacts)
        if isinstance(outcome.artifacts, dict)
        else tuple(outcome.artifacts),
        "metadata": dict(outcome.metadata),
        "needs_followup": outcome.needs_followup,
    }


def orchestration_trace_event_to_dict(event: OrchestrationTraceEvent) -> dict[str, Any]:
    """Return a serializable trace event for logs and UI snapshots."""
    return {
        "sequence": event.sequence,
        "event_type": event.event_type.value,
        "task_id": event.task_id,
        "agent": event.agent,
        "message": event.message,
        "metadata": dict(event.metadata),
    }


def task_artifact_to_dict(artifact: TaskArtifact) -> RapidTaskArtifactPayload:
    """Return a plain representation of an artifact produced by a task."""
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "agent": artifact.agent,
        "kind": artifact.kind,
        "value": artifact.value,
        "metadata": dict(artifact.metadata),
    }


def task_execution_context_to_dict(context: TaskExecutionContext) -> RapidTaskExecutionContextPayload:
    """Return a serializable task context for legacy route metadata."""
    return {
        "request": context.request,
        "dependency_outcomes": tuple(
            agent_step_outcome_to_dict(outcome) for outcome in context.dependency_outcomes
        ),
        "artifacts": tuple(task_artifact_to_dict(artifact) for artifact in context.artifacts),
        "metadata": dict(context.metadata),
    }


def _validate_agent(agent: str) -> None:
    if agent not in KNOWN_ORCHESTRATOR_AGENTS:
        allowed = ", ".join(KNOWN_ORCHESTRATOR_AGENTS)
        raise ValueError(f"Unknown orchestrator agent {agent!r}; expected one of: {allowed}.")


def normalize_resource_locks(resources: tuple[ResourceLock, ...]) -> tuple[ResourceLock, ...]:
    """Return resource locks coerced to enum values and deduplicated in input order."""
    normalized: list[ResourceLock] = []
    seen: set[ResourceLock] = set()
    for resource in resources:
        lock = ResourceLock(resource)
        if lock in seen:
            continue
        seen.add(lock)
        normalized.append(lock)
    return tuple(normalized)


def _coerce_task_status(status: TaskStatus) -> TaskStatus:
    return TaskStatus(status)
