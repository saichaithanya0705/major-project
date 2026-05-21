"""Prompt-state formatting for rapid chained routing."""

from __future__ import annotations

from models.rapid_orchestrator_contracts import RapidAgentStepResult
from models.routing_payload_parser import BlockedStepSignature, ScreenContextPayload
from models.text_normalization import clean_text


def format_blocked_step_signatures_for_prompt(
    blocked_step_signatures: set[BlockedStepSignature] | None,
) -> str:
    if not blocked_step_signatures:
        return ""

    lines = []
    for agent, task in sorted(blocked_step_signatures):
        lines.append(f"- agent={agent} task={task}")

    return (
        "\n# Loop Guard\n"
        "The following delegated steps already repeated in this turn and are now blocked.\n"
        "Do NOT choose them again unless the user explicitly asked to repeat the exact same action.\n"
        "Choose a materially different next step, request `screen_context` if verification is needed, "
        "or call `direct_response` if the overall task is complete.\n"
        + "\n".join(lines)
        + "\n"
    )


def format_chain_state_for_prompt(
    *,
    user_prompt: str,
    chain_steps: list[RapidAgentStepResult],
    max_steps: int,
    latest_screen_context: ScreenContextPayload | None,
    blocked_step_signatures: set[BlockedStepSignature] | None = None,
) -> str:
    context_lines = ""
    if latest_screen_context:
        summary = clean_text(latest_screen_context.get("summary"), "", max_len=260)
        repo_url = clean_text(latest_screen_context.get("repo_url"), "", max_len=220)
        local_url = clean_text(latest_screen_context.get("local_url"), "", max_len=220)
        recommended_agent = clean_text(latest_screen_context.get("recommended_agent"), "", max_len=40)
        recommended_task = clean_text(latest_screen_context.get("recommended_task"), "", max_len=240)
        hints = clean_text(latest_screen_context.get("hints"), "", max_len=240)

        rows = []
        if summary:
            rows.append(f"- Summary: {summary}")
        if repo_url:
            rows.append(f"- Repo URL: {repo_url}")
        if local_url:
            rows.append(f"- Local URL: {local_url}")
        if recommended_agent:
            rows.append(f"- Recommended agent: {recommended_agent}")
        if recommended_task:
            rows.append(f"- Recommended next task: {recommended_task}")
        if hints:
            rows.append(f"- Extra hints: {hints}")
        if rows:
            context_lines = "\n# Latest Screen Context\n" + "\n".join(rows) + "\n"
    loop_guard_lines = format_blocked_step_signatures_for_prompt(blocked_step_signatures)

    if not chain_steps:
        return (
            "\n# Multi-Agent Chaining Mode\n"
            "This task may require multiple delegated tools.\n"
            "Pick the best first tool call, and treat this as step 1 of a multi-step execution.\n"
            "Before choosing, compare agent capabilities against the underlying data source and required action.\n"
            "Prefer CLI for programmatically inspectable local state; use CUA vision only for intrinsic visual UI interaction.\n"
            "If the request depends on currently visible UI context, call `request_screen_context` first.\n"
            "For action/execution requests ('do X for me', clone/run/open/click/type), do NOT use `invoke_jarvis`.\n"
            "Use `invoke_jarvis` only for explanation/annotation requests.\n"
            "When the overall user request is fully complete, call `direct_response`.\n"
            + context_lines
            + loop_guard_lines
            + f"Never exceed {max_steps} delegated steps.\n"
        )

    lines = []
    for idx, step in enumerate(chain_steps, start=1):
        complete = step.get("complete", True) is not False
        lines.append(
            f"{idx}. agent={step.get('agent')} success={step.get('success')} complete={complete} "
            f"task={step.get('task')} outcome={step.get('message')}"
        )

    return (
        "\n# Multi-Agent Chaining Mode\n"
        "Continue from prior delegated work. Choose the single best next tool call.\n"
        "If the original request is complete, call `direct_response` now.\n"
        "If any recent delegated step has complete=False, do NOT call `direct_response`; choose a different agent or verification step to finish the remaining work.\n"
        "Before choosing, compare agent capabilities against the underlying data source and required action.\n"
        "Prefer CLI for programmatically inspectable local state; use CUA vision only for intrinsic visual UI interaction.\n"
        "Avoid repeating the exact same delegated step unless something materially changed.\n"
        "If you still need visible context, call `request_screen_context` again.\n"
        "For action/execution requests, do NOT use `invoke_jarvis`.\n"
        f"Original request: {user_prompt}\n"
        f"Completed delegated steps ({len(chain_steps)}/{max_steps}):\n"
        + "\n".join(lines)
        + context_lines
        + loop_guard_lines
        + "\n"
    )


__all__ = [
    "format_blocked_step_signatures_for_prompt",
    "format_chain_state_for_prompt",
]
