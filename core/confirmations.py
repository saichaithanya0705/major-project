"""
Ask the user to approve a risky action and wait for their answer in chat.

An agent calls ``CONFIRMATIONS.request("click 'Place order' on amazon.in")``.
The question appears in the chat window; the user's next message (typed or
spoken) answers it. "yes"-like replies approve; anything else, or no reply
within the timeout, declines. Set ``JARVIS_CONFIRM_RISKY_ACTIONS=off`` to
approve everything without asking.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Awaitable, Callable

DEFAULT_TIMEOUT_SECONDS = 120.0
_YES = re.compile(r"^\s*(?:y|yes|yeah|yep|yup|sure|ok(?:ay)?|allow|approve|go ahead|do it|confirm(?:ed)?|proceed)\b[\s.!]*$", re.IGNORECASE)

Notifier = Callable[[str], Awaitable[None]]


async def _notify_chat(text: str) -> None:
    from ui.visualization_api.client import get_client

    try:
        client = await get_client()
        await client.send({"command": "confirmation_request", "text": text})
    except Exception as exc:  # noqa: BLE001 - the UI is optional; the request still times out safely.
        print(f"[Confirm] Could not show confirmation in chat: {exc}")


def confirmations_enabled() -> bool:
    return os.getenv("JARVIS_CONFIRM_RISKY_ACTIONS", "on").strip().lower() not in {"off", "0", "false", "no"}


class ConfirmationBroker:
    def __init__(self, notify: Notifier | None = None, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._notify = notify or _notify_chat
        self._timeout_seconds = timeout_seconds
        self._pending: asyncio.Future[bool] | None = None

    @property
    def has_pending(self) -> bool:
        return self._pending is not None and not self._pending.done()

    async def request(self, action: str) -> bool:
        if not confirmations_enabled():
            return True
        if self.has_pending:
            # One question at a time; a second risky action while waiting is declined.
            return False
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending = future
        await self._notify(
            f"**Confirm:** Jarvis wants to {action}.\n\nReply **yes** to allow it, or anything else to cancel."
        )
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=self._timeout_seconds)
        except asyncio.TimeoutError:
            await self._notify("No answer, so I cancelled that action.")
            return False
        finally:
            if self._pending is future:
                self._pending = None

    def answer(self, text: str) -> bool:
        """Treat ``text`` as the answer to a pending question. Returns True if it was consumed."""
        if not self.has_pending:
            return False
        assert self._pending is not None
        self._pending.set_result(bool(_YES.match(text or "")))
        return True


CONFIRMATIONS = ConfirmationBroker()
