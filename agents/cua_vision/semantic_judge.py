"""
Provider-backed semantic completion judge for CUA Vision.

The criticizer calls this only when the planner claims completion. It asks a
separate model role to decide whether the observed screen state independently
satisfies the user's original task.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from agents.cua_vision.contracts import ActionResult, ComputerAction
from agents.cua_vision.model_policy import CuaModelPolicy, ModelPolicyContext, ModelRole
from agents.cua_vision.provider_runtime import (
    format_provider_failure,
    iter_cua_vision_providers,
    provider_failure_summary,
    screenshot_base64_to_data_url,
    trim_text,
)
from agents.cua_vision.session_state import CuaSession
from models.router_backends import call_openrouter_text_sync
from models.routing_payload_parser import parse_json_object
from models.text_normalization import clean_text


CRITIC_SYSTEM_PROMPT = """
You are an independent computer-use completion critic.
Judge only whether the user's original desktop task is complete in the current observed screen state.
Do not trust the planner's completion claim by itself.
Return only a JSON object with complete, should_continue, confidence, reason, and next_hint.
""".strip()


class ProviderSemanticJudge:
    """Use a strong vision-capable provider to verify completion claims."""

    def __init__(
        self,
        *,
        model_policy: CuaModelPolicy | None = None,
        max_tokens: int = 700,
        temperature: float = 0.0,
    ):
        self.model_policy = model_policy or CuaModelPolicy.from_env()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_model_name: str | None = None
        self.last_provider_label: str | None = None

    async def __call__(
        self,
        *,
        task: str,
        action: ComputerAction,
        result: ActionResult,
        session: CuaSession | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        purpose = self.model_policy.provider_purpose(
            ModelRole.CRITIC,
            ModelPolicyContext(action=action, completion_claim=True),
        )
        user_prompt = _build_critic_prompt(task, action, result, session, prompt)
        image_data_url = _result_image_data_url(result, session)

        failures: list[str] = []
        for provider in iter_cua_vision_providers(purpose):
            for model_name in provider.models:
                try:
                    text = await asyncio.to_thread(
                        call_openrouter_text_sync,
                        openrouter_api_key=provider.api_key,
                        openrouter_url=provider.url,
                        openrouter_site_url=provider.site_url,
                        openrouter_site_name=provider.site_name,
                        openrouter_timeout_seconds=provider.timeout_seconds,
                        model_name=model_name,
                        system_prompt=CRITIC_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        clean_text=clean_text,
                        response_format={"type": "json_object"},
                        image_data_url=image_data_url,
                    )
                    payload = parse_json_object(text)
                    verdict = _normalize_verdict_payload(payload)
                    self.last_model_name = model_name
                    self.last_provider_label = provider.label
                    return verdict
                except Exception as exc:
                    failures.append(
                        format_provider_failure(
                            provider=provider,
                            model_name=model_name,
                            exc=exc,
                            max_len=280,
                        )
                    )

        return {
            "complete": False,
            "should_continue": True,
            "confidence": 0.2,
            "reason": (
                "Completion could not be independently verified by the semantic critic. "
                + provider_failure_summary(
                    failures,
                    max_items=3,
                    empty_message="No critic provider is configured.",
                )
            ),
            "next_hint": "Re-observe the screen and provide concrete goal-state evidence.",
        }


def _build_critic_prompt(
    task: str,
    action: ComputerAction,
    result: ActionResult,
    session: CuaSession | None,
    prompt: str | None,
) -> str:
    after = result.after or (session.last_trusted_observation if session else None)
    sections = [
        prompt or "",
        f"User goal: {task}",
        f"Planner completion message: {action.text or ''}",
        f"Action result: executed={result.executed}, message={result.message}",
        f"Result metrics: {dict(result.metrics or {})}",
    ]
    if after is not None:
        sections.extend(
            [
                f"Current active window: {after.active_window_title or 'Unknown'}",
                f"Capture context: {after.capture_context}",
                f"Accessibility capabilities: {after.capabilities}",
                f"Accessibility element count: {len(after.elements)}",
            ]
        )
        if after.accessibility_tree:
            sections.append(f"Accessibility tree:\n{trim_text(after.accessibility_tree, 2400)}")
    if session is not None and session.warnings:
        sections.append(f"Recent controller warnings: {session.warnings[-3:]}")
    if session is not None and session.last_critic is not None:
        sections.append(f"Previous critic: {asdict(session.last_critic)}")
    return "\n\n".join(section for section in sections if section)


def _normalize_verdict_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    complete = bool(payload.get("complete"))
    should_continue = bool(payload.get("should_continue"))
    if complete:
        should_continue = False
    confidence = _clamp_float(payload.get("confidence", 0.0))
    reason = clean_text(payload.get("reason"), "", 700)
    next_hint_value = payload.get("next_hint")
    return {
        "complete": complete,
        "should_continue": should_continue,
        "confidence": confidence,
        "reason": reason or "Semantic critic did not provide a reason.",
        "next_hint": clean_text(next_hint_value, "", 420) if next_hint_value is not None else None,
    }


def _result_image_data_url(result: ActionResult, session: CuaSession | None) -> str | None:
    observation = result.after or (session.last_trusted_observation if session else None)
    raw = observation.screenshot_png_base64 if observation else None
    return screenshot_base64_to_data_url(raw)


def _clamp_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
