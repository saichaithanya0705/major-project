"""Small deterministic connection commands and selected-session routing policy."""
import os
import re


def extension_mode() -> bool:
    return os.getenv("JARVIS_BROWSER_MODE", "managed").strip().lower() == "extension"


def control_command(text: str):
    value = " ".join(text.lower().strip().rstrip(".!?").split())
    commands = {"connect browser": "connect", "connect my browser": "connect",
                "disconnect browser": "disconnect", "disconnect my browser": "disconnect",
                "browser status": "status", "stop browser": "stop", "stop browser task": "stop"}
    if value in commands:
        return commands[value], None
    match = re.fullmatch(r"use browser tab (\d+)", value)
    return ("select", int(match.group(1))) if match else None


def native_browser_request(text: str) -> bool:
    value = text.lower()
    return bool(re.search(r"\b(minimi[sz]e|maximi[sz]e|restore|focus window|switch window|work profile|personal profile|specific profile|browser profile)\b", value)
                or ("profile" in value and re.search(r"\b(chrome|brave|comet|edge|browser)\b", value)))


def connected_session_request(text: str) -> bool:
    if not extension_mode() or native_browser_request(text):
        return False
    value = text.lower()
    if control_command(value):
        return True
    surface = re.search(r"\b(browser|tabs?|website|webpage|web page|forms?)\b|https?://", value)
    action = re.search(r"\b(open|use|fill|click|type|search|read|inspect|extract|compare|summari[sz]e|select|scroll|navigate|submit|find)\b", value)
    return bool(surface and action)
