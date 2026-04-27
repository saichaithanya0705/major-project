"""
Runtime state for rapid-response routing sessions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from PIL import ImageGrab


Cleaner = Callable[[str], str]


@dataclass(slots=True)
class RapidSessionState:
    max_history: int = 32
    history: deque[dict[str, str]] = field(init=False)
    _stored_screenshot: object = None

    def __post_init__(self) -> None:
        self.history = deque(maxlen=self.max_history)

    def capture_screenshot(self):
        self._stored_screenshot = ImageGrab.grab()
        return self._stored_screenshot

    def consume_or_capture_screenshot(self):
        screenshot = self._stored_screenshot if self._stored_screenshot else ImageGrab.grab()
        self._stored_screenshot = None
        return screenshot

    def append_history(
        self,
        *,
        role: str,
        text: str,
        source: str,
        cleaner: Cleaner,
    ) -> None:
        cleaned = cleaner(text or "")
        if not cleaned:
            return
        self.history.append(
            {
                "role": role,
                "source": source,
                "text": cleaned,
            }
        )

    def format_history_for_prompt(self) -> str:
        if not self.history:
            return ""

        lines = []
        for entry in list(self.history)[-20:]:
            role = entry.get("role")
            source = entry.get("source")
            text = entry.get("text", "")

            if role == "user":
                label = "User"
            elif source in {"browser_use", "cua_cli", "cua_vision", "jarvis", "screen_judge"}:
                label = "Agent"
            else:
                label = "Rapid Assistant"

            lines.append(f"{label}: {text}")

        if not lines:
            return ""

        return (
            "\n# Conversation History (Rapid-Model Messages Only)\n"
            "Use this history for context. Agent entries are short summaries only.\n"
            + "\n".join(lines)
            + "\n"
        )


RAPID_SESSION_STATE = RapidSessionState()
