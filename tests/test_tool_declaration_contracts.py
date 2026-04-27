"""
Contract checks for function-calling tool declarations and implementations.

Usage:
    python tests/test_tool_declaration_contracts.py
"""

import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from agents.cua_vision.tool_declarations import (
    VISION_DECLARED_TOOL_NAMES,
    VISION_FUNCTION_DECLARATIONS,
)
from agents.cua_vision.tools import VISION_TOOL_MAP, VISION_TOOLS
from agents.jarvis.tool_declarations import (
    JARVIS_DECLARED_TOOL_NAMES,
    JARVIS_FUNCTION_DECLARATIONS,
)
from agents.jarvis.tools import JARVIS_TOOL_MAP, JARVIS_TOOLS


def _assert_names_match(declarations: list[dict], names: tuple[str, ...], label: str) -> None:
    extracted = tuple(
        declaration.get("name", "").strip()
        for declaration in declarations
    )
    assert extracted == names, f"{label} declaration names do not match exported name contract."
    assert len(set(extracted)) == len(extracted), f"{label} declaration names must be unique."


def _assert_implemented(names: tuple[str, ...], tool_map: dict, label: str) -> None:
    missing = [name for name in names if name not in tool_map]
    assert not missing, f"{label} declarations missing implementations: {missing}"
    non_callable = [name for name in names if not callable(tool_map.get(name))]
    assert not non_callable, f"{label} tool map has non-callable entries: {non_callable}"


def run_checks() -> None:
    _assert_names_match(VISION_FUNCTION_DECLARATIONS, VISION_DECLARED_TOOL_NAMES, "Vision")
    _assert_names_match(JARVIS_FUNCTION_DECLARATIONS, JARVIS_DECLARED_TOOL_NAMES, "JARVIS")

    _assert_implemented(VISION_DECLARED_TOOL_NAMES, VISION_TOOL_MAP, "Vision")
    _assert_implemented(JARVIS_DECLARED_TOOL_NAMES, JARVIS_TOOL_MAP, "JARVIS")

    assert len(VISION_TOOLS) == 1, "Vision should expose exactly one function-calling tool bundle."
    assert len(JARVIS_TOOLS) == 1, "JARVIS should expose exactly one function-calling tool bundle."
    assert VISION_TOOLS[0].function_declarations == VISION_FUNCTION_DECLARATIONS
    assert JARVIS_TOOLS[0].function_declarations == JARVIS_FUNCTION_DECLARATIONS


if __name__ == "__main__":
    run_checks()
    print("[test_tool_declaration_contracts] All checks passed.")
