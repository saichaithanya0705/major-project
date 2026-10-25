"""
Text "brain" for chat answers: local model first, stronger models on escalation.

The primary provider (``JARVIS_BRAIN_PRIMARY``, default ``local``) is the
Ollama model also used for routing. Escalation providers
(``JARVIS_BRAIN_ESCALATION``, default ``gemini,openrouter,claude,codex,copilot``)
are tried in order when:

- the local model fails, times out, or returns nothing,
- the local model replies with the escalation marker because it cannot answer
  reliably (``JARVIS_BRAIN_SELF_ESCALATE``), or
- the user explicitly asks for a stronger model ("think harder", "ask codex").

``claude``, ``codex`` and ``copilot`` run the user's signed-in CLI in
answer-only mode (no shell, file-writing, or MCP tools), which is how a ChatGPT
subscription is used through Codex CLI without handling its credentials.
Providers that are not configured or installed are skipped.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import requests

from agents.cua_cli.backends import BACKENDS, BackendRequest
from agents.cua_cli.backends.runner import run_backend_for_answer
from models.openrouter_runtime import openrouter_model_enabled

ESCALATE_MARKER = "ESCALATE"
SELF_ESCALATION_INSTRUCTION = (
    "\n\nIf answering well needs knowledge or multi-step reasoning you are not confident "
    f"about, reply with exactly {ESCALATE_MARKER} and nothing else; a stronger model will answer instead."
)

_STRONG_MODEL_REQUEST = re.compile(
    r"\b(?:think (?:harder|deeply|carefully|step by step)|deep ?think|"
    r"use (?:the |a )?(?:strong|stronger|big|bigger|best|smart|smarter|cloud) model|"
    r"ask (?:claude|codex|chatgpt|gpt|copilot|gemini)|escalate)\b",
    re.IGNORECASE,
)


class BrainProviderUnavailable(RuntimeError):
    """The provider is not configured or installed on this machine."""


@dataclass(frozen=True)
class BrainReply:
    text: str
    provider: str
    label: str
    escalated: bool


def wants_strong_model(user_prompt: str) -> bool:
    return bool(_STRONG_MODEL_REQUEST.search(user_prompt or ""))


def _is_escalation_marker(text: str) -> bool:
    return text.strip().strip(".`*\"' ").upper() == ESCALATE_MARKER


async def _local_reply(
    model: Any, system: str, user: str, temperature: float, max_tokens: int, *, json_mode: bool = False
) -> str:
    payload: dict[str, Any] = {
        "model": model.brain_model,
        "stream": False,
        "think": False,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": model.brain_num_ctx},
    }
    if getattr(model, "ollama_keep_alive", ""):
        payload["keep_alive"] = model.ollama_keep_alive
    if json_mode:
        # Grammar-constrained output: the model can only emit valid JSON.
        payload["format"] = "json"

    def _post() -> str:
        try:
            response = requests.post(
                f"{model.ollama_base_url}/api/chat",
                json=payload,
                timeout=model.brain_timeout_seconds,
            )
        except requests.ConnectionError as exc:
            raise BrainProviderUnavailable(f"Ollama is not reachable at {model.ollama_base_url}") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
        message = (response.json() or {}).get("message") or {}
        return str(message.get("content") or "")

    return await asyncio.to_thread(_post)


async def _gemini_reply(
    model: Any, system: str, user: str, temperature: float, max_tokens: int, *, json_mode: bool = False
) -> str:
    del temperature, max_tokens, json_mode  # direct_answer_config carries Gemini sampling settings.
    if getattr(model, "client", None) is None:
        raise BrainProviderUnavailable("GEMINI_API_KEY is not set")
    response = await model.client.aio.models.generate_content(
        model=model.jarvis_model,
        contents=[f"{system}\n\n{user}"],
        config=model.direct_answer_config,
    )
    return str(getattr(response, "text", "") or "")


async def _openrouter_reply(
    model: Any, system: str, user: str, temperature: float, max_tokens: int, *, json_mode: bool = False
) -> str:
    del json_mode
    if not openrouter_model_enabled(model, model.openrouter_model):
        raise BrainProviderUnavailable("OPENROUTER_API_KEY is not set")
    return await asyncio.to_thread(
        model._call_openrouter_text_sync,
        system,
        user,
        temperature,
        max_tokens,
        model=model.openrouter_model,
    )


def _cli_reply(name: str) -> Callable[..., Awaitable[str]]:
    async def _reply(
        model: Any, system: str, user: str, temperature: float, max_tokens: int, *, json_mode: bool = False
    ) -> str:
        del temperature, max_tokens, json_mode
        backend = BACKENDS[name]()
        if not backend.is_available():
            raise BrainProviderUnavailable(f"{backend.display_name} is not installed")
        request = BackendRequest(
            prompt=f"{system}\n\nAnswer directly; do not run tools or edit files.\n\n{user}",
            cwd=tempfile.gettempdir(),
            answer_only=True,
        )
        return await run_backend_for_answer(backend, request, timeout=model.brain_cli_timeout_seconds)

    return _reply


_PROVIDERS: dict[str, Callable[..., Awaitable[str]]] = {
    "local": _local_reply,
    "gemini": _gemini_reply,
    "openrouter": _openrouter_reply,
    "claude": _cli_reply("claude"),
    "codex": _cli_reply("codex"),
    "copilot": _cli_reply("copilot"),
}


def provider_label(model: Any, name: str) -> str:
    if name == "local":
        return f"{model.brain_model} (local)"
    if name == "gemini":
        return str(model.jarvis_model)
    if name == "openrouter":
        return str(model.openrouter_model)
    return BACKENDS[name].display_name


def provider_configured(model: Any, name: str) -> bool:
    """Cheap check used to decide whether escalation is possible at all."""
    if name == "local":
        return bool(getattr(model, "brain_model", ""))
    if name == "gemini":
        return getattr(model, "client", None) is not None
    if name == "openrouter":
        return openrouter_model_enabled(model, getattr(model, "openrouter_model", ""))
    return BACKENDS[name]().is_available()


async def generate_brain_reply(
    model: Any,
    *,
    system: str,
    user: str,
    temperature: float = 0.4,
    max_tokens: int = 1800,
    force_escalation: bool = False,
    allow_self_escalation: bool = True,
    json_mode: bool = False,
    providers: dict[str, Callable[..., Awaitable[str]]] | None = None,
) -> BrainReply:
    providers = providers or _PROVIDERS
    primary = model.brain_primary
    escalation = [name for name in model.brain_escalation if name != primary]
    can_escalate = any(provider_configured(model, name) for name in escalation)
    failures: list[str] = []

    async def _attempt(name: str, system_prompt: str) -> str | None:
        try:
            text = (
                await providers[name](model, system_prompt, user, temperature, max_tokens, json_mode=json_mode)
            ).strip()
        except BrainProviderUnavailable as exc:
            failures.append(f"{name}: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 - every provider failure falls through to the next one.
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            return None
        if not text:
            failures.append(f"{name}: empty reply")
            return None
        return text

    if not (force_escalation and can_escalate):
        self_escalate = allow_self_escalation and model.brain_self_escalate and can_escalate
        text = await _attempt(primary, system + (SELF_ESCALATION_INSTRUCTION if self_escalate else ""))
        if text is not None and not _is_escalation_marker(text):
            return BrainReply(text, primary, provider_label(model, primary), escalated=False)
        if text is not None:
            failures.append(f"{primary}: asked to escalate")

    for name in escalation:
        text = await _attempt(name, system)
        if text is not None and not _is_escalation_marker(text):
            return BrainReply(text, name, provider_label(model, name), escalated=True)

    raise RuntimeError("No model could answer this request. " + "; ".join(failures))


__all__ = [
    "BrainProviderUnavailable",
    "BrainReply",
    "ESCALATE_MARKER",
    "generate_brain_reply",
    "provider_configured",
    "provider_label",
    "wants_strong_model",
]
