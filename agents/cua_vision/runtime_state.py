"""
Runtime state container for CUA vision execution.

Keeping state in a dedicated module clarifies ownership and allows consumers
outside tool declarations (for example loop engines/tests) to use one contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from PIL import Image


@dataclass
class VisionRuntimeState:
    memory_text: list[str] = field(default_factory=list)
    memory_image: list[Image.Image] = field(default_factory=list)
    execution_history: str | None = None
    master_prompt: str | None = None
    retries: int = 0
    stop_requested: bool = False
    last_capture_context: dict | None = None
    last_capture_image: Image.Image | None = None


_STATE = VisionRuntimeState()


def reset_state():
    """Reset all runtime state for a new task."""
    _STATE.memory_text = []
    _STATE.memory_image = []
    _STATE.execution_history = None
    _STATE.master_prompt = None
    _STATE.retries = 0
    _STATE.last_capture_context = None
    _STATE.last_capture_image = None


def get_memory():
    """Get current memory state."""
    return _STATE.memory_text, _STATE.memory_image


def request_stop():
    """Request that the current CUA vision task stop as soon as possible."""
    _STATE.stop_requested = True


def clear_stop_request():
    """Clear any pending stop request before starting a new task."""
    _STATE.stop_requested = False


def is_stop_requested() -> bool:
    """Return whether a stop request has been issued."""
    return _STATE.stop_requested


def set_last_capture_context(
    width: int,
    height: int,
    logical_width: int,
    logical_height: int,
    offset_x: float,
    offset_y: float,
    scale_x: float,
    scale_y: float,
    mode: str,
):
    """Store the most recent capture frame metadata for coordinate remapping."""
    _STATE.last_capture_context = {
        "width": int(width),
        "height": int(height),
        "logical_width": int(logical_width),
        "logical_height": int(logical_height),
        "offset_x": float(offset_x),
        "offset_y": float(offset_y),
        "scale_x": float(scale_x),
        "scale_y": float(scale_y),
        "mode": mode,
    }


def get_last_capture_context() -> dict | None:
    """Get the most recent capture frame metadata."""
    return _STATE.last_capture_context


def set_last_capture_image(image: Image.Image):
    """Store the last capture image used for model reasoning."""
    try:
        _STATE.last_capture_image = image.copy()
    except Exception:
        _STATE.last_capture_image = image


def get_last_capture_image() -> Image.Image | None:
    """Get a copy of the last capture image if available."""
    if _STATE.last_capture_image is None:
        return None
    try:
        return _STATE.last_capture_image.copy()
    except Exception:
        return _STATE.last_capture_image


def remember_text(thing_to_remember: str) -> None:
    _STATE.memory_text.append(thing_to_remember)


def remember_image(image: Image.Image) -> None:
    _STATE.memory_image.append(image)
