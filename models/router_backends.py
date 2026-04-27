"""
Provider-specific router backend clients (OpenRouter and Ollama).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import requests


CleanText = Callable[[object, str, int], str]
ParseJsonObject = Callable[[str], dict[str, Any]]


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
) -> str:
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if openrouter_site_url:
        headers["HTTP-Referer"] = openrouter_site_url
    if openrouter_site_name:
        headers["X-Title"] = openrouter_site_name

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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
        raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {body}")

    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("OpenRouter returned a non-object response.")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter returned no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")

    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            piece = item.get("text")
            if isinstance(piece, str) and piece.strip():
                parts.append(piece.strip())
        text = "\n".join(parts).strip()
    else:
        text = ""

    if not text:
        raise RuntimeError("OpenRouter returned empty message content.")

    return text


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
        raise RuntimeError(f"OpenRouter router returned non-JSON payload: {text}")
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
        raise RuntimeError(f"Ollama router returned non-JSON payload: {content}")
    return parsed
