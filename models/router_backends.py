"""
Provider-specific router backend clients (OpenRouter and Ollama).
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Callable, Optional

import requests


CleanText = Callable[[object, str, int], str]
ParseJsonObject = Callable[[str], dict[str, Any]]

_ROUTER_TEXT_TOOL_TO_AGENT = {
    "direct_response": "direct",
    "invoke_jarvis": "jarvis",
    "invoke_browser": "browser",
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


def _extract_message_text(content: Any) -> str:
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


def _parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str) and raw_arguments.strip():
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _literal_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


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


def _parse_router_text_tool_call(text: str) -> dict[str, Any]:
    """Accept legacy router tool-call text emitted by smaller local models."""
    if not text:
        return {}

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

        args: dict[str, Any] = {}
        for keyword in expression.keywords:
            if not keyword.arg:
                continue
            value = _literal_value(keyword.value)
            if isinstance(value, dict) and keyword.arg in {"args", "arguments"}:
                args.update(value)
            elif value is not None:
                args[keyword.arg] = value

        default_key = "query" if agent == "jarvis" else "text" if agent == "direct" else "task"
        for positional in expression.args:
            value = _literal_value(positional)
            if isinstance(value, dict):
                args.update(value)
            elif value is not None and default_key not in args:
                args[default_key] = value

        if agent == "direct":
            response_text = str(args.get("response_text") or args.get("text") or "").strip()
            if response_text:
                return {"agent": agent, "response_text": response_text}
        elif agent == "jarvis":
            query = str(args.get("query") or args.get("task") or "").strip()
            if query:
                return {"agent": agent, "query": query}
        elif agent == "screen_context":
            task = str(args.get("task") or args.get("query") or "").strip()
            if task:
                payload = {"agent": agent, "task": task}
                focus = str(args.get("focus") or "").strip()
                if focus:
                    payload["focus"] = focus
                return payload
        else:
            task = str(args.get("task") or args.get("query") or "").strip()
            if task:
                return {"agent": agent, "task": task}

    return {}


def _normalize_tool_call(
    raw_call: Any,
    valid_tool_names: set[str],
) -> Optional[dict[str, Any]]:
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

    raw_arguments = (
        source.get("arguments")
        if "arguments" in source
        else source.get("args")
        if "args" in source
        else raw_call.get("arguments")
        if "arguments" in raw_call
        else raw_call.get("args")
    )
    return {"name": name, "arguments": _parse_tool_arguments(raw_arguments)}


def _parse_json_value_from_text(text: str) -> Any:
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


def _tool_calls_from_json_payload(
    payload: Any,
    valid_tool_names: set[str],
) -> list[dict[str, Any]]:
    raw_calls: list[Any] = []
    if isinstance(payload, list):
        raw_calls = payload
    elif isinstance(payload, dict):
        for key in ("tool_calls", "function_calls", "calls", "tools"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_calls.extend(value)
        if not raw_calls:
            raw_calls = [payload]

    parsed: list[dict[str, Any]] = []
    for raw_call in raw_calls:
        call = _normalize_tool_call(raw_call, valid_tool_names)
        if call:
            parsed.append(call)
    return parsed


def _parse_text_tool_calls(
    text: str,
    valid_tool_names: set[str],
) -> list[dict[str, Any]]:
    payload = _parse_json_value_from_text(text)
    if payload is None:
        return []
    return _tool_calls_from_json_payload(payload, valid_tool_names)


def call_openrouter_text_sync(
    *,
    openrouter_api_key: str,
    openrouter_url: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    openrouter_timeout_seconds: int,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    clean_text: CleanText,
    response_format: Optional[dict[str, Any]] = None,
    image_data_url: Optional[str] = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if openrouter_site_url:
        headers["HTTP-Referer"] = openrouter_site_url
    if openrouter_site_name:
        headers["X-Title"] = openrouter_site_name

    user_content: str | list[dict[str, Any]]
    if image_data_url:
        user_content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        user_content = user_prompt

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    response = requests.post(
        openrouter_url,
        headers=headers,
        json=payload,
        timeout=openrouter_timeout_seconds,
    )
    if response.status_code >= 400:
        body = clean_text(response.text, "", 320)
        raise RuntimeError(f"Provider HTTP {response.status_code}: {body}")

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Provider returned a non-object response.")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Provider returned no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")

    text = _extract_message_text(content)

    if not text:
        raise RuntimeError("Provider returned empty message content.")

    return text


def call_openrouter_tool_sync(
    *,
    openrouter_api_key: str,
    openrouter_url: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    openrouter_timeout_seconds: int,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    function_declarations: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    clean_text: CleanText,
    image_data_url: Optional[str] = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if openrouter_site_url:
        headers["HTTP-Referer"] = openrouter_site_url
    if openrouter_site_name:
        headers["X-Title"] = openrouter_site_name

    user_content: str | list[dict[str, Any]]
    if image_data_url:
        user_content = [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        user_content = user_prompt

    tools = [
        {
            "type": "function",
            "function": {
                "name": declaration.get("name"),
                "description": declaration.get("description", ""),
                "parameters": declaration.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for declaration in function_declarations
        if isinstance(declaration, dict) and declaration.get("name")
    ]

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    response = requests.post(
        openrouter_url,
        headers=headers,
        json=payload,
        timeout=openrouter_timeout_seconds,
    )
    if response.status_code >= 400:
        body = clean_text(response.text, "", 420)
        raise RuntimeError(f"Provider HTTP {response.status_code}: {body}")

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Provider returned a non-object response.")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Provider returned no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    text = _extract_message_text(content)

    parsed_tool_calls: list[dict[str, Any]] = []
    valid_tool_names = {
        str(declaration.get("name") or "").strip()
        for declaration in function_declarations
        if isinstance(declaration, dict) and declaration.get("name")
    }
    for raw_call in message.get("tool_calls") or []:
        call = _normalize_tool_call(raw_call, valid_tool_names)
        if call:
            parsed_tool_calls.append(call)

    if not parsed_tool_calls and text:
        parsed_tool_calls.extend(_parse_text_tool_calls(text, valid_tool_names))

    if not text and not parsed_tool_calls:
        raise RuntimeError("Provider returned neither text nor tool calls.")

    return {"text": text, "tool_calls": parsed_tool_calls}


def call_openrouter_router_sync(
    *,
    openrouter_api_key: str,
    openrouter_url: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    openrouter_timeout_seconds: int,
    openrouter_router_model: str,
    openrouter_router_max_tokens: int,
    router_system_prompt: str,
    prompt: str,
    clean_text: CleanText,
    parse_json_object_from_text: ParseJsonObject,
) -> dict[str, Any]:
    text = call_openrouter_text_sync(
        openrouter_api_key=openrouter_api_key,
        openrouter_url=openrouter_url,
        openrouter_site_url=openrouter_site_url,
        openrouter_site_name=openrouter_site_name,
        openrouter_timeout_seconds=openrouter_timeout_seconds,
        model_name=openrouter_router_model,
        system_prompt=router_system_prompt,
        user_prompt=prompt,
        temperature=0.0,
        max_tokens=openrouter_router_max_tokens,
        clean_text=clean_text,
        response_format={"type": "json_object"},
    )
    parsed = parse_json_object_from_text(text)
    if not isinstance(parsed, dict) or not parsed:
        parsed = _parse_router_text_tool_call(text)
    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError(f"OpenRouter router returned non-JSON payload: {text}")
    return parsed


def call_nvidia_router_sync(
    *,
    nvidia_api_key: str,
    nvidia_url: str,
    nvidia_timeout_seconds: int,
    nvidia_router_model: str,
    nvidia_router_max_tokens: int,
    router_system_prompt: str,
    prompt: str,
    clean_text: CleanText,
    parse_json_object_from_text: ParseJsonObject,
) -> dict[str, Any]:
    text = call_openrouter_text_sync(
        openrouter_api_key=nvidia_api_key,
        openrouter_url=nvidia_url,
        openrouter_site_url="",
        openrouter_site_name="",
        openrouter_timeout_seconds=nvidia_timeout_seconds,
        model_name=nvidia_router_model,
        system_prompt=router_system_prompt,
        user_prompt=prompt,
        temperature=0.0,
        max_tokens=nvidia_router_max_tokens,
        clean_text=clean_text,
        response_format={"type": "json_object"},
    )
    parsed = parse_json_object_from_text(text)
    if not isinstance(parsed, dict) or not parsed:
        parsed = _parse_router_text_tool_call(text)
    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError(f"NVIDIA router returned non-JSON payload: {text}")
    return parsed


def call_ollama_router_sync(
    *,
    ollama_base_url: str,
    ollama_router_model: str,
    ollama_router_num_predict: int,
    ollama_router_num_ctx: int,
    ollama_router_think: bool,
    ollama_keep_alive: str,
    ollama_router_timeout_seconds: int,
    router_system_prompt: str,
    prompt: str,
    clean_text: CleanText,
    parse_json_object_from_text: ParseJsonObject,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": ollama_router_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": router_system_prompt},
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.0,
            "num_predict": ollama_router_num_predict,
            "num_ctx": ollama_router_num_ctx,
        },
    }
    payload["think"] = ollama_router_think
    if ollama_keep_alive:
        payload["keep_alive"] = ollama_keep_alive

    url = f"{ollama_base_url}/api/chat"
    response = requests.post(
        url,
        json=payload,
        timeout=ollama_router_timeout_seconds,
    )
    if response.status_code >= 400:
        body = clean_text(response.text, "", 400)
        raise RuntimeError(f"Ollama HTTP {response.status_code}: {body}")

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Ollama returned a non-object response.")

    message = data.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Ollama response missing message object.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama response contained empty content.")

    parsed = parse_json_object_from_text(content)
    if not isinstance(parsed, dict) or not parsed:
        parsed = _parse_router_text_tool_call(content)
    if not isinstance(parsed, dict) or not parsed:
        raise RuntimeError(f"Ollama router returned non-JSON payload: {content}")
    return parsed


def validate_ollama_router_model_sync(
    *,
    ollama_base_url: str,
    ollama_router_model: str,
    timeout_seconds: int,
    clean_text: CleanText,
) -> str | None:
    model_name = (ollama_router_model or "").strip()
    if not model_name:
        return "Ollama router model is not configured."

    url = f"{ollama_base_url.rstrip('/')}/api/tags"
    try:
        response = requests.get(url, timeout=timeout_seconds)
    except Exception as exc:
        return (
            "Unable to validate Ollama router model at startup: "
            f"{type(exc).__name__}: {clean_text(str(exc), '', 240)}"
        )

    if response.status_code >= 400:
        body = clean_text(response.text, "", 240)
        return f"Unable to validate Ollama router model: HTTP {response.status_code}: {body}"

    try:
        data = response.json()
    except Exception as exc:
        return f"Unable to validate Ollama router model: invalid /api/tags JSON ({type(exc).__name__})."

    available: set[str] = set()
    for item in data.get("models") or []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                available.add(value.strip())

    if model_name in available:
        return None

    short_available = ", ".join(sorted(available)[:8]) or "none"
    return (
        f"Ollama router model '{model_name}' was not found. "
        "Run `ollama pull <model>` or set OLLAMA_ROUTER_MODEL / rapid_response_model "
        f"to an installed model. Installed models: {short_available}."
    )
