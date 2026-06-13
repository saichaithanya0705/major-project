"""
Typed contracts for router backend parsing boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NormalizedToolCall:
    name: str
    arguments: JsonObject

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "arguments": dict(self.arguments),
        }
