"""
JARVIS Agent - Screen annotation and explanation.

This agent can see the user's screen and draw annotations (boxes, text, pointers)
to explain or highlight elements. It's the visual explanation component of JARVIS.
"""
from importlib import import_module
from typing import TYPE_CHECKING

__all__ = [
    "JARVIS_SYSTEM_PROMPT",
    "JARVIS_TOOL_MAP",
    "JARVIS_TOOLS",
    "JarvisAgent",
    "clear_screen",
    "create_text",
    "create_text_for_box",
    "destroy_box",
    "destroy_text",
    "direct_response",
    "draw_bounding_box",
    "draw_pointer_to_object",
]

_AGENT_EXPORTS = {"JarvisAgent"}
_TOOL_EXPORTS = {
    "JARVIS_TOOLS",
    "JARVIS_TOOL_MAP",
    "draw_bounding_box",
    "draw_pointer_to_object",
    "create_text",
    "create_text_for_box",
    "clear_screen",
    "destroy_box",
    "destroy_text",
    "direct_response",
}

if TYPE_CHECKING:
    from agents.jarvis.agent import JarvisAgent
    from agents.jarvis.prompts import JARVIS_SYSTEM_PROMPT
    from agents.jarvis.tools import (
        JARVIS_TOOL_MAP,
        JARVIS_TOOLS,
        clear_screen,
        create_text,
        create_text_for_box,
        destroy_box,
        destroy_text,
        direct_response,
        draw_bounding_box,
        draw_pointer_to_object,
    )


def __getattr__(name: str):
    if name in _AGENT_EXPORTS:
        return getattr(import_module("agents.jarvis.agent"), name)
    if name in _TOOL_EXPORTS:
        return getattr(import_module("agents.jarvis.tools"), name)
    if name == "JARVIS_SYSTEM_PROMPT":
        return getattr(import_module("agents.jarvis.prompts"), name)
    raise AttributeError(f"module 'agents.jarvis' has no attribute '{name}'")
