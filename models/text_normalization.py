"""Shared text normalization helpers for model and router runtimes."""

from __future__ import annotations

import re
from typing import Any


def clean_text(value: Any, fallback: str, max_len: int | None = 1400) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    if max_len is not None and len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def format_direct_response_text(
    value: Any,
    fallback: str = "Task completed.",
    max_len: int | None = None,
) -> str:
    if value is None:
        return fallback

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return fallback
    if max_len is not None and len(text) > max_len:
        return f"{text[:max_len - 3].rstrip()}..."
    return text


__all__ = [
    "clean_text",
    "format_direct_response_text",
]
