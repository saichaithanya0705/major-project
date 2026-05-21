"""Shared typed contracts for the rapid orchestrator runtime surface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Literal, Protocol, TypeAlias, TypedDict

from models.rapid_step_payloads import (
    RapidSourceRecord,
    RapidStepArtifactCollection,
    RapidStepMetadataPayload,
    RapidTaskExecutionContextPayload,
    RapidToolCallRecord,
)
from models.routing_payload_parser import (
    BlockedStepSignature,
    RouteAgentName,
    RoutePayload,
    RoutingResult,
    ScreenContextPayload,
)

RapidStepAgentName = RouteAgentName | Literal["router_guard"]


class RapidAgentStepResult(TypedDict, total=False):
    agent: RapidStepAgentName
    task: str
    success: bool
    complete: bool
    message: str
    source: str
    metadata: RapidStepMetadataPayload
    tool_calls: list[RapidToolCallRecord]
    output_file_path: str
    sources: list[RapidSourceRecord]
    artifacts: RapidStepArtifactCollection
    orchestrator_context: RapidTaskExecutionContextPayload

RapidRoutingResult: TypeAlias = RoutingResult
RapidRouteResult: TypeAlias = RoutePayload
RapidHistoryAppender: TypeAlias = Callable[[str, str, str], None]
RapidHistoryFormatter: TypeAlias = Callable[[], str]
RapidStepRunner: TypeAlias = Callable[..., Awaitable[RapidAgentStepResult]]
RapidRoutingResultEnricher: TypeAlias = Callable[[RoutePayload, str], RoutePayload]
RapidStepContextRecorder: TypeAlias = Callable[[RapidAgentStepResult], None]
RapidScreenshotGetter: TypeAlias = Callable[[], Any]
RapidScreenshotPreparer: TypeAlias = Callable[..., Awaitable[Any]]
RapidTextCleaner: TypeAlias = Callable[[object, str, int | None], str]
RapidRoutingGuardrails: TypeAlias = Callable[[str, RoutePayload, ScreenContextPayload | None], RoutePayload]
RapidRoutingTaskText: TypeAlias = Callable[[RoutePayload], str]
RapidRoutingSignature: TypeAlias = Callable[[RoutePayload], BlockedStepSignature]
RapidRepeatPredicate: TypeAlias = Callable[[str], bool]
RapidDirectQaPredicate: TypeAlias = Callable[[str], bool]
RapidDirectAnswerer: TypeAlias = Callable[..., Awaitable[str]]
RapidScreenContextMessage: TypeAlias = Callable[[ScreenContextPayload], str]
RapidAssistantLogger: TypeAlias = Callable[..., None]
RapidToolMap: TypeAlias = dict[str, Callable[..., Any]]


class RapidChainFormatter(Protocol):
    def __call__(
        self,
        *,
        user_prompt: str,
        chain_steps: list[RapidAgentStepResult],
        max_steps: int,
        latest_screen_context: ScreenContextPayload | None,
        blocked_step_signatures: set[BlockedStepSignature] | None = None,
    ) -> str: ...


class RapidDirectResponseFinalizer(Protocol):
    def __call__(
        self,
        *,
        user_prompt: str,
        chain_steps: Sequence[RapidAgentStepResult],
        text: object,
    ) -> str: ...


class RapidModel(Protocol):
    async def route_request(self, prompt: str) -> RapidRoutingResult: ...

    async def answer_direct_request(
        self,
        *,
        user_prompt: str,
        history_block: str = "",
    ) -> str: ...

    async def generate_screen_context(
        self,
        user_request: str,
        image: Any = None,
        focus: str = "",
    ) -> ScreenContextPayload: ...


RapidModelFactory: TypeAlias = Callable[[str, str], RapidModel]


class RapidDirectQaFlowDeps(Protocol):
    append_rapid_history: RapidHistoryAppender
    answer_direct_request: RapidDirectAnswerer
    clean_text: RapidTextCleaner
    finalize_direct_response_text: RapidDirectResponseFinalizer
    format_rapid_history_for_prompt: RapidHistoryFormatter
    log_assistant_event: RapidAssistantLogger
    router_tool_map: RapidToolMap


class RapidPlanDeps(Protocol):
    run_routed_agent_step: RapidStepRunner
    record_step_context: RapidStepContextRecorder
    prepare_vision_screenshot: RapidScreenshotPreparer
    finalize_direct_response_text: RapidDirectResponseFinalizer
    append_rapid_history: RapidHistoryAppender
    clean_text: RapidTextCleaner
    log_assistant_event: RapidAssistantLogger
    router_tool_map: RapidToolMap


class RapidStepExecutionDeps(Protocol):
    append_rapid_history: RapidHistoryAppender
    clean_text: RapidTextCleaner
    finalize_direct_response_text: RapidDirectResponseFinalizer
    log_assistant_event: RapidAssistantLogger
    prepare_vision_screenshot: RapidScreenshotPreparer
    record_step_context: RapidStepContextRecorder
    router_tool_map: RapidToolMap
    routing_task_text: RapidRoutingTaskText
    run_routed_agent_step: RapidStepRunner
    screen_context_message: RapidScreenContextMessage


__all__ = [
    "RapidAgentStepResult",
    "RapidAssistantLogger",
    "RapidChainFormatter",
    "RapidDirectAnswerer",
    "RapidDirectQaFlowDeps",
    "RapidDirectQaPredicate",
    "RapidDirectResponseFinalizer",
    "RapidHistoryAppender",
    "RapidHistoryFormatter",
    "RapidModel",
    "RapidModelFactory",
    "RapidPlanDeps",
    "RapidRepeatPredicate",
    "RapidRouteResult",
    "RapidRoutingGuardrails",
    "RapidRoutingResult",
    "RapidRoutingResultEnricher",
    "RapidRoutingSignature",
    "RapidStepAgentName",
    "RapidRoutingTaskText",
    "RapidScreenContextMessage",
    "RapidScreenshotGetter",
    "RapidScreenshotPreparer",
    "RapidStepExecutionDeps",
    "RapidStepContextRecorder",
    "RapidStepRunner",
    "RapidTextCleaner",
    "RapidToolMap",
]
