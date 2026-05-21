"""Runtime initialization boundary for GeminiModel."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable

from agents.jarvis.tools import JARVIS_TOOLS as _JARVIS_TOOLS
from models.function_calls import TOOL_CONFIG as _TOOL_CONFIG
from models.router_preflight import (
    build_default_model_runtime_config as _build_default_model_runtime_config,
)
from models.runtime_config import ModelRuntimeConfig


DEFAULT_SCREEN_JUDGE_MODEL = "gemini-3-flash-preview"
DEFAULT_ROUTER_WALL_TIMEOUT_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class GeminiModelContentConfigs:
    screen_judge_model: str
    jarvis_config: Any
    screen_judge_config: Any
    direct_answer_config: Any


def apply_model_runtime_config(
    model: Any,
    runtime_config: ModelRuntimeConfig,
    *,
    router_wall_timeout_grace_seconds: float = DEFAULT_ROUTER_WALL_TIMEOUT_GRACE_SECONDS,
) -> None:
    for runtime_field in fields(ModelRuntimeConfig):
        setattr(model, runtime_field.name, getattr(runtime_config, runtime_field.name))
    model.router_wall_timeout_grace_seconds = float(router_wall_timeout_grace_seconds)


def build_gemini_model_content_configs(
    *,
    types_module: Any,
    jarvis_thinking_budget: int,
    jarvis_tools: list[dict[str, Any]],
    tool_config: Any,
    screen_judge_model: str = DEFAULT_SCREEN_JUDGE_MODEL,
) -> GeminiModelContentConfigs:
    return GeminiModelContentConfigs(
        screen_judge_model=screen_judge_model,
        jarvis_config=types_module.GenerateContentConfig(
            temperature=1.2,
            top_p=0.95,
            top_k=64,
            max_output_tokens=3000,
            thinking_config=types_module.ThinkingConfig(
                thinking_budget=jarvis_thinking_budget
            ),
            tools=jarvis_tools,
            tool_config=tool_config,
        ),
        screen_judge_config=types_module.GenerateContentConfig(
            temperature=0.2,
            top_p=0.9,
            top_k=40,
            max_output_tokens=1200,
            response_mime_type="application/json",
        ),
        direct_answer_config=types_module.GenerateContentConfig(
            temperature=0.4,
            top_p=0.95,
            top_k=40,
            max_output_tokens=1800,
        ),
    )


def initialize_gemini_model_runtime(
    model: Any,
    *,
    rapid_response_model: str,
    types_module: Any,
    build_default_model_runtime_config: Callable[[str], ModelRuntimeConfig] = _build_default_model_runtime_config,
    jarvis_tools: list[dict[str, Any]] = _JARVIS_TOOLS,
    tool_config: Any = _TOOL_CONFIG,
) -> None:
    runtime_config = build_default_model_runtime_config(rapid_response_model)
    apply_model_runtime_config(model, runtime_config)
    content_configs = build_gemini_model_content_configs(
        types_module=types_module,
        jarvis_thinking_budget=model.jarvis_thinking_budget,
        jarvis_tools=jarvis_tools,
        tool_config=tool_config,
    )
    model.screen_judge_model = content_configs.screen_judge_model
    model.jarvis_config = content_configs.jarvis_config
    model.screen_judge_config = content_configs.screen_judge_config
    model.direct_answer_config = content_configs.direct_answer_config
