"""
CLI Agent - Desktop control via Gemini CLI.

Wraps the gemini-cli (TypeScript) to provide shell-based computer control.
The rapid response model invokes this agent for CLI tasks.
"""
import atexit
import asyncio
import json
import os
import tempfile
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Callable, Awaitable, Any

from dotenv import load_dotenv
from agents.cua_cli.background_manager import (
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
from agents.cua_cli.response_parser import (
    parse_json_response,
    parse_stream_json_response,
)
from agents.cua_cli.stream_event_policy import (
    emit_terminal_stream_event,
    format_tool_status,
    safe_preview,
    status_from_stream_event,
)
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

# Load environment variables (ensures GEMINI_API_KEY is available)
load_dotenv()


@dataclass
class CLIResponse:
    """Structured response from the CLI agent."""
    success: bool
    output: str
    error: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None


def _clean_join_text(*parts: Any) -> str:
    cleaned_parts: List[str] = []
    for part in parts:
        text = " ".join(str(part or "").split())
        if text:
            cleaned_parts.append(text)
    return " | ".join(cleaned_parts)


def _stringify_terminal_value(value: Any, max_len: int = 6000) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, indent=2, ensure_ascii=True)
        except Exception:
            text = str(value)

    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    if len(normalized) > max_len:
        clipped = normalized[: max_len - 18].rstrip()
        return f"{clipped}\n...[truncated]..."
    return normalized


class CLIAgent:
    """
    Desktop control agent using Gemini CLI.

    Capable of:
    - Running shell commands
    - Opening applications
    - File system operations
    - Script execution
    - Process management

    The agent wraps the gemini-cli (Node.js) and communicates via subprocess.
    """
    _cleanup_hook_registered = False
    _managed_background_processes: Dict[str, Dict[str, Any]] = {}
    _active_foreground_processes: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        gemini_cli_path: Optional[str] = None,
        approval_mode: str = "yolo",
        output_format: str = "stream-json",
        model: Optional[str] = None,
    ):
        """
        Initialize the CLI agent.

        Args:
            gemini_cli_path: Path to gemini-cli directory. Defaults to ./gemini-cli
            approval_mode: Tool approval mode (yolo, auto_edit, default, plan)
            output_format: Output format (text, json, stream-json)
            model: Optional model override
        """
        if gemini_cli_path is None:
            # Default to gemini-cli in the same directory as this agent
            gemini_cli_path = str(Path(__file__).parent / "gemini-cli")

        self.gemini_cli_path = gemini_cli_path
        self.cli_bin = os.path.join(gemini_cli_path, "bundle", "gemini.js")
        self.approval_mode = approval_mode
        self.output_format = output_format
        self.model = model
        self._base_workspace_dirs = self._compute_workspace_dirs()
        self._gemini_cli_home = self._ensure_gemini_cli_home()
        self._trusted_folders_path = self._ensure_trusted_folders_config()
        self._ensure_cleanup_hook_registered()

        # Check if CLI is built
        self._check_cli_built()

    def _check_cli_built(self) -> None:
        """Check if the gemini-cli has been built."""
        if not os.path.exists(self.cli_bin):
            raise RuntimeError(
                f"Gemini CLI not built. Run 'npm install && npm run build' in {self.gemini_cli_path}"
            )

    def _build_command(self, task: str) -> list[str]:
        """Build the command to execute the CLI."""
        cmd = [
            "node",
            self.cli_bin,
            "--prompt", task,
            "--output-format", self.output_format,
            "--approval-mode", self.approval_mode,
        ]

        for include_dir in self._workspace_dirs_for_task(task):
            cmd.extend(["--include-directories", include_dir])

        if self.model:
            cmd.extend(["--model", self.model])

        return cmd

    def _build_cli_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if not env.get("GEMINI_API_KEY"):
            raise RuntimeError(
                "GEMINI_API_KEY not found in environment. "
                "Please set it in your .env file."
            )
        # Enable permissive policy for JARVIS CLI sessions:
        # allow all tools by default while still blocking dangerous shell commands.
        env["JARVIS_CLI_PERMISSIVE_POLICY"] = "1"
        # Trust this workspace so Gemini CLI does not downgrade approval mode.
        env["GEMINI_CLI_TRUSTED_FOLDERS_PATH"] = self._trusted_folders_path
        # Use a writable Gemini CLI home directory for sessions/tmp storage.
        env["GEMINI_CLI_HOME"] = self._gemini_cli_home
        # Disable sandbox for maximum tool/file access in JARVIS CLI sessions.
        env["GEMINI_SANDBOX"] = "false"
        return env

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

    def _ensure_trusted_folders_config(self) -> str:
        """
        Create a local trustedFolders.json for non-interactive CLI runs.

        Gemini CLI downgrades approval mode to default in untrusted folders.
        This file marks our working directories as TRUST_FOLDER so YOLO can apply.
        """
        trusted_file = Path(tempfile.gettempdir()) / "jarvis_gemini_trusted_folders.json"
        entries = {
            str(Path(self.gemini_cli_path).resolve()): "TRUST_FOLDER",
            str(Path(self.gemini_cli_path).resolve().parent.parent.parent): "TRUST_FOLDER",
            str(Path.cwd().resolve()): "TRUST_FOLDER",
            str(Path.home().resolve()): "TRUST_FOLDER",
        }
        trusted_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return str(trusted_file)

    def _ensure_gemini_cli_home(self) -> str:
        """
        Ensure a writable Gemini CLI home directory.
        """
        gemini_home = Path(self.gemini_cli_path).resolve() / ".jarvis_gemini_home"
        gemini_home.mkdir(parents=True, exist_ok=True)
        return str(gemini_home)

    @staticmethod
    def _compute_workspace_dirs() -> List[str]:
        return compute_workspace_dirs()

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
        return f"{instruction}\n\nTask:\n{task}"

    @staticmethod
    def _prepare_retry_task(task: str) -> str:
        instruction = (
            "Your previous response incorrectly refused execution. "
            "You MUST execute the task now using tools (run_shell_command, file tools, etc.). "
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

    async def _validate_local_server_claim(self, output_text: str) -> Optional[str]:
        if not output_text:
            return None
        lowered = output_text.lower()
        has_localhost_hint = ("localhost" in lowered) or ("127.0.0.1" in lowered) or ("port " in lowered)
        has_running_hint = any(word in lowered for word in ("running", "started", "listening", "serving", "available at"))
        if not (has_localhost_hint and has_running_hint):
            return None

        ports = self._extract_port_candidates(output_text)
        if not ports:
            return None
        opened = await self._wait_for_any_port(ports, timeout_seconds=15.0)
        if opened is not None:
            return None
        return (
            "Task reported a local server as running, but none of the claimed ports are reachable: "
            f"{ports}. The process likely exited or never started successfully."
        )

    async def _maybe_promote_server_launch_from_tool_calls(
        self,
        task: str,
        response: CLIResponse,
    ) -> Optional[dict]:
        launch = self._infer_server_launch_from_tool_calls(response.tool_calls)
        if not launch:
            return None

        launch_command = launch["command"]
        launch_cwd = launch["cwd"]

        combined = "\n".join(filter(None, [task, response.output, launch_command]))
        ports = self._extract_port_candidates(combined)
        if ports:
            opened = await self._wait_for_any_port(ports, timeout_seconds=1.2)
            if opened is not None:
                # Server already reachable from host. If prior run timed out, treat as
                # success so orchestration can continue.
                if self._is_timeout_error_text(response.error):
                    return {
                        "success": True,
                        "result": _clean_join_text(
                            response.output,
                            f"Local server is reachable on http://127.0.0.1:{opened}.",
                        ),
                        "error": None,
                        "tool_calls": response.tool_calls,
                    }
                return None

        env = self._build_cli_env()
        started = await self._start_background_process(
            command=launch_command,
            env=env,
            working_dir=launch_cwd,
            task=task,
        )

        merged_result = _clean_join_text(response.output, started.get("result"))
        merged_tool_calls: List[Dict[str, Any]] = []
        if response.tool_calls:
            merged_tool_calls.extend(response.tool_calls)
        if started.get("tool_calls"):
            merged_tool_calls.extend(started["tool_calls"])

        return {
            "success": True,
            "result": merged_result,
            "error": None,
            "tool_calls": merged_tool_calls or None,
        }

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
    def _looks_like_generic_api_failure(error_text: Optional[str]) -> bool:
        lowered = str(error_text or "").lower()
        if not lowered:
            return False
        markers = (
            "fetch failed",
            "sending request",
            "[api error:",
            "exception typeerror",
            "session error",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _collect_tool_error_messages(
        tool_calls: Optional[List[Dict[str, Any]]],
    ) -> List[str]:
        messages: List[str] = []
        for tool_call in tool_calls or []:
            if not isinstance(tool_call, dict):
                continue
            if str(tool_call.get("status") or "").strip().lower() != "error":
                continue

            message = ""
            raw_error = tool_call.get("error")
            if isinstance(raw_error, dict):
                message = str(raw_error.get("message") or raw_error.get("error") or "")
            elif raw_error is not None:
                message = str(raw_error)

            if not message:
                raw_result = tool_call.get("result")
                if isinstance(raw_result, str):
                    message = raw_result
                elif raw_result is not None:
                    message = _stringify_terminal_value(raw_result, max_len=800)

            cleaned = " ".join(str(message or "").split())
            if cleaned and cleaned not in messages:
                messages.append(cleaned)
        return messages

    @classmethod
    def _normalize_cli_response(cls, response: CLIResponse) -> CLIResponse:
        tool_errors = cls._collect_tool_error_messages(response.tool_calls)
        if not tool_errors:
            return response

        primary_error = tool_errors[-1]
        if not response.output and not response.success:
            response.output = primary_error

        if response.error:
            if cls._looks_like_generic_api_failure(response.error):
                response.error = _clean_join_text(primary_error, response.error)
        elif not response.success:
            response.error = primary_error

        return response

    async def execute(
        self,
        task: str,
        timeout: int = 300,
        status_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> dict:
        """
        Execute a CLI task.

        Args:
            task: The task description for the CLI agent
            timeout: Maximum execution time in seconds
            status_callback: Optional async callback for live status updates

        Returns:
            dict with keys: success, result, error, raw_output
        """
        try:
            management_response = await self._maybe_handle_background_management_task(task)
            if management_response is not None:
                return management_response

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
                )
            if (
                response.success
                and not response.tool_calls
                and self._looks_like_execution_refusal(response.output)
            ):
                # Retry once with stronger execution-only instructions.
                retry_task = self._prepare_retry_task(task)
                response = await self._run_cli(
                    retry_task,
                    run_timeout,
                    status_callback=status_callback,
                )
            response = self._normalize_cli_response(response)
            # If CLI used a server-like launch command in tool calls, auto-persist it.
            # This avoids "it said localhost is up, but the process already exited".
            if response.tool_calls:
                promoted = await self._maybe_promote_server_launch_from_tool_calls(task, response)
                if promoted is not None:
                    return promoted
            localhost_claim_error = await self._validate_local_server_claim(response.output)
            if localhost_claim_error:
                # Last chance: if tool traces exist, try one more promotion pass
                # before failing the chain on localhost reachability.
                if response.tool_calls:
                    promoted = await self._maybe_promote_server_launch_from_tool_calls(task, response)
                    if promoted is not None:
                        return promoted
                return {
                    "success": False,
                    "result": response.output,
                    "error": localhost_claim_error,
                    "tool_calls": response.tool_calls,
                }
            return {
                "success": response.success,
                "result": response.output,
                "error": response.error,
                "tool_calls": response.tool_calls,
            }
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
    ) -> CLIResponse:
        """
        Run the gemini-cli with the given task.

        Returns structured response parsed from JSON output.
        """
        cmd = self._build_command(task)
        session_id = uuid.uuid4().hex[:8]

        env = self._build_cli_env()

        # Run the CLI process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path.cwd().resolve()),
            env=env,
        )
        self._register_foreground_process(session_id, process, task)

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []
        tool_by_id: Dict[str, str] = {}
        shell_command_by_id: Dict[str, str] = {}

        async def _read_stdout() -> None:
            if process.stdout is None:
                return
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                stdout_lines.append(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                status_text = self._status_from_stream_event(event, tool_by_id)
                await self._emit_terminal_stream_event(
                    session_id=session_id,
                    event=event,
                    tool_by_id=tool_by_id,
                    shell_command_by_id=shell_command_by_id,
                )
                await self._emit_status(status_callback, status_text)

        async def _read_stderr() -> None:
            if process.stderr is None:
                return
            while True:
                raw = await process.stderr.readline()
                if not raw:
                    break
                decoded = raw.decode("utf-8", errors="replace")
                stderr_lines.append(decoded)

        timed_out = False
        stdout_task = asyncio.create_task(_read_stdout())
        stderr_task = asyncio.create_task(_read_stderr())
        wait_task = asyncio.create_task(process.wait())

        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task, wait_task),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            self._terminate_process_tree_sync({"pid": process.pid})
            try:
                await process.wait()
            except Exception:
                pass
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            await self._emit_terminal_event(
                session_id,
                kind="session_stopped",
                text="CLI session stopped.",
                status="stopped",
            )
            raise
        except asyncio.TimeoutError:
            timed_out = True
            self._terminate_process_tree_sync({"pid": process.pid})
            try:
                await process.wait()
            except Exception:
                pass
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            await self._emit_terminal_event(
                session_id,
                kind="session_error",
                text=f"CLI session timed out after {timeout} seconds.",
                status="error",
            )
        finally:
            self._unregister_foreground_process(session_id)

        stdout_text = "\n".join(stdout_lines)
        stderr_text = "".join(stderr_lines)
        if stderr_text.strip() and not stdout_lines:
            await self._emit_terminal_event(
                session_id,
                kind="session_error",
                text=_stringify_terminal_value(stderr_text, max_len=1200) or "CLI session failed.",
                status="error",
            )

        # Parse the output based on format
        if self.output_format == "stream-json":
            response = self._parse_stream_json(stdout_text, stderr_text, process.returncode)
        elif self.output_format == "json":
            response = self._parse_json(stdout_text, stderr_text, process.returncode)
        else:
            response = CLIResponse(
                success=process.returncode == 0,
                output=stdout_text,
                error=stderr_text if process.returncode != 0 else None,
            )

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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.CancelledError:
            self._terminate_process_tree_sync({"pid": process.pid})
            try:
                await process.wait()
            except Exception:
                pass
            await self._emit_terminal_event(
                session_id,
                kind="session_stopped",
                text="Direct CLI session stopped.",
                status="stopped",
            )
            raise
        except asyncio.TimeoutError:
            timed_out = True
            self._terminate_process_tree_sync({"pid": process.pid})
            try:
                await process.wait()
            except Exception:
                pass
            stdout = b""
            stderr = f"Command timed out after {timeout} seconds".encode("utf-8")
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

    def _parse_json(self, stdout: str, stderr: str, returncode: int) -> CLIResponse:
        parsed = parse_json_response(
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

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return "", "Command timed out", -1

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
