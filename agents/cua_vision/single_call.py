"""
Primary single-call execution engine for CUA Vision.

This module handles per-step model calls where the model returns both the next
action and user-visible status text in one response.
"""

import asyncio
import json
import os
import time

try:
    from google.api_core.exceptions import InternalServerError
except ImportError:
    class InternalServerError(Exception):
        """Fallback exception type when google-api-core is unavailable."""
        pass

from integrations.audio import tts_speak
from agents.cua_vision.action_guard import (
    ClickLoopState,
    action_signature as compute_action_signature,
    extract_position_bbox_args,
    infer_click_type,
    register_action_and_detect_click_loop,
    resolve_click_type,
)
from agents.cua_vision.interaction_policy import (
    build_fallback_context,
    default_status_text,
    describe_action_for_feedback,
    resolve_target_description,
)
from agents.cua_vision.prompts import VISION_AGENT_SYSTEM_PROMPT
from agents.cua_vision.image import image_change, reset_image_state
from agents.cua_vision.runtime_state import (
    get_last_capture_context as _get_last_capture_context,
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
AUTO_CLICK_AFTER_REPEAT_POSITIONING_THRESHOLD = 2
POSITION_BUCKET_SIZE = 40
CLICK_CYCLE_LOOP_STOP_THRESHOLD = 4
DEFAULT_ACTION_SETTLE_TIMEOUT_SECONDS = 2.0
DEFAULT_ACTION_SETTLE_POLL_INTERVAL_SECONDS = 0.2
POST_BATCH_DELAY_SECONDS = 0.05
VISUAL_NOOP_SIMILARITY_THRESHOLD = 0.9995
TARGET_REGION_NOOP_SIMILARITY_THRESHOLD = 0.995
REPEATED_VISUAL_NOOP_FALLBACK_THRESHOLD = 2
MAX_RUNTIME_OBSERVATIONS = 4
TARGET_REGION_PADDING_PX = 24
TARGET_REGION_MIN_SIDE_PX = 48
VISUAL_EFFECT_VERIFICATION_TOOLS = {
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


class DebugStopAfterFirstGoTo(RuntimeError):
    """Raised when debug mode intentionally stops after first go_to_element."""


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
        self.debug_stop_after_first_goto = _is_truthy_env(
            os.getenv("CUA_VISION_DEBUG_STOP_AFTER_FIRST_GOTO", "0")
        )

    async def run(self, task: str):
        """Execute the task until completion or unrecoverable failure."""
        try:
            self._raise_if_stopped()
            while True:
                self._raise_if_stopped()
                response = await self._generate_step_response(task)
                self._raise_if_stopped()
                function_calls = self._extract_function_calls(response)

                if not function_calls:
                    should_continue = await self._handle_no_function_call(task)
                    if should_continue:
                        continue
                    return

                function_calls = self._normalize_function_call_batch(function_calls)
                if len(function_calls) > 1:
                    print(f"[VisionAgent] Executing {len(function_calls)} tool calls from one model response.")

                done = await self._handle_function_calls(task, function_calls)
                if done:
                    return

                self._raise_if_stopped()
                await asyncio.sleep(POST_BATCH_DELAY_SECONDS)
        finally:
            await self._hide_statuses(delay_ms=400)

    async def _generate_step_response(self, task: str):
        self._raise_if_stopped()
        active_window = get_active_window_title()
        memory_text, _ = get_memory()

        model_prompt = self._build_model_prompt(task, active_window, memory_text)
        screenshot = capture_active_window()

        thinking_text = THINKING_MESSAGES[self._thinking_index % len(THINKING_MESSAGES)]
        self._thinking_index += 1
        await self._set_status(thinking_text)

        model_task = asyncio.create_task(
            self.agent.client.aio.models.generate_content(
                model=self.agent.model_name,
                contents=[model_prompt, screenshot],
                config=getattr(
                    self.agent,
                    "interaction_config",
                    getattr(self.agent, "analysis_config", None),
                ),
            )
        )
        try:
            while True:
                self._raise_if_stopped()
                done, _ = await asyncio.wait({model_task}, timeout=0.15)
                if done:
                    response = model_task.result()
                    self.agent.retries = 0
                    return response
        except asyncio.CancelledError:
            model_task.cancel()
            raise
        except InternalServerError as e:
            self.agent.retries += 1
            if self.agent.retries < self.agent.max_retries:
                await self._set_status(
                    f"Model error. Retrying ({self.agent.retries}/{self.agent.max_retries})..."
                )
                await asyncio.sleep(1)
                self._raise_if_stopped()
                return await self._generate_step_response(task)
            raise e

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
- You may call ONE function, or a TWO-function position+click sequence.
- If you call TWO functions, they must be:
  1) `go_to_element` or `crop_and_search`
  2) then one click tool (`click_left_click`/`click_double_left_click`/`click_right_click`)
- Never emit more than TWO function calls in one response.
- Prefer direct action tools (position/click/type/hotkeys) over descriptive selectors.
- Click actions are two-step:
  1) Position cursor with `go_to_element` (or `crop_and_search` when uncertain)
  2) Then click, either immediately in the same response or in the next step
- Do NOT pass x/y coordinates to click tools.
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
- App-launch tasks on macOS should prefer keyboard flow:
  1) `press_ctrl_hotkey(key="space")` (maps to Command+Space on macOS)
  2) `type_string(string="<app name>", submit=true)`
  3) continue the rest of the task after app opens
- Avoid clicking tiny menu bar Spotlight icons when shortcut launch is available.
- Do not stop immediately after opening an app if the user asked for more actions.
"""

    def _extract_function_calls(self, response):
        try:
            parts = response.candidates[0].content.parts
        except Exception:
            return []
        return [part.function_call for part in parts if part.function_call]

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
                if len(function_calls) >= 3 and function_calls[2].name == "task_is_complete":
                    if len(function_calls) > 3:
                        print(
                            "[VisionAgent] Received more than 3 function calls; "
                            "dropping extras after position+click+complete."
                        )
                    return function_calls[:3]
                if len(function_calls) > 2:
                    print(
                        "[VisionAgent] Received more than 2 function calls; "
                        "dropping extras after position+click."
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
        has_explicit_click = any(call.name in CLICK_TOOL_TO_TYPE for call in function_calls)
        for function_call in function_calls:
            done = await self._handle_function_call(
                task,
                function_call,
                allow_positioning_autoclick=not has_explicit_click,
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
    ) -> bool:
        self._raise_if_stopped()
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
            auto_click_tool = CLICK_TYPE_TO_TOOL[auto_click_type]
            target = resolve_target_description(
                task=task,
                args=args,
                last_target_description=self.last_target_description,
            )
            auto_click_args = {"target_description": target}
            auto_click_signature = self._action_signature(auto_click_tool, auto_click_args)
            pre_action_frame, pre_action_context = (
                self._capture_verification_snapshot()
                if self._should_verify_visual_effect(auto_click_tool)
                else (None, None)
            )
            await self._set_status(f"Position repeated. Executing {auto_click_type} on {target}...")
            execute_tool_call(auto_click_tool, auto_click_args)
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
            if name in {"crop_and_search", "go_to_element"}:
                # These tools can do blocking model work; run them off-loop.
                await asyncio.to_thread(execute_tool_call, name, args)
            else:
                execute_tool_call(name, args)
            self.consecutive_failures = 0

            if name in POSITIONING_TOOLS:
                self.last_target_description = resolve_target_description(
                    task=task,
                    args=args,
                    last_target_description=self.last_target_description,
                )
                self._last_position_bbox_args = self._extract_position_bbox_args(args)

            if name == "go_to_element":
                await self._maybe_debug_stop_after_first_goto(task, args)

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

            if name in {"tts_speak", "task_is_complete"}:
                await self._set_status("Task complete")
                await self._hide_statuses(delay_ms=700)
                return True

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
            if isinstance(e, DebugStopAfterFirstGoTo):
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

    async def _maybe_debug_stop_after_first_goto(self, task: str, args: dict):
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
        del args
        return resolve_click_type(tool_name, CLICK_TOOL_TO_TYPE)

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
        try:
            frame = capture_active_window()
            return frame, self._snapshot_current_capture_context()
        except Exception as e:
            print(f"[VisionAgent] Verification capture failed: {e}")
            return None, None

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
        globally_unchanged = (
            global_similarity is not None
            and global_similarity >= VISUAL_NOOP_SIMILARITY_THRESHOLD
        )
        target_unchanged = (
            target_similarity is None
            or target_similarity >= TARGET_REGION_NOOP_SIMILARITY_THRESHOLD
        )

        if not globally_unchanged or not target_unchanged:
            self._reset_visual_noop_state()
            return

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

        if click_type and self._repeated_visual_noop_count >= REPEATED_VISUAL_NOOP_FALLBACK_THRESHOLD:
            await self._set_status(f"{action_description} had no visible effect. Trying precision fallback...")
            fallback_success = await self._attempt_fallback(task, click_type, args)
            if fallback_success:
                self.consecutive_failures = 0
                self.repeated_action_count = 0
                await self._wait_for_ui_settle()
                self._reset_visual_noop_state()

    def _raise_if_stopped(self):
        if is_stop_requested():
            raise asyncio.CancelledError("Stop requested by user")
