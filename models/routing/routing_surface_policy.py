"""
Surface-selection helpers for execution-oriented routing decisions.
"""

from __future__ import annotations

from models.routing_intent_policy import matches_any_marker
from models.routing_payload_parser import RouteAgentName, ScreenContextPayload

EXECUTION_INTENT_MARKERS = (
    "click",
    "open",
    "run",
    "type",
    "install",
    "clone",
    "start",
    "stop",
    "search",
    "go to",
    "create",
    "delete",
    "move",
    "copy",
    "paste",
    "scroll",
    "press",
    "launch",
    "execute",
    "minimize",
    "maximize",
    "restore",
    "close",
    "switch",
    "focus",
    "drag",
    "drop",
    "select",
    "debug",
    "fix",
    "build",
    "deploy",
    "test",
    "edit",
    "update",
)
BROWSER_EXECUTION_MARKERS = (
    "http://",
    "https://",
    "www.",
    "browser",
    "website",
    "web site",
    "webpage",
    "tab",
    "url",
    ".com",
    ".org",
    ".net",
)
VISION_EXECUTION_MARKERS = (
    "click",
    "button",
    "menu",
    "dropdown",
    "checkbox",
    "radio button",
    "icon",
    "drag",
    "drop",
    "cursor",
    "on screen",
    "desktop app",
    "window",
    "dialog",
)
CLI_EXECUTION_MARKERS = (
    "terminal",
    "from terminal",
    "shell",
    "command",
    "powershell",
    "bash",
    "zsh",
    "cmd",
    "ping",
    "curl",
    "wget",
    "nslookup",
    "tracert",
    "ipconfig",
    "git",
    "npm",
    "pnpm",
    "yarn",
    "pip",
    "python",
    "node",
    "repo",
    "repository",
    "file",
    "folder",
    "directory",
    "localhost",
    "127.0.0.1",
)
WINDOW_MANAGEMENT_MARKERS = (
    "minimize",
    "maximize",
    "restore",
    "close the app",
    "close the window",
    "switch window",
    "focus window",
)
DESKTOP_SURFACE_MARKERS = (
    "desktop app",
    "installed app",
    "native app",
    "local app",
    "application",
    "app window",
    "desktop window",
    "existing window",
    "already open",
    "currently open",
    "active window",
    "current window",
    "my browser",
    "my installed browser",
    "use my browser",
    "open my browser",
)
SPECIFIC_BROWSER_CONTEXT_MARKERS = (
    "profile",
    "work profile",
    "personal profile",
    "browser profile",
    "specific profile",
)
BROWSER_SURFACE_MARKERS = (
    "browser",
    "new tab",
    "tab",
    "web",
    "website",
    "web site",
    "webpage",
    "url",
    "http://",
    "https://",
    "www.",
)


def is_execution_request(text: str) -> bool:
    return matches_any_marker(text, EXECUTION_INTENT_MARKERS)


def is_window_management_request(text: str) -> bool:
    return matches_any_marker(text, WINDOW_MANAGEMENT_MARKERS)


def requires_desktop_control_surface(text: str) -> bool:
    lowered = (text or "").lower()
    if not lowered:
        return False

    if is_window_management_request(lowered):
        return True

    has_desktop_surface = matches_any_marker(lowered, DESKTOP_SURFACE_MARKERS)
    has_specific_browser_context = matches_any_marker(lowered, SPECIFIC_BROWSER_CONTEXT_MARKERS)
    has_browser_surface = matches_any_marker(lowered, BROWSER_SURFACE_MARKERS)

    if has_desktop_surface and (has_browser_surface or has_specific_browser_context):
        return True
    if has_specific_browser_context and has_browser_surface and is_execution_request(lowered):
        return True
    return False


def choose_actionable_agent(
    task_text: str,
    latest_screen_context: ScreenContextPayload | None,
) -> RouteAgentName:
    recommended = ""
    if latest_screen_context:
        recommended = str(latest_screen_context.get("recommended_agent") or "").strip().lower()
    if recommended in {"cua_cli", "cua_vision", "browser"}:
        return recommended

    lowered = (task_text or "").lower()
    if is_window_management_request(lowered):
        return "cua_vision"
    if matches_any_marker(lowered, BROWSER_EXECUTION_MARKERS):
        return "browser"
    if matches_any_marker(lowered, CLI_EXECUTION_MARKERS):
        return "cua_cli"
    if matches_any_marker(lowered, VISION_EXECUTION_MARKERS):
        return "cua_vision"
    return "cua_cli"


__all__ = [
    "BROWSER_EXECUTION_MARKERS",
    "BROWSER_SURFACE_MARKERS",
    "CLI_EXECUTION_MARKERS",
    "DESKTOP_SURFACE_MARKERS",
    "EXECUTION_INTENT_MARKERS",
    "SPECIFIC_BROWSER_CONTEXT_MARKERS",
    "VISION_EXECUTION_MARKERS",
    "WINDOW_MANAGEMENT_MARKERS",
    "choose_actionable_agent",
    "is_execution_request",
    "is_window_management_request",
    "requires_desktop_control_surface",
]
