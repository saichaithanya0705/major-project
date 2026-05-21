"""Typed routing guardrail helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from models.routing_payload_parser import (
    RouteAgentName,
    RoutePayload,
    ScreenContextPayload,
    copy_route_payload,
)

GuardrailRewriteReason = Literal[
    "browser_resume",
    "source_grounded_web_qa",
    "screen_context_to_actionable_agent",
    "execution_request_needs_actionable_agent",
    "browser_needs_desktop_control_surface",
]

BuildBrowserResumeRoute = Callable[[str], RoutePayload | None]
CleanText = Callable[[object, str, int | None], str]
ChooseActionableAgent = Callable[[str, ScreenContextPayload | None], RouteAgentName]
IsExecutionRequest = Callable[[str], bool]
IsWebQaRequest = Callable[[str], bool]
RequiresDesktopControlSurface = Callable[[str], bool]
RoutingTaskText = Callable[[RoutePayload], str]


@dataclass(frozen=True, slots=True)
class GuardrailApplication:
    route: RoutePayload
    rewritten_from: RoutePayload | None = None
    rewrite_reason: GuardrailRewriteReason | None = None

    @property
    def was_rewritten(self) -> bool:
        return self.rewritten_from is not None


def _route_payload_copy(route: RoutePayload) -> RoutePayload:
    return copy_route_payload(route, error_source="guardrail route copy")


def _rewritten(
    route: RoutePayload,
    *,
    rewritten_from: RoutePayload,
    reason: GuardrailRewriteReason,
) -> GuardrailApplication:
    return GuardrailApplication(
        route=_route_payload_copy(route),
        rewritten_from=_route_payload_copy(rewritten_from),
        rewrite_reason=reason,
    )


def _unchanged(route: RoutePayload) -> GuardrailApplication:
    return GuardrailApplication(route=_route_payload_copy(route))


def _resolve_policy_helpers() -> tuple[
    BuildBrowserResumeRoute,
    CleanText,
    ChooseActionableAgent,
    IsExecutionRequest,
    IsWebQaRequest,
    RequiresDesktopControlSurface,
    RoutingTaskText,
]:
    from models import routing_policy as policy
    from models import routing_question_policy as question_policy
    from models import routing_surface_policy as surface_policy

    return (
        policy.build_browser_resume_route,
        policy._clean_text,
        surface_policy.choose_actionable_agent,
        surface_policy.is_execution_request,
        question_policy.is_web_qa_request,
        surface_policy.requires_desktop_control_surface,
        policy._routing_task_text,
    )


def apply_routing_guardrails(
    *,
    user_prompt: str,
    routing_result: RoutePayload,
    latest_screen_context: ScreenContextPayload | None,
    build_browser_resume_route: BuildBrowserResumeRoute | None = None,
    clean_text: CleanText | None = None,
    choose_actionable_agent: ChooseActionableAgent | None = None,
    is_execution_request: IsExecutionRequest | None = None,
    is_web_qa_request: IsWebQaRequest | None = None,
    requires_desktop_control_surface: RequiresDesktopControlSurface | None = None,
    routing_task_text: RoutingTaskText | None = None,
) -> GuardrailApplication:
    if (
        build_browser_resume_route is None
        or clean_text is None
        or choose_actionable_agent is None
        or is_execution_request is None
        or is_web_qa_request is None
        or requires_desktop_control_surface is None
        or routing_task_text is None
    ):
        (
            default_resume_route,
            default_clean_text,
            default_choose_actionable_agent,
            default_is_execution_request,
            default_is_web_qa_request,
            default_requires_desktop_control_surface,
            default_routing_task_text,
        ) = _resolve_policy_helpers()
        build_browser_resume_route = build_browser_resume_route or default_resume_route
        clean_text = clean_text or default_clean_text
        choose_actionable_agent = choose_actionable_agent or default_choose_actionable_agent
        is_execution_request = is_execution_request or default_is_execution_request
        is_web_qa_request = is_web_qa_request or default_is_web_qa_request
        requires_desktop_control_surface = (
            requires_desktop_control_surface or default_requires_desktop_control_surface
        )
        routing_task_text = routing_task_text or default_routing_task_text

    original_route = _route_payload_copy(routing_result)
    agent = str(routing_result.get("agent") or "").strip().lower()
    execution_request = is_execution_request(user_prompt)

    resume_route = build_browser_resume_route(user_prompt)
    if resume_route:
        return _rewritten(
            resume_route,
            rewritten_from=original_route,
            reason="browser_resume",
        )

    if is_web_qa_request(user_prompt) and agent in {"direct", "browser"}:
        task_text = clean_text(user_prompt, "", max_len=420)
        print("[Router][Guardrail] Re-routing source-grounded Q&A request -> web_qa")
        return _rewritten(
            {
                "agent": "web_qa",
                "task": task_text,
            },
            rewritten_from=original_route,
            reason="source_grounded_web_qa",
        )

    if execution_request and agent == "screen_context" and latest_screen_context:
        recommended_agent = str(
            latest_screen_context.get("recommended_agent") or ""
        ).strip().lower()
        if recommended_agent in {"cua_cli", "cua_vision", "browser"}:
            task_text = clean_text(
                latest_screen_context.get("recommended_task"),
                "",
                max_len=420,
            ) or clean_text(user_prompt, "", max_len=420)
            print(
                "[Router][Guardrail] Promoting repeated screen_context to actionable agent: "
                f"{recommended_agent}"
            )
            return _rewritten(
                {
                    "agent": recommended_agent,
                    "task": task_text,
                },
                rewritten_from=original_route,
                reason="screen_context_to_actionable_agent",
            )

    if execution_request and agent == "jarvis":
        task_text = routing_task_text(routing_result)
        if not task_text:
            task_text = clean_text(user_prompt, "", max_len=420)
        actionable_agent = choose_actionable_agent(task_text, latest_screen_context)
        print(
            "[Router][Guardrail] Re-routing execution request away from jarvis -> "
            f"{actionable_agent}"
        )
        return _rewritten(
            {
                "agent": actionable_agent,
                "task": task_text,
            },
            rewritten_from=original_route,
            reason="execution_request_needs_actionable_agent",
        )

    if execution_request and agent == "browser":
        task_text = routing_task_text(routing_result) or clean_text(user_prompt, "", max_len=420)
        if requires_desktop_control_surface(task_text):
            print(
                "[Router][CapabilityGate] Browser route needs desktop/profile/window control -> "
                "cua_vision"
            )
            return _rewritten(
                {
                    "agent": "cua_vision",
                    "task": task_text,
                },
                rewritten_from=original_route,
                reason="browser_needs_desktop_control_surface",
            )

    return _unchanged(routing_result)


def apply_routing_guardrails_route(
    user_prompt: str,
    routing_result: RoutePayload,
    latest_screen_context: ScreenContextPayload | None,
    *,
    build_browser_resume_route: BuildBrowserResumeRoute | None = None,
    clean_text: CleanText | None = None,
    choose_actionable_agent: ChooseActionableAgent | None = None,
    is_execution_request: IsExecutionRequest | None = None,
    is_web_qa_request: IsWebQaRequest | None = None,
    requires_desktop_control_surface: RequiresDesktopControlSurface | None = None,
    routing_task_text: RoutingTaskText | None = None,
) -> RoutePayload:
    return apply_routing_guardrails(
        user_prompt=user_prompt,
        routing_result=routing_result,
        latest_screen_context=latest_screen_context,
        build_browser_resume_route=build_browser_resume_route,
        clean_text=clean_text,
        choose_actionable_agent=choose_actionable_agent,
        is_execution_request=is_execution_request,
        is_web_qa_request=is_web_qa_request,
        requires_desktop_control_surface=requires_desktop_control_surface,
        routing_task_text=routing_task_text,
    ).route


__all__ = [
    "GuardrailApplication",
    "GuardrailRewriteReason",
    "apply_routing_guardrails",
    "apply_routing_guardrails_route",
]
