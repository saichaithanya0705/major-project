"""
Status UI presentation helpers for CUA vision runtime.
"""

from __future__ import annotations

import asyncio

from ui.visualization_api.cursor_status import (
    hide_cursor_status,
    show_cursor_status,
    update_cursor_status,
)
from ui.visualization_api.status_bubble import (
    hide_status_bubble,
    show_status_bubble,
    update_status_bubble,
)


class StatusPresenter:
    def __init__(self, source: str = "cua_vision"):
        self.source = source
        self._visible = False
        self._last_text: str | None = None

    async def set(self, text: str) -> None:
        if text == self._last_text:
            return

        if not self._visible:
            await self.safe_ui_call(
                show_status_bubble(text, source=self.source),
                "show_status_bubble",
            )
            await self.safe_ui_call(
                show_cursor_status(text, source=self.source),
                "show_cursor_status",
            )
            self._visible = True
            self._last_text = text
            return

        await self.safe_ui_call(
            update_status_bubble(text, source=self.source),
            "update_status_bubble",
        )
        await self.safe_ui_call(
            update_cursor_status(text, source=self.source),
            "update_cursor_status",
        )
        self._last_text = text

    async def hide(self, delay_ms: int = 0) -> None:
        if not self._visible:
            return

        await self.safe_ui_call(hide_cursor_status(), "hide_cursor_status")
        await self.safe_ui_call(hide_status_bubble(delay=delay_ms), "hide_status_bubble")
        self._visible = False
        self._last_text = None

    async def safe_ui_call(self, coro, label: str) -> None:
        """Best-effort UI calls: visualization failures must not block task execution."""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[VisionAgent] UI call failed ({label}): {e}")
