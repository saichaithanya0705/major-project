"""
Runtime state for rapid-response routing sessions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import re
from typing import Callable

from PIL import ImageGrab

from models.output_file_artifacts import (
    extract_output_file_path_from_tool_calls,
    extract_path_from_text,
    looks_like_file_status,
)
from models.rapid_orchestrator_contracts import RapidAgentStepResult


Cleaner = Callable[[str], str]
DEFAULT_RAPID_SESSION_ID = "__default__"

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CONTENT_REFERENCE_PHRASES = tuple(
    tuple(_TOKEN_RE.findall(phrase))
    for phrase in (
        "it",
        "this",
        "that",
        "all this",
        "all of this",
        "everything above",
        "previous answer",
        "the answer",
        "the response",
        "this response",
    )
)


def _task_tokens(value: object) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(str(value or "").lower()))


def _tokens_contain_phrase(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    if not tokens or not phrase or len(phrase) > len(tokens):
        return False
    phrase_length = len(phrase)
    return any(
        tokens[index : index + phrase_length] == phrase
        for index in range(0, len(tokens) - phrase_length + 1)
    )


def _tokens_contain_any_phrase(
    tokens: tuple[str, ...],
    phrases: tuple[tuple[str, ...], ...],
) -> bool:
    return any(_tokens_contain_phrase(tokens, phrase) for phrase in phrases)


def _tokens_contain_any_word(tokens: tuple[str, ...], words: set[str]) -> bool:
    return any(token in words for token in tokens)


def _normalize_context_text(value: object, max_len: int = 12000) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_len:
        return text[: max_len - 18].rstrip() + "\n...[truncated]..."
    return text


def _task_has_context_reference(task: str) -> bool:
    return _tokens_contain_any_phrase(_task_tokens(task), _CONTENT_REFERENCE_PHRASES)


def _task_is_contextual_file_write(task: str) -> bool:
    tokens = _task_tokens(task)
    if not tokens:
        return False
    has_write = _tokens_contain_any_word(tokens, {"dump", "put", "save", "write"})
    has_file_target = _tokens_contain_any_word(tokens, {"desktop", "down", "file", "note", "txt"})
    return has_write and has_file_target and _tokens_contain_any_phrase(
        tokens,
        _CONTENT_REFERENCE_PHRASES,
    )


def _task_is_contextual_file_open(task: str) -> bool:
    tokens = _task_tokens(task)
    if not tokens:
        return False
    has_open = _tokens_contain_any_word(tokens, {"launch", "open", "show"})
    has_file_ref = "file" in tokens or _tokens_contain_any_phrase(
        tokens,
        _CONTENT_REFERENCE_PHRASES,
    )
    has_editor = _tokens_contain_any_word(tokens, {"code", "editor", "vscode"}) or _tokens_contain_phrase(
        tokens,
        ("vs", "code"),
    )
    return has_open and has_file_ref and has_editor


def _task_has_path(task: str) -> bool:
    return bool(extract_path_from_text(task))


@dataclass(slots=True)
class RapidSessionState:
    max_history: int = 32
    history: deque[dict[str, str]] = field(init=False)
    _histories: dict[str, deque[dict[str, str]]] = field(init=False, repr=False)
    _contexts: dict[str, dict[str, str]] = field(init=False, repr=False)
    _stored_screenshot: object = None

    def __post_init__(self) -> None:
        self._histories = {
            DEFAULT_RAPID_SESSION_ID: deque(maxlen=self.max_history),
        }
        self._contexts = {DEFAULT_RAPID_SESSION_ID: {}}
        self.history = self._histories[DEFAULT_RAPID_SESSION_ID]

    def normalize_session_id(self, session_id: str | None = None) -> str:
        if isinstance(session_id, str):
            cleaned = session_id.strip()
            if cleaned:
                return cleaned[:160]
        return DEFAULT_RAPID_SESSION_ID

    def get_history(self, session_id: str | None = None) -> deque[dict[str, str]]:
        normalized_session_id = self.normalize_session_id(session_id)
        if normalized_session_id not in self._histories:
            self._histories[normalized_session_id] = deque(maxlen=self.max_history)
        return self._histories[normalized_session_id]

    def get_context(self, session_id: str | None = None) -> dict[str, str]:
        normalized_session_id = self.normalize_session_id(session_id)
        if normalized_session_id not in self._contexts:
            self._contexts[normalized_session_id] = {}
        return self._contexts[normalized_session_id]

    def clear_history(self, session_id: str | None = None) -> None:
        normalized_session_id = self.normalize_session_id(session_id)
        self.get_history(normalized_session_id).clear()
        self.get_context(normalized_session_id).clear()

    def capture_screenshot(self):
        self._stored_screenshot = ImageGrab.grab()
        return self._stored_screenshot

    def capture_fresh_screenshot(self):
        screenshot = ImageGrab.grab()
        self._stored_screenshot = None
        return screenshot

    def consume_or_capture_screenshot(self):
        screenshot = self._stored_screenshot if self._stored_screenshot else ImageGrab.grab()
        self._stored_screenshot = None
        return screenshot

    def append_history(
        self,
        *,
        role: str,
        text: str,
        source: str,
        cleaner: Cleaner,
        session_id: str | None = None,
    ) -> None:
        self.record_assistant_context(
            role=role,
            text=text,
            source=source,
            session_id=session_id,
        )
        cleaned = cleaner(text or "")
        if not cleaned:
            return
        self.get_history(session_id).append(
            {
                "role": role,
                "source": source,
                "text": cleaned,
            }
        )

    def record_assistant_context(
        self,
        *,
        role: str,
        text: object,
        source: str,
        session_id: str | None = None,
    ) -> None:
        if str(role or "").strip().lower() != "assistant":
            return
        normalized = _normalize_context_text(text)
        if not normalized or looks_like_file_status(normalized):
            return

        context = self.get_context(session_id)
        context["last_assistant_message"] = normalized
        context["last_assistant_source"] = str(source or "").strip()

    def record_step_context(
        self,
        step_result: RapidAgentStepResult,
        session_id: str | None = None,
    ) -> None:
        if not step_result.get("success"):
            return

        path = extract_output_file_path_from_tool_calls(step_result.get("tool_calls"))
        message = step_result.get("message")
        if not path and looks_like_file_status(str(message or "")):
            path = extract_path_from_text(message)
        if path:
            context = self.get_context(session_id)
            context["last_file_path"] = path

    def enrich_routing_result(
        self,
        routing_result: dict[str, object],
        *,
        user_prompt: str,
        session_id: str | None = None,
    ) -> dict[str, object]:
        agent = str(routing_result.get("agent") or "").strip().lower()
        if agent not in {"cua_cli", "cua_vision"}:
            return routing_result

        task = str(routing_result.get("task") or routing_result.get("query") or user_prompt or "")
        context = self.get_context(session_id)
        enriched_task = task
        enriched_agent = agent

        if (
            agent == "cua_vision"
            and _task_is_contextual_file_open(task)
            and not _task_has_path(task)
            and context.get("last_file_path", "").strip()
        ):
            enriched_agent = "cua_cli"

        if enriched_agent != "cua_cli":
            return routing_result

        if _task_is_contextual_file_write(task):
            content = context.get("last_assistant_message", "").strip()
            if content:
                enriched_task = (
                    f"{enriched_task}\n\n"
                    "Use this prior assistant answer as the exact content to write. "
                    "Do not write CLI startup, workspace, or tool-context text instead.\n"
                    "--- PRIOR ASSISTANT ANSWER START ---\n"
                    f"{content}\n"
                    "--- PRIOR ASSISTANT ANSWER END ---"
                )

        if _task_is_contextual_file_open(task) and not _task_has_path(task):
            path = context.get("last_file_path", "").strip()
            if path:
                enriched_task = (
                    f"{enriched_task}\n\n"
                    f"Target file path from this chat session: {path}"
                )

        if enriched_task == task and enriched_agent == agent:
            return routing_result

        enriched = dict(routing_result)
        enriched["agent"] = enriched_agent
        enriched["task"] = enriched_task
        return enriched

    def format_history_for_prompt(self, session_id: str | None = None) -> str:
        history = self.get_history(session_id)
        context = self.get_context(session_id)

        lines = []
        for entry in list(history)[-20:]:
            role = entry.get("role")
            source = entry.get("source")
            text = entry.get("text", "")

            if role == "user":
                label = "User"
            elif source in {"browser_use", "cua_cli", "cua_vision", "jarvis", "screen_judge"}:
                label = "Agent"
            else:
                label = "Rapid Assistant"

            lines.append(f"{label}: {text}")

        context_lines = []
        last_file_path = context.get("last_file_path", "").strip()
        if last_file_path:
            context_lines.append(f"- Last created/edited file path: {last_file_path}")
            context_lines.append(
                "- For follow-up requests to open, show, or edit this known local file in VS Code "
                "or another editor, prefer cua_cli with the path; use cua_vision only for visible UI clicks."
            )

        if not lines and not context_lines:
            return ""

        blocks = []
        if lines:
            blocks.append(
                "\n# Conversation History (Rapid-Model Messages Only)\n"
                "Use this history for context. Agent entries are short summaries only.\n"
                + "\n".join(lines)
                + "\n"
            )
        if context_lines:
            blocks.append(
                "\n# Session Context\n"
                "Use these persisted facts for short follow-up requests.\n"
                + "\n".join(context_lines)
                + "\n"
            )
        return "".join(blocks)


RAPID_SESSION_STATE = RapidSessionState()
