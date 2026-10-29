"""
CLI Agent - Desktop control and coding through coding-agent CLIs.

Drives opencode (local model) for shell/desktop tasks and delegates coding
tasks to Claude Code, Codex CLI, or GitHub Copilot CLI when installed. See
``agents.cua_cli.backends`` for backend selection.
The rapid response model invokes this agent for CLI tasks.
"""
import atexit
import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Callable, Awaitable, Any

from dotenv import load_dotenv
from agents.cua_cli.backends import (
    BackendRequest,
    BackendUnavailableError,
    BackendUnsafeArgumentsError,
    CodingBackend,
    NormalizationState,
    backend_chain_for_task,
    coding_delegation_enabled,
    is_coding_task,
    looks_like_auth_failure,
)
from agents.cua_cli.background_manager import (
    await_foreground_process_operation,
    cleanup_background_processes_sync,
    is_local_port_open,
    list_background_processes,
    register_foreground_process,
    resolve_background_shell,
    start_background_process,
    stop_all_background_processes,
    stop_background_process,
    terminate_process_tree_sync,
    unregister_foreground_process,
    wait_for_any_port,
)
from agents.cua_cli.direct_command_policy import DirectCommand, extract_safe_direct_command
from agents.cua_cli.server_launch_policy import (
    extract_explicit_shell_command,
    extract_port_candidates,
    extract_server_subcommand,
    extract_shell_command_from_tool_call,
    infer_server_launch_from_tool_calls,
    is_background_intent_task,
    is_quick_server_launch_task,
    is_server_intent_text,
    is_server_like_command,
    resolve_shell_path,
)
from agents.cua_cli.response_parser import parse_stream_json_response
from agents.cua_cli.response_runtime import (
    ResponseRuntimeDependencies,
    clean_join_text as _clean_join_text,
    finalize_cli_response,
    stringify_terminal_value as _stringify_terminal_value,
)
from agents.cua_cli.stream_event_policy import (
    emit_terminal_stream_event,
    format_tool_status,
    safe_preview,
    status_from_stream_event,
)
from agents.skills.brain_bridge import generate_spec_with_brain
from agents.skills.registry import SkillRegistry
from agents.skills.structured import SpecGenerator, run_structured_skill
from agents.cua_cli.workspace_policy import (
    compute_workspace_dirs,
    dedupe_workspace_dirs,
    extract_drive_roots_from_task,
    extract_path_candidates_from_task,
    nearest_existing_workspace_scope,
    task_requests_terminal_execution,
    workspace_dirs_for_task,
)
from ui.visualization_api.client import get_client

# Load environment variables (backend model and binary overrides live in .env).
load_dotenv()


@dataclass
class CLIResponse:
    """Structured response from the CLI agent."""
    success: bool
    output: str
    error: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    backend: Optional[str] = None


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


class CLIAgent:
    """
    Desktop control and coding agent backed by coding-agent CLIs.

    Capable of:
    - Running shell commands
    - Opening applications
    - File system operations
    - Script execution and coding tasks
    - Process management

    Each run is a subprocess of the selected backend CLI whose JSONL events are
    normalized into one shared event schema.
    """
    _cleanup_hook_registered = False
    _managed_background_processes: Dict[str, Dict[str, Any]] = {}
    _active_foreground_processes: Dict[str, Dict[str, Any]] = {}

    def __init__(self, spec_generator: Optional[SpecGenerator] = None) -> None:
        self._full_trust = _truthy_env("JARVIS_CLI_FULL_TRUST")
        self._base_workspace_dirs = self._compute_workspace_dirs()
        self._spec_generator = spec_generator or generate_spec_with_brain
        self._ensure_cleanup_hook_registered()

    def _build_cli_env(self) -> Dict[str, str]:
        """Environment for processes Jarvis launches itself (background servers)."""
        return os.environ.copy()

    @staticmethod
    def _is_shell_tool_name(tool_name: str) -> bool:
        return str(tool_name or "").strip().lower() in {"run_shell_command", "shell", "bash"}

    @classmethod
    async def _emit_terminal_event(
        cls,
        session_id: str,
        kind: str,
        text: str = "",
        shell_command: str = "",
        status: str = "",
        source: str = "cua_cli",
    ) -> None:
        payload = {
            "command": "terminal_session_event",
            "sessionId": session_id,
            "kind": kind,
            "source": source,
            "ts": int(time.time() * 1000),
        }
        if text:
            payload["text"] = text
        if shell_command:
            payload["shellCommand"] = shell_command
        if status:
            payload["status"] = status

        try:
            client = await get_client()
            await client.send(payload)
        except Exception:
            # Best-effort UI transcript only.
            pass

    @classmethod
    def _register_foreground_process(
        cls,
        session_id: str,
        process: asyncio.subprocess.Process,
        task: str,
    ) -> Dict[str, Any]:
        return register_foreground_process(
            store=cls._active_foreground_processes,
            session_id=session_id,
            process=process,
            task=task,
        )

    @classmethod
    def _unregister_foreground_process(cls, session_id: str) -> None:
        unregister_foreground_process(
            store=cls._active_foreground_processes,
            session_id=session_id,
        )

    @classmethod
    def _ensure_cleanup_hook_registered(cls) -> None:
        if cls._cleanup_hook_registered:
            return
        atexit.register(cls._cleanup_background_processes_sync)
        cls._cleanup_hook_registered = True

    @staticmethod
    def _compute_workspace_dirs() -> List[str]:
        return compute_workspace_dirs(full_trust=_truthy_env("JARVIS_CLI_FULL_TRUST"))

    @staticmethod
    def _task_requests_terminal_execution(task: str) -> bool:
        return task_requests_terminal_execution(task)

    @staticmethod
    def _extract_drive_roots_from_task(task: str) -> List[str]:
        return extract_drive_roots_from_task(task)

    @staticmethod
    def _extract_path_candidates_from_task(task: str) -> List[str]:
        return extract_path_candidates_from_task(task)

    @staticmethod
    def _nearest_existing_workspace_scope(path_expr: str) -> Optional[str]:
        return nearest_existing_workspace_scope(path_expr)

    @staticmethod
    def _dedupe_workspace_dirs(paths: List[str]) -> List[str]:
        return dedupe_workspace_dirs(paths)

    def _workspace_dirs_for_task(self, task: str) -> List[str]:
        return workspace_dirs_for_task(self._base_workspace_dirs, task)

    def _working_dir_for_task(self, workspace_dirs: List[str]) -> str:
        """Run inside the first location the task names, else the default scope."""
        base = {
            os.path.normcase(os.path.normpath(path))
            for path in self._base_workspace_dirs
        }
        for path in workspace_dirs:
            if os.path.normcase(os.path.normpath(path)) not in base:
                return path
        return workspace_dirs[0] if workspace_dirs else str(Path.cwd().resolve())

    def _prepare_cli_task(self, task: str) -> str:
        """
        Add execution guidance so the CLI model performs actions rather than
        only describing commands.
        """
        extra_scope = [
            path for path in self._workspace_dirs_for_task(task)
            if os.path.normcase(os.path.normpath(path))
            not in {
                os.path.normcase(os.path.normpath(base_dir))
                for base_dir in self._base_workspace_dirs
            }
        ]
        extra_guidance: List[str] = []
        if self._task_requests_terminal_execution(task):
            extra_guidance.append(
                "The user explicitly asked to use the terminal. Prefer shell commands over write_file/edit tools for filesystem changes."
            )
        if extra_scope:
            extra_guidance.append(
                "This task explicitly references filesystem locations under: "
                + ", ".join(extra_scope)
                + "."
            )
            extra_guidance.append(
                "When the user specifies a drive, directory, or absolute path, operate there exactly and do not silently redirect to a different folder."
            )

        skills_section = self._skills_section(task)
        instruction = (
            "You are running inside JARVIS with tool access enabled. "
            "Execute the request directly using tools/shell commands instead of giving manual instructions. "
            "Do not claim you cannot access the system. "
            "If a command is blocked by policy or fails, report the exact command and exact error. "
            "For long-running local servers, never run foreground. "
            "Launch detached with nohup/background so it stays alive after this turn, "
            "then verify localhost/port reachability before claiming success."
        )
        if extra_guidance:
            instruction = f"{instruction} {' '.join(extra_guidance)}"
        if skills_section:
            instruction = f"{instruction}\n\n{skills_section}"
        return f"{instruction}\n\nTask:\n{task}"

    @staticmethod
    def _skills_section(task: str) -> str:
        """Skill instructions for the CLI: the full text of a named skill, else a short catalog."""
        registry = SkillRegistry.discover()
        named = registry.explicit_skill(task)
        if named is not None and not named.manifest.is_structured:
            return (
                f"The user asked you to use the '{named.name}' skill. Follow its instructions. "
                f"Its files are in {named.manifest.directory}.\n\n{named.manifest.body}"
            )
        relevant = registry.relevant_skills(task)
        if not relevant:
            return ""
        lines = [f"- {entry.name}: {entry.manifest.description} (read {entry.manifest.path})" for entry in relevant]
        return (
            "Installed skills that may help. Read a skill's SKILL.md before using it, "
            "and skip any that do not fit the task:\n" + "\n".join(lines)
        )

    @staticmethod
    def _prepare_retry_task(task: str) -> str:
        instruction = (
            "Your previous response did not provide verified execution evidence. "
            "You MUST execute the task now using your shell and file tools. "
            "Do not provide a 'run this in terminal' suggestion. "
            "Return what you executed and outcome."
        )
        return f"{instruction}\n\nTask:\n{task}"

    @staticmethod
    def _extract_explicit_shell_command(task: str) -> Optional[str]:
        return extract_explicit_shell_command(task)

    @staticmethod
    def _is_server_like_command(command: str) -> bool:
        return is_server_like_command(command)

    @classmethod
    def _is_background_intent_task(cls, task: str, command: str) -> bool:
        del cls
        return is_background_intent_task(task, command)

    @classmethod
    def _is_server_intent_text(cls, text: str) -> bool:
        del cls
        return is_server_intent_text(text)

    @classmethod
    def _is_quick_server_launch_task(cls, text: str) -> bool:
        del cls
        return is_quick_server_launch_task(text)

    @staticmethod
    def _extract_port_candidates(text: str) -> List[int]:
        return extract_port_candidates(text)

    @staticmethod
    def _resolve_shell_path(path_expr: str, base_dir: Path) -> Path:
        return resolve_shell_path(path_expr, base_dir)

    @classmethod
    def _extract_server_subcommand(cls, command: str) -> str:
        del cls
        return extract_server_subcommand(command)

    @staticmethod
    def _extract_shell_command_from_tool_call(tool_call: Dict[str, Any]) -> Optional[str]:
        return extract_shell_command_from_tool_call(tool_call)

    @classmethod
    def _infer_server_launch_from_tool_calls(
        cls,
        tool_calls: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, str]]:
        del cls
        return infer_server_launch_from_tool_calls(tool_calls)

    @staticmethod
    async def _is_local_port_open(port: int) -> bool:
        return await is_local_port_open(port)

    @classmethod
    async def _wait_for_any_port(cls, ports: List[int], timeout_seconds: float = 8.0) -> Optional[int]:
        del cls
        return await wait_for_any_port(ports=ports, timeout_seconds=timeout_seconds)

    @staticmethod
    def _resolve_background_shell() -> tuple[list[str], dict[str, Any]]:
        return resolve_background_shell()

    @staticmethod
    def _terminate_process_tree_sync(metadata: Dict[str, Any]) -> None:
        terminate_process_tree_sync(metadata)

    @classmethod
    async def _start_background_process(
        cls,
        command: str,
        env: Dict[str, str],
        working_dir: str,
        task: str,
    ) -> dict:
        return await start_background_process(
            managed_store=cls._managed_background_processes,
            command=command,
            env=env,
            working_dir=working_dir,
            task=task,
            extract_port_candidates=cls._extract_port_candidates,
        )

    def _response_runtime_dependencies(self) -> ResponseRuntimeDependencies:
        return ResponseRuntimeDependencies(
            infer_server_launch_from_tool_calls=self._infer_server_launch_from_tool_calls,
            extract_port_candidates=self._extract_port_candidates,
            wait_for_any_port=self._wait_for_any_port,
            start_background_process=self._start_background_process,
            build_cli_env=self._build_cli_env,
            is_timeout_error_text=self._is_timeout_error_text,
        )

    async def _finalize_cli_response(self, task: str, response: CLIResponse) -> dict:
        result = await finalize_cli_response(
            task,
            response,
            deps=self._response_runtime_dependencies(),
        )
        if response.backend:
            result.setdefault("backend", response.backend)
        return result

    @classmethod
    def _cleanup_background_processes_sync(cls) -> None:
        cleanup_background_processes_sync(managed_store=cls._managed_background_processes)

    @classmethod
    async def stop_background_process(cls, process_id: str) -> bool:
        return await stop_background_process(
            managed_store=cls._managed_background_processes,
            process_id=process_id,
        )

    @classmethod
    async def stop_all_background_processes(cls) -> int:
        return await stop_all_background_processes(
            managed_store=cls._managed_background_processes,
        )

    @classmethod
    async def stop_all_running_processes(cls) -> int:
        foreground_ids = list(cls._active_foreground_processes.keys())
        stopped = 0

        for proc_id in foreground_ids:
            meta = cls._active_foreground_processes.get(proc_id)
            if not meta:
                continue
            cls._terminate_process_tree_sync(meta)
            cls._active_foreground_processes.pop(proc_id, None)
            stopped += 1
            await cls._emit_terminal_event(
                proc_id,
                kind="session_stopped",
                text="Terminal session stopped.",
                status="stopped",
            )

        stopped += await cls.stop_all_background_processes()
        return stopped

    @classmethod
    def list_background_processes(cls) -> List[Dict[str, Any]]:
        return list_background_processes(managed_store=cls._managed_background_processes)

    @classmethod
    def active_background_log_paths(cls) -> List[str]:
        return [
            str(meta.get("log_path"))
            for meta in cls._managed_background_processes.values()
            if meta.get("log_path")
        ]

    async def _maybe_handle_background_management_task(self, task: str) -> Optional[dict]:
        lower = task.strip().lower()
        if any(phrase in lower for phrase in (
            "close terminal",
            "close the terminal",
            "stop terminal",
            "stop the terminal",
            "kill terminal",
            "stop cli agent",
        )):
            count = await self.stop_all_running_processes()
            return {"success": True, "result": f"Stopped {count} CLI process(es).", "error": None}

        if "list background process" in lower or "show background process" in lower:
            rows = self.list_background_processes()
            if not rows:
                return {"success": True, "result": "No managed background processes.", "error": None}
            lines = [
                f"{row['id']} pid={row['pid']} port={row.get('active_port','-')} uptime={row['uptime_seconds']}s cmd={row['command']}"
                for row in rows
            ]
            return {"success": True, "result": "Managed background processes:\n" + "\n".join(lines), "error": None}

        if "stop all background process" in lower or "kill all background process" in lower:
            count = await self.stop_all_background_processes()
            return {"success": True, "result": f"Stopped {count} background process(es).", "error": None}

        m = re.search(r"(?:stop|kill)\s+background\s+process\s+([a-zA-Z0-9_-]+)", task, flags=re.IGNORECASE)
        if m:
            proc_id = m.group(1).strip()
            ok = await self.stop_background_process(proc_id)
            if ok:
                return {"success": True, "result": f"Stopped background process {proc_id}.", "error": None}
            return {"success": False, "result": None, "error": f"No background process found: {proc_id}"}

        return None

    @staticmethod
    def _is_timeout_error_text(text: Optional[str]) -> bool:
        lowered = str(text or "").lower()
        return "timed out" in lowered or "timeout" in lowered

    @staticmethod
    def _looks_like_execution_refusal(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        patterns = [
            r"\bi (?:am|do not have|don't have).{0,30}\b(?:ability|access|permission)\b",
            r"\bi cannot\b.{0,40}\b(?:run|execute|create|move|delete|modify)\b",
            r"\bi can (?:however )?provide (?:you )?with (?:the )?commands\b",
            r"\brun (?:the|this) command in your terminal\b",
            r"\bi(?:'m| am) unable to execute shell commands\b",
        ]
        return any(re.search(p, lowered) for p in patterns)

    @staticmethod
    def _default_timeout_for_task(task: str) -> int:
        """Delegated coding sessions routinely run longer than shell tasks."""
        if coding_delegation_enabled() and is_coding_task(task):
            return _int_env("JARVIS_CODING_TIMEOUT_SECONDS", 900)
        return _int_env("JARVIS_CLI_TIMEOUT_SECONDS", 300)

    async def execute(
        self,
        task: str,
        timeout: Optional[int] = None,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> dict:
        """
        Execute a CLI task.

        Args:
            task: The task description for the CLI agent
            timeout: Maximum execution time in seconds (defaults per task type)
            status_callback: Optional async callback for live status updates

        Returns:
            dict with keys: success, result, error, raw_output
        """
        if timeout is None:
            timeout = self._default_timeout_for_task(task)
        try:
            management_response = await self._maybe_handle_background_management_task(task)
            if management_response is not None:
                return management_response

            structured_skill = SkillRegistry.discover().structured_skill_for(task)
            if structured_skill is not None:
                await self._emit_status(status_callback, f"Using the {structured_skill.name} skill...")
                return await run_structured_skill(structured_skill, task, generate=self._spec_generator)

            explicit_command = self._extract_explicit_shell_command(task)
            if explicit_command and self._is_background_intent_task(task, explicit_command):
                env = self._build_cli_env()
                return await self._start_background_process(
                    command=explicit_command,
                    env=env,
                    working_dir=str(Path.cwd().resolve()),
                    task=task,
                )

            direct_command = extract_safe_direct_command(
                task,
                explicit_command=explicit_command,
            )
            if direct_command is not None:
                return await self._run_direct_command(
                    direct_command,
                    timeout=min(timeout, direct_command.timeout_seconds),
                    status_callback=status_callback,
                )

            run_timeout = timeout
            short_timeout_applied = False
            if self._is_quick_server_launch_task(task):
                # Keep server-launch turns snappy so long-running foreground processes
                # are promoted to background quickly.
                run_timeout = min(run_timeout, 3)
                short_timeout_applied = run_timeout < timeout

            prepared_task = self._prepare_cli_task(task)
            response = await self._run_cli(
                prepared_task,
                run_timeout,
                status_callback=status_callback,
                tool_context_task=task,
            )
            if (
                short_timeout_applied
                and self._is_timeout_error_text(response.error)
                and not response.tool_calls
            ):
                # Short timeout fired before any tool execution. Retry once with full
                # timeout so setup-heavy tasks (clone/install/start) can proceed.
                response = await self._run_cli(
                    prepared_task,
                    timeout,
                    status_callback=status_callback,
                    tool_context_task=task,
                )
            if (
                response.success
                and not response.tool_calls
                and (self._task_requests_terminal_execution(task)
                     or self._looks_like_execution_refusal(response.output))
            ):
                # Retry once with stronger execution-only instructions.
                retry_task = self._prepare_retry_task(task)
                response = await self._run_cli(
                    retry_task,
                    run_timeout,
                    status_callback=status_callback,
                    tool_context_task=task,
                )
            if response.success and not response.tool_calls and self._task_requests_terminal_execution(task):
                response.success = False
                response.error = "The CLI returned no execution evidence for the requested terminal task."
                response.output = ""
            return await self._finalize_cli_response(task, response)
        except asyncio.TimeoutError:
            return {
                "success": False,
                "result": None,
                "error": f"CLI task timed out after {timeout} seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e),
            }

    @staticmethod
    def _safe_preview(value: object, max_len: int = 80) -> str:
        return safe_preview(value, max_len=max_len)

    @classmethod
    def _format_tool_status(cls, tool_name: str, parameters: dict) -> str:
        del cls
        return format_tool_status(
            tool_name=tool_name,
            parameters=parameters,
            safe_preview_fn=safe_preview,
        )

    @classmethod
    def _status_from_stream_event(
        cls,
        event: dict,
        tool_by_id: Dict[str, str],
    ) -> Optional[str]:
        del cls
        return status_from_stream_event(
            event=event,
            tool_by_id=tool_by_id,
            safe_preview_fn=safe_preview,
            format_tool_status_fn=format_tool_status,
        )

    @classmethod
    async def _emit_terminal_stream_event(
        cls,
        session_id: str,
        event: dict,
        tool_by_id: Dict[str, str],
        shell_command_by_id: Dict[str, str],
    ) -> None:
        await emit_terminal_stream_event(
            session_id=session_id,
            event=event,
            tool_by_id=tool_by_id,
            shell_command_by_id=shell_command_by_id,
            emit_terminal_event=cls._emit_terminal_event,
            is_shell_tool_name=cls._is_shell_tool_name,
            safe_preview_fn=safe_preview,
            stringify_terminal_value_fn=_stringify_terminal_value,
        )

    async def _emit_status(
        self,
        status_callback: Optional[Callable[[str], Awaitable[None]]],
        text: Optional[str],
    ) -> None:
        if not status_callback or not text:
            return
        try:
            await status_callback(text)
        except Exception:
            # UI status updates should never break CLI execution.
            pass

    async def _run_cli(
        self,
        task: str,
        timeout: int,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
        tool_context_task: Optional[str] = None,
    ) -> CLIResponse:
        """
        Run the task on the first backend in the chain that can start.

        A backend is skipped only when it is not installed, refuses its
        arguments, or fails authentication before running any tool, so a task
        is never executed twice.
        """
        tool_context = tool_context_task or task
        workspace_dirs = self._workspace_dirs_for_task(tool_context)
        request = BackendRequest(
            prompt=task,
            cwd=self._working_dir_for_task(workspace_dirs),
            workspace_dirs=tuple(workspace_dirs),
            full_trust=self._full_trust,
        )
        skipped: List[str] = []
        for backend in backend_chain_for_task(tool_context):
            try:
                invocation = backend.invocation(request)
            except (BackendUnavailableError, BackendUnsafeArgumentsError) as exc:
                skipped.append(str(exc))
                continue
            await self._emit_status(status_callback, f"Using {backend.display_name}...")
            try:
                response = await self._run_backend(backend, invocation, timeout, task, status_callback)
            except OSError as exc:
                skipped.append(f"{backend.display_name} failed to start: {exc}")
                continue
            if self._should_try_next_backend(response):
                skipped.append(f"{backend.display_name}: {response.error}")
                continue
            response.backend = backend.name
            return response
        return CLIResponse(
            success=False,
            output="",
            error="No coding CLI could run this task. " + " | ".join(skipped),
        )

    @staticmethod
    def _should_try_next_backend(response: CLIResponse) -> bool:
        if response.success or response.tool_calls:
            return False
        return looks_like_auth_failure(response.error) or looks_like_auth_failure(response.output)

    async def _run_backend(
        self,
        backend: CodingBackend,
        invocation,
        timeout: int,
        task: str,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> CLIResponse:
        session_id = uuid.uuid4().hex[:8]
        process = await asyncio.create_subprocess_exec(
            *invocation.argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=invocation.cwd,
            env=invocation.env,
            # CLI initialization and file/tool events can exceed asyncio's 64 KB default.
            limit=4 * 1024 * 1024,
        )
        self._register_foreground_process(session_id, process, task)

        normalized_lines: List[str] = []
        stderr_lines: List[str] = []
        tool_by_id: Dict[str, str] = {}
        shell_command_by_id: Dict[str, str] = {}
        state = NormalizationState()

        async def _publish(event: dict) -> None:
            normalized_lines.append(json.dumps(event))
            status_text = self._status_from_stream_event(event, tool_by_id)
            await self._emit_terminal_stream_event(
                session_id=session_id,
                event=event,
                tool_by_id=tool_by_id,
                shell_command_by_id=shell_command_by_id,
            )
            await self._emit_status(status_callback, status_text)

        async def _write_prompt() -> None:
            if process.stdin is None:
                return
            try:
                process.stdin.write(invocation.stdin_text.encode("utf-8"))
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        async def _read_stdout() -> None:
            if process.stdout is None:
                return
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                for normalized in backend.normalize_event(event, state):
                    await _publish(normalized)

        async def _read_stderr() -> None:
            if process.stderr is None:
                return
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                stderr_lines.append(raw.decode("utf-8", errors="replace"))

        timed_out = False
        stdin_task = asyncio.create_task(_write_prompt())
        stdout_task = asyncio.create_task(_read_stdout())
        stderr_task = asyncio.create_task(_read_stderr())
        wait_task = asyncio.create_task(process.wait())

        try:
            wait_outcome = await await_foreground_process_operation(
                process=process,
                timeout=timeout,
                operation=asyncio.gather(stdin_task, stdout_task, stderr_task, wait_task),
                cleanup=lambda: asyncio.gather(
                    stdin_task,
                    stdout_task,
                    stderr_task,
                    wait_task,
                    return_exceptions=True,
                ),
                terminate_process_tree=self._terminate_process_tree_sync,
            )
            timed_out = wait_outcome.timed_out
            if timed_out:
                await self._emit_terminal_event(
                    session_id,
                    kind="session_error",
                    text=f"{backend.display_name} timed out after {timeout} seconds.",
                    status="error",
                )
        except asyncio.CancelledError:
            await self._emit_terminal_event(
                session_id,
                kind="session_stopped",
                text=f"{backend.display_name} session stopped.",
                status="stopped",
            )
            raise
        finally:
            self._unregister_foreground_process(session_id)

        stderr_text = "".join(stderr_lines)
        if not timed_out:
            for normalized in backend.finalize(state, process.returncode or 0, stderr_text):
                await _publish(normalized)

        response = self._parse_stream_json("\n".join(normalized_lines), stderr_text, process.returncode)
        if timed_out:
            timeout_msg = f"CLI task timed out after {timeout} seconds"
            response.success = False
            response.error = _clean_join_text(response.error, timeout_msg)
        return response

    async def _run_direct_command(
        self,
        command: DirectCommand,
        timeout: int,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> dict:
        session_id = uuid.uuid4().hex[:8]
        await self._emit_terminal_event(
            session_id,
            kind="session_started",
            text="Direct CLI session started.",
            status="running",
        )
        await self._emit_terminal_event(
            session_id,
            kind="command_started",
            shell_command=command.display,
            text=command.display,
            status="running",
        )
        await self._emit_status(
            status_callback,
            f"Running shell command: {command.display}",
        )

        process = await asyncio.create_subprocess_exec(
            *command.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.cwd().resolve()),
        )
        self._register_foreground_process(session_id, process, command.display)

        timed_out = False
        try:
            command_outcome = await await_foreground_process_operation(
                process=process,
                timeout=timeout,
                operation=process.communicate(),
                terminate_process_tree=self._terminate_process_tree_sync,
            )
            timed_out = command_outcome.timed_out
            if timed_out:
                stdout = b""
                stderr = f"Command timed out after {timeout} seconds".encode("utf-8")
            else:
                stdout, stderr = command_outcome.value or (b"", b"")
        except asyncio.CancelledError:
            await self._emit_terminal_event(
                session_id,
                kind="session_stopped",
                text="Direct CLI session stopped.",
                status="stopped",
            )
            raise
        finally:
            self._unregister_foreground_process(session_id)

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        success = (process.returncode == 0) and not timed_out
        result_text = stdout_text or stderr_text
        status = "success" if success else "error"

        await self._emit_terminal_event(
            session_id,
            kind="command_output",
            shell_command=command.display,
            text=result_text or "(command completed with no output)",
            status=status,
        )
        await self._emit_terminal_event(
            session_id,
            kind="session_finished" if success else "session_error",
            text="Direct CLI session finished." if success else (stderr_text or "Direct CLI session failed."),
            status=status,
        )

        return {
            "success": success,
            "result": result_text,
            "error": None if success else (stderr_text or f"Command exited with code {process.returncode}"),
            "tool_calls": [
                {
                    "tool_name": "run_shell_command",
                    "tool_id": f"direct-{session_id}",
                    "parameters": {"command": command.display},
                    "result": result_text,
                    "status": status,
                    "error": None if success else (stderr_text or f"exit_code={process.returncode}"),
                }
            ],
        }

    def _parse_stream_json(self, stdout: str, stderr: str, returncode: int) -> CLIResponse:
        parsed = parse_stream_json_response(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
        return CLIResponse(
            success=bool(parsed.get("success")),
            output=str(parsed.get("output") or ""),
            error=parsed.get("error"),
            tool_calls=parsed.get("tool_calls"),
        )

    async def run_command(self, command: str, timeout: int = 30) -> tuple[str, str, int]:
        """
        Run a shell command directly (bypass LLM).

        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds

        Returns:
            Tuple of (stdout, stderr, return_code)
        """
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        command_outcome = await await_foreground_process_operation(
            process=process,
            timeout=timeout,
            operation=process.communicate(),
        )
        if command_outcome.timed_out:
            return "", "Command timed out", -1
        stdout, stderr = command_outcome.value or (b"", b"")

        return (
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
            process.returncode or 0,
        )


# Convenience function for quick execution
async def run_cli_task(task: str, **kwargs) -> dict:
    """
    Quick helper to run a CLI task.

    Args:
        task: The task description
        **kwargs: Additional arguments for CLIAgent

    Returns:
        Result dict with success, result, error keys
    """
    agent = CLIAgent(**kwargs)
    return await agent.execute(task)
