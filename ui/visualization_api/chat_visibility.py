from ui.visualization_api.client import get_client


async def send_vision_capture_started():
    client = await get_client()
    await client.send({"command": "vision_capture_started"})


async def send_vision_chat_restore():
    client = await get_client()
    await client.send({"command": "vision_chat_restore"})
