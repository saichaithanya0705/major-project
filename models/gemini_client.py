"""Access to the optional Gemini client used for screen tasks."""

from __future__ import annotations

from typing import Any


class GeminiNotConfiguredError(RuntimeError):
    """Raised when a Gemini call is attempted without GEMINI_API_KEY.

    Callers treat it like a quota error so the OpenRouter fallback runs.
    """


def gemini_client(model: Any) -> Any:
    client = getattr(model, "client", None)
    if client is None:
        raise GeminiNotConfiguredError("GEMINI_API_KEY is not set")
    return client
