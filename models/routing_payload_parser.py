"""Typed routing payload parsing helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Literal, TypeAlias, TypeGuard, TypedDict, cast

from models.json_payload_coercion import coerce_json_object
from models.rapid_step_payloads import RapidTaskExecutionContextPayload
from models.router_backend_types import JsonObject, JsonValue


DirectResponseArgsPayload: TypeAlias = JsonObject
RouteAgentName = Literal[
    "direct",
    "jarvis",
    "browser",
    "cua_cli",
    "cua_vision",
    "screen_context",
    "web_qa",
]
ScreenContextRecommendedAgent = RouteAgentName | Literal[""]
BlockedStepSignature: TypeAlias = tuple[RouteAgentName, str]
JsonParseStage = Literal["full_text", "json_code_block", "embedded_object"]
JsonObjectParseMode = Literal[
    "empty",
    "direct_object",
    "json_code_block",
    "embedded_object",
    "invalid",
]
ParsedJsonObjectParseMode = Literal[
    "direct_object",
    "json_code_block",
    "embedded_object",
]


class RoutePayload(TypedDict, total=False):
    agent: RouteAgentName
    response_text: str
    query: str
    task: str
    focus: str
    direct_response_args: DirectResponseArgsPayload
    orchestrator_context: RapidTaskExecutionContextPayload


class ScreenContextPayload(TypedDict, total=False):
    summary: str
    repo_url: str
    local_url: str
    recommended_agent: ScreenContextRecommendedAgent
    recommended_task: str
    hints: str
    model: str


class PlanTaskPayload(TypedDict, total=False):
    id: str
    agent: RouteAgentName
    response_text: str
    query: str
    task: str
    focus: str
    direct_response_args: DirectResponseArgsPayload
    resources: list[str]
    depends_on: list[str]
    max_attempts: int


class PlanDecisionPayload(TypedDict):
    tasks: list[PlanTaskPayload]
    max_parallel: int


RoutingResult: TypeAlias = RoutePayload | PlanDecisionPayload


@dataclass(frozen=True, slots=True)
class JsonObjectParseFailure:
    stage: JsonParseStage
    message: str


@dataclass(frozen=True, slots=True)
class JsonObjectParseResult:
    payload: JsonObject
    mode: JsonObjectParseMode
    failures: tuple[JsonObjectParseFailure, ...] = ()

    @property
    def salvaged(self) -> bool:
        return self.mode in {"json_code_block", "embedded_object"}


@dataclass(frozen=True, slots=True)
class EmptyJsonObjectBoundary:
    kind: Literal["empty"] = "empty"


@dataclass(frozen=True, slots=True)
class ParsedJsonObjectBoundary:
    payload: JsonObject
    mode: ParsedJsonObjectParseMode
    failures: tuple[JsonObjectParseFailure, ...] = ()
    kind: Literal["parsed"] = "parsed"

    @property
    def salvaged(self) -> bool:
        return self.mode in {"json_code_block", "embedded_object"}


@dataclass(frozen=True, slots=True)
class MalformedJsonObjectBoundary:
    failures: tuple[JsonObjectParseFailure, ...]
    kind: Literal["malformed"] = "malformed"


JsonObjectBoundary = (
    EmptyJsonObjectBoundary
    | ParsedJsonObjectBoundary
    | MalformedJsonObjectBoundary
)


def _failure(stage: JsonParseStage, message: str) -> JsonObjectParseFailure:
    return JsonObjectParseFailure(stage=stage, message=str(message).strip())


def _parse_candidate(candidate: str, *, stage: JsonParseStage) -> tuple[JsonObject | None, JsonObjectParseFailure | None]:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, _failure(stage, str(exc))

    normalized = coerce_json_object(parsed)
    if normalized is None:
        return None, _failure(
            stage,
            f"Expected JSON object but got {type(parsed).__name__}.",
        )

    return normalized, None


def _extract_code_block_candidate(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return ""

    lines = stripped.splitlines()
    if len(lines) < 3:
        return ""
    if lines[-1].strip() != "```":
        return ""

    return "\n".join(lines[1:-1]).strip()


def _extract_embedded_object_candidate(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""

    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue

        if char in {'"', "'"}:
            quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return ""


def parse_json_object_text(raw_text: str) -> JsonObjectParseResult:
    text = (raw_text or "").strip()
    if not text:
        return JsonObjectParseResult(payload={}, mode="empty")

    failures: list[JsonObjectParseFailure] = []

    parsed, failure = _parse_candidate(text, stage="full_text")
    if parsed is not None:
        return JsonObjectParseResult(payload=parsed, mode="direct_object")
    if failure is not None:
        failures.append(failure)

    code_block_candidate = _extract_code_block_candidate(text)
    if code_block_candidate and code_block_candidate != text:
        parsed, failure = _parse_candidate(code_block_candidate, stage="json_code_block")
        if parsed is not None:
            return JsonObjectParseResult(
                payload=parsed,
                mode="json_code_block",
                failures=tuple(failures),
            )
        if failure is not None:
            failures.append(failure)

    embedded_candidate = _extract_embedded_object_candidate(text)
    if embedded_candidate and embedded_candidate != text:
        parsed, failure = _parse_candidate(embedded_candidate, stage="embedded_object")
        if parsed is not None:
            return JsonObjectParseResult(
                payload=parsed,
                mode="embedded_object",
                failures=tuple(failures),
            )
        if failure is not None:
            failures.append(failure)

    return JsonObjectParseResult(
        payload={},
        mode="invalid",
        failures=tuple(failures),
    )


def parse_json_object_boundary_text(raw_text: str) -> JsonObjectBoundary:
    result = parse_json_object_text(raw_text)
    if result.mode == "empty":
        return EmptyJsonObjectBoundary()
    if result.mode == "invalid":
        return MalformedJsonObjectBoundary(failures=result.failures)
    return ParsedJsonObjectBoundary(
        payload=result.payload,
        mode=cast(ParsedJsonObjectParseMode, result.mode),
        failures=result.failures,
    )


def parse_json_object(raw_text: str) -> JsonObject:
    return parse_json_object_text(raw_text).payload


def coerce_direct_response_args(value: object) -> DirectResponseArgsPayload | None:
    if value is None:
        return None
    return coerce_json_object(value)


def normalize_direct_response_route_payload(
    route: RoutePayload,
    *,
    error_source: str = "route payload",
) -> RoutePayload:
    normalized: RoutePayload = dict(route)
    if "direct_response_args" not in normalized:
        return normalized

    direct_response_args = coerce_direct_response_args(normalized.get("direct_response_args"))
    if direct_response_args is None:
        raise ValueError(f"{error_source} direct_response_args must be a JSON object.")

    safe_args: DirectResponseArgsPayload = dict(direct_response_args)
    text_value = safe_args.pop("text", None)
    if normalized.get("agent") == "direct":
        response_text = normalized.get("response_text")
        if (not isinstance(response_text, str) or not response_text) and text_value is not None:
            normalized["response_text"] = text_value if isinstance(text_value, str) else str(text_value)

    if safe_args:
        normalized["direct_response_args"] = safe_args
    else:
        normalized.pop("direct_response_args", None)
    return normalized


def copy_route_payload(
    route: RoutePayload,
    *,
    error_source: str = "route payload",
) -> RoutePayload:
    copied: RoutePayload = {}
    agent = route.get("agent")
    if is_route_agent_name(agent):
        copied["agent"] = agent
    for key in ("response_text", "query", "task", "focus"):
        value = route.get(key)
        if isinstance(value, str) and value:
            copied[key] = value
    if "direct_response_args" in route:
        copied["direct_response_args"] = route.get("direct_response_args")
    if "orchestrator_context" in route:
        orchestrator_context = route.get("orchestrator_context")
        if isinstance(orchestrator_context, dict):
            copied["orchestrator_context"] = dict(orchestrator_context)
    return normalize_direct_response_route_payload(copied, error_source=error_source)


def copy_plan_task_payload(
    task: PlanTaskPayload | dict[str, object],
    *,
    error_source: str = "plan task payload",
) -> PlanTaskPayload:
    route_copy = copy_route_payload(cast(RoutePayload, task), error_source=error_source)
    copied: PlanTaskPayload = {}

    task_id = task.get("id")
    if isinstance(task_id, str) and task_id.strip():
        copied["id"] = task_id.strip()

    agent = route_copy.get("agent")
    if agent is not None:
        copied["agent"] = agent
    for key in ("response_text", "query", "task", "focus"):
        value = route_copy.get(key)
        if isinstance(value, str) and value:
            copied[key] = value  # type: ignore[literal-required]
    if "direct_response_args" in route_copy:
        copied["direct_response_args"] = route_copy.get("direct_response_args")

    resources = _copy_string_sequence(
        task.get("resources"),
        field_name="resources",
        error_source=error_source,
    )
    if resources is not None:
        copied["resources"] = resources

    depends_on = _copy_string_sequence(
        task.get("depends_on"),
        field_name="depends_on",
        error_source=error_source,
    )
    if depends_on is not None:
        copied["depends_on"] = depends_on

    max_attempts = task.get("max_attempts")
    if max_attempts is not None:
        try:
            parsed_max_attempts = int(max_attempts)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{error_source} max_attempts must be a positive integer.") from exc
        if parsed_max_attempts < 1:
            raise ValueError(f"{error_source} max_attempts must be a positive integer.")
        copied["max_attempts"] = parsed_max_attempts

    return copied


def _copy_string_sequence(
    value: object,
    *,
    field_name: str,
    error_source: str,
) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(f"{error_source} {field_name} must be a string or a list of strings.")


def route_payload_work_text(route: RoutePayload) -> str:
    return str(
        route.get("response_text")
        or route.get("task")
        or route.get("query")
        or ""
    ).strip()


ROUTE_AGENT_NAMES: tuple[RouteAgentName, ...] = (
    "direct",
    "jarvis",
    "browser",
    "cua_cli",
    "cua_vision",
    "screen_context",
    "web_qa",
)


def is_route_agent_name(value: object) -> TypeGuard[RouteAgentName]:
    return isinstance(value, str) and value in ROUTE_AGENT_NAMES


__all__ = [
    "BlockedStepSignature",
    "DirectResponseArgsPayload",
    "EmptyJsonObjectBoundary",
    "JsonObject",
    "JsonObjectBoundary",
    "JsonObjectParseFailure",
    "MalformedJsonObjectBoundary",
    "ParsedJsonObjectBoundary",
    "ParsedJsonObjectParseMode",
    "JsonObjectParseMode",
    "JsonObjectParseResult",
    "PlanDecisionPayload",
    "PlanTaskPayload",
    "ROUTE_AGENT_NAMES",
    "RoutePayload",
    "RouteAgentName",
    "RoutingResult",
    "ScreenContextPayload",
    "ScreenContextRecommendedAgent",
    "JsonValue",
    "coerce_direct_response_args",
    "copy_plan_task_payload",
    "copy_route_payload",
    "is_route_agent_name",
    "normalize_direct_response_route_payload",
    "parse_json_object",
    "parse_json_object_boundary_text",
    "parse_json_object_text",
    "route_payload_work_text",
]
