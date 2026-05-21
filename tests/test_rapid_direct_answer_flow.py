"""Checks extracted direct-QA fast-path flow for the rapid orchestrator."""

import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from models.rapid_direct_answer_flow import try_handle_direct_qa_request


class _FakeDeps:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.history: list[tuple[str, str, str]] = []
        self.direct_calls: list[dict[str, object]] = []
        self.router_tool_map = {"direct_response": self._direct_response}

    async def answer_direct_request(self, *, model, user_prompt: str, history_block: str = "") -> str:
        del model
        assert "Tell me everything about elon musk." in user_prompt
        assert "history block" in history_block
        return "Elon Musk is an entrepreneur."

    def append_rapid_history(self, role: str, text: str, source: str) -> None:
        self.history.append((role, text, source))

    def clean_text(self, value: object, fallback: str, max_len: int | None = None) -> str:
        text = str(value or "").strip() or fallback
        return text if max_len is None else text[:max_len]

    def finalize_direct_response_text(self, *, user_prompt: str, chain_steps, text: str) -> str:
        del user_prompt, chain_steps
        return text.strip()

    def format_rapid_history_for_prompt(self) -> str:
        return "history block"

    def log_assistant_event(self, event_type: str, **kwargs) -> None:
        self.events.append({"event_type": event_type, **kwargs})

    def _direct_response(self, **kwargs) -> None:
        self.direct_calls.append(dict(kwargs))


def test_try_handle_direct_qa_request_returns_true_and_emits_response() -> None:
    async def _run() -> None:
        deps = _FakeDeps()
        handled = await try_handle_direct_qa_request(
            model=object(),
            user_prompt="Tell me everything about elon musk.",
            request_id="req-1",
            deps=deps,
            chain_steps=[],
        )

        assert handled is True
        assert deps.direct_calls == [
            {"text": "Elon Musk is an entrepreneur.", "source": "rapid_response"}
        ]
        assert deps.history[-1] == (
            "assistant",
            "Elon Musk is an entrepreneur.",
            "rapid",
        )
        assert [event["event_type"] for event in deps.events] == [
            "router_decision",
            "request_completed",
        ]

    asyncio.run(_run())


def test_try_handle_direct_qa_request_propagates_structural_error() -> None:
    async def _run() -> None:
        class _BrokenDeps(_FakeDeps):
            async def answer_direct_request(
                self,
                *,
                model,
                user_prompt: str,
                history_block: str = "",
            ) -> str:
                del model, user_prompt, history_block
                raise AttributeError("direct qa wiring bug")

        try:
            await try_handle_direct_qa_request(
                model=object(),
                user_prompt="Tell me everything about elon musk.",
                request_id="req-2",
                deps=_BrokenDeps(),
                chain_steps=[],
            )
            raise AssertionError("Expected structural direct-QA error to propagate.")
        except AttributeError as exc:
            assert str(exc) == "direct qa wiring bug", exc

    asyncio.run(_run())
