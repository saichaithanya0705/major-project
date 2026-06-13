"""
Shared JSON-object coercion helpers for router and orchestrator payload seams.
"""

from __future__ import annotations

from models.router_backend_types import JsonObject, JsonValue

_INVALID = object()


def _coerce_json_value(value: object) -> JsonValue | object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        items: list[JsonValue] = []
        for item in value:
            normalized = _coerce_json_value(item)
            if normalized is _INVALID:
                return _INVALID
            items.append(normalized)
        return items
    if isinstance(value, dict):
        normalized_dict: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return _INVALID
            normalized = _coerce_json_value(item)
            if normalized is _INVALID:
                return _INVALID
            normalized_dict[key] = normalized
        return normalized_dict
    return _INVALID


def coerce_json_object(value: object) -> JsonObject | None:
    normalized = _coerce_json_value(value)
    if normalized is _INVALID or not isinstance(normalized, dict):
        return None
    return normalized


__all__ = ["coerce_json_object"]
