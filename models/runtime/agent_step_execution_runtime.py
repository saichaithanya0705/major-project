"""Shared delegated-agent execution helpers for routed step handling."""

from __future__ import annotations

import asyncio
import os
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, TypedDict, cast

from models.router_backend_types import JsonObject, JsonValue
from models.rapid_step_payloads import RapidToolCallRecord

T = TypeVar("T")
_INVALID = object()
DEFAULT_VISION_AGENT_TIMEOUT_SECONDS = 150.0

StatusCallback = Callable[[str], Awaitable[None]]


class AgentExecutionPayload(TypedDict, total=False):
    success: bool
    result: object
    error: str | None
    complete: bool
    tool_calls: list[RapidToolCallRecord]
    critic: JsonObject


@dataclass(frozen=True, slots=True)
class CapturedAsyncOutcome(Generic[T]):
    value: T | None
    error: Exception | None = None
    traceback_text: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True, slots=True)
class AgentExecutionOutcome:
    payload: AgentExecutionPayload
    traceback_text: str | None = None

    @property
    def success(self) -> bool:
        return bool(self.payload.get("success", False))

    @property
    def result(self) -> object:
        return self.payload.get("result")

    @property
    def result_metadata(self) -> JsonValue | None:
        normalized = _coerce_json_value(self.result)
        if normalized is _INVALID:
            return None
        return cast(JsonValue, normalized)

    @property
    def error(self) -> str | None:
        return self.payload.get("error")

    @property
    def complete(self) -> bool | None:
        complete = self.payload.get("complete")
        return complete if isinstance(complete, bool) else None

    @property
    def tool_calls(self) -> list[RapidToolCallRecord] | None:
        return self.payload.get("tool_calls")

    @property
    def critic(self) -> JsonObject | None:
        return self.payload.get("critic")


class TaskAgent(Protocol):
    async def execute(self, task: str) -> Mapping[str, object]: ...


class CliTaskAgent(Protocol):
    async def execute(
        self,
        task: str,
        status_callback: StatusCallback | None = None,
    ) -> Mapping[str, object]: ...


class VisionTaskAgent(Protocol):
    async def execute(
        self,
        task: str,
        screenshot: object = None,
    ) -> Mapping[str, object]: ...


async def capture_async_operation(
    operation: Callable[[], Awaitable[T]],
) -> CapturedAsyncOutcome[T]:
    try:
        return CapturedAsyncOutcome(value=await operation())
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return CapturedAsyncOutcome(
            value=None,
            error=exc,
            traceback_text=traceback.format_exc(),
        )


def _coerce_json_value(value: object) -> JsonValue | object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        normalized_items: list[JsonValue] = []
        for item in value:
            normalized = _coerce_json_value(item)
            if normalized is _INVALID:
                return _INVALID
            normalized_items.append(cast(JsonValue, normalized))
        return normalized_items
    if isinstance(value, Mapping):
        normalized_mapping: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return _INVALID
            normalized = _coerce_json_value(item)
            if normalized is _INVALID:
                return _INVALID
            normalized_mapping[key] = cast(JsonValue, normalized)
        return normalized_mapping
    return _INVALID


def _coerce_json_object(value: object) -> JsonObject | None:
    if not isinstance(value, Mapping):
        return None
    normalized_object: JsonObject = {}
    for key, raw_item in value.items():
        if not isinstance(key, str):
            continue
        normalized_item = _coerce_json_value(raw_item)
        if normalized_item is _INVALID:
            continue
        normalized_object[key] = cast(JsonValue, normalized_item)
    return normalized_object or None


def _coerce_tool_call(value: object) -> RapidToolCallRecord | None:
    if not isinstance(value, Mapping):
        return None

    normalized: dict[str, JsonValue] = {}
    for key, raw_item in value.items():
        if not isinstance(key, str):
            continue
        if key in {"parameters", "arguments"}:
            normalized_item = _coerce_json_object(raw_item)
        else:
            normalized_item = _coerce_json_value(raw_item)
            if normalized_item is _INVALID:
                normalized_item = None
        if normalized_item is not None:
            normalized[key] = cast(JsonValue, normalized_item)

    return cast(RapidToolCallRecord, normalized) or None


def _coerce_tool_calls(value: object) -> list[RapidToolCallRecord] | None:
    if not isinstance(value, list):
        return None
    normalized: list[RapidToolCallRecord] = []
    for item in value:
        record = _coerce_tool_call(item)
        if record is not None:
            normalized.append(record)
    return normalized or None


def _coerce_agent_payload(value: Mapping[str, object]) -> AgentExecutionPayload:
    payload: AgentExecutionPayload = {
        "success": bool(value.get("success", False)),
        "result": value.get("result"),
    }
    if "error" in value:
        error = value.get("error")
        payload["error"] = None if error is None else str(error)
    if isinstance(value.get("complete"), bool):
        payload["complete"] = bool(value.get("complete"))
    tool_calls = _coerce_tool_calls(value.get("tool_calls"))
    if tool_calls is not None:
        payload["tool_calls"] = tool_calls
    critic = _coerce_json_object(value.get("critic"))
    if critic is not None:
        payload["critic"] = critic
    return payload


async def capture_agent_execution(
    operation: Callable[[], Awaitable[Mapping[str, object]]],
    *,
    failure_complete: bool | None = None,
    timeout_seconds: float | None = None,
) -> AgentExecutionOutcome:
    async def _operation_with_optional_timeout() -> Mapping[str, object]:
        if timeout_seconds is None:
            return await operation()
        return await asyncio.wait_for(operation(), timeout=timeout_seconds)

    outcome = await capture_async_operation(_operation_with_optional_timeout)
    if outcome.succeeded:
        value = outcome.value
        if isinstance(value, Mapping):
            return AgentExecutionOutcome(payload=_coerce_agent_payload(value))
        return AgentExecutionOutcome(
            payload={
                "success": False,
                "result": value,
                "error": "Agent returned an invalid result payload.",
            }
        )

    error_text = str(outcome.error)
    if isinstance(outcome.error, TimeoutError) or not error_text:
        timeout_bits = (
            f" after {timeout_seconds:.1f}s"
            if timeout_seconds is not None
            else ""
        )
        error_text = f"Agent execution timed out{timeout_bits}."

    payload: AgentExecutionPayload = {
        "success": False,
        "result": None,
        "error": error_text,
    }
    if failure_complete is not None:
        payload["complete"] = failure_complete
    return AgentExecutionOutcome(
        payload=payload,
        traceback_text=outcome.traceback_text,
    )


async def execute_task_agent(
    *,
    task: str,
    agent_factory: Callable[[], TaskAgent],
    failure_complete: bool | None = None,
) -> AgentExecutionOutcome:
    async def _run() -> Mapping[str, object]:
        return await agent_factory().execute(task)

    return await capture_agent_execution(_run, failure_complete=failure_complete)


async def execute_cli_agent(
    *,
    task: str,
    agent_factory: Callable[[], CliTaskAgent],
    status_callback: StatusCallback | None = None,
) -> AgentExecutionOutcome:
    async def _run() -> Mapping[str, object]:
        return await agent_factory().execute(task, status_callback=status_callback)

    return await capture_agent_execution(_run)


async def execute_vision_agent(
    *,
    task: str,
    screenshot: object,
    agent_factory: Callable[[], VisionTaskAgent],
    timeout_seconds: float | None = None,
) -> AgentExecutionOutcome:
    async def _run() -> Mapping[str, object]:
        return await agent_factory().execute(task, screenshot)

    return await capture_agent_execution(
        _run,
        failure_complete=False,
        timeout_seconds=_resolve_vision_timeout_seconds(timeout_seconds),
    )


def _resolve_vision_timeout_seconds(timeout_seconds: float | None) -> float:
    if timeout_seconds is not None:
        return max(0.001, float(timeout_seconds))
    raw = os.getenv("CUA_VISION_AGENT_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_VISION_AGENT_TIMEOUT_SECONDS


__all__ = [
    "AgentExecutionOutcome",
    "AgentExecutionPayload",
    "CapturedAsyncOutcome",
    "CliTaskAgent",
    "DEFAULT_VISION_AGENT_TIMEOUT_SECONDS",
    "StatusCallback",
    "TaskAgent",
    "VisionTaskAgent",
    "capture_agent_execution",
    "capture_async_operation",
    "execute_cli_agent",
    "execute_task_agent",
    "execute_vision_agent",
]
