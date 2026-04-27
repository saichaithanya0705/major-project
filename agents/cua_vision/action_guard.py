"""
Action signature and loop-detection policy for CUA vision single-call execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


def infer_click_type(task: str, args: Mapping[str, object]) -> str:
    """Infer click type from task and tool metadata."""
    pieces = [
        args.get("status_text"),
        args.get("target_description"),
        task,
    ]
    haystack = " ".join(str(piece).lower() for piece in pieces if piece)
    if "double click" in haystack or "double-click" in haystack:
        return "double left click"
    if "right click" in haystack or "right-click" in haystack or "context menu" in haystack:
        return "right click"
    return "left click"


def to_norm_0_1000(value: object) -> float | None:
    """Normalize supported coordinate formats into 0-1000 space."""
    try:
        val = float(value)
    except Exception:
        return None

    if 0.0 <= val <= 1.0:
        return val * 1000.0
    if 0.0 <= val <= 1000.0:
        return val
    # If already pixel coordinates, keep as-is; bucketing still works heuristically.
    return val


def position_bucket(args: Mapping[str, object], bucket_size: int) -> tuple[int, int] | None:
    """Create coarse center buckets so small bbox jitter counts as repetition."""
    ymin = to_norm_0_1000(args.get("ymin"))
    xmin = to_norm_0_1000(args.get("xmin"))
    ymax = to_norm_0_1000(args.get("ymax"))
    xmax = to_norm_0_1000(args.get("xmax"))
    if None in {ymin, xmin, ymax, xmax}:
        return None

    center_x = (xmin + xmax) / 2.0
    center_y = (ymin + ymax) / 2.0
    bucket_x = int(center_x // bucket_size)
    bucket_y = int(center_y // bucket_size)
    return (bucket_x, bucket_y)


def action_signature(
    *,
    name: str,
    args: Mapping[str, object],
    metadata_keys: set[str],
    click_tool_to_type: Mapping[str, str],
    positioning_tools: set[str],
    last_target_description: str | None,
    bucket_size: int,
) -> tuple:
    filtered = {k: v for k, v in args.items() if k not in metadata_keys}
    if name in click_tool_to_type:
        click_target = args.get("target_description") or last_target_description
        if click_target:
            filtered["target_description"] = click_target
    if name in positioning_tools:
        bucket = position_bucket(filtered, bucket_size=bucket_size)
        if bucket is not None:
            # Deliberately ignore target_description text to survive label jitter.
            return (name, ("bucket", bucket[0], bucket[1]))
    return (name, tuple(sorted(filtered.items())))


def resolve_click_type(tool_name: str, click_tool_to_type: Mapping[str, str]) -> str | None:
    return click_tool_to_type.get(tool_name)


def extract_position_bbox_args(args: Mapping[str, object]) -> dict[str, float] | None:
    required = ("ymin", "xmin", "ymax", "xmax")
    if not all(key in args for key in required):
        return None
    try:
        return {key: float(args[key]) for key in required}
    except Exception:
        return None


def task_expects_repeated_clicks(task: str) -> bool:
    text = (task or "").lower()
    markers = [
        "times",
        "repeatedly",
        "keep clicking",
        "click again",
        "double click multiple",
        "spam click",
        "until",
        "every",
        "loop",
    ]
    return any(marker in text for marker in markers)


@dataclass(slots=True)
class ClickLoopState:
    pending_position_signature: tuple | None = None
    last_click_cycle_signature: tuple | None = None
    repeated_click_cycle_count: int = 0


def register_action_and_detect_click_loop(
    *,
    state: ClickLoopState,
    task: str,
    name: str,
    signature: tuple,
    click_type: str | None,
    positioning_tools: set[str],
    click_cycle_loop_stop_threshold: int,
) -> bool:
    """
    Detect alternating position+click loops (A,B,A,B...) that can evade
    immediate-repeat checks and lead to infinite interaction cycles.
    """
    if name in positioning_tools:
        state.pending_position_signature = signature
        return False

    if click_type:
        if state.pending_position_signature is None:
            return False

        cycle_signature = (state.pending_position_signature, signature)
        if cycle_signature == state.last_click_cycle_signature:
            state.repeated_click_cycle_count += 1
        else:
            state.last_click_cycle_signature = cycle_signature
            state.repeated_click_cycle_count = 1

        if (
            state.repeated_click_cycle_count >= click_cycle_loop_stop_threshold
            and not task_expects_repeated_clicks(task)
        ):
            return True
        return False

    # Non click/position actions reset this specific loop detector.
    state.pending_position_signature = None
    state.last_click_cycle_signature = None
    state.repeated_click_cycle_count = 0
    return False
