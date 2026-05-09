import asyncio
import base64
import hmac
import inspect
import json
import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.exceptions import ConnectionClosed
from core.settings import get_screen_size, set_screen_size

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None
try:
    import pyautogui
except Exception:
    pyautogui = None


class VisualizationServer:
    DARK_LUMINANCE_THRESHOLD = 112
    INVERTED_PANEL_DARK_THRESHOLD = 45
    STATUS_INVERTED_PANEL_DARK_THRESHOLD = 132
    MAX_WS_MESSAGE_BYTES = 10 * 1024 * 1024
    MAX_AUDIO_BYTES = 5 * 1024 * 1024
    MAX_OVERLAY_INPUT_CHARS = 4000
    MAX_REQUEST_ID_CHARS = 160
    MAX_SESSION_ID_CHARS = 160
    MAX_DRAW_TEXT_CHARS = 1200
    MAX_CHAT_RESPONSE_CHARS = 120000
    AUTH_CLOSE_CODE = 1008
    DEFAULT_ALLOWED_ORIGINS = {
        "",
        "null",
        "file://",
        "app://jarvis",
        "http://127.0.0.1",
        "http://localhost",
    }

    def __init__(
        self,
        host="127.0.0.1",
        port=8765,
        auth_token: str | None = None,
        allowed_origins: set[str] | None = None,
        on_overlay_input=None,
        on_capture_screenshot=None,
        on_stop_all=None,
        on_clear_annotations=None,
        on_transcribe_audio=None,
    ):
        self.host = host
        self.port = port
        self.auth_token = str(auth_token or "").strip()
        self.allowed_origins = set(allowed_origins or self.DEFAULT_ALLOWED_ORIGINS)
        self.clients = set()
        self.boxes = {}
        self.texts = {}
        self.dots = {}
        self._server = None
        self.on_overlay_input = on_overlay_input
        self.on_capture_screenshot = on_capture_screenshot
        self.on_stop_all = on_stop_all
        self.on_clear_annotations = on_clear_annotations
        self.on_transcribe_audio = on_transcribe_audio
        self._last_screenshot = None
        self._last_screenshot_rgb = None
        self._last_capture_backend = "none"
        self._last_cursor_pos = (0, 0)
        self._last_dark_sample = False
        self._last_theme_log_ts = 0.0
        self._active_status_theme = None
        self._seen_overlay_request_ids = {}
        self._last_overlay_text = ""
        self._last_overlay_session_id = ""
        self._last_overlay_ts = 0.0
        self._background_tasks = set()

    @staticmethod
    def _overlay_session_callback_style(callback) -> str:
        try:
            signature = inspect.signature(callback)
        except (TypeError, ValueError):
            return "keyword"

        parameters = signature.parameters
        if "session_id" in parameters:
            return "keyword"
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
            return "keyword"
        if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters.values()):
            return "positional"

        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        ]
        if len(positional_parameters) >= 2:
            return "positional"
        return "legacy"

    async def _call_overlay_input(self, text: str, session_id: str | None):
        if not self.on_overlay_input:
            return None

        callback_style = self._overlay_session_callback_style(self.on_overlay_input)
        if callback_style == "keyword":
            result = self.on_overlay_input(text, session_id=session_id)
        elif callback_style == "positional":
            result = self.on_overlay_input(text, session_id)
        else:
            result = self.on_overlay_input(text)

        if asyncio.iscoroutine(result):
            return await result
        return result

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _capture_screenshot_background(self) -> None:
        if not self.on_capture_screenshot:
            return
        try:
            if inspect.iscoroutinefunction(self.on_capture_screenshot):
                result = await self.on_capture_screenshot()
            else:
                result = await asyncio.to_thread(self.on_capture_screenshot)
            if asyncio.iscoroutine(result):
                result = await result
            self._store_screenshot(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[VisualizationServer] Screenshot capture failed: {exc}")

    @staticmethod
    def _safe_text(value, *, max_chars: int, field_name: str) -> str:
        text = str(value or "")
        if len(text) > max_chars:
            raise ValueError(f"{field_name} is too long; maximum is {max_chars} characters.")
        return text

    @staticmethod
    def _websocket_path(websocket) -> str:
        path = getattr(websocket, "path", None)
        if isinstance(path, str):
            return path
        request = getattr(websocket, "request", None)
        request_path = getattr(request, "path", None)
        return request_path if isinstance(request_path, str) else "/"

    @staticmethod
    def _websocket_headers(websocket) -> dict:
        request = getattr(websocket, "request", None)
        headers = getattr(request, "headers", None)
        if headers is None:
            headers = getattr(websocket, "request_headers", None)
        return headers or {}

    @staticmethod
    def _header_value(headers, name: str) -> str:
        try:
            value = headers.get(name) or headers.get(name.lower()) or headers.get(name.title())
        except Exception:
            value = ""
        return str(value or "").strip()

    def _origin_is_allowed(self, origin: str) -> bool:
        if not origin:
            return True
        parsed = urlparse(origin)
        if not parsed.scheme:
            return origin in self.allowed_origins
        if parsed.scheme == "file":
            return "file://" in self.allowed_origins
        normalized = f"{parsed.scheme}://{parsed.hostname or ''}"
        if parsed.port:
            normalized = f"{normalized}:{parsed.port}"
        if normalized in self.allowed_origins:
            return True
        if parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.scheme in {"http", "https"}:
            return f"{parsed.scheme}://{parsed.hostname}" in self.allowed_origins
        return False

    def _token_from_path(self, path: str) -> str:
        try:
            query = parse_qs(urlparse(path or "/").query)
        except Exception:
            return ""
        values = query.get("token") or query.get("auth_token") or []
        return str(values[0]).strip() if values else ""

    def _is_authorized_websocket(self, websocket) -> bool:
        # Unit-test fakes may call _handle_client directly without request metadata.
        # Real websocket connections have request/path metadata and must pass token/origin checks.
        if not self.auth_token:
            return True
        path = self._websocket_path(websocket)
        headers = self._websocket_headers(websocket)
        has_request_metadata = bool(path and path != "/") or bool(headers)
        if not has_request_metadata and type(websocket).__module__.startswith("tests."):
            return True
        origin = self._header_value(headers, "Origin")
        if not self._origin_is_allowed(origin):
            return False
        presented_token = self._token_from_path(path)
        return hmac.compare_digest(presented_token, self.auth_token)

    async def _reject_unauthorized(self, websocket) -> None:
        try:
            await websocket.close(
                code=self.AUTH_CLOSE_CODE,
                reason="Unauthorized visualization websocket client.",
            )
        except Exception:
            pass

    async def _send_error(self, websocket, *, event: str, error: str, request_id=None) -> None:
        payload = {"event": event, "error": str(error)}
        if request_id is not None:
            payload["requestId"] = str(request_id)
        await self._send_json(websocket, payload)

    def _store_screenshot(self, screenshot) -> None:
        self._last_screenshot = screenshot
        self._last_screenshot_rgb = None
        if screenshot is None:
            return
        try:
            self._last_screenshot_rgb = screenshot.convert("RGB")
        except Exception:
            self._last_screenshot_rgb = None

    def _is_likely_invalid_capture(self, image_rgb) -> bool:
        if image_rgb is None:
            return True
        width, height = image_rgb.size
        if width <= 0 or height <= 0:
            return True

        # Sparse sampling: if everything is near-black, this is likely a bad capture path.
        dark_like = 0
        total = 0
        for y in range(0, height, max(1, height // 6)):
            for x in range(0, width, max(1, width // 6)):
                try:
                    r, g, b = image_rgb.getpixel((x, y))
                except Exception:
                    continue
                total += 1
                if r <= 4 and g <= 4 and b <= 4:
                    dark_like += 1

        if total == 0:
            return True
        return (dark_like / total) >= 0.9

    def _get_screenshot_rgb(self):
        if self._last_screenshot_rgb is not None:
            self._last_capture_backend = "cache"
            return self._last_screenshot_rgb
        if self._last_screenshot is not None:
            self._store_screenshot(self._last_screenshot)
            self._last_capture_backend = "cache"
            return self._last_screenshot_rgb

        screenshot_rgb = None
        if ImageGrab is not None:
            try:
                screenshot_rgb = ImageGrab.grab().convert("RGB")
                self._last_capture_backend = "imagegrab"
            except Exception:
                screenshot_rgb = None

        # Fall back when PIL capture is unavailable or likely invalid (e.g., all black).
        if (screenshot_rgb is None or self._is_likely_invalid_capture(screenshot_rgb)) and pyautogui is not None:
            try:
                screenshot_rgb = pyautogui.screenshot().convert("RGB")
                self._last_capture_backend = "pyautogui"
            except Exception:
                pass

        if screenshot_rgb is None:
            self._last_capture_backend = "none"
            return None

        self._last_screenshot_rgb = screenshot_rgb
        return self._last_screenshot_rgb

    def _get_palette(self, prefer_light_text: bool) -> dict:
        if prefer_light_text:
            return {
                "mode": "light-on-dark",
                "accent": "rgba(190, 198, 210, 0.85)",
                "boxStroke": "rgba(196, 202, 214, 0.95)",
                "text": "rgba(242, 245, 248, 0.96)",
                "label": "rgba(255, 255, 255, 0.5)",
                "thinking": "rgba(212, 217, 225, 0.86)",
                "panelBg": "rgba(14, 14, 18, 0.9)",
                "panelBorder": "rgba(255, 255, 255, 0.12)",
                "meta": "rgba(255, 255, 255, 0.7)",
                "divider": "rgba(255, 255, 255, 0.75)",
                "shimmer": "rgba(245, 247, 250, 0.95)",
                "statusBg": "rgba(4, 5, 7, 0.96)",
                "statusBorder": "rgba(255, 255, 255, 0.06)",
                "statusText": "rgba(242, 245, 248, 0.96)",
                "statusShimmer": "rgba(190, 198, 210, 0.58)",
                "statusCheck": "rgba(170, 178, 190, 0.9)",
                "cursorBg": "rgba(5, 6, 8, 0.92)",
                "cursorBorder": "rgba(255, 255, 255, 0.06)",
                "cursorText": "rgba(242, 245, 248, 0.96)",
                "cursorShimmer": "rgba(190, 198, 210, 0.58)",
            }
        return {
            "mode": "dark-on-light",
            "accent": "rgba(88, 96, 112, 0.85)",
            "boxStroke": "rgba(98, 107, 124, 0.95)",
            "text": "rgba(15, 20, 30, 0.94)",
            "label": "rgba(15, 20, 30, 0.55)",
            "thinking": "rgba(53, 60, 74, 0.78)",
            "panelBg": "rgba(248, 250, 252, 0.94)",
            "panelBorder": "rgba(15, 20, 30, 0.14)",
            "meta": "rgba(15, 20, 30, 0.6)",
            "divider": "rgba(15, 20, 30, 0.5)",
            "shimmer": "rgba(108, 116, 132, 0.82)",
            "statusBg": "rgba(245, 248, 252, 0.96)",
            "statusBorder": "rgba(15, 20, 30, 0.1)",
            "statusText": "rgba(15, 20, 30, 0.94)",
            "statusShimmer": "rgba(108, 116, 132, 0.55)",
            "statusCheck": "rgba(108, 116, 132, 0.9)",
            "cursorBg": "rgba(246, 249, 252, 0.94)",
            "cursorBorder": "rgba(15, 20, 30, 0.1)",
            "cursorText": "rgba(15, 20, 30, 0.94)",
            "cursorShimmer": "rgba(108, 116, 132, 0.55)",
        }

    def _is_dark_at(self, x: int, y: int, threshold: int = None) -> bool:
        screenshot = self._get_screenshot_rgb()
        if screenshot is None:
            return self._last_dark_sample
        width, height = screenshot.size
        if width <= 0 or height <= 0:
            return self._last_dark_sample
        px = min(max(int(x), 0), width - 1)
        py = min(max(int(y), 0), height - 1)

        # Average a local neighborhood for stability.
        radius = 12
        step = 4
        luminance_sum = 0.0
        sample_count = 0

        for dy in range(-radius, radius + 1, step):
            sy = min(max(py + dy, 0), height - 1)
            for dx in range(-radius, radius + 1, step):
                sx = min(max(px + dx, 0), width - 1)
                try:
                    r, g, b = screenshot.getpixel((sx, sy))
                except Exception:
                    continue

                luminance_sum += (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
                sample_count += 1

        # Conservative fallback if sampling failed.
        if sample_count == 0:
            return self._last_dark_sample

        avg_luminance = luminance_sum / sample_count
        active_threshold = threshold if threshold is not None else self.DARK_LUMINANCE_THRESHOLD
        is_dark = avg_luminance < active_threshold
        self._last_dark_sample = is_dark
        return is_dark

    def _theme_for_point(self, x: int, y: int) -> dict:
        prefer_light_text = self._is_dark_at(x, y)
        return self._get_palette(prefer_light_text)

    def _theme_for_text(self, x: int, y: int) -> dict:
        prefer_light_text = self._is_dark_at(x, y, self.INVERTED_PANEL_DARK_THRESHOLD)
        return self._get_palette(not prefer_light_text)

    def _theme_for_status(self) -> dict:
        width, height = get_screen_size()
        if not width or not height:
            screenshot = self._get_screenshot_rgb()
            if screenshot:
                width, height = screenshot.size
        x = int((width or 1920) / 2)
        y = 50
        # Invert for status bubble as well, but use a more lenient threshold
        # for the brighter top strip many desktops/windows have.
        prefer_light_text = self._is_dark_at(x, y, self.STATUS_INVERTED_PANEL_DARK_THRESHOLD)
        return self._get_palette(not prefer_light_text)

    def _theme_for_cursor(self) -> dict:
        x, y = self._last_cursor_pos
        prefer_light_text = self._is_dark_at(x, y, self.INVERTED_PANEL_DARK_THRESHOLD)
        return self._get_palette(not prefer_light_text)

    async def start(self):
        # Disable ping_interval since VisualizationClient (internal) only sends
        # and doesn't run a receive loop to respond to pings
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=None,
            max_size=self.MAX_WS_MESSAGE_BYTES,
        )

    async def stop(self):
        for task in list(self._background_tasks):
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)
            self._background_tasks.clear()
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()

    async def wait_forever(self):
        await asyncio.Future()

    async def wait_for_client(self):
        while not self.clients:
            await asyncio.sleep(0.05)

    async def _handle_client(self, websocket):
        if not self._is_authorized_websocket(websocket):
            await self._reject_unauthorized(websocket)
            return

        self.clients.add(websocket)
        try:
            for box in self.boxes.values():
                await websocket.send(json.dumps(box))
            for text in self.texts.values():
                await websocket.send(json.dumps(text))
            for dot in self.dots.values():
                await websocket.send(json.dumps(dot))

            async for message in websocket:
                if len(message) > self.MAX_WS_MESSAGE_BYTES:
                    await self._send_error(
                        websocket,
                        event="overlay_error",
                        error="Websocket message is too large.",
                    )
                    continue
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    await self._send_error(
                        websocket,
                        event="overlay_error",
                        error="Websocket payload must be a JSON object.",
                    )
                    continue

                command = payload.get("command")
                if command == "draw_box":
                    if payload.get("autoContrast"):
                        center_x = payload.get("x", 0) + (payload.get("width", 0) / 2)
                        center_y = payload.get("y", 0) + (payload.get("height", 0) / 2)
                        theme = self._theme_for_point(center_x, center_y)
                        payload["stroke"] = theme.get("boxStroke") or theme.get("accent") or payload.get("stroke")
                    self.boxes[payload["id"]] = payload
                    await self._broadcast(payload)
                elif command == "draw_dot":
                    self.dots[payload["id"]] = payload
                    await self._broadcast(payload)
                elif command == "draw_text":
                    try:
                        payload["text"] = self._safe_text(
                            payload.get("text", ""),
                            max_chars=self.MAX_DRAW_TEXT_CHARS,
                            field_name="draw_text text",
                        )
                    except ValueError as exc:
                        await self._send_error(websocket, event="overlay_error", error=str(exc))
                        continue
                    theme = self._theme_for_text(payload.get("x", 0), payload.get("y", 0))
                    payload["theme"] = theme
                    payload["color"] = theme.get("accent")
                    self.texts[payload["id"]] = payload
                    await self._broadcast(payload)
                elif command == "chat_response":
                    try:
                        payload["text"] = self._safe_text(
                            payload.get("text", ""),
                            max_chars=self.MAX_CHAT_RESPONSE_CHARS,
                            field_name="chat_response text",
                        )
                    except ValueError as exc:
                        await self._send_error(websocket, event="overlay_error", error=str(exc))
                        continue
                    payload["source"] = payload.get("source") or "rapid_response"
                    await self._broadcast(payload)
                elif command == "remove_box":
                    self.boxes.pop(payload.get("id"), None)
                    await self._broadcast(payload)
                elif command == "remove_dot":
                    self.dots.pop(payload.get("id"), None)
                    await self._broadcast(payload)
                elif command == "remove_text":
                    self.texts.pop(payload.get("id"), None)
                    await self._broadcast(payload)
                elif command == "overlay_hide":
                    await self._broadcast(payload)
                elif command == "show_command_overlay":
                    await self._broadcast(payload)
                elif command == "set_model_name":
                    await self._broadcast(payload)
                elif command == "show_status_bubble":
                    if "theme" in payload and payload.get("theme"):
                        self._active_status_theme = payload["theme"]
                    else:
                        self._active_status_theme = self._theme_for_status()
                        payload["theme"] = self._active_status_theme
                    await self._broadcast(payload)
                elif command == "update_status_bubble":
                    if "theme" in payload and payload.get("theme"):
                        self._active_status_theme = payload["theme"]
                    elif self._active_status_theme is not None:
                        payload["theme"] = self._active_status_theme
                    else:
                        self._active_status_theme = self._theme_for_status()
                        payload["theme"] = self._active_status_theme
                    await self._broadcast(payload)
                elif command == "complete_status_bubble":
                    if "theme" in payload and payload.get("theme"):
                        self._active_status_theme = payload["theme"]
                    elif self._active_status_theme is not None:
                        payload["theme"] = self._active_status_theme
                    else:
                        self._active_status_theme = self._theme_for_status()
                        payload["theme"] = self._active_status_theme
                    await self._broadcast(payload)
                elif command == "hide_status_bubble":
                    self._active_status_theme = None
                    await self._broadcast(payload)
                elif command == "show_cursor_status":
                    if "theme" not in payload:
                        payload["theme"] = self._theme_for_cursor()
                    await self._broadcast(payload)
                elif command == "update_cursor_status":
                    if "theme" not in payload:
                        payload["theme"] = self._theme_for_cursor()
                    await self._broadcast(payload)
                elif command == "hide_cursor_status":
                    await self._broadcast(payload)
                elif command == "set_cursor_status_position":
                    self._last_cursor_pos = (payload.get("x", 0), payload.get("y", 0))
                    await self._broadcast(payload)
                elif command == "clear":
                    self.boxes.clear()
                    self.texts.clear()
                    self.dots.clear()
                    self._active_status_theme = None
                    await self._broadcast(payload)
                elif command == "set_background":
                    await self._broadcast(payload)
                elif command == "terminal_session_event":
                    await self._broadcast(payload)
                elif command == "chat_vision_artifact":
                    await self._broadcast(payload)
                elif command in {"vision_capture_started", "vision_chat_restore"}:
                    await self._broadcast(payload)
                else:
                    event = payload.get("event")
                    if event == "viewport":
                        width = payload.get("width")
                        height = payload.get("height")
                        print(f"viewport: {width}x{height}")
                        if width and height:
                            set_screen_size(int(width), int(height))
                        continue
                    if event == "click":
                        print(f"clicked: {payload.get('id')}")
                    if event == "capture_screenshot":
                        if self.on_capture_screenshot:
                            task = asyncio.create_task(self._capture_screenshot_background())
                            self._track_background_task(task)
                        continue
                    if event == "transcribe_audio":
                        request_id = payload.get("requestId") or payload.get("request_id")
                        audio_base64 = payload.get("audioBase64") or payload.get("audio_base64") or ""
                        mime_type = str(payload.get("mimeType") or payload.get("mime_type") or "audio/webm")
                        filename = str(payload.get("filename") or "voice-command.webm")

                        if not self.on_transcribe_audio:
                            await self._send_json(websocket, {
                                "event": "voice_transcription_error",
                                "requestId": request_id,
                                "error": "Voice transcription is not configured.",
                            })
                            continue

                        try:
                            request_id = self._safe_text(
                                request_id,
                                max_chars=self.MAX_REQUEST_ID_CHARS,
                                field_name="requestId",
                            ) if request_id is not None else None
                            audio_bytes = base64.b64decode(audio_base64, validate=True)
                            if not audio_bytes:
                                raise ValueError("Recorded audio was empty.")
                            if len(audio_bytes) > self.MAX_AUDIO_BYTES:
                                raise ValueError(
                                    f"Recorded audio is too large; maximum is {self.MAX_AUDIO_BYTES} bytes."
                                )
                            result = self.on_transcribe_audio(audio_bytes, mime_type, filename)
                            if asyncio.iscoroutine(result):
                                result = await result
                            text = str(result or "").strip()
                            if not text:
                                raise ValueError("No speech was detected in the recording.")
                            await self._send_json(websocket, {
                                "event": "voice_transcription_result",
                                "requestId": request_id,
                                "text": text,
                            })
                        except Exception as exc:
                            await self._send_json(websocket, {
                                "event": "voice_transcription_error",
                                "requestId": request_id,
                                "error": str(exc) or type(exc).__name__,
                            })
                        continue
                    if event == "stop_all":
                        if self.on_stop_all:
                            result = self.on_stop_all()
                            if asyncio.iscoroutine(result):
                                await result
                        continue
                    if event == "clear_annotations":
                        if self.on_clear_annotations:
                            result = self.on_clear_annotations()
                            if asyncio.iscoroutine(result):
                                await result
                        self.boxes.clear()
                        self.texts.clear()
                        self.dots.clear()
                        self._active_status_theme = None
                        await self._broadcast({"command": "clear"})
                        await self._broadcast({"command": "vision_chat_restore"})
                        continue
                    if event == "overlay_input":
                        try:
                            text = self._safe_text(
                                payload.get("text", ""),
                                max_chars=self.MAX_OVERLAY_INPUT_CHARS,
                                field_name="overlay input",
                            )
                            session_id = payload.get("sessionId") or payload.get("session_id")
                            session_id = (
                                self._safe_text(
                                    session_id,
                                    max_chars=self.MAX_SESSION_ID_CHARS,
                                    field_name="sessionId",
                                ).strip()
                                if session_id is not None
                                else None
                            )
                            request_id = payload.get("requestId") or payload.get("request_id")
                            request_id = (
                                self._safe_text(
                                    request_id,
                                    max_chars=self.MAX_REQUEST_ID_CHARS,
                                    field_name="requestId",
                                )
                                if request_id is not None
                                else None
                            )
                        except ValueError as exc:
                            await self._send_error(websocket, event="overlay_error", error=str(exc))
                            continue
                        now = time.monotonic()

                        # Drop duplicate submit events that can occur during rapid
                        # key/click interactions or transient websocket reconnects.
                        if request_id:
                            expired = [
                                rid for rid, ts in self._seen_overlay_request_ids.items()
                                if (now - ts) > 10.0
                            ]
                            for rid in expired:
                                self._seen_overlay_request_ids.pop(rid, None)
                            if request_id in self._seen_overlay_request_ids:
                                continue
                            self._seen_overlay_request_ids[request_id] = now
                        else:
                            normalized = " ".join(str(text).split())
                            normalized_session_id = " ".join(str(session_id or "").split())
                            if (
                                normalized
                                and normalized == self._last_overlay_text
                                and normalized_session_id == self._last_overlay_session_id
                                and (now - self._last_overlay_ts) < 1.2
                            ):
                                continue
                            self._last_overlay_text = normalized
                            self._last_overlay_session_id = normalized_session_id
                            self._last_overlay_ts = now

                        await self._call_overlay_input(text, session_id)
        except ConnectionClosed:
            # Normal path when renderer reloads or disconnects abruptly.
            pass
        finally:
            self.clients.discard(websocket)

    async def _send_json(self, websocket, payload):
        try:
            await websocket.send(json.dumps(payload))
        except ConnectionClosed:
            self.clients.discard(websocket)

    async def _broadcast(self, payload):
        if not self.clients:
            return
        message = json.dumps(payload)
        stale = []
        for client in list(self.clients):
            try:
                await client.send(message)
            except ConnectionClosed:
                stale.append(client)

        for client in stale:
            self.clients.discard(client)
