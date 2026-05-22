"""
Provider-backed CUA planner for the typed controller loop.

The planner is deliberately narrow: it turns one screen observation plus the
current session state into one normalized model tool call. Grounding, execution,
verification, and completion remain owned by the controller pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Any

from agents.cua_vision.contracts import ScreenObservation
from agents.cua_vision.errors import OpenRouterFallbackError
from agents.cua_vision.model_policy import CuaModelPolicy, ModelPolicyContext, ModelRole
from agents.cua_vision.prompts import VISION_AGENT_SYSTEM_PROMPT
from agents.cua_vision.provider_runtime import (
    format_provider_failure,
    iter_cua_vision_providers,
    observation_image_data_url,
    provider_failure_summary,
    trim_text,
)
from agents.cua_vision.session_state import CuaSession
from agents.cua_vision.tool_declarations import VISION_FUNCTION_DECLARATIONS
from models.router_backends import call_openrouter_tool_sync
from models.text_normalization import clean_text


POSITIONING_TOOLS = {"go_to_element", "crop_and_search"}
CLICK_TOOL_TO_TYPE = {
    "click_left_click": "left click",
    "click_double_left_click": "double left click",
    "click_right_click": "right click",
}


class ProviderVisionPlanner:
    """Plan the next CUA action using NVIDIA first, then OpenRouter."""

    def __init__(
        self,
        *,
        model_policy: CuaModelPolicy | None = None,
        max_tokens: int = 1400,
        temperature: float = 0.1,
    ):
        self.model_policy = model_policy or CuaModelPolicy.from_env()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_model_name: str | None = None
        self.last_provider_label: str | None = None

    async def next_action(
        self,
        task: str,
        observation: ScreenObservation,
        session: CuaSession,
    ) -> dict[str, Any]:
        purpose = self.model_policy.provider_purpose(
            ModelRole.PLANNER,
            ModelPolicyContext(
                completion_claim=bool(
                    session.last_critic and not session.last_critic.complete
                ),
                unclear_screen=not bool(observation.screenshot_png_base64),
            ),
        )
        prompt = _build_planner_prompt(task, observation, session)
        image_data_url = observation_image_data_url(observation)

        failures: list[str] = []
        for provider in iter_cua_vision_providers(purpose):
            for model_name in provider.models:
                try:
                    result = await asyncio.to_thread(
                        call_openrouter_tool_sync,
                        openrouter_api_key=provider.api_key,
                        openrouter_url=provider.url,
                        openrouter_site_url=provider.site_url,
                        openrouter_site_name=provider.site_name,
                        openrouter_timeout_seconds=provider.timeout_seconds,
                        model_name=model_name,
                        system_prompt=VISION_AGENT_SYSTEM_PROMPT,
                        user_prompt=prompt,
                        function_declarations=VISION_FUNCTION_DECLARATIONS,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        clean_text=clean_text,
                        image_data_url=image_data_url,
                    )
                    action = _select_single_action(result.get("tool_calls") or [])
                    self.last_model_name = model_name
                    self.last_provider_label = provider.label
                    return action
                except Exception as exc:
                    failures.append(
                        format_provider_failure(
                            provider=provider,
                            model_name=model_name,
                            exc=exc,
                            max_len=360,
                        )
                    )

        detail = provider_failure_summary(
            failures,
            max_items=4,
            empty_message="No CUA vision provider is configured.",
        )
        raise OpenRouterFallbackError(f"No configured CUA planner provider responded. {detail}")


def _build_planner_prompt(
    task: str,
    observation: ScreenObservation,
    session: CuaSession,
) -> str:
    parts = [
        f"User goal: {task}",
        f"Active window: {observation.active_window_title or 'Unknown'}",
        f"Action count so far: {session.action_count}/{session.max_actions}",
        "",
        "Return exactly one tool call for the next desktop action.",
        "Prefer click_target with a visible bounding box for UI clicks.",
        "Call task_is_complete only when the current screen itself proves the goal is done.",
        "Call task_is_complete with a concise explanation if the goal is impossible or unavailable.",
    ]

    if session.warnings:
        parts.extend(["", "Recent controller warnings:", *session.warnings[-3:]])
    if session.last_critic is not None:
        parts.extend(
            [
                "",
                "Previous critic verdict:",
                f"- complete: {session.last_critic.complete}",
                f"- should_continue: {session.last_critic.should_continue}",
                f"- reason: {session.last_critic.reason}",
                f"- next_hint: {session.last_critic.next_hint or ''}",
            ]
        )
    if observation.accessibility_tree:
        parts.extend(["", "Accessibility snapshot:", trim_text(observation.accessibility_tree, 2400)])
    elif observation.capabilities:
        parts.extend(["", f"Accessibility capabilities: {observation.capabilities}"])
    if observation.capture_context:
        parts.extend(["", f"Capture context: {observation.capture_context}"])

    return "\n".join(parts)


def _select_single_action(tool_calls: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    calls = [
        {"name": str(call.get("name") or "").strip(), "arguments": dict(call.get("arguments") or {})}
        for call in tool_calls
        if isinstance(call, Mapping) and str(call.get("name") or "").strip()
    ]
    if not calls:
        raise RuntimeError("Provider returned no executable tool call.")

    if len(calls) >= 2 and calls[0]["name"] in POSITIONING_TOOLS and calls[1]["name"] in CLICK_TOOL_TO_TYPE:
        args = dict(calls[0]["arguments"])
        args["type_of_click"] = CLICK_TOOL_TO_TYPE[calls[1]["name"]]
        return {"name": "click_target", "arguments": args}

    return calls[0]
