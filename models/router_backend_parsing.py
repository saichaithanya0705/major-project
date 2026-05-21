"""
Typed parsing helpers for router backend text and tool-call responses.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Callable

from models.contracts import RouteDecision
from models.json_payload_coercion import coerce_json_object
from models.router_backend_types import JsonObject, NormalizedToolCall

ParseJsonObject = Callable[[str], JsonObject]
NormalizeText = Callable[[object, str, int | None], str]
RouterRefusalDetector = Callable[[str], bool]
_INVALID = object()
_ROUTER_TEXT_TOOL_TO_AGENT = {
    "direct_response": "direct",
    "invoke_jarvis": "jarvis",
    "invoke_browser": "browser",
    "invoke_web_qa": "web_qa",
    "invoke_cua_cli": "cua_cli",
    "invoke_cua_vision": "cua_vision",
    "request_screen_context": "screen_context",
}
_ROUTER_TEXT_TOOL_RE = re.compile(
    r"\b("
    + "|".join(re.escape(name) for name in _ROUTER_TEXT_TOOL_TO_AGENT)
    + r")\s*\(",
    re.DOTALL,
)
_VALID_ROUTE_AGENTS = frozenset(_ROUTER_TEXT_TOOL_TO_AGENT.values())


def extract_message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            piece = item.get("text")
            if isinstance(piece, str) and piece.strip():
                parts.append(piece.strip())
        return "\n".join(parts).strip()
    return ""


def _default_clean_text(value: object, fallback: str, max_len: int | None) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback
    if max_len is not None:
        return text[:max_len]
    return text
def _parse_tool_arguments(
    raw_arguments: object,
    *,
    arguments_supplied: bool,
) -> JsonObject | None:
    if not arguments_supplied or raw_arguments is None:
        return {}
    if isinstance(raw_arguments, str):
        if not raw_arguments.strip():
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return None
        return coerce_json_object(parsed)
    return coerce_json_object(raw_arguments)


def _literal_value(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return _INVALID


def _extract_balanced_call(text: str, start: int) -> str:
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

        if char in {"'", '"'}:
            quote = char
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    return ""


def normalize_route_decision_payload(
    payload: object,
    *,
    latest_request: str = "",
    clean_text: NormalizeText = _default_clean_text,
    format_direct_response_text: NormalizeText = _default_clean_text,
    looks_like_router_refusal: RouterRefusalDetector | None = None,
    default_direct_response: str | None = None,
) -> RouteDecision | None:
    if not isinstance(payload, dict):
        return None

    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in _VALID_ROUTE_AGENTS:
        return None

    try:
        if agent == "direct":
            direct_response_args_supplied = "direct_response_args" in payload
            direct_response_args = _parse_tool_arguments(
                payload.get("direct_response_args"),
                arguments_supplied=direct_response_args_supplied,
            )
            if direct_response_args_supplied and direct_response_args is None:
                return None
            response_text = format_direct_response_text(
                payload.get("response_text")
                or payload.get("text")
                or (direct_response_args or {}).get("text"),
                default_direct_response or "",
                max_len=None,
            )
            if not response_text.strip():
                return None
            safe_direct_response_args = dict(direct_response_args or {})
            safe_direct_response_args.pop("text", None)
            return RouteDecision(
                agent="direct",
                response_text=response_text,
                direct_response_args=safe_direct_response_args,
            )

        if agent == "jarvis":
            query = clean_text(
                payload.get("query") or payload.get("task"),
                latest_request,
                max_len=420,
            )
            if not query.strip():
                return None
            return RouteDecision(agent="jarvis", query=query)

        task = clean_text(
            payload.get("task") or payload.get("query"),
            latest_request,
            max_len=420,
        )
        if looks_like_router_refusal is not None and looks_like_router_refusal(task):
            task = latest_request
        if not task.strip():
            return None

        if agent == "screen_context":
            focus = clean_text(payload.get("focus"), "", max_len=220)
            return RouteDecision(agent="screen_context", task=task, focus=focus)

        return RouteDecision(agent=agent, task=task)
    except ValueError:
        return None


def parse_router_text_tool_call(text: str) -> RouteDecision | None:
    """Accept legacy router tool-call text emitted by smaller local models."""
    if not text:
        return None

    for match in _ROUTER_TEXT_TOOL_RE.finditer(text):
        call_text = _extract_balanced_call(text, match.start())
        if not call_text:
            continue
        try:
            expression = ast.parse(call_text, mode="eval").body
        except SyntaxError:
            continue
        if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name):
            continue

        tool_name = expression.func.id
        agent = _ROUTER_TEXT_TOOL_TO_AGENT.get(tool_name)
        if not agent:
            continue

        args: dict[str, object] = {}
        for keyword in expression.keywords:
            if not keyword.arg:
                continue
            value = _literal_value(keyword.value)
            if value is _INVALID:
                continue
            if isinstance(value, dict) and keyword.arg in {"args", "arguments"}:
                args.update(value)
            else:
                args[keyword.arg] = value

        default_key = "query" if agent == "jarvis" else "text" if agent == "direct" else "task"
        for positional in expression.args:
            value = _literal_value(positional)
            if value is _INVALID:
                continue
            if isinstance(value, dict):
                args.update(value)
            elif default_key not in args:
                args[default_key] = value

        decision = normalize_route_decision_payload(
            {"agent": agent, **args},
            latest_request="",
        )
        if decision is not None:
            return decision

    return None


def normalize_tool_call(
    raw_call: object,
    valid_tool_names: set[str],
) -> NormalizedToolCall | None:
    if not isinstance(raw_call, dict):
        return None

    function = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else {}
    function_call = (
        raw_call.get("function_call")
        if isinstance(raw_call.get("function_call"), dict)
        else {}
    )
    source = function or function_call or raw_call
    name = str(
        source.get("name")
        or source.get("tool")
        or source.get("tool_name")
        or raw_call.get("name")
        or raw_call.get("tool")
        or raw_call.get("tool_name")
        or ""
    ).strip()
    if not name or (valid_tool_names and name not in valid_tool_names):
        return None

    raw_arguments: object = None
    arguments_supplied = False
    for container in (source, raw_call):
        if not isinstance(container, dict):
            continue
        if "arguments" in container:
            raw_arguments = container.get("arguments")
            arguments_supplied = True
            break
        if "args" in container:
            raw_arguments = container.get("args")
            arguments_supplied = True
            break

    arguments = _parse_tool_arguments(
        raw_arguments,
        arguments_supplied=arguments_supplied,
    )
    if arguments is None:
        return None

    return NormalizedToolCall(name=name, arguments=arguments)


def _parse_json_value_from_text(text: str) -> object | None:
    candidates: list[str] = []
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidates.append("\n".join(lines[1:-1]).strip())

    for opener, closer in [("{", "}"), ("[", "]")]:
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start >= 0 and end > start:
            candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def tool_calls_from_json_payload(
    payload: object,
    valid_tool_names: set[str],
) -> tuple[NormalizedToolCall, ...]:
    raw_calls: list[object] = []
    if isinstance(payload, list):
        raw_calls = payload
    elif isinstance(payload, dict):
        for key in ("tool_calls", "function_calls", "calls", "tools"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_calls.extend(value)
        if not raw_calls:
            raw_calls = [payload]

    parsed: list[NormalizedToolCall] = []
    for raw_call in raw_calls:
        call = normalize_tool_call(raw_call, valid_tool_names)
        if call:
            parsed.append(call)
    return tuple(parsed)


def parse_text_tool_calls(
    text: str,
    valid_tool_names: set[str],
) -> tuple[NormalizedToolCall, ...]:
    payload = _parse_json_value_from_text(text)
    if payload is None:
        return ()
    return tool_calls_from_json_payload(payload, valid_tool_names)


def parse_router_response(
    text: str,
    parse_json_object_from_text: ParseJsonObject,
) -> JsonObject | None:
    payload = coerce_json_object(parse_json_object_from_text(text))
    if payload:
        return payload

    decision = parse_router_text_tool_call(text)
    if decision is not None:
        return coerce_json_object(decision.as_dict())
    return None


__all__ = [
    "NormalizeText",
    "ParseJsonObject",
    "RouterRefusalDetector",
    "extract_message_text",
    "normalize_route_decision_payload",
    "normalize_tool_call",
    "parse_router_response",
    "parse_router_text_tool_call",
    "parse_text_tool_calls",
    "tool_calls_from_json_payload",
]
