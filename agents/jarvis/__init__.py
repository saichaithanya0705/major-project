"""
JARVIS Agent - Screen annotation and explanation.

This agent can see the user's screen and draw annotations (boxes, text, pointers)
to explain or highlight elements. It's the visual explanation component of JARVIS.
"""
from agents.jarvis.agent import JarvisAgent
from agents.jarvis.tools import (
    JARVIS_TOOLS,
    JARVIS_TOOL_MAP,
    draw_bounding_box,
    draw_pointer_to_object,
    create_text,
    create_text_for_box,
    clear_screen,
    destroy_box,
    destroy_text,
    direct_response,
)
from agents.jarvis.prompts import JARVIS_SYSTEM_PROMPT
