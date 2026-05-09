from ui.visualization_api.client import get_client


def build_chat_response_payload(text: str, source: str = "rapid_response") -> dict:
    return {
        "command": "chat_response",
        "text": str(text or ""),
        "source": str(source or "rapid_response"),
    }


async def send_chat_response(text: str, source: str = "rapid_response"):
    client = await get_client()
    await client.send(build_chat_response_payload(text, source=source))
