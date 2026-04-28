import os
import asyncio
import time
import shutil
import subprocess
from PIL import ImageGrab
from core.settings import set_host_and_port, set_screen_size, get_model_configs, get_screen_size

from models.models import call_gemini, store_screenshot
from agents.jarvis.tools import stop_all_actions
from agents.cua_cli.agent import CLIAgent
from agents.cua_vision.tools import (
    reset_state as reset_cua_vision_state,
    request_stop as request_cua_vision_stop,
)
from integrations.audio import transcribe_audio_bytes
from ui.server import VisualizationServer


def maybe_launch_electron_ui(project_root: str):
    auto_launch = os.getenv("JARVIS_AUTO_LAUNCH_ELECTRON", "1").strip().lower()
    if auto_launch in {"0", "false", "no", "off"}:
        return

    ui_root = os.path.join(project_root, "ui")
    if not os.path.isdir(ui_root):
        print(f"Electron auto-launch skipped (missing UI directory): {ui_root}")
        return

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    npm_path = shutil.which(npm_command) or shutil.which("npm")
    if not npm_path:
        print("Electron auto-launch skipped (npm not found on PATH).")
        return

    env = os.environ.copy()
    electron_binary = os.path.join(
        ui_root,
        "node_modules",
        "electron",
        "dist",
        "electron.exe" if os.name == "nt" else "electron",
    )
    if os.path.exists(electron_binary):
        env.setdefault("JARVIS_ELECTRON_BINARY", electron_binary)

    try:
        kwargs = {
            "cwd": ui_root,
            "env": env,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        subprocess.Popen([npm_path, "run", "dev"], **kwargs)
        print("Launching Electron UI...")
    except Exception as exc:
        print(f"Electron auto-launch failed: {type(exc).__name__}: {exc}")


async def main():
    # Figure out open port and set it in settings.json
    settings_path = os.path.join(os.path.dirname(__file__), "settings.json")
    host, port = set_host_and_port(settings_path)

    # Figure out dimensions of the user's screen and set it in settings.json.
    # Fallback to configured size if capture is unavailable at startup.
    try:
        screen_width, screen_height = await asyncio.wait_for(
            asyncio.to_thread(lambda: ImageGrab.grab().size),
            timeout=2.0,
        )
    except Exception as exc:
        try:
            screen_width, screen_height = get_screen_size(settings_path)
        except Exception:
            screen_width, screen_height = (1920, 1080)
        print(
            f"Screen capture unavailable at startup ({type(exc).__name__}: {exc}). "
            f"Using configured size {screen_width}x{screen_height}."
        )
    set_screen_size(screen_width, screen_height)

    # Retrieve model configs from settings
    rapid_response_model, jarvis_model = get_model_configs(settings_path)
    print(f"Models loaded - Rapid: {rapid_response_model}, JARVIS: {jarvis_model}")

    current_task = None
    task_lock = asyncio.Lock()
    last_overlay_text = ""
    last_overlay_ts = 0.0

    async def stop_all():
        nonlocal current_task
        print("Stop requested: cancelling active tasks.")
        request_cua_vision_stop()
        async with task_lock:
            task = current_task
        if task and not task.done():
            task.cancel()
        await CLIAgent.stop_all_running_processes()
        stop_all_actions()
        reset_cua_vision_state()

    async def _run_overlay_task(text: str):
        nonlocal current_task
        try:
            await call_gemini(text, rapid_response_model, jarvis_model)
        except asyncio.CancelledError:
            print("Active task cancelled.")
        except Exception as exc:
            print(f"Active task failed: {exc}")
        finally:
            async with task_lock:
                if current_task is asyncio.current_task():
                    current_task = None

    async def handle_overlay_input(text):
        nonlocal current_task, last_overlay_text, last_overlay_ts
        text = text.strip()
        if not text:
            return
        now = time.monotonic()
        if text == last_overlay_text and (now - last_overlay_ts) < 1.2:
            print(f"Overlay input ignored (duplicate within 1.2s): {text}")
            return

        last_overlay_text = text
        last_overlay_ts = now
        async with task_lock:
            if current_task and not current_task.done():
                print("Overlay input ignored (task already running).")
                return
            print(f"Overlay input: {text}")
            task = asyncio.create_task(_run_overlay_task(text))
            current_task = task

    async def handle_voice_transcription(audio_bytes: bytes, mime_type: str, filename: str) -> str:
        return await asyncio.to_thread(
            transcribe_audio_bytes,
            audio_bytes,
            filename=filename,
            mime_type=mime_type,
        )

    server = VisualizationServer(
        host=host,
        port=port,
        on_overlay_input=handle_overlay_input,
        on_capture_screenshot=store_screenshot,
        on_stop_all=stop_all,
        on_transcribe_audio=handle_voice_transcription,
    )
    await server.start()
    print(f"Visualization server listening at ws://{host}:{port}")
    maybe_launch_electron_ui(os.path.dirname(__file__))
    print("Waiting for overlay client connection...")
    await server.wait_for_client()
    print("Overlay client connected.")

    await server.wait_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        # _clear_screen()
        pass
