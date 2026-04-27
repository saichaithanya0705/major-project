"""
JARVIS Models - LLM integration and routing.

The package keeps imports lazy so lightweight consumers (for example, tests
that only need contracts/prompts) do not eagerly pull optional runtime deps.
"""

from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "GeminiModel",
    "RAPID_RESPONSE_SYSTEM_PROMPT",
    "RAPID_RESPONSE_TOOL_MAP",
    "RAPID_RESPONSE_TOOLS",
    "ROUTER_TOOL_MAP",
    "ROUTER_TOOLS",
    "TOOL_CONFIG",
    "call_gemini",
    "get_stored_screenshot",
    "store_screenshot",
]

_MODEL_EXPORTS = {
    "call_gemini",
    "store_screenshot",
    "get_stored_screenshot",
    "GeminiModel",
}
_FUNCTION_CALL_EXPORTS = {
    "ROUTER_TOOLS",
    "ROUTER_TOOL_MAP",
    "TOOL_CONFIG",
    "RAPID_RESPONSE_TOOLS",
    "RAPID_RESPONSE_TOOL_MAP",
}

if TYPE_CHECKING:
    from models.function_calls import (
        RAPID_RESPONSE_TOOL_MAP,
        RAPID_RESPONSE_TOOLS,
        ROUTER_TOOL_MAP,
        ROUTER_TOOLS,
        TOOL_CONFIG,
    )
    from models.models import GeminiModel, call_gemini, get_stored_screenshot, store_screenshot
    from models.prompts import RAPID_RESPONSE_SYSTEM_PROMPT


def __getattr__(name: str):
    if name in _MODEL_EXPORTS:
        return getattr(import_module("models.models"), name)
    if name in _FUNCTION_CALL_EXPORTS:
        return getattr(import_module("models.function_calls"), name)
    if name == "RAPID_RESPONSE_SYSTEM_PROMPT":
        return getattr(import_module("models.prompts"), name)
    raise AttributeError(f"module 'models' has no attribute '{name}'")
