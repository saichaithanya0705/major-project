"""Spec generation for structured skills through the local-first brain."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _brain_model() -> Any:
    # Imported lazily: models.models pulls in the router stack.
    from core.settings import get_model_configs
    from models.models import GeminiModel

    rapid_response_model, jarvis_model = get_model_configs()
    return GeminiModel(jarvis_model=jarvis_model, rapid_response_model=rapid_response_model)


async def generate_spec_with_brain(system: str, user: str, force_escalation: bool) -> str:
    from models.brain import generate_brain_reply

    reply = await generate_brain_reply(
        _brain_model(),
        system=system,
        user=user,
        temperature=0.3,
        max_tokens=4000,
        force_escalation=force_escalation,
        allow_self_escalation=False,
        json_mode=True,
    )
    return reply.text
