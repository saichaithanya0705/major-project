from __future__ import annotations

from typing import Any

from ui.visualization_api.client import get_client


async def send_chat_vision_artifact(
    *,
    summary: str,
    artifact: dict[str, Any],
    source: str = "jarvis",
):
    client = await get_client()
    await client.send(
        {
            "command": "chat_vision_artifact",
            "source": source,
            "summary": str(summary or "Screen analysis snapshot"),
            "artifact": artifact,
        }
    )
