"""
Provider-specific router backend clients (OpenRouter and Ollama).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import requests
from models.router_backend_parsing import (
    ParseJsonObject,
    extract_message_text,
    normalize_tool_call,
    parse_router_response,
    parse_router_text_tool_call,
    parse_text_tool_calls,
    tool_calls_from_json_payload,
)
from models.router_backend_types import JsonObject, JsonValue, NormalizedToolCall


CleanText = Callable[[object, str, int | None], str]


class RouterBackendError(RuntimeError):
    """Expected provider/backend failure safe to surface or retry."""


class RouterBackendTransportError(RouterBackendError):
    """Transport-layer failure while calling a router backend."""


class RouterBackendParseError(RouterBackendError):
    """JSON decoding/parsing failure from a router backend."""


class RouterBackendResponseError(RouterBackendError):
    """Invalid or incomplete structured response from a router backend."""


def _extract_message_text(content: object) -> str:
    return extract_message_text(content)


def _parse_router_text_tool_call(text: str) -> JsonObject:
    decision = parse_router_text_tool_call(text)
    return decision.as_dict() if decision is not None else {}


def _normalize_tool_call(
    raw_call: object,
    valid_tool_names: set[str],
) -> Optional[dict[str, JsonValue]]:
    call = normalize_tool_call(raw_call, valid_tool_names)
    return call.as_dict() if call is not None else None


def _tool_calls_from_json_payload(
    payload: object,
    valid_tool_names: set[str],
) -> list[dict[str, JsonValue]]:
    return [call.as_dict() for call in tool_calls_from_json_payload(payload, valid_tool_names)]


def _parse_text_tool_calls(
    text: str,
    valid_tool_names: set[str],
) -> list[dict[str, JsonValue]]:
    return [call.as_dict() for call in parse_text_tool_calls(text, valid_tool_names)]


def _backend_error_message(
    *,
    prefix: str,
    exc: BaseException,
    clean_text: CleanText,
    max_len: int,
) -> str:
    detail = clean_text(str(exc), "", max_len)
    if detail:
        return f"{prefix} ({type(exc).__name__}): {detail}"
    return f"{prefix} ({type(exc).__name__})."


def _load_json_object_response(
    response: object,
    *,
    provider_name: str,
) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise RouterBackendParseError(
            f"{provider_name} returned invalid JSON ({type(exc).__name__})."
        ) from exc

    if not isinstance(data, dict):
        raise RouterBackendResponseError(f"{provider_name} returned a non-object response.")
    return data


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

    try:
        response = requests.post(
            openrouter_url,
            headers=headers,
            json=payload,
            timeout=openrouter_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RouterBackendTransportError(
            _backend_error_message(
                prefix="Provider request failed",
                exc=exc,
                clean_text=clean_text,
                max_len=320,
            )
        ) from exc
    if response.status_code >= 400:
        body = clean_text(response.text, "", 320)
        raise RouterBackendResponseError(f"Provider HTTP {response.status_code}: {body}")

    data = _load_json_object_response(response, provider_name="Provider")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RouterBackendResponseError("Provider returned no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")

    text = _extract_message_text(content)

    if not text:
        raise RouterBackendResponseError("Provider returned empty message content.")

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

    try:
        response = requests.post(
            openrouter_url,
            headers=headers,
            json=payload,
            timeout=openrouter_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RouterBackendTransportError(
            _backend_error_message(
                prefix="Provider request failed",
                exc=exc,
                clean_text=clean_text,
                max_len=420,
            )
        ) from exc
    if response.status_code >= 400:
        body = clean_text(response.text, "", 420)
        raise RouterBackendResponseError(f"Provider HTTP {response.status_code}: {body}")

    data = _load_json_object_response(response, provider_name="Provider")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RouterBackendResponseError("Provider returned no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    text = _extract_message_text(content)

    parsed_tool_calls: list[NormalizedToolCall] = []
    valid_tool_names = {
        str(declaration.get("name") or "").strip()
        for declaration in function_declarations
        if isinstance(declaration, dict) and declaration.get("name")
    }
    for raw_call in message.get("tool_calls") or []:
        call = normalize_tool_call(raw_call, valid_tool_names)
        if call:
            parsed_tool_calls.append(call)

    if not parsed_tool_calls and text:
        parsed_tool_calls.extend(parse_text_tool_calls(text, valid_tool_names))

    if not text and not parsed_tool_calls:
        raise RouterBackendResponseError("Provider returned neither text nor tool calls.")

    return {
        "text": text,
        "tool_calls": [call.as_dict() for call in parsed_tool_calls],
    }


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
) -> JsonObject:
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
    parsed = parse_router_response(text, parse_json_object_from_text)
    if parsed is None:
        raise RouterBackendResponseError(f"OpenRouter router returned non-JSON payload: {text}")
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
) -> JsonObject:
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
    parsed = parse_router_response(text, parse_json_object_from_text)
    if parsed is None:
        raise RouterBackendResponseError(f"NVIDIA router returned non-JSON payload: {text}")
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
) -> JsonObject:
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
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=ollama_router_timeout_seconds,
        )
    except requests.RequestException as exc:
        raise RouterBackendTransportError(
            _backend_error_message(
                prefix="Ollama request failed",
                exc=exc,
                clean_text=clean_text,
                max_len=400,
            )
        ) from exc
    if response.status_code >= 400:
        body = clean_text(response.text, "", 400)
        raise RouterBackendResponseError(f"Ollama HTTP {response.status_code}: {body}")

    data = _load_json_object_response(response, provider_name="Ollama")

    message = data.get("message")
    if not isinstance(message, dict):
        raise RouterBackendResponseError("Ollama response missing message object.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RouterBackendResponseError("Ollama response contained empty content.")

    parsed = parse_router_response(content, parse_json_object_from_text)
    if parsed is None:
        raise RouterBackendResponseError(f"Ollama router returned non-JSON payload: {content}")
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
    except requests.RequestException as exc:
        return (
            "Unable to validate Ollama router model at startup: "
            f"{type(exc).__name__}: {clean_text(str(exc), '', 240)}"
        )

    if response.status_code >= 400:
        body = clean_text(response.text, "", 240)
        return f"Unable to validate Ollama router model: HTTP {response.status_code}: {body}"

    try:
        data = response.json()
    except ValueError as exc:
        return f"Unable to validate Ollama router model: invalid /api/tags JSON ({type(exc).__name__})."

    if not isinstance(data, dict):
        return (
            "Unable to validate Ollama router model: "
            f"/api/tags returned {type(data).__name__}, expected object."
        )

    raw_models = data.get("models")
    if raw_models is None:
        return "Unable to validate Ollama router model: /api/tags response missing models list."
    if not isinstance(raw_models, list):
        return (
            "Unable to validate Ollama router model: "
            f"/api/tags models was {type(raw_models).__name__}, expected list."
        )

    available: set[str] = set()
    for item in raw_models:
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
