import json
import os
import socket
import tempfile
from hashlib import sha1
from pathlib import Path
from typing import Tuple, Union

DEFAULT_SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "settings.json")
_RUNTIME_STATE_ENV_VAR = "JARVIS_RUNTIME_STATE_PATH"


def _read_json_file(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        pass
    except Exception:
        pass
    return {}


def _write_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=4)
    temp_path.replace(path)


def _runtime_state_path(settings_path: str = DEFAULT_SETTINGS_PATH) -> Path:
    explicit = os.getenv(_RUNTIME_STATE_ENV_VAR, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    settings_root = Path(settings_path).resolve().parent
    digest = sha1(str(settings_root).encode("utf-8")).hexdigest()[:12]
    filename = f"{settings_root.name}-{digest}.json"
    return Path(tempfile.gettempdir()) / "jarvis-runtime" / filename


def get_runtime_state_path(settings_path: str = DEFAULT_SETTINGS_PATH) -> str:
    """Return the runtime state file used for ephemeral host/screen/viewport state."""
    return str(_runtime_state_path(settings_path))


def _read_settings_file(settings_path: str = DEFAULT_SETTINGS_PATH) -> dict:
    return _read_json_file(Path(settings_path).expanduser().resolve())


def _read_runtime_state(settings_path: str = DEFAULT_SETTINGS_PATH) -> dict:
    return _read_json_file(_runtime_state_path(settings_path))


def _write_runtime_state(payload: dict, settings_path: str = DEFAULT_SETTINGS_PATH) -> None:
    _write_json_file(_runtime_state_path(settings_path), payload)


def _as_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


# ================================================================================================
# HOST AND PORT
# ================================================================================================

def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def set_host_and_port(settings_path: str = DEFAULT_SETTINGS_PATH) -> tuple[str, int]:
    settings = _read_settings_file(settings_path)
    runtime_state = _read_runtime_state(settings_path)

    host = str(runtime_state.get("host") or settings.get("host") or "127.0.0.1")
    preferred_port = _as_int(settings.get("port", 8765), 8765)
    if _is_port_free(host, preferred_port):
        port = preferred_port
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            port = sock.getsockname()[1]

    runtime_state["host"] = host
    runtime_state["port"] = port
    _write_runtime_state(runtime_state, settings_path)

    return host, port


def set_runtime_host_and_port(
    host: str,
    port: int,
    settings_path: str = DEFAULT_SETTINGS_PATH,
) -> tuple[str, int]:
    """
    Persist an explicit runtime host/port pair without mutating static settings.

    Useful for tests that spin isolated local websocket servers.
    """
    runtime_state = _read_runtime_state(settings_path)
    runtime_state["host"] = str(host or "127.0.0.1")
    runtime_state["port"] = _as_int(port, 8765)
    _write_runtime_state(runtime_state, settings_path)
    return str(runtime_state["host"]), int(runtime_state["port"])


def get_host(settings_path: str = DEFAULT_SETTINGS_PATH) -> str:
    runtime_state = _read_runtime_state(settings_path)
    if runtime_state.get("host"):
        return str(runtime_state["host"])
    settings = _read_settings_file(settings_path)
    return str(settings.get("host", "127.0.0.1"))


def get_port(settings_path: str = DEFAULT_SETTINGS_PATH) -> int:
    runtime_state = _read_runtime_state(settings_path)
    if runtime_state.get("port") is not None:
        return _as_int(runtime_state.get("port"), 8765)
    settings = _read_settings_file(settings_path)
    return _as_int(settings.get("port"), 8765)


# ================================================================================================
# SCREEN SIZE
# ================================================================================================

def set_screen_size(screen_width: int, screen_height: int, settings_path: str = DEFAULT_SETTINGS_PATH) -> None:
    runtime_state = _read_runtime_state(settings_path)
    runtime_state["screen_width"] = int(screen_width)
    runtime_state["screen_height"] = int(screen_height)
    _write_runtime_state(runtime_state, settings_path)


def get_screen_size(settings_path: str = DEFAULT_SETTINGS_PATH) -> tuple[int, int]:
    runtime_state = _read_runtime_state(settings_path)
    settings = _read_settings_file(settings_path)
    width = _as_int(runtime_state.get("screen_width", settings.get("screen_width", 1920)), 1920)
    height = _as_int(runtime_state.get("screen_height", settings.get("screen_height", 1080)), 1080)
    return width, height


def set_viewport_size(viewport_width: int, viewport_height: int, settings_path: str = DEFAULT_SETTINGS_PATH) -> None:
    runtime_state = _read_runtime_state(settings_path)
    runtime_state["viewport_width"] = int(viewport_width)
    runtime_state["viewport_height"] = int(viewport_height)
    _write_runtime_state(runtime_state, settings_path)


def get_viewport_size(settings_path: str = DEFAULT_SETTINGS_PATH) -> tuple[int, int]:
    runtime_state = _read_runtime_state(settings_path)
    settings = _read_settings_file(settings_path)
    width = _as_int(runtime_state.get("viewport_width", settings.get("viewport_width", 0)), 0)
    height = _as_int(runtime_state.get("viewport_height", settings.get("viewport_height", 0)), 0)
    return width, height


# ================================================================================================
# MODEL CONFIG
# ================================================================================================

def get_model_configs(settings_path: str = DEFAULT_SETTINGS_PATH) -> tuple[str, str]:
    """Get both model configurations: (rapid_response_model, jarvis_model)"""
    settings = _read_settings_file(settings_path)
    return (
        settings.get("rapid_response_model", "qwen3.5:4b-q4_K_M"),
        settings.get("jarvis_model", "gemini-3-flash-preview")
    )


def get_rapid_response_model(settings_path: str = DEFAULT_SETTINGS_PATH) -> str:
    settings = _read_settings_file(settings_path)
    return settings.get("rapid_response_model", "qwen3.5:4b-q4_K_M")


def get_jarvis_model(settings_path: str = DEFAULT_SETTINGS_PATH) -> str:
    settings = _read_settings_file(settings_path)
    return settings.get("jarvis_model", "gemini-3-flash-preview")


# ================================================================================================
# TTS CONFIG
# ================================================================================================

def get_tts_active_bool(settings_path: str = DEFAULT_SETTINGS_PATH) -> tuple[bool]:
    """Return tuple with boolean if TTS should be active or not"""
    settings = _read_settings_file(settings_path)
    return (settings.get("tts", False),)


# ================================================================================================
# PERSONALIZATION CONFIG
# ================================================================================================

def get_personalization_config(settings_path: str = DEFAULT_SETTINGS_PATH) -> Tuple[Union[str, bool]]:
    """Return tuple with personalization string or False if not set"""
    settings = _read_settings_file(settings_path)
    return (settings.get("personalization", False),)
