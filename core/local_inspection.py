"""Recognize requests that need observations from the user's own machine."""

import re


def is_local_machine_state_request(text: str) -> bool:
    lowered = " ".join((text or "").lower().split())
    if re.search(r"\b(?:how (?:do|can|should) i|how to|tutorial|instructions|search the web)\b", lowered):
        return False
    device = re.search(r"\b(?:my|this)\s+(?:laptop|computer|pc|machine|system|device)\b", lowered)
    subject = re.search(r"\b(?:process(?:es)?|programs?|apps?|services?|cpu|ram|memory|disk|storage|battery|installed)\b", lowered)
    return bool(device and subject)


def is_local_process_inspection(text: str) -> bool:
    lowered = (text or "").lower()
    if not is_local_machine_state_request(lowered):
        return False
    if re.search(r"\b(?:kill|terminate|stop|close|restart|install|uninstall|delete|remove|disable|enable)\b", lowered):
        return False
    return bool(re.search(r"\bprocess(?:es)?\b|\b(?:programs?|apps?)\b.*\brunning\b|\brunning\b.*\b(?:programs?|apps?)\b", lowered))
