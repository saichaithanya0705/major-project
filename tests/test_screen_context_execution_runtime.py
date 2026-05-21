"""
Checks the shared screen-context execution runtime used by rapid orchestrators.
"""

import asyncio
import os
import sys
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.screen_context_execution_runtime import (
    ScreenContextStepRequest,
    execute_screen_context_step,
)
from models.routing_payload_parser import ScreenContextPayload


class _FakeDeps:
    def __init__(self) -> None:
        self.logged_events: list[dict[str, Any]] = []
        self.prepare_calls: list[bool] = []

    async def prepare_vision_screenshot(self, *, keep_chat_hidden: bool = False) -> str:
        self.prepare_calls.append(keep_chat_hidden)
        return "fake-screenshot"

    def clean_text(self, value: object, fallback: str, max_len: int | None) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            text = fallback
        if max_len is not None:
            text = text[:max_len]
        return text

    def screen_context_message(self, payload: ScreenContextPayload) -> str:
        return f"summary: {payload['summary']}"

    def log_assistant_event(self, event_type: str, **kwargs: Any) -> None:
        self.logged_events.append({"event_type": event_type, **kwargs})


class _ScreenshotFailDeps(_FakeDeps):
    async def prepare_vision_screenshot(self, *, keep_chat_hidden: bool = False) -> str:
        self.prepare_calls.append(keep_chat_hidden)
        raise TimeoutError("screenshot capture timed out after 0.1s")


class _SuccessfulModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def generate_screen_context(
        self,
        user_request: str,
        image: Any = None,
        focus: str = "",
    ) -> ScreenContextPayload:
        self.calls.append(
            {
                "user_request": user_request,
                "image": image,
                "focus": focus,
            }
        )
        return {
            "summary": "Repo visible.",
            "repo_url": "https://github.com/example/repo",
            "recommended_agent": "cua_cli",
            "recommended_task": "Clone the repo locally.",
        }


class _FailingModel:
    async def generate_screen_context(
        self,
        user_request: str,
        image: Any = None,
        focus: str = "",
    ) -> dict[str, Any]:
        raise RuntimeError("screen context exploded")


class _SlowModel:
    async def generate_screen_context(
        self,
        user_request: str,
        image: Any = None,
        focus: str = "",
    ) -> dict[str, Any]:
        await asyncio.sleep(10)
        return {"summary": "late"}


def test_screen_context_step_request_extracts_route_fields() -> None:
    request = ScreenContextStepRequest.from_route(
        {"task": "  inspect repository page  ", "focus": "  address bar  ", "agent": "screen_context"},
        user_prompt="fallback prompt",
    )

    assert request.task == "  inspect repository page  "
    assert request.focus == "  address bar  "


def test_screen_context_step_request_falls_back_to_user_prompt() -> None:
    request = ScreenContextStepRequest.from_route({}, user_prompt="fallback prompt")

    assert request.task == "fallback prompt"
    assert request.focus == ""


def test_execute_screen_context_step_returns_step_result_and_logs_success() -> None:
    deps = _FakeDeps()
    model = _SuccessfulModel()

    result = asyncio.run(
        execute_screen_context_step(
            model=model,
            step_request=ScreenContextStepRequest(
                task="  inspect repository page  ",
                focus="  address bar  ",
            ),
            request_id="req-1",
            deps=deps,
        )
    )

    assert deps.prepare_calls == [False]
    assert model.calls == [
        {
            "user_request": "  inspect repository page  ",
            "image": "fake-screenshot",
            "focus": "  address bar  ",
        }
    ]
    assert result.latest_screen_context == {
        "summary": "Repo visible.",
        "repo_url": "https://github.com/example/repo",
        "recommended_agent": "cua_cli",
        "recommended_task": "Clone the repo locally.",
    }
    assert result.step_result == {
        "agent": "screen_context",
        "task": "inspect repository page",
        "success": True,
        "message": "summary: Repo visible.",
        "source": "screen_judge",
    }
    assert [event["event_type"] for event in deps.logged_events] == [
        "agent_step_started",
        "agent_step_completed",
    ]
    assert deps.logged_events[0]["metadata"] == {"focus": "address bar"}
    assert deps.logged_events[1]["metadata"] == result.latest_screen_context
    assert deps.logged_events[1]["success"] is True


def test_execute_screen_context_step_returns_failure_result_and_logs_error() -> None:
    deps = _FakeDeps()
    model = _FailingModel()

    result = asyncio.run(
        execute_screen_context_step(
            model=model,
            step_request=ScreenContextStepRequest(
                task="find the visible repo url",
                focus=" general ",
            ),
            request_id="req-2",
            deps=deps,
        )
    )

    assert deps.prepare_calls == [False]
    assert result.latest_screen_context is None
    assert result.step_result == {
        "agent": "screen_context",
        "task": "find the visible repo url",
        "success": False,
        "message": "screen context exploded",
        "source": "screen_judge",
    }
    assert [event["event_type"] for event in deps.logged_events] == [
        "agent_step_started",
        "agent_step_failed",
    ]
    assert deps.logged_events[0]["metadata"] == {"focus": "general"}
    assert deps.logged_events[1]["error"] == "screen context exploded"
    assert deps.logged_events[1]["success"] is False
    assert "RuntimeError: screen context exploded" in deps.logged_events[1]["metadata"]["traceback"]


def test_execute_screen_context_step_logs_screenshot_prepare_failure() -> None:
    deps = _ScreenshotFailDeps()
    model = _SuccessfulModel()

    result = asyncio.run(
        execute_screen_context_step(
            model=model,
            step_request=ScreenContextStepRequest(
                task="observe after cua",
                focus="goal-state evidence",
            ),
            request_id="req-3",
            deps=deps,
        )
    )

    assert deps.prepare_calls == [False]
    assert model.calls == []
    assert result.latest_screen_context is None
    assert result.step_result == {
        "agent": "screen_context",
        "task": "observe after cua",
        "success": False,
        "message": "screenshot capture timed out after 0.1s",
        "source": "screen_judge",
    }
    assert [event["event_type"] for event in deps.logged_events] == [
        "agent_step_started",
        "agent_step_failed",
    ]
    assert deps.logged_events[1]["agent"] == "screen_context"
    assert "screenshot capture timed out" in deps.logged_events[1]["error"]


def test_execute_screen_context_step_times_out_slow_model() -> None:
    deps = _FakeDeps()
    model = _SlowModel()

    result = asyncio.run(
        execute_screen_context_step(
            model=model,
            step_request=ScreenContextStepRequest(
                task="observe after cua",
                focus="goal-state evidence",
            ),
            request_id="req-4",
            deps=deps,
            timeout_seconds=0.01,
        )
    )

    assert result.latest_screen_context is None
    assert result.step_result["success"] is False
    assert "timed out" in result.step_result["message"].lower()
    assert [event["event_type"] for event in deps.logged_events] == [
        "agent_step_started",
        "agent_step_failed",
    ]
