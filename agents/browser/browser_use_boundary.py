"""
Typed boundary for the external browser_use package.

This module keeps dependency resolution, session construction, cleanup, stop
registration, and interrupted-work state outside BrowserAgent's routing policy.
"""

from __future__ import annotations

import importlib.util
import inspect
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BrowserUseBoundaryError(RuntimeError):
    """Base class for browser_use boundary failures."""


class BrowserUseDependencyError(BrowserUseBoundaryError):
    """Raised when the external browser_use dependency cannot be used."""


class BrowserUsePackageNotInstalledError(BrowserUseDependencyError):
    """Raised when browser_use cannot be resolved at runtime."""


class BrowserUseVendoredPackageError(BrowserUseDependencyError):
    """Raised when imports would resolve to the in-repo vendored package."""


class BrowserUseLifecycleError(BrowserUseBoundaryError):
    """Raised when browser_use lifecycle operations fail."""


class BrowserUseSessionCreationError(BrowserUseLifecycleError):
    """Raised when a browser_use session cannot be created."""


class BrowserUseAgentCreationError(BrowserUseLifecycleError):
    """Raised when a browser_use Agent cannot be created."""


class BrowserUseToolsCreationError(BrowserUseLifecycleError):
    """Raised when browser_use tool configuration cannot be created."""


@dataclass(frozen=True)
class BrowserUseLifecycleFailure:
    operation: str
    error: BaseException
    subject: str = ""


def _format_failures(failures: tuple[BrowserUseLifecycleFailure, ...]) -> str:
    return "; ".join(
        f"{failure.operation}{f'[{failure.subject}]' if failure.subject else ''}: {failure.error}"
        for failure in failures
    )


class BrowserUseCleanupError(BrowserUseLifecycleError):
    def __init__(self, failures: tuple[BrowserUseLifecycleFailure, ...]):
        self.failures = failures
        super().__init__(f"browser_use cleanup failed: {_format_failures(failures)}")


class BrowserUseStateResumeError(BrowserUseLifecycleError):
    def __init__(self, failures: tuple[BrowserUseLifecycleFailure, ...]):
        self.failures = failures
        super().__init__(f"browser_use resume state update failed: {_format_failures(failures)}")


@dataclass(frozen=True)
class BrowserUseStopResult:
    stopped: int
    failures: tuple[BrowserUseLifecycleFailure, ...] = ()


@dataclass(frozen=True)
class BrowserUseSessionHandle:
    session: Any
    user_data_dir: str | None


@dataclass
class BrowserUseInterruptedWork:
    state: Any
    task: str
    summary: str = ""


@dataclass(frozen=True)
class BrowserUseToolPolicy:
    excluded_actions: tuple[str, ...] = ("write_file", "replace_file")


@dataclass(frozen=True)
class BrowserUseSessionPolicy:
    headless: bool = False
    keep_alive: bool = True
    temp_prefix: str = "jarvis-browser-use-"


def is_subpath(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class BrowserUseBoundary:
    def __init__(
        self,
        *,
        package_name: str = "browser_use",
        vendored_root: Path | None = None,
    ) -> None:
        self.package_name = package_name
        self.vendored_root = (
            Path(vendored_root).resolve()
            if vendored_root is not None
            else (Path(__file__).resolve().parent / "browser_use").resolve()
        )
        self._resolution_checked = False

    @property
    def resolution_checked(self) -> bool:
        return self._resolution_checked

    def reset_resolution_cache(self) -> None:
        self._resolution_checked = False

    def ensure_external_package(self) -> None:
        if self._resolution_checked:
            return

        spec = importlib.util.find_spec(self.package_name)
        origin = getattr(spec, "origin", None) if spec is not None else None
        if spec is None or not origin:
            raise BrowserUsePackageNotInstalledError(
                "browser_use is not installed. Install dependencies so BrowserAgent "
                "can use the canonical external browser_use package."
            )

        resolved_origin = Path(origin).resolve()
        if is_subpath(resolved_origin, self.vendored_root):
            raise BrowserUseVendoredPackageError(
                "Refusing to import vendored browser_use from this repository. "
                "Use the installed browser_use dependency instead."
            )

        self._resolution_checked = True

    def import_agent_class(self):
        self.ensure_external_package()
        try:
            from browser_use import Agent
        except ImportError as exc:
            raise BrowserUseDependencyError(f"Failed to import browser_use.Agent: {exc}") from exc
        return Agent

    def import_tools_class(self):
        self.ensure_external_package()
        try:
            from browser_use.tools.service import Tools
        except ImportError as exc:
            raise BrowserUseDependencyError(f"Failed to import browser_use Tools: {exc}") from exc
        return Tools

    def import_browser_session_classes(self):
        self.ensure_external_package()
        try:
            from browser_use.browser import BrowserProfile, BrowserSession
        except ImportError as exc:
            raise BrowserUseDependencyError(
                f"Failed to import browser_use browser session classes: {exc}"
            ) from exc
        return BrowserProfile, BrowserSession

    def import_google_llm_class(self):
        self.ensure_external_package()
        try:
            from browser_use.llm.google.chat import ChatGoogle
        except ImportError as exc:
            raise BrowserUseDependencyError(f"Failed to import browser_use ChatGoogle: {exc}") from exc
        return ChatGoogle

    def import_openrouter_llm_class(self):
        self.ensure_external_package()
        try:
            from browser_use.llm.openrouter.chat import ChatOpenRouter
        except ImportError as exc:
            raise BrowserUseDependencyError(
                f"Failed to import browser_use ChatOpenRouter: {exc}"
            ) from exc
        return ChatOpenRouter

    def create_session(
        self,
        *,
        session_policy: BrowserUseSessionPolicy | None = None,
        headless: bool | None = None,
        keep_alive: bool | None = None,
        temp_prefix: str | None = None,
    ) -> BrowserUseSessionHandle:
        BrowserProfile, BrowserSession = self.import_browser_session_classes()
        resolved_policy = self._resolve_session_policy(
            session_policy=session_policy,
            headless=headless,
            keep_alive=keep_alive,
            temp_prefix=temp_prefix,
        )
        user_data_dir = tempfile.mkdtemp(prefix=resolved_policy.temp_prefix)
        try:
            profile = BrowserProfile(
                headless=resolved_policy.headless,
                user_data_dir=user_data_dir,
                keep_alive=resolved_policy.keep_alive,
            )
            session = BrowserSession(browser_profile=profile)
        except Exception as exc:
            try:
                self.cleanup_temp_dir(user_data_dir, expected_prefix=resolved_policy.temp_prefix)
            except BrowserUseCleanupError:
                pass
            raise BrowserUseSessionCreationError(f"Failed to create browser_use session: {exc}") from exc
        return BrowserUseSessionHandle(session=session, user_data_dir=user_data_dir)

    def _resolve_session_policy(
        self,
        *,
        session_policy: BrowserUseSessionPolicy | None,
        headless: bool | None,
        keep_alive: bool | None,
        temp_prefix: str | None,
    ) -> BrowserUseSessionPolicy:
        if session_policy is None:
            session_policy = BrowserUseSessionPolicy()
        return BrowserUseSessionPolicy(
            headless=session_policy.headless if headless is None else headless,
            keep_alive=session_policy.keep_alive if keep_alive is None else keep_alive,
            temp_prefix=session_policy.temp_prefix if temp_prefix is None else temp_prefix,
        )

    def keep_session_alive(self, session: Any) -> None:
        profile = getattr(session, "browser_profile", None)
        if profile is None:
            raise BrowserUseLifecycleError("browser_use session has no browser_profile.")
        try:
            profile.keep_alive = True
        except Exception as exc:
            raise BrowserUseLifecycleError(
                f"Failed to mark browser_use session keep_alive: {exc}"
            ) from exc

    def create_agent(
        self,
        *,
        task: str,
        llm: Any,
        browser_session: Any,
        available_file_paths: list[str],
        register_should_stop_callback: Any,
        injected_agent_state: Any,
        tool_policy: BrowserUseToolPolicy | None = None,
    ) -> Any:
        Agent = self.import_agent_class()
        try:
            tools = self.create_tools(tool_policy=tool_policy)
            return Agent(
                task=task,
                llm=llm,
                browser_session=browser_session,
                available_file_paths=available_file_paths,
                register_should_stop_callback=register_should_stop_callback,
                injected_agent_state=injected_agent_state,
                tools=tools,
            )
        except BrowserUseBoundaryError:
            raise
        except Exception as exc:
            raise BrowserUseAgentCreationError(f"Failed to create browser_use Agent: {exc}") from exc

    def create_tools(self, *, tool_policy: BrowserUseToolPolicy | None = None) -> Any:
        Tools = self.import_tools_class()
        resolved_policy = tool_policy or BrowserUseToolPolicy()
        try:
            return Tools(exclude_actions=list(resolved_policy.excluded_actions))
        except Exception as exc:
            raise BrowserUseToolsCreationError(
                f"Failed to create browser_use tools: {exc}"
            ) from exc

    async def cleanup_session(
        self,
        session: Any,
        *,
        user_data_dir: str | None,
        expected_prefix: str = "jarvis-browser-use-",
    ) -> None:
        failures: list[BrowserUseLifecycleFailure] = []

        if session is not None:
            kill = getattr(session, "kill", None)
            if not callable(kill):
                failures.append(
                    BrowserUseLifecycleFailure(
                        operation="session.kill",
                        error=TypeError("browser_use session has no callable kill()."),
                    )
                )
            else:
                try:
                    kill_result = kill()
                    if inspect.isawaitable(kill_result):
                        await kill_result
                except Exception as exc:
                    failures.append(
                        BrowserUseLifecycleFailure(operation="session.kill", error=exc)
                    )

        if user_data_dir:
            try:
                self.cleanup_temp_dir(user_data_dir, expected_prefix=expected_prefix)
            except BrowserUseCleanupError as exc:
                failures.extend(exc.failures)

        if failures:
            raise BrowserUseCleanupError(tuple(failures))

    def cleanup_temp_dir(
        self,
        path: str | Path,
        *,
        expected_prefix: str,
        temp_root: Path | None = None,
    ) -> None:
        temp_root = (temp_root or Path(tempfile.gettempdir())).resolve()
        resolved_path = Path(path).resolve()
        failures: list[BrowserUseLifecycleFailure] = []

        if not is_subpath(resolved_path, temp_root):
            failures.append(
                BrowserUseLifecycleFailure(
                    operation="tempdir.guard",
                    error=ValueError(f"{resolved_path} is outside {temp_root}."),
                    subject=str(resolved_path),
                )
            )
        if not resolved_path.name.startswith(expected_prefix):
            failures.append(
                BrowserUseLifecycleFailure(
                    operation="tempdir.guard",
                    error=ValueError(
                        f"{resolved_path.name} does not start with {expected_prefix}."
                    ),
                    subject=str(resolved_path),
                )
            )

        if failures:
            raise BrowserUseCleanupError(tuple(failures))
        if not resolved_path.exists():
            return

        try:
            shutil.rmtree(resolved_path, ignore_errors=False)
        except FileNotFoundError:
            return
        except Exception as exc:
            raise BrowserUseCleanupError(
                (
                    BrowserUseLifecycleFailure(
                        operation="tempdir.remove",
                        error=exc,
                        subject=str(resolved_path),
                    ),
                )
            ) from exc


class BrowserUseLifecycle:
    def __init__(self) -> None:
        self.active_agents: set[Any] = set()
        self.stop_requested = False
        self.interrupted_work: BrowserUseInterruptedWork | None = None
        self.session: Any = None
        self.user_data_dir: str | None = None
        self.last_stop_failures: tuple[BrowserUseLifecycleFailure, ...] = ()
        self.last_cleanup_failures: tuple[BrowserUseLifecycleFailure, ...] = ()
        self.resolution_checked = False

    def clear_stop_request(self) -> None:
        self.stop_requested = False

    def remember_resolution(self, checked: bool) -> None:
        self.resolution_checked = bool(checked)

    def remember_session(self, handle: BrowserUseSessionHandle) -> Any:
        self.session = handle.session
        self.user_data_dir = handle.user_data_dir
        return self.session

    def reuse_session(self, boundary: BrowserUseBoundary) -> Any:
        if self.session is None:
            return None
        boundary.keep_session_alive(self.session)
        return self.session

    def detach_session(self) -> BrowserUseSessionHandle | None:
        if self.session is None and self.user_data_dir is None:
            return None
        handle = BrowserUseSessionHandle(
            session=self.session,
            user_data_dir=self.user_data_dir,
        )
        self.session = None
        self.user_data_dir = None
        return handle

    def remember_cleanup_failures(
        self,
        failures: tuple[BrowserUseLifecycleFailure, ...],
    ) -> None:
        self.last_cleanup_failures = tuple(failures)

    def register_active_agent(self, agent: Any) -> None:
        self.active_agents.add(agent)

    def unregister_active_agent(self, agent: Any) -> None:
        self.active_agents.discard(agent)

    def request_stop_all(self) -> BrowserUseStopResult:
        self.stop_requested = True
        return self._stop_agents(list(self.active_agents))

    def stop_agent(self, agent: Any) -> BrowserUseStopResult:
        return self._stop_agents([agent])

    def _stop_agents(self, agents: list[Any]) -> BrowserUseStopResult:
        stopped = 0
        failures: list[BrowserUseLifecycleFailure] = []

        for agent in agents:
            stop = getattr(agent, "stop", None)
            if not callable(stop):
                failures.append(
                    BrowserUseLifecycleFailure(
                        operation="agent.stop",
                        error=TypeError("browser_use agent has no callable stop()."),
                        subject=repr(agent),
                    )
                )
                continue
            try:
                stop()
                stopped += 1
            except Exception as exc:
                failures.append(
                    BrowserUseLifecycleFailure(
                        operation="agent.stop",
                        error=exc,
                        subject=repr(agent),
                    )
                )

        result = BrowserUseStopResult(stopped=stopped, failures=tuple(failures))
        self.last_stop_failures = result.failures
        return result

    async def should_stop_agent(self) -> bool:
        return self.stop_requested

    @staticmethod
    def normalize_resume_text(value: str) -> str:
        return " ".join(str(value or "").split()).strip().lower()

    @classmethod
    def is_resume_request(cls, task: str) -> bool:
        lowered = cls.normalize_resume_text(task)
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "continue",
                "resume",
                "keep going",
                "carry on",
                "pick up where",
                "where you left off",
                "from where you left",
            )
        )

    def has_interrupted_work(self) -> bool:
        return self.interrupted_work is not None and bool(self.interrupted_work.task.strip())

    def resolve_resume_task(self, user_prompt: str) -> str | None:
        if not self.has_interrupted_work() or not self.is_resume_request(user_prompt):
            return None
        assert self.interrupted_work is not None
        return self.interrupted_work.task

    def remember_interrupted_agent(self, agent: Any, *, task: str, summary: str = "") -> bool:
        state = getattr(agent, "state", None)
        if state is None:
            return False
        self.interrupted_work = BrowserUseInterruptedWork(
            state=state,
            task=str(task or "").strip(),
            summary=str(summary or "").strip(),
        )
        return True

    def clear_interrupted_agent(self, task: str = "") -> None:
        if self.interrupted_work is None:
            return
        if task and self.normalize_resume_text(task) != self.normalize_resume_text(
            self.interrupted_work.task
        ):
            return
        self.interrupted_work = None

    def consume_resume_state_for_task(self, task: str) -> Any:
        if not self.has_interrupted_work():
            return None
        assert self.interrupted_work is not None

        normalized_task = self.normalize_resume_text(task)
        normalized_interrupted = self.normalize_resume_text(self.interrupted_work.task)
        if normalized_task != normalized_interrupted and not self.is_resume_request(task):
            return None

        state = self.interrupted_work.state
        failures: list[BrowserUseLifecycleFailure] = []
        for attr, value in (
            ("paused", False),
            ("stopped", False),
            ("follow_up_task", True),
        ):
            try:
                setattr(state, attr, value)
            except Exception as exc:
                failures.append(
                    BrowserUseLifecycleFailure(
                        operation=f"state.{attr}",
                        error=exc,
                        subject=type(state).__name__,
                    )
                )

        if failures:
            raise BrowserUseStateResumeError(tuple(failures))
        return state
