"""
Primary single-call execution engine for CUA Vision.

This module handles per-step model calls where the model returns both the next
action and user-visible status text in one response.
"""

import asyncio
import json
import os
import time
from types import SimpleNamespace

from integrations.audio import tts_speak
from agents.cua_vision.action_policy import normalize_click_type
from agents.cua_vision.action_guard import (
    ClickLoopState,
    action_signature as compute_action_signature,
    extract_position_bbox_args,
    infer_click_type,
    register_action_and_detect_click_loop,
    resolve_click_type,
    task_expects_repeated_actions,
)
from agents.cua_vision.interaction_policy import (
    build_fallback_context,
    default_status_text,
    describe_action_for_feedback,
    resolve_target_description,
)
from agents.cua_vision.contracts import (
    ActionResult,
    ActionType,
    ComputerAction,
    CriticVerdict,
    CuaRunResult,
    TargetKind,
    TargetRef,
)
from agents.cua_vision.criticizer import CuaCriticizer
from agents.cua_vision.model_policy import CuaModelPolicy, ModelPolicyContext, ModelRole
from agents.cua_vision.prompts import (
    VISION_AGENT_SYSTEM_PROMPT,
    WINDOWS_APP_LAUNCH_WORKFLOW,
)
from agents.cua_vision.image import image_change, reset_image_state
from agents.cua_vision.runtime_state import (
    get_last_capture_context as _get_last_capture_context,
    get_last_capture_image as _get_last_capture_image,
    set_last_capture_context as _set_last_capture_context,
    set_last_capture_image as _set_last_capture_image,
)
from agents.cua_vision.screen_context import (
    ScreenFrame,
    capture_active_window_frame,
    register_provided_screenshot_frame,
)
from agents.cua_vision.status_presenter import StatusPresenter
from agents.cua_vision.visual_feedback import (
    crop_target_region as compute_target_region_crop,
    image_similarity as compute_image_similarity,
    resolve_target_bbox_for_verification,
    visual_similarity_metrics as compute_visual_similarity_metrics,
)
from agents.cua_vision.tools import (
    capture_active_window,
    get_active_window_title,
    get_memory,
    execute_tool_call,
    run_legacy_locator_fallback,
    is_stop_requested,
    save_go_to_element_debug_snapshot,
)
from agents.cua_vision.tool_declarations import VISION_FUNCTION_DECLARATIONS
from models.openrouter_fallback import (
    get_nvidia_api_key,
    get_nvidia_chat_url,
    get_nvidia_models,
    get_nvidia_timeout_seconds,
    get_openrouter_api_key,
    get_openrouter_chat_url,
    get_openrouter_models,
    get_openrouter_site_name,
    get_openrouter_site_url,
    get_openrouter_timeout_seconds,
    image_to_data_url,
    tool_result_to_vision_response,
)
from models.router_backends import call_openrouter_tool_sync
from models.routing_policy import _clean_text

CLICK_TOOL_TO_TYPE = {
    "click_left_click": "left click",
    "click_double_left_click": "double left click",
    "click_right_click": "right click",
}
CLICK_TYPE_TO_TOOL = {
    "left click": "click_left_click",
    "double left click": "click_double_left_click",
    "right click": "click_right_click",
}
POSITIONING_TOOLS = {"go_to_element", "crop_and_search"}
CLICK_TARGET_TOOL = "click_target"
SCREEN_FRAME_TOOLS = {CLICK_TARGET_TOOL, "go_to_element", "crop_and_search"}
AUTO_CLICK_AFTER_REPEAT_POSITIONING_THRESHOLD = 2
POSITION_BUCKET_SIZE = 40
CLICK_CYCLE_LOOP_STOP_THRESHOLD = 4
DEFAULT_ACTION_SETTLE_TIMEOUT_SECONDS = 2.0
DEFAULT_ACTION_SETTLE_POLL_INTERVAL_SECONDS = 0.2
POST_BATCH_DELAY_SECONDS = 0.05
VISUAL_NOOP_SIMILARITY_THRESHOLD = 0.9995
TARGET_REGION_NOOP_SIMILARITY_THRESHOLD = 0.995
REPEATED_VISUAL_NOOP_FALLBACK_THRESHOLD = 2
REPEATED_NON_CLICK_NOOP_STOP_THRESHOLD = 2
NON_CLICK_NOOP_STOP_TOOLS = {
    "type_string",
    "press_ctrl_hotkey",
    "press_alt_hotkey",
    "press_key_for_duration",
}
MAX_RUNTIME_OBSERVATIONS = 4
TARGET_REGION_PADDING_PX = 24
TARGET_REGION_MIN_SIDE_PX = 48
DEFAULT_MAX_STEPS = 12
DEFAULT_MAX_DURATION_SECONDS = 90.0
DEFAULT_MAX_PROVIDER_CALLS = 12
VISUAL_EFFECT_VERIFICATION_TOOLS = {
    "click_target",
    "click_left_click",
    "click_double_left_click",
    "click_right_click",
    "type_string",
    "press_ctrl_hotkey",
    "press_alt_hotkey",
    "press_key_for_duration",
}

THINKING_MESSAGES = [
    "Analyzing screen...",
    "Reviewing visible UI elements...",
    "Planning the next action...",
    "Checking the safest interaction...",
]

TOOL_METADATA_KEYS = {"status_text", "target_description"}


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 1000) -> int:
    try:
        value = int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def _env_float(name: str, default: float, *, minimum: float = 1.0, maximum: float = 3600.0) -> float:
    try:
        value = float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


class DebugStopAfterFirstGoTo(RuntimeError):
    """Raised when debug mode intentionally stops after first go_to_element."""


class RepeatedNoopActionError(RuntimeError):
    """Raised when a repeated non-click action is visibly doing nothing."""


class OpenRouterFallbackError(RuntimeError):
    """Raised when no configured vision provider responds."""


class SingleCallVisionEngine:
    """Runs the main task loop for VisionAgent using one model call per step."""

    def __init__(self, agent):
        self.agent = agent
        self.consecutive_failures = 0
        self.max_failures_before_fallback = 3
        self.last_action_signature = None
        self.repeated_action_count = 0
        self.last_click_context = None
        self.last_target_description = None
        self._click_loop_state = ClickLoopState()
        self._status_presenter = StatusPresenter(source="cua_vision")
        self._thinking_index = 0
        self._debug_snapshot_taken = False
        self._action_settle_timeout_seconds = DEFAULT_ACTION_SETTLE_TIMEOUT_SECONDS
        self._action_settle_poll_interval_seconds = DEFAULT_ACTION_SETTLE_POLL_INTERVAL_SECONDS
        self._runtime_observations: list[str] = []
        self._last_visual_noop_signature = None
        self._repeated_visual_noop_count = 0
        self._last_position_bbox_args = None
        self._executed_action_count = 0
        self._last_action_had_visible_effect: bool | None = None
        self._criticizer = CuaCriticizer()
        self._model_policy = CuaModelPolicy.from_env()
        self._last_completion_verdict = None
        self._terminal_incomplete_verdict = None
        self._rejected_completion_count = 0
        self._current_screen_frame: ScreenFrame | None = None
        self._max_steps = _env_int("CUA_VISION_MAX_STEPS", DEFAULT_MAX_STEPS, minimum=1, maximum=100)
        self._max_duration_seconds = _env_float(
            "CUA_VISION_MAX_DURATION_SECONDS",
            DEFAULT_MAX_DURATION_SECONDS,
            minimum=5.0,
            maximum=1800.0,
        )
        self._max_provider_calls = _env_int(
            "CUA_VISION_MAX_PROVIDER_CALLS",
            DEFAULT_MAX_PROVIDER_CALLS,
            minimum=1,
            maximum=100,
        )
        self._provider_call_count = 0
        self._run_deadline_monotonic: float | None = None
        self.debug_stop_after_first_goto = _is_truthy_env(
            os.getenv("CUA_VISION_DEBUG_STOP_AFTER_FIRST_GOTO", "0")
        )

    async def run(self, task: str, initial_screenshot=None):
        """Execute the task until completion or unrecoverable failure."""
        started_at = time.monotonic()
        self._run_deadline_monotonic = started_at + self._max_duration_seconds
        step_count = 0
        next_step_screenshot = initial_screenshot
        try:
            self._raise_if_stopped()
            while True:
                self._raise_if_stopped()
                if step_count >= self._max_steps:
                    raise RuntimeError(
                        f"CUA Vision step budget exceeded ({self._max_steps} steps)."
                    )
                if not self._has_remaining_run_budget():
                    raise RuntimeError(
                        f"CUA Vision time budget exceeded ({self._max_duration_seconds:.1f}s)."
                    )
                step_count += 1
                if next_step_screenshot is None:
                    response = await self._generate_step_response(task)
                else:
                    response = await self._generate_step_response(
                        task,
                        screenshot=next_step_screenshot,
                    )
                    next_step_screenshot = None
                self._raise_if_stopped()
                function_calls = self._extract_function_calls(response)

                if not function_calls:
                    should_continue = await self._handle_no_function_call(task)
                    if should_continue:
                        continue
                    return CuaRunResult(
                        success=True,
                        complete=False,
                        result="Vision model did not return an executable action.",
                    )

                function_calls = self._normalize_function_call_batch(function_calls)
                if len(function_calls) > 1:
                    print(f"[VisionAgent] Executing {len(function_calls)} tool calls from one model response.")

                done = await self._handle_function_calls(task, function_calls)
                if done:
                    if self._terminal_incomplete_verdict is not None:
                        return CuaRunResult(
                            success=True,
                            complete=False,
                            result=self._terminal_incomplete_verdict.reason,
                            critic=self._terminal_incomplete_verdict,
                        )
                    return CuaRunResult(
                        success=True,
                        complete=True,
                        result="Task completed",
                        critic=self._last_completion_verdict,
                    )

                self._raise_if_stopped()
                await asyncio.sleep(POST_BATCH_DELAY_SECONDS)
        except RepeatedNoopActionError as exc:
            verdict = CriticVerdict(
                complete=False,
                should_continue=False,
                confidence=0.45,
                reason=str(exc),
            )
            return CuaRunResult(
                success=True,
                complete=False,
                result=str(exc),
                critic=verdict,
            )
        finally:
            self._run_deadline_monotonic = None
            await self._hide_statuses(delay_ms=400)

    async def _generate_step_response(self, task: str, screenshot=None):
        self._raise_if_stopped()
        active_window = get_active_window_title()
        memory_text, _ = get_memory()

        model_prompt = self._build_model_prompt(task, active_window, memory_text)
        if screenshot is None:
            screen_frame = capture_active_window_frame()
        elif isinstance(screenshot, ScreenFrame):
            screen_frame = screenshot
        else:
            screen_frame = register_provided_screenshot_frame(screenshot)
        self._current_screen_frame = screen_frame

        thinking_text = THINKING_MESSAGES[self._thinking_index % len(THINKING_MESSAGES)]
        self._thinking_index += 1
        await self._set_status(thinking_text)

        response = await self._generate_provider_step_response(
            model_prompt,
            screen_frame.image,
            model_role=ModelRole.PLANNER,
            model_context=self._next_step_model_policy_context(),
        )
        self.agent.retries = 0
        return response

    async def _generate_provider_step_response(
        self,
        model_prompt: str,
        screenshot,
        *,
        system_prompt: str | None = None,
        function_declarations: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 900,
        status_prefix: str = "Calling vision model",
        model_role: ModelRole = ModelRole.PLANNER,
        model_context: ModelPolicyContext | None = None,
    ):
        nvidia_api_key = get_nvidia_api_key()
        api_key = get_openrouter_api_key()
        if not api_key and not nvidia_api_key:
            message = (
                "CUA vision requires NVIDIA_API_KEY or OPENROUTER_API_KEY. "
                "Gemini is not used for vision."
            )
            print(f"[VisionAgent] {message}")
            raise OpenRouterFallbackError(message)

        image_data_url = image_to_data_url(screenshot)
        system_prompt = system_prompt or (
            "You are a computer-use vision agent. Analyze the screenshot and choose the next "
            "tool call. Use task_is_complete when the user's goal is complete."
        )
        function_declarations = (
            VISION_FUNCTION_DECLARATIONS
            if function_declarations is None
            else function_declarations
        )
        attempts: list[str] = []
        errors: list[str] = []
        model_purpose = self._model_policy.provider_purpose(model_role, model_context)
        nvidia_models_to_try = get_nvidia_models(model_purpose) if nvidia_api_key else []
        openrouter_models_to_try = get_openrouter_models(model_purpose) if api_key else []
        if not openrouter_models_to_try and not nvidia_models_to_try:
            raise OpenRouterFallbackError(
                "No NVIDIA or OpenRouter vision models are configured."
            )

        providers_to_try = [
            {
                "label": "NVIDIA",
                "api_key": nvidia_api_key,
                "url": get_nvidia_chat_url() if nvidia_api_key else "",
                "site_url": "",
                "site_name": "",
                "timeout": get_nvidia_timeout_seconds(),
                "models": nvidia_models_to_try,
            },
            {
                "label": "OpenRouter",
                "api_key": api_key,
                "url": get_openrouter_chat_url() if api_key else "",
                "site_url": get_openrouter_site_url() if api_key else "",
                "site_name": get_openrouter_site_name() if api_key else "",
                "timeout": get_openrouter_timeout_seconds(),
                "models": openrouter_models_to_try,
            },
        ]

        for provider in providers_to_try:
            if not provider["api_key"] or not provider["models"]:
                continue
            for model_name in provider["models"]:
                self._raise_if_stopped()
                provider_timeout = self._timeout_within_run_budget(
                    float(provider["timeout"])
                )
                if self._provider_call_count >= self._max_provider_calls:
                    raise OpenRouterFallbackError(
                        f"Vision provider call budget exceeded ({self._max_provider_calls})."
                    )
                self._provider_call_count += 1
                attempt_label = f"{provider['label']}:{model_name}"
                attempts.append(attempt_label)
                try:
                    await self._set_status(
                        f"{status_prefix}: {provider['label']} {model_name}..."
                    )
                    result = await asyncio.to_thread(
                        call_openrouter_tool_sync,
                        openrouter_api_key=provider["api_key"],
                        openrouter_url=provider["url"],
                        openrouter_site_url=provider["site_url"],
                        openrouter_site_name=provider["site_name"],
                        openrouter_timeout_seconds=provider_timeout,
                        model_name=model_name,
                        system_prompt=system_prompt,
                        user_prompt=model_prompt,
                        function_declarations=function_declarations,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        clean_text=lambda value, fallback, max_len: _clean_text(
                            value,
                            fallback,
                            max_len=max_len,
                        ),
                        image_data_url=image_data_url,
                    )
                    print(
                        f"[VisionAgent] {provider['label']} fallback succeeded with "
                        f"model {model_name}."
                    )
                    return tool_result_to_vision_response(result)
                except Exception as fallback_exc:
                    error = f"{attempt_label}: {fallback_exc}"
                    errors.append(error)
                    print(f"[VisionAgent] {provider['label']} fallback failed with {model_name}: {fallback_exc}")
        if errors:
            await self._set_status("Vision provider fallback failed.")
            raise OpenRouterFallbackError(
                f"Vision providers failed after trying "
                f"{', '.join(attempts)}. Last fallback error: {errors[-1]}"
            )
        raise OpenRouterFallbackError("Vision provider fallback did not run.")

    def _has_remaining_run_budget(self) -> bool:
        deadline = self._run_deadline_monotonic
        if deadline is None:
            return True
        return time.monotonic() < deadline

    def _timeout_within_run_budget(self, configured_timeout_seconds: float) -> float:
        timeout = max(0.001, float(configured_timeout_seconds))
        deadline = self._run_deadline_monotonic
        if deadline is None:
            return timeout

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"CUA Vision time budget exceeded ({self._max_duration_seconds:.1f}s)."
            )
        return max(0.001, min(timeout, remaining))

    async def _generate_openrouter_step_response(self, model_prompt: str, screenshot):
        """Backward-compatible wrapper for the provider-based vision call."""
        return await self._generate_provider_step_response(model_prompt, screenshot)

    def _next_step_model_policy_context(self) -> ModelPolicyContext:
        return ModelPolicyContext(
            repeated_noop=self._repeated_visual_noop_count > 0,
            unclear_screen=any(
                "inconclusive" in observation.lower()
                for observation in self._runtime_observations[-MAX_RUNTIME_OBSERVATIONS:]
            ),
            completion_claim=self._rejected_completion_count > 0,
        )

    def _build_model_prompt(self, task: str, active_window: str, memory_text):
        memory_json = json.dumps(memory_text)
        runtime_observations_json = json.dumps(
            self._runtime_observations[-MAX_RUNTIME_OBSERVATIONS:]
        )
        return f"""
{VISION_AGENT_SYSTEM_PROMPT}

You are controlling the user's active application window.
Application: {active_window}
User goal: {task}
Stored memory: {memory_json}
Recent controller observations: {runtime_observations_json}

First, analyze the screenshot in detail privately.
Then decide the best NEXT action for this exact screen.

IMPORTANT:
- You may call ONE function, or a legacy TWO-function position+click sequence.
- For normal visible UI clicks, prefer `click_target` with the target bounding box and click type.
- If you call TWO functions, they must be:
  1) `go_to_element` or `crop_and_search`
  2) then one click tool (`click_left_click`/`click_double_left_click`/`click_right_click`)
- Never emit more than TWO function calls in one response.
- Prefer direct action tools (position/click/type/hotkeys) over descriptive selectors.
- `click_target` is atomic: it maps the visible target bbox, moves the cursor, and clicks immediately.
- Legacy click tools use only the current cursor location. Do NOT pass x/y coordinates to them.
- Only use separate `go_to_element`/`crop_and_search` plus a legacy click when you need a positioning-only step.
- Do not call `go_to_element`/`crop_and_search` repeatedly for the same target on unchanged screen.
- After positioning for a target, your next step should usually be the click itself.
- `crop_and_search` is OPTIONAL and should only be used when helpful.
- If the target location is clear, use `go_to_element`.
- If the target is tiny/crowded or click confidence is low, use `crop_and_search`.
- For `crop_and_search`, provide a best-effort bounding box [ymin, xmin, ymax, xmax] (0-1000 coords).
- Do not pass a single point to `go_to_element` or `crop_and_search`; pass a box around the likely target.
- The crop tool adds padding internally, so your box can be approximate.
- For every non-terminal action function call, include a concise `status_text` argument.
  Example: "Searching for Next button..." or "Typing into email field..."
- For click tools, also include `target_description` (short target label) for fallback.
- Only interact with elements you can currently see.
- Before choosing an action, check if the user goal is already satisfied on this screen.
- Treat "Recent controller observations" as factual feedback from executed actions and follow-up screenshots.
- If an action was reported as having no visible effect, do not repeat it unchanged. Adjust the target or strategy.
- When the task is fully complete, call `task_is_complete` and do not call any other function.
{WINDOWS_APP_LAUNCH_WORKFLOW}
"""

    def _extract_function_calls(self, response):
        try:
            parts = response.candidates[0].content.parts
        except Exception:
            return []
        return [part.function_call for part in parts if part.function_call]

    @staticmethod
    def _position_click_call_to_click_target(position_call, click_call):
        position_args = dict(position_call.args or {})
        click_args = dict(click_call.args or {})
        converted_args = {
            key: position_args[key]
            for key in ("ymin", "xmin", "ymax", "xmax")
            if key in position_args
        }
        converted_args["type_of_click"] = CLICK_TOOL_TO_TYPE[click_call.name]
        converted_args["target_description"] = (
            click_args.get("target_description")
            or position_args.get("target_description")
            or "target"
        )
        status_text = click_args.get("status_text") or position_args.get("status_text")
        if status_text:
            converted_args["status_text"] = status_text
        return SimpleNamespace(name=CLICK_TARGET_TOOL, args=converted_args)

    async def _handle_no_function_call(self, task: str) -> bool:
        self._raise_if_stopped()
        self.consecutive_failures += 1
        self.agent.retries += 1

        if self.consecutive_failures >= self.max_failures_before_fallback:
            fallback_success = await self._attempt_fallback(task, None, None)
            if fallback_success:
                self.agent.retries = 0
                self.consecutive_failures = 0
                return True

        if self.agent.retries < self.agent.max_retries:
            await self._set_status(
                f"No action selected. Retrying ({self.agent.retries}/{self.agent.max_retries})..."
            )
            return True

        tts_speak("I couldn't determine the next action. Please try again.")
        raise RuntimeError("Max retries reached without function call")

    def _normalize_function_call_batch(self, function_calls: list):
        """Allow controlled multi-call sequences per model response."""
        if len(function_calls) <= 1:
            return function_calls

        first = function_calls[0]
        if first.name == "task_is_complete":
            return [first]

        if len(function_calls) >= 2:
            second = function_calls[1]
            if first.name in POSITIONING_TOOLS and second.name in CLICK_TOOL_TO_TYPE:
                click_target_call = self._position_click_call_to_click_target(first, second)
                if len(function_calls) >= 3 and function_calls[2].name == "task_is_complete":
                    if len(function_calls) > 3:
                        print(
                            "[VisionAgent] Received more than 3 function calls; "
                            "dropping extras after position+click+complete."
                        )
                    return [click_target_call, function_calls[2]]
                if len(function_calls) > 2:
                    print(
                        "[VisionAgent] Received more than 2 function calls; "
                        "dropping extras after position+click."
                    )
                return [click_target_call]

            if first.name == CLICK_TARGET_TOOL and second.name == "task_is_complete":
                if len(function_calls) > 2:
                    print(
                        "[VisionAgent] Received more than 2 function calls; "
                        "dropping extras after click_target+complete."
                    )
                return function_calls[:2]

            if first.name in CLICK_TOOL_TO_TYPE and second.name == "task_is_complete":
                if len(function_calls) > 2:
                    print(
                        "[VisionAgent] Received more than 2 function calls; "
                        "dropping extras after click+complete."
                    )
                return function_calls[:2]

        print(
            "[VisionAgent] Multi-call sequence is unsupported; "
            "executing only the first call."
        )
        return [first]

    async def _handle_function_calls(self, task: str, function_calls: list) -> bool:
        """Execute one to three controlled tool calls from a single model response."""
        screen_frame = self._current_screen_frame
        has_explicit_click = any(
            call.name in CLICK_TOOL_TO_TYPE or call.name == CLICK_TARGET_TOOL
            for call in function_calls
        )
        for function_call in function_calls:
            done = await self._handle_function_call(
                task,
                function_call,
                allow_positioning_autoclick=not has_explicit_click,
                screen_frame=screen_frame,
            )
            if done:
                return True
            self._raise_if_stopped()
        return False

    async def _handle_function_call(
        self,
        task: str,
        function_call,
        allow_positioning_autoclick: bool = True,
        screen_frame: ScreenFrame | None = None,
    ) -> bool:
        self._raise_if_stopped()
        action_screen_frame = screen_frame or self._current_screen_frame
        name = function_call.name
        args = dict(function_call.args or {})

        status_text = args.get("status_text") or default_status_text(name, CLICK_TOOL_TO_TYPE)
        if status_text:
            await self._set_status(status_text)

        click_type = self._resolve_click_type(name, args)
        signature = self._action_signature(name, args)
        if signature == self.last_action_signature:
            self.repeated_action_count += 1
        else:
            self.last_action_signature = signature
            self.repeated_action_count = 1

        if click_type and self.repeated_action_count >= self.max_failures_before_fallback:
            fallback_success = await self._attempt_fallback(task, click_type, args)
            if fallback_success:
                self.consecutive_failures = 0
                self.repeated_action_count = 0
                return False

        if (
            allow_positioning_autoclick
            and
            name in POSITIONING_TOOLS
            and self.repeated_action_count >= AUTO_CLICK_AFTER_REPEAT_POSITIONING_THRESHOLD
        ):
            auto_click_type = self._infer_click_type(task, args)
            target = resolve_target_description(
                task=task,
                args=args,
                last_target_description=self.last_target_description,
            )
            bbox_args = self._extract_position_bbox_args(args) or {}
            if bbox_args:
                auto_click_tool = CLICK_TARGET_TOOL
                auto_click_args = {
                    "target_description": target,
                    "type_of_click": auto_click_type,
                    **bbox_args,
                }
            else:
                auto_click_tool = CLICK_TYPE_TO_TOOL[auto_click_type]
                auto_click_args = {"target_description": target}
            auto_click_signature = self._action_signature(auto_click_tool, auto_click_args)
            pre_action_frame, pre_action_context = (
                self._capture_verification_snapshot()
                if self._should_verify_visual_effect(auto_click_tool)
                else (None, None)
            )
            await self._set_status(f"Position repeated. Executing {auto_click_type} on {target}...")
            auto_click_frame = self._screen_frame_for_tool(auto_click_tool, action_screen_frame)
            if auto_click_frame is None:
                execute_tool_call(auto_click_tool, auto_click_args)
            else:
                execute_tool_call(
                    auto_click_tool,
                    auto_click_args,
                    screen_frame=auto_click_frame,
                )
            self.last_target_description = target
            self.last_click_context = {
                "type_of_click": auto_click_type,
                "target_description": target,
            }
            self.last_action_signature = None
            self.repeated_action_count = 0
            self.consecutive_failures = 0
            print(
                "[VisionAgent] Auto-click before repeated positioning: "
                f"{auto_click_type} on {target}"
            )
            post_action_frame = await self._wait_for_ui_settle()
            post_action_context = self._snapshot_current_capture_context()
            await self._handle_post_action_visual_feedback(
                task=task,
                name=auto_click_tool,
                args=auto_click_args,
                signature=auto_click_signature,
                click_type=auto_click_type,
                pre_action_frame=pre_action_frame,
                pre_action_context=pre_action_context,
                post_action_frame=post_action_frame,
                post_action_context=post_action_context,
            )
            return False

        print(f"[VisionAgent] Function: {name}")
        print(f"[VisionAgent] Arguments: {args}")

        try:
            self._raise_if_stopped()
            pre_action_frame, pre_action_context = (
                self._capture_verification_snapshot()
                if self._should_verify_visual_effect(name)
                else (None, None)
            )
            if name == "task_is_complete":
                if await self._should_accept_model_completion(task, args):
                    tool_screen_frame = self._screen_frame_for_tool(name, action_screen_frame)
                    if tool_screen_frame is None:
                        execute_tool_call(name, args)
                    else:
                        execute_tool_call(name, args, screen_frame=tool_screen_frame)
                    await self._set_status("Task complete")
                    await self._hide_statuses(delay_ms=700)
                    return True
                if self._rejected_completion_count >= 2:
                    self._terminal_incomplete_verdict = self._last_completion_verdict
                    return True
                await self._set_status("Completion needs verification. Continuing...")
                return False

            if name == "tts_speak":
                tool_screen_frame = self._screen_frame_for_tool(name, action_screen_frame)
                if tool_screen_frame is None:
                    execute_tool_call(name, args)
                else:
                    execute_tool_call(name, args, screen_frame=tool_screen_frame)
                self.consecutive_failures = 0
                return False

            tool_screen_frame = self._screen_frame_for_tool(name, action_screen_frame)
            if name in {"crop_and_search", "go_to_element"}:
                # These tools can do blocking model work; run them off-loop.
                if tool_screen_frame is None:
                    await asyncio.to_thread(execute_tool_call, name, args)
                else:
                    await asyncio.to_thread(
                        execute_tool_call,
                        name,
                        args,
                        screen_frame=tool_screen_frame,
                    )
            else:
                if tool_screen_frame is None:
                    execute_tool_call(name, args)
                else:
                    execute_tool_call(name, args, screen_frame=tool_screen_frame)
            self.consecutive_failures = 0
            self._executed_action_count += 1

            if name in POSITIONING_TOOLS:
                self.last_target_description = resolve_target_description(
                    task=task,
                    args=args,
                    last_target_description=self.last_target_description,
                )
                self._last_position_bbox_args = self._extract_position_bbox_args(args)
            elif name == CLICK_TARGET_TOOL:
                self._last_position_bbox_args = self._extract_position_bbox_args(args)

            if name == "go_to_element":
                await self._maybe_debug_stop_after_first_goto(
                    task,
                    args,
                    screen_frame=action_screen_frame,
                )

            if click_type:
                resolved_target = resolve_target_description(
                    task=task,
                    args=args,
                    last_target_description=self.last_target_description,
                )
                self.last_target_description = resolved_target
                self.last_click_context = {
                    "type_of_click": click_type,
                    "target_description": resolved_target,
                }

            if self._register_action_and_detect_click_loop(task, name, signature, click_type):
                target = resolve_target_description(
                    task=task,
                    args=args,
                    last_target_description=self.last_target_description,
                )
                await self._set_status("Task appears complete. Stopping repeated clicks.")
                print(
                    "[VisionAgent] Detected repeated position+click loop "
                    f"on {target}. Stopping to avoid infinite retries."
                )
                await self._hide_statuses(delay_ms=700)
                self._terminal_incomplete_verdict = CriticVerdict(
                    complete=False,
                    should_continue=False,
                    confidence=0.45,
                    reason=(
                        "Stopped a repeated position+click loop without independent "
                        "completion evidence."
                    ),
                    next_hint="Re-observe the target and use a different action strategy.",
                )
                return True

            post_action_frame = await self._wait_for_ui_settle()
            post_action_context = self._snapshot_current_capture_context()
            await self._handle_post_action_visual_feedback(
                task=task,
                name=name,
                args=args,
                signature=signature,
                click_type=click_type,
                pre_action_frame=pre_action_frame,
                pre_action_context=pre_action_context,
                post_action_frame=post_action_frame,
                post_action_context=post_action_context,
            )
            return False
        except Exception as e:
            if isinstance(e, (DebugStopAfterFirstGoTo, RepeatedNoopActionError)):
                raise
            print(f"[VisionAgent] Tool execution failed: {e}")
            self.consecutive_failures += 1

            if click_type and self.consecutive_failures >= self.max_failures_before_fallback:
                fallback_success = await self._attempt_fallback(task, click_type, args)
                if fallback_success:
                    self.consecutive_failures = 0
                    self.repeated_action_count = 0
                    await self._wait_for_ui_settle()
                    return False

            if self.agent.retries < self.agent.max_retries:
                self.agent.retries += 1
                await self._set_status(
                    f"Action failed. Retrying ({self.agent.retries}/{self.agent.max_retries})..."
                )
                return False

            raise

    async def _maybe_debug_stop_after_first_goto(
        self,
        task: str,
        args: dict,
        screen_frame: ScreenFrame | None = None,
    ):
        """Optional debugging: save bbox overlay and stop after first go_to_element."""
        if not self.debug_stop_after_first_goto or self._debug_snapshot_taken:
            return

        required = ("ymin", "xmin", "ymax", "xmax")
        if not all(key in args for key in required):
            return

        target = resolve_target_description(
            task=task,
            args=args,
            last_target_description=self.last_target_description,
        )
        try:
            snapshot_path = save_go_to_element_debug_snapshot(
                ymin=float(args["ymin"]),
                xmin=float(args["xmin"]),
                ymax=float(args["ymax"]),
                xmax=float(args["xmax"]),
                target_description=target,
                screen_frame=screen_frame,
            )
        except Exception as e:
            snapshot_path = f"<failed to save snapshot: {e}>"

        self._debug_snapshot_taken = True
        await self._set_status("Debug snapshot saved. Stopping after first positioning step.")
        print(f"[VisionAgent][Debug] go_to_element snapshot: {snapshot_path}")
        raise DebugStopAfterFirstGoTo(
            "Debug stop after first go_to_element. "
            f"Snapshot: {snapshot_path}"
        )

    def _infer_click_type(self, task: str, args: dict) -> str:
        return infer_click_type(task, args)

    def _action_signature(self, name: str, args: dict) -> tuple:
        return compute_action_signature(
            name=name,
            args=args,
            metadata_keys=TOOL_METADATA_KEYS,
            click_tool_to_type=CLICK_TOOL_TO_TYPE,
            positioning_tools=POSITIONING_TOOLS,
            last_target_description=self.last_target_description,
            bucket_size=POSITION_BUCKET_SIZE,
        )

    def _resolve_click_type(self, tool_name: str, args: dict) -> str | None:
        if tool_name == CLICK_TARGET_TOOL:
            return normalize_click_type(args.get("type_of_click", "left click"))
        return resolve_click_type(tool_name, CLICK_TOOL_TO_TYPE)

    @staticmethod
    def _screen_frame_for_tool(
        tool_name: str,
        screen_frame: ScreenFrame | None,
    ) -> ScreenFrame | None:
        if tool_name not in SCREEN_FRAME_TOOLS:
            return None
        return screen_frame

    @staticmethod
    def _extract_position_bbox_args(args: dict) -> dict | None:
        return extract_position_bbox_args(args)

    def _register_action_and_detect_click_loop(
        self,
        task: str,
        name: str,
        signature: tuple,
        click_type: str | None,
    ) -> bool:
        return register_action_and_detect_click_loop(
            state=self._click_loop_state,
            task=task,
            name=name,
            signature=signature,
            click_type=click_type,
            positioning_tools=POSITIONING_TOOLS,
            click_cycle_loop_stop_threshold=CLICK_CYCLE_LOOP_STOP_THRESHOLD,
        )

    async def _attempt_fallback(self, task: str, click_type: str | None, args: dict | None) -> bool:
        self._raise_if_stopped()
        context = build_fallback_context(
            task=task,
            click_type=click_type,
            args=args,
            last_click_context=self.last_click_context,
            last_target_description=self.last_target_description,
        )

        if not context:
            return False

        target = context.get("target_description")
        click_type = context.get("type_of_click")
        if not target or not click_type:
            return False

        await self._set_status(f"{target} is uncertain. Using precision fallback...")
        self._raise_if_stopped()
        success = run_legacy_locator_fallback(click_type, target)

        if success:
            await self._set_status(f"Fallback located {target}.")
            self._remember_runtime_observation(
                f"Precision fallback was used for {target} after direct interaction struggled."
            )
            return True

        return False

    async def _set_status(self, text: str):
        await self._status_presenter.set(text)

    async def _hide_statuses(self, delay_ms: int = 0):
        await self._status_presenter.hide(delay_ms=delay_ms)

    async def _wait_for_ui_settle(self):
        """Poll until the active window appears visually stable or times out."""
        timeout = float(self._action_settle_timeout_seconds)
        poll_interval = float(self._action_settle_poll_interval_seconds)
        if timeout <= 0 or poll_interval <= 0:
            return None

        reset_image_state()
        deadline = time.monotonic() + timeout
        last_frame = None

        while True:
            self._raise_if_stopped()
            frame = capture_active_window()
            last_frame = frame
            if image_change(frame):
                return frame

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print("[VisionAgent] UI did not fully stabilize before timeout; continuing.")
                return last_frame

            await asyncio.sleep(min(poll_interval, remaining))

    def _should_verify_visual_effect(self, tool_name: str) -> bool:
        return tool_name in VISUAL_EFFECT_VERIFICATION_TOOLS

    def _snapshot_current_capture_context(self) -> dict | None:
        context = _get_last_capture_context()
        if not isinstance(context, dict):
            return None
        return dict(context)

    def _capture_verification_snapshot(self):
        saved_context = self._snapshot_current_capture_context()
        saved_image = _get_last_capture_image()
        try:
            verification_frame = capture_active_window_frame()
            return verification_frame.image, verification_frame.context_dict()
        except Exception as e:
            print(f"[VisionAgent] Verification capture failed: {e}")
            return None, None
        finally:
            self._restore_capture_snapshot(saved_context, saved_image)

    @staticmethod
    def _restore_capture_snapshot(context: dict | None, image) -> None:
        if isinstance(context, dict):
            try:
                _set_last_capture_context(
                    width=int(context["width"]),
                    height=int(context["height"]),
                    logical_width=int(context.get("logical_width") or context["width"]),
                    logical_height=int(context.get("logical_height") or context["height"]),
                    offset_x=float(context.get("offset_x", 0.0)),
                    offset_y=float(context.get("offset_y", 0.0)),
                    scale_x=float(context.get("scale_x", 1.0)),
                    scale_y=float(context.get("scale_y", 1.0)),
                    mode=str(context.get("mode", "restored")),
                )
            except Exception as e:
                print(f"[VisionAgent] Capture context restore failed: {e}")
        if image is not None:
            try:
                _set_last_capture_image(image)
            except Exception as e:
                print(f"[VisionAgent] Capture image restore failed: {e}")

    @staticmethod
    def _image_similarity(before_frame, after_frame) -> float | None:
        return compute_image_similarity(before_frame, after_frame)

    def _resolve_target_bbox_for_verification(self, tool_name: str, args: dict) -> dict | None:
        return resolve_target_bbox_for_verification(
            tool_name=tool_name,
            args=args,
            click_tool_to_type=CLICK_TOOL_TO_TYPE,
            last_position_bbox_args=self._last_position_bbox_args,
        )

    def _crop_target_region(self, frame, context: dict | None, bbox_args: dict | None):
        return compute_target_region_crop(
            frame=frame,
            context=context,
            bbox_args=bbox_args,
            padding_px=TARGET_REGION_PADDING_PX,
            min_side_px=TARGET_REGION_MIN_SIDE_PX,
        )

    def _visual_similarity_metrics(
        self,
        tool_name: str,
        args: dict,
        before_frame,
        before_context: dict | None,
        after_frame,
        after_context: dict | None,
    ) -> dict:
        return compute_visual_similarity_metrics(
            tool_name=tool_name,
            args=args,
            before_frame=before_frame,
            before_context=before_context,
            after_frame=after_frame,
            after_context=after_context,
            click_tool_to_type=CLICK_TOOL_TO_TYPE,
            last_position_bbox_args=self._last_position_bbox_args,
            target_region_padding_px=TARGET_REGION_PADDING_PX,
            target_region_min_side_px=TARGET_REGION_MIN_SIDE_PX,
        )

    def _remember_runtime_observation(self, text: str):
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        if self._runtime_observations and self._runtime_observations[-1] == cleaned:
            return
        self._runtime_observations.append(cleaned)
        if len(self._runtime_observations) > MAX_RUNTIME_OBSERVATIONS:
            self._runtime_observations = self._runtime_observations[-MAX_RUNTIME_OBSERVATIONS:]

    def _reset_visual_noop_state(self):
        self._last_visual_noop_signature = None
        self._repeated_visual_noop_count = 0

    async def _handle_post_action_visual_feedback(
        self,
        task: str,
        name: str,
        args: dict,
        signature: tuple,
        click_type: str | None,
        pre_action_frame,
        pre_action_context: dict | None,
        post_action_frame,
        post_action_context: dict | None,
    ) -> None:
        if not self._should_verify_visual_effect(name):
            self._reset_visual_noop_state()
            self._last_action_had_visible_effect = None
            return

        metrics = self._visual_similarity_metrics(
            tool_name=name,
            args=args,
            before_frame=pre_action_frame,
            before_context=pre_action_context,
            after_frame=post_action_frame,
            after_context=post_action_context,
        )
        global_similarity = metrics["global_similarity"]
        target_similarity = metrics["target_similarity"]
        if global_similarity is None:
            self._reset_visual_noop_state()
            self._last_action_had_visible_effect = None
            self._remember_runtime_observation(
                "Visual verification was inconclusive after the last action."
            )
            return

        globally_unchanged = global_similarity >= VISUAL_NOOP_SIMILARITY_THRESHOLD
        target_unchanged = (
            target_similarity is None
            or target_similarity >= TARGET_REGION_NOOP_SIMILARITY_THRESHOLD
        )

        if not globally_unchanged or not target_unchanged:
            self._reset_visual_noop_state()
            self._last_action_had_visible_effect = True
            return

        self._last_action_had_visible_effect = False

        if signature == self._last_visual_noop_signature:
            self._repeated_visual_noop_count += 1
        else:
            self._last_visual_noop_signature = signature
            self._repeated_visual_noop_count = 1

        action_description = describe_action_for_feedback(
            tool_name=name,
            task=task,
            args=args,
            click_tool_to_type=CLICK_TOOL_TO_TYPE,
            last_target_description=self.last_target_description,
        )
        if self._repeated_visual_noop_count == 1:
            observation = f"After {action_description}, the visible UI looked unchanged."
        else:
            observation = (
                f"After {action_description}, the visible UI still looked unchanged "
                f"after {self._repeated_visual_noop_count} attempts."
            )
        self._remember_runtime_observation(observation)
        similarity_bits = [f"global={global_similarity:.4f}"]
        if target_similarity is not None:
            similarity_bits.append(f"target={target_similarity:.4f}")
        print(f"[VisionAgent] {observation} {' '.join(similarity_bits)}")

        if (
            click_type is None
            and name in NON_CLICK_NOOP_STOP_TOOLS
            and self._repeated_visual_noop_count >= REPEATED_NON_CLICK_NOOP_STOP_THRESHOLD
            and not task_expects_repeated_actions(task)
        ):
            await self._set_status(f"{action_description} had no visible effect. Stopping.")
            raise RepeatedNoopActionError(
                f"Repeated {action_description} had no visible effect; stopping to avoid a loop."
            )

        if click_type and self._repeated_visual_noop_count >= REPEATED_VISUAL_NOOP_FALLBACK_THRESHOLD:
            await self._set_status(f"{action_description} had no visible effect. Trying precision fallback...")
            fallback_success = await self._attempt_fallback(task, click_type, args)
            if fallback_success:
                self.consecutive_failures = 0
                self.repeated_action_count = 0
                await self._wait_for_ui_settle()
                self._reset_visual_noop_state()

    async def _should_accept_model_completion(self, task: str, args: dict) -> bool:
        visual_change_since_last_action = (
            self._executed_action_count > 0
            and self._last_action_had_visible_effect is True
        )
        action = ComputerAction(
            action_type=ActionType.COMPLETE,
            target=TargetRef(TargetKind.NONE),
            text=str(args.get("text") or args.get("status_text") or ""),
            raw_name="task_is_complete",
            raw_args=dict(args),
        )
        result = ActionResult(
            executed=True,
            message="Model claimed completion.",
            metrics={
                "visual_change_since_last_action": visual_change_since_last_action,
                "completion_evidence_reason": (
                    "last verified action changed pixels, but no goal-state evidence was provided"
                    if visual_change_since_last_action
                    else "no verified semantic, accessibility, or structural goal evidence"
                ),
            },
        )
        verdict = await self._criticizer.review(
            task=task,
            action=action,
            result=result,
            model_claimed_complete=True,
        )
        self._last_completion_verdict = verdict
        if verdict.complete:
            self._rejected_completion_count = 0
            return True
        self._rejected_completion_count += 1
        self._remember_runtime_observation(verdict.reason)
        print(f"[VisionAgent] Completion rejected by critic: {verdict.reason}")
        return False

    def _raise_if_stopped(self):
        if is_stop_requested():
            raise asyncio.CancelledError("Stop requested by user")
