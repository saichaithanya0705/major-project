"""
Runtime state for rapid-response routing sessions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from PIL import ImageGrab


Cleaner = Callable[[str], str]
DEFAULT_RAPID_SESSION_ID = "__default__"


@dataclass(slots=True)
class RapidSessionState:
    max_history: int = 32
    history: deque[dict[str, str]] = field(init=False)
    _histories: dict[str, deque[dict[str, str]]] = field(init=False, repr=False)
    _stored_screenshot: object = None

    def __post_init__(self) -> None:
        self._histories = {
            DEFAULT_RAPID_SESSION_ID: deque(maxlen=self.max_history),
        }
        self.history = self._histories[DEFAULT_RAPID_SESSION_ID]

    def normalize_session_id(self, session_id: str | None = None) -> str:
        if isinstance(session_id, str):
            cleaned = session_id.strip()
            if cleaned:
                return cleaned[:160]
        return DEFAULT_RAPID_SESSION_ID

    def get_history(self, session_id: str | None = None) -> deque[dict[str, str]]:
        normalized_session_id = self.normalize_session_id(session_id)
        if normalized_session_id not in self._histories:
            self._histories[normalized_session_id] = deque(maxlen=self.max_history)
        return self._histories[normalized_session_id]

    def clear_history(self, session_id: str | None = None) -> None:
        self.get_history(session_id).clear()

    def capture_screenshot(self):
        self._stored_screenshot = ImageGrab.grab()
        return self._stored_screenshot

    def capture_fresh_screenshot(self):
        screenshot = ImageGrab.grab()
        self._stored_screenshot = None
        return screenshot

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
        session_id: str | None = None,
    ) -> None:
        cleaned = cleaner(text or "")
        if not cleaned:
            return
        self.get_history(session_id).append(
            {
                "role": role,
                "source": source,
                "text": cleaned,
            }
        )

    def format_history_for_prompt(self, session_id: str | None = None) -> str:
        history = self.get_history(session_id)
        if not history:
            return ""

        lines = []
        for entry in list(history)[-20:]:
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
