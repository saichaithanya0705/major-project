"""Raw human input carried separately from model-authored routing/task text."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserInput:
    text: str
    session_id: str


_current: ContextVar[UserInput | None] = ContextVar("jarvis_user_input", default=None)


def current_user_input() -> UserInput | None:
    return _current.get()


@contextmanager
def user_input_scope(text: str, session_id: str):
    token = _current.set(UserInput(text=text, session_id=session_id))
    try:
        yield
    finally:
        _current.reset(token)
