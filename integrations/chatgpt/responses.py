"""
Models and inference on the signed-in ChatGPT plan, through the public Responses API.

Follows https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
and .../errors-and-recovery:

- the model list comes from ``GET /v1/models`` (entries with ``visibility: "list"``),
- every request sets ``store: false`` and ``stream: true`` and succeeds only on
  ``response.completed``,
- the system prompt goes in ``instructions`` and ``input`` is a message array;
  sampling fields such as ``temperature`` and ``max_output_tokens`` are not sent,
- a usage limit pauses ChatGPT requests and points at ChatGPT settings, an
  ineligible account is not retried, and an unavailable usage check backs off.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Iterable, Iterator

import requests

from integrations.chatgpt import auth

API_BASE = auth.RESOURCE
USAGE_SETTINGS_URL = "https://chatgpt.com/settings/usage"
DEFAULT_LIMIT_PAUSE_SECONDS = 1800
BACKOFF_START_SECONDS = 30
BACKOFF_MAX_SECONDS = 600

LIMIT_EXCEEDED = "subscription_sharing_usage_limit_exceeded"
USAGE_UNAVAILABLE = "subscription_sharing_usage_unavailable"
NOT_ELIGIBLE = "subscription_sharing_user_not_eligible"

class ChatGPTResponseError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class ChatGPTPaused(ChatGPTResponseError):
    """ChatGPT plan requests are paused after a usage limit, ineligibility, or outage."""


def _session_stamp() -> str:
    """Changes only when the user signs in again (not on token refresh)."""
    credentials = auth.load_credentials() or {}
    return f"{credentials.get('subject', '')}:{credentials.get('signed_in_at', '')}"


class _PauseState:
    """
    Pause shared by every caller in this process; one limit hit stops them all.

    A fresh sign-in (for example from ``python -m integrations.chatgpt login`` in
    another terminal) lifts the pause.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.until = 0.0
        self.reason = ""
        self.code = ""
        self.session = ""
        self.backoff = 0.0

    def check(self) -> None:
        with self._lock:
            if self.until <= time.time():
                return
            if self.session != _session_stamp():
                self.until, self.reason, self.code, self.backoff = 0.0, "", "", 0.0
                return
            raise ChatGPTPaused(self.reason, code=self.code)

    def pause(self, code: str, reason: str, seconds: float) -> None:
        with self._lock:
            self.until = time.time() + seconds
            self.reason = reason
            self.code = code
            self.session = _session_stamp()

    def next_backoff(self) -> float:
        with self._lock:
            self.backoff = min(BACKOFF_MAX_SECONDS, self.backoff * 2) if self.backoff else BACKOFF_START_SECONDS
            return self.backoff

    def clear(self) -> None:
        with self._lock:
            self.until, self.reason, self.code, self.backoff = 0.0, "", "", 0.0

    def status(self) -> str:
        with self._lock:
            return self.reason if self.until > time.time() else ""


PAUSE = _PauseState()
_models_cache: dict[str, list[dict[str, str]]] = {}


def _limit_pause_seconds() -> float:
    try:
        return max(60.0, float(os.getenv("JARVIS_CHATGPT_LIMIT_PAUSE_SECONDS") or DEFAULT_LIMIT_PAUSE_SECONDS))
    except ValueError:
        return float(DEFAULT_LIMIT_PAUSE_SECONDS)


def _handle_error(code: str, message: str, status: int = 0) -> ChatGPTResponseError:
    """Apply OpenAI's documented recovery for a plan-usage error and return the error to raise."""
    if code == LIMIT_EXCEEDED:
        reason = (
            "Your ChatGPT plan usage limit for Jarvis was reached, so ChatGPT requests are paused. "
            f"Check {USAGE_SETTINGS_URL}"
        )
        PAUSE.pause(code, reason, _limit_pause_seconds())
        return ChatGPTPaused(reason, code=code, status=status or 429)
    if code == NOT_ELIGIBLE:
        reason = (
            "ChatGPT plan usage is not available for this account, workspace, or region, "
            "so Jarvis will not use ChatGPT until you sign in again."
        )
        # Never retried for this process: repeating the request or the sign-in does not help.
        PAUSE.pause(code, reason, float("inf"))
        return ChatGPTPaused(reason, code=code, status=status or 403)
    if code == USAGE_UNAVAILABLE or status == 503:
        delay = PAUSE.next_backoff()
        reason = f"ChatGPT usage could not be checked right now; retrying after {delay:.0f}s."
        PAUSE.pause(code or "unavailable", reason, delay)
        return ChatGPTPaused(reason, code=code, status=status or 503)
    detail = f"{code}: {message}" if code else message
    return ChatGPTResponseError(f"ChatGPT request failed ({detail})", code=code, status=status)


def _error_from_body(response: requests.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        return "", response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or ""), str(error.get("message") or "")
    return "", str(body)[:300]


def _authorized(method: str, path: str, *, timeout: float, **kwargs: Any) -> requests.Response:
    """Send with the plan token, refreshing once on 401 (the token may have just rotated or expired)."""
    url = f"{API_BASE}{path}"
    for attempt in range(2):
        token = auth.access_token(force_refresh=attempt == 1)
        response = requests.request(
            method, url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout, **kwargs
        )
        if response.status_code != 401:
            return response
        response.close()
    raise auth.NotSignedInError(
        "ChatGPT did not accept Jarvis's sign-in. Check the account and run: python -m integrations.chatgpt login"
    )


def list_models(*, refresh: bool = False, timeout: float = 30) -> list[dict[str, str]]:
    """Display-ready models for the signed-in account, in the server's order."""
    credentials = auth.load_credentials() or {}
    key = str(credentials.get("subject") or "")
    if not refresh and key in _models_cache:
        return _models_cache[key]
    response = _authorized("GET", "/models", timeout=timeout)
    if response.status_code >= 400:
        code, message = _error_from_body(response)
        raise _handle_error(code, message, response.status_code)
    models = [
        {"slug": str(entry["slug"]), "display_name": str(entry.get("display_name") or entry["slug"])}
        for entry in (response.json() or {}).get("models", [])
        if isinstance(entry, dict) and entry.get("visibility") == "list" and entry.get("slug")
    ]
    _models_cache[key] = models
    return models


def default_model() -> str:
    configured = os.getenv("JARVIS_CHATGPT_MODEL", "").strip()
    if configured:
        return configured
    models = list_models()
    if not models:
        raise ChatGPTResponseError("Your ChatGPT account did not list any models Jarvis can use.")
    return models[0]["slug"]


def _sse_events(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    data: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not line:
            if data:
                payload = "\n".join(data)
                data = []
                if payload != "[DONE]":
                    yield json.loads(payload)
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))


def generate(
    *,
    instructions: str,
    user: str,
    model: str | None = None,
    json_mode: bool = False,
    timeout: float = 180,
) -> str:
    """Stream one answer and return its text. Raises unless the stream reaches response.completed."""
    PAUSE.check()
    if json_mode:
        # Plan usage documents no structured-output field, so ask for JSON in the instructions.
        instructions = f"{instructions}\n\nReply with a single valid JSON object and nothing else."
    body = {
        "model": model or default_model(),
        "instructions": instructions,
        "input": [{"role": "user", "content": user}],
        "store": False,
        "stream": True,
    }
    response = _authorized("POST", "/responses", json=body, stream=True, timeout=timeout)
    with response:
        if response.status_code >= 400:
            code, message = _error_from_body(response)
            raise _handle_error(code, message, response.status_code)
        parts: list[str] = []
        for event in _sse_events(response.iter_lines()):
            kind = event.get("type")
            if kind == "response.output_text.delta":
                parts.append(str(event.get("delta") or ""))
            elif kind == "response.completed":
                PAUSE.clear()
                text = "".join(parts)
                return text or _completed_text(event.get("response") or {})
            elif kind == "response.failed":
                error = (event.get("response") or {}).get("error") or {}
                raise _handle_error(str(error.get("code") or "unknown_error"), str(error.get("message") or ""))
            elif kind == "response.incomplete":
                details = (event.get("response") or {}).get("incomplete_details") or {}
                raise ChatGPTResponseError(f"ChatGPT stopped early ({details.get('reason') or 'incomplete'}).")
            elif kind == "error":
                raise _handle_error(str(event.get("code") or ""), str(event.get("message") or "stream error"))
    raise ChatGPTResponseError("ChatGPT stream ended before the answer completed.")


def _completed_text(response: dict[str, Any]) -> str:
    return "".join(
        str(part.get("text") or "")
        for item in response.get("output") or []
        if isinstance(item, dict) and item.get("type") == "message"
        for part in item.get("content") or []
        if isinstance(part, dict) and part.get("type") == "output_text"
    )
