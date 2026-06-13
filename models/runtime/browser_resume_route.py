"""Shared browser-resume routing boundary for router/model modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


BrowserAgentLoader = Callable[[], Any]


@dataclass(frozen=True)
class BrowserResumeRouteFailure:
    operation: str
    user_prompt: str
    error: BaseException
    message: str


_LAST_BROWSER_RESUME_ROUTE_FAILURES: tuple[BrowserResumeRouteFailure, ...] = ()


def get_last_browser_resume_route_failures() -> tuple[BrowserResumeRouteFailure, ...]:
    return _LAST_BROWSER_RESUME_ROUTE_FAILURES


def clear_last_browser_resume_route_failures() -> None:
    global _LAST_BROWSER_RESUME_ROUTE_FAILURES
    _LAST_BROWSER_RESUME_ROUTE_FAILURES = ()


def _record_browser_resume_route_failure(
    *,
    operation: str,
    user_prompt: str,
    error: BaseException,
    message: str,
) -> None:
    global _LAST_BROWSER_RESUME_ROUTE_FAILURES
    _LAST_BROWSER_RESUME_ROUTE_FAILURES = (
        *_LAST_BROWSER_RESUME_ROUTE_FAILURES,
        BrowserResumeRouteFailure(
            operation=operation,
            user_prompt=str(user_prompt or ""),
            error=error,
            message=str(message or "").strip(),
        ),
    )


def _load_browser_agent() -> Any:
    from agents.browser.agent import BrowserAgent

    return BrowserAgent


def resolve_browser_resume_task(
    user_prompt: str,
    *,
    browser_agent_loader: BrowserAgentLoader = _load_browser_agent,
) -> str | None:
    clear_last_browser_resume_route_failures()

    try:
        browser_agent = browser_agent_loader()
    except Exception as exc:
        _record_browser_resume_route_failure(
            operation="load_browser_agent",
            user_prompt=user_prompt,
            error=exc,
            message=f"Failed to load BrowserAgent for resume routing: {exc}",
        )
        return None

    try:
        task = browser_agent.resolve_resume_task(user_prompt)
    except Exception as exc:
        _record_browser_resume_route_failure(
            operation="resolve_resume_task",
            user_prompt=user_prompt,
            error=exc,
            message=f"BrowserAgent resume resolution failed: {exc}",
        )
        return None

    cleaned_task = str(task or "").strip()
    return cleaned_task or None


def build_browser_resume_route(
    user_prompt: str,
    *,
    browser_agent_loader: BrowserAgentLoader = _load_browser_agent,
) -> dict[str, str] | None:
    task = resolve_browser_resume_task(
        user_prompt,
        browser_agent_loader=browser_agent_loader,
    )
    if not task:
        return None
    return {
        "agent": "browser",
        "task": task,
    }
