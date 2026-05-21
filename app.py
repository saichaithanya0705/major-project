import os
import asyncio
import time
from pathlib import Path
from core import app_runtime_lifecycle
from core.process_lifecycle import (
    ManagedProcessHandle,
    ProcessSupervisor,
    summarize_stop_results,
)
from core.settings import (
    ensure_auth_token,
    get_model_configs,
    set_host_and_port,
    set_screen_size,
)

from models.models import call_gemini, preflight_router_configuration, store_screenshot
from agents.browser.agent import BrowserAgent
from agents.jarvis.tools import clear_annotation_actions, stop_all_actions
from agents.cua_cli.agent import CLIAgent
from agents.cua_vision.tools import (
    reset_state as reset_cua_vision_state,
    request_stop as request_cua_vision_stop,
)
from integrations.audio import transcribe_audio_bytes
from ui.server import VisualizationServer


_DEFAULT_PROCESS_SUPERVISOR = ProcessSupervisor()


def run_runtime_cleanup(project_root: str | os.PathLike[str]) -> None:
    outcome = app_runtime_lifecycle.run_runtime_cleanup(
        project_root,
        active_background_logs_provider=CLIAgent.active_background_log_paths,
    )
    for line in outcome.log_lines():
        print(line)


def maybe_launch_electron_ui(
    project_root: str,
    *,
    supervisor: ProcessSupervisor | None = None,
) -> ManagedProcessHandle | None:
    outcome = app_runtime_lifecycle.launch_electron_ui(
        project_root,
        supervisor=supervisor or _DEFAULT_PROCESS_SUPERVISOR,
    )
    if outcome.message:
        print(outcome.message)
    return outcome.handle


async def main():
    project_root = Path(__file__).resolve().parent
    process_supervisor = ProcessSupervisor()
    run_runtime_cleanup(project_root)

    # Figure out open port and set it in settings.json
    settings_path = str(project_root / "settings.json")
    host, port = set_host_and_port(settings_path)
    auth_token = ensure_auth_token(settings_path)

    startup_screen_size = await app_runtime_lifecycle.resolve_startup_screen_size(
        settings_path,
    )
    if startup_screen_size.warning:
        print(startup_screen_size.warning)
    set_screen_size(
        startup_screen_size.width,
        startup_screen_size.height,
        settings_path,
    )

    # Retrieve model configs from settings
    rapid_response_model, jarvis_model = get_model_configs(settings_path)
    print(f"Models loaded - Rapid: {rapid_response_model}, JARVIS: {jarvis_model}")
    router_preflight_warning = await asyncio.to_thread(
        preflight_router_configuration,
        rapid_response_model,
    )
    if router_preflight_warning:
        print(f"[Router][Preflight] {router_preflight_warning}")

    current_task = None
    task_lock = asyncio.Lock()
    last_overlay_text = ""
    last_overlay_session_id = ""
    last_overlay_ts = 0.0

    async def stop_all():
        nonlocal current_task
        print("Stop requested: cancelling active tasks.")
        request_cua_vision_stop()
        BrowserAgent.request_stop_all()
        async with task_lock:
            task = current_task
        if task and not task.done():
            task.cancel()
        await CLIAgent.stop_all_running_processes()
        stop_all_actions()
        reset_cua_vision_state()

    async def _run_overlay_task(text: str, session_id: str | None = None):
        nonlocal current_task
        try:
            outcome = await app_runtime_lifecycle.execute_runtime_task(
                lambda: call_gemini(
                    text,
                    rapid_response_model,
                    jarvis_model,
                    session_id=session_id,
                )
            )
            if outcome.status == "cancelled":
                print("Active task cancelled.")
            elif outcome.status == "failed":
                print(f"Active task failed: {outcome.error}")
        finally:
            async with task_lock:
                if current_task is asyncio.current_task():
                    current_task = None

    async def handle_overlay_input(text, session_id: str | None = None):
        nonlocal current_task, last_overlay_text, last_overlay_session_id, last_overlay_ts
        text = text.strip()
        if not text:
            return
        normalized_session_id = str(session_id or "").strip()
        now = time.monotonic()
        if (
            text == last_overlay_text
            and normalized_session_id == last_overlay_session_id
            and (now - last_overlay_ts) < 1.2
        ):
            print(f"Overlay input ignored (duplicate within 1.2s): {text}")
            return

        last_overlay_text = text
        last_overlay_session_id = normalized_session_id
        last_overlay_ts = now
        async with task_lock:
            if current_task and not current_task.done():
                print("Overlay input ignored (task already running).")
                return
            print(f"Overlay input: {text}")
            BrowserAgent.clear_stop_request()
            task = asyncio.create_task(_run_overlay_task(text, session_id=normalized_session_id or None))
            current_task = task

    async def handle_voice_transcription(audio_bytes: bytes, mime_type: str, filename: str) -> str:
        return await asyncio.to_thread(
            transcribe_audio_bytes,
            audio_bytes,
            filename=filename,
            mime_type=mime_type,
        )

    try:
        server = VisualizationServer(
            host=host,
            port=port,
            auth_token=auth_token,
            on_overlay_input=handle_overlay_input,
            on_capture_screenshot=store_screenshot,
            on_stop_all=stop_all,
            on_clear_annotations=clear_annotation_actions,
            on_transcribe_audio=handle_voice_transcription,
        )
        await server.start()
        print(f"Visualization server listening at ws://{host}:{port}")
        maybe_launch_electron_ui(str(project_root), supervisor=process_supervisor)
        print("Waiting for overlay client connection...")
        await server.wait_for_client()
        print("Overlay client connected.")

        await server.wait_forever()
    finally:
        for message in summarize_stop_results(process_supervisor.stop_all()):
            print(f"[ProcessCleanup] {message}")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        run_runtime_cleanup(Path(__file__).resolve().parent)
