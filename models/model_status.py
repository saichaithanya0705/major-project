"""Observable boundary for optional model-status UI updates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelStatusUpdateFailure:
    label: str
    context: str
    error: BaseException


_LAST_MODEL_STATUS_UPDATE_FAILURES: tuple[ModelStatusUpdateFailure, ...] = ()


def get_last_model_status_update_failures() -> tuple[ModelStatusUpdateFailure, ...]:
    return _LAST_MODEL_STATUS_UPDATE_FAILURES


def clear_last_model_status_update_failures() -> None:
    global _LAST_MODEL_STATUS_UPDATE_FAILURES
    _LAST_MODEL_STATUS_UPDATE_FAILURES = ()


async def set_model_label(label: str, *, context: str) -> bool:
    """
    Best-effort UI status update with machine-observable failure state.

    Model execution must not fail just because the status UI is unavailable, but
    the failure should be inspectable by tests and future telemetry.
    """
    global _LAST_MODEL_STATUS_UPDATE_FAILURES

    try:
        from models import models as model_module

        await model_module.set_model_name(label)
        return True
    except Exception as exc:
        _LAST_MODEL_STATUS_UPDATE_FAILURES = (
            *_LAST_MODEL_STATUS_UPDATE_FAILURES,
            ModelStatusUpdateFailure(
                label=label,
                context=context,
                error=exc,
            ),
        )
        print(f"[ModelStatus] Label update skipped for {context}: {exc}")
        return False
