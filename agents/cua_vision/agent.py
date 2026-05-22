"""
Vision Agent - Desktop control via screen understanding + mouse/keyboard.

This agent can see the user's screen and interact with it by clicking elements,
typing, and using keyboard shortcuts. It uses a vision model to understand
what's on screen and decide what actions to take.
"""
import inspect
import os
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

from agents.cua_vision.accessibility import build_accessibility_provider
from agents.cua_vision.computer_backend import PyAutoGuiComputerBackend
from agents.cua_vision.controller import CuaController
from agents.cua_vision.tools import (
    reset_state,
    clear_stop_request,
    capture_active_window,
    capture_active_window_frame,
    get_active_window_title,
    execute_tool_call,
)
from integrations.audio import tts_speak
from agents.cua_vision.contracts import CuaRunResult
from agents.cua_vision.criticizer import CuaCriticizer
from agents.cua_vision.errors import OpenRouterFallbackError
from agents.cua_vision.model_policy import CuaModelPolicy
from agents.cua_vision.provider_planner import ProviderVisionPlanner
from agents.cua_vision.semantic_judge import ProviderSemanticJudge
from agents.cua_vision.single_call import SingleCallVisionEngine
from agents.cua_vision.tool_declarations import VISION_FUNCTION_DECLARATIONS
from agents.cua_vision.prompts import (
    LOOK_AT_SCREEN_PROMPT,
    WATCH_SCREEN_PROMPT,
)
from agents.cua_vision.image import image_change, reset_image_state
from agents.cua_vision.trajectory import CuaTrajectoryRecorder

load_dotenv()


def _truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _build_trajectory_recorder() -> CuaTrajectoryRecorder:
    directory_text = str(os.getenv("CUA_VISION_TRAJECTORY_DIR") or "").strip()
    enabled = _truthy_env(os.getenv("CUA_VISION_TRACE")) or bool(directory_text)
    directory = Path(directory_text) if directory_text else Path(".cua_vision_traces")
    return CuaTrajectoryRecorder(enabled=enabled, directory=directory)


def _critic_payload(value):
    if value is None or isinstance(value, Mapping):
        return value
    try:
        return asdict(value)
    except TypeError:
        return value


class VisionAgent:
    """
    Desktop control agent using screen understanding + mouse/keyboard.

    Capable of:
    - Screenshot capture and analysis
    - Element detection via vision models
    - Mouse movement and clicking
    - Keyboard input
    - Visual verification of actions
    - Continuous screen watching
    """

    def __init__(self, model_name: str = "nvidia/openrouter-vision"):
        # Kept for compatibility with callers that inspect these attributes. CUA
        # vision requests are executed through NVIDIA first, then OpenRouter.
        self.client = None
        self.model_name = model_name
        self.backup_model_name = ""
        self.max_retries = 3
        self.retries = 0

        self.interaction_config = None
        self.analysis_config = None

        # Chat history for multi-turn interaction
        self.chat_history = []

    @staticmethod
    def _is_temporary_model_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "503",
            "unavailable",
            "high demand",
            "temporarily unavailable",
            "overloaded",
            "resource_exhausted",
            "429",
        )
        return any(marker in text for marker in markers)

    async def execute(self, task: str, screenshot: Image.Image = None) -> dict:
        """
        Execute a vision-based desktop task.

        This is the main entry point for the vision agent. It will:
        1. Reset state for a new task
        2. Capture the current screen (or use provided screenshot)
        3. Loop until the task is complete or max retries reached

        Args:
            task: Description of what the user wants to accomplish
            screenshot: Optional pre-captured screenshot

        Returns:
            dict with success, result, and error fields
        """
        reset_state()
        clear_stop_request()
        self.retries = 0
        self.chat_history = []

        try:
            loop_result = await self._call_interaction_loop(task, screenshot)
            if isinstance(loop_result, CuaRunResult):
                return {
                    "success": loop_result.success,
                    "complete": loop_result.complete,
                    "result": loop_result.result,
                    "error": loop_result.error,
                    "critic": asdict(loop_result.critic) if loop_result.critic else None,
                }
            if isinstance(loop_result, Mapping):
                return {
                    "success": bool(loop_result.get("success", True)),
                    "complete": bool(loop_result.get("complete", False)),
                    "result": loop_result.get("result"),
                    "error": loop_result.get("error"),
                    "critic": _critic_payload(loop_result.get("critic")),
                }
            return {
                "success": True,
                "complete": True,
                "result": "Task completed",
                "error": None
            }
        except OpenRouterFallbackError as e:
            return {
                "success": False,
                "complete": False,
                "result": None,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "complete": False,
                "result": None,
                "error": str(e)
            }

    async def _call_interaction_loop(self, task: str, screenshot: Image.Image = None):
        """
        Invoke the interaction loop while preserving older test/plugin shims
        that replaced _interact_with_screen with a one-argument coroutine.
        """
        interact = self._interact_with_screen
        try:
            signature = inspect.signature(interact)
            parameters = list(signature.parameters.values())
            supports_keyword = (
                "screenshot" in signature.parameters
                or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters)
            )
            supports_positional = (
                any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in parameters)
                or len([
                    param
                    for param in parameters
                    if param.kind in {
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    }
                ]) >= 2
            )
        except (TypeError, ValueError):
            supports_keyword = True
            supports_positional = False

        if supports_keyword:
            return await interact(task, screenshot=screenshot)
        if supports_positional:
            return await interact(task, screenshot)
        return await interact(task)

    async def _interact_with_screen(self, task: str, screenshot: Image.Image = None):
        """Run the primary typed controller loop for screen interaction."""
        if _truthy_env(os.getenv("CUA_VISION_USE_LEGACY_ENGINE")):
            print('[VisionAgent] Starting legacy single-call screen interaction...')
            engine = SingleCallVisionEngine(self)
            return await engine.run(task, initial_screenshot=screenshot)

        print('[VisionAgent] Starting controller-based screen interaction...')
        model_policy = CuaModelPolicy.from_env()
        planner = ProviderVisionPlanner(model_policy=model_policy)
        semantic_judge = ProviderSemanticJudge(model_policy=model_policy)
        controller = CuaController(
            backend=PyAutoGuiComputerBackend(
                accessibility_provider=build_accessibility_provider(),
                initial_screenshot=screenshot,
            ),
            planner=planner,
            criticizer=CuaCriticizer(semantic_judge=semantic_judge),
            trajectory=_build_trajectory_recorder(),
            max_actions=_env_int(
                "CUA_VISION_MAX_ACTIONS",
                _env_int("CUA_VISION_MAX_STEPS", 25, minimum=1, maximum=100),
                minimum=1,
                maximum=100,
            ),
            max_retries=_env_int("CUA_VISION_MAX_RETRIES", self.max_retries, minimum=0, maximum=20),
            model_name=self.model_name,
        )
        return await controller.run(task)

    async def look_at_screen_and_respond(self, prompt: str) -> str:
        """
        Look at the current window once and respond.

        This is for simple queries that just need to analyze the screen once
        without taking actions.

        Args:
            prompt: What the user wants to know about the screen

        Returns:
            Response from the model
        """
        print('[VisionAgent] Looking at screen...')

        active_window = get_active_window_title()
        screen_frame = capture_active_window_frame()
        screenshot = screen_frame.image

        system_instruction = LOOK_AT_SCREEN_PROMPT.format(active_window=active_window)

        model_prompt = f"""
        Silently describe everything you see in this image in depth.
        Include all icons, buttons, text, colors, and positions.

        Have you fulfilled the user's goal: {prompt}?

        Rules:
        - When you want to tell the user something, use tts_speak
        - When you need to write something, use type_string
        - Give verbal confirmation once you've executed your task

        Now respond to this prompt: {prompt}
        """

        engine = SingleCallVisionEngine(self)
        response = await engine._generate_provider_step_response(
            model_prompt,
            screenshot,
            system_prompt=system_instruction,
            function_declarations=VISION_FUNCTION_DECLARATIONS,
            temperature=0.2,
            max_tokens=900,
            status_prefix="Analyzing screen",
        )

        # Process function calls
        parts = response.candidates[0].content.parts
        function_calls = [part.function_call for part in parts if part.function_call]

        for function_call in function_calls:
            print(f'[VisionAgent] Function: {function_call.name}')
            try:
                execute_tool_call(
                    function_call.name,
                    function_call.args,
                    screen_frame=screen_frame,
                )
            except ValueError:
                print(f'[VisionAgent] Unknown function: {function_call.name}')

        return response.text if hasattr(response, 'text') else ""

    async def watch_screen_and_respond(self, prompt: str):
        """
        Continuously watch the screen and respond when it changes.

        This will run until the active window changes.

        Args:
            prompt: What the user wants to monitor/respond to
        """
        print('[VisionAgent] Starting screen watch...')

        reset_image_state()
        active_window = get_active_window_title()

        engine = SingleCallVisionEngine(self)

        while get_active_window_title() == active_window:
            time.sleep(0.2)
            screenshot = capture_active_window()

            try:
                if image_change(screenshot):
                    watch_prompt = f"""
                    Describe everything you see in detail.
                    Continue to fulfill the user's request: {prompt}.
                    Analyze ALL text on screen. Translate if not in English.
                    """

                    response = await engine._generate_provider_step_response(
                        watch_prompt,
                        screenshot,
                        system_prompt=WATCH_SCREEN_PROMPT,
                        function_declarations=[],
                        temperature=0.2,
                        max_tokens=900,
                        status_prefix="Watching screen",
                    )

                    if response.text:
                        tts_speak(response.text)

            except Exception as e:
                print(f'[VisionAgent] Watch error: {e}')
                continue

        print('[VisionAgent] Window changed, stopping watch')


# ================================================================================
# CONVENIENCE FUNCTIONS (for backwards compatibility with old Jayu interface)
# ================================================================================

_default_agent = None


def get_default_agent() -> VisionAgent:
    """Get or create the default VisionAgent instance."""
    global _default_agent
    if _default_agent is None:
        _default_agent = VisionAgent()
    return _default_agent


async def start_interact_with_screen(prompt: str):
    """Start interacting with the screen to accomplish a task.

    This is the main entry point matching the old Jayu interface.

    Args:
        prompt: The user's goal/task to accomplish
    """
    agent = get_default_agent()
    await agent.execute(prompt)


async def look_at_screen_and_respond(prompt: str) -> str:
    """Look at the screen once and respond.

    Args:
        prompt: What the user wants to know about the screen
    """
    agent = get_default_agent()
    return await agent.look_at_screen_and_respond(prompt)


async def watch_screen_and_respond(prompt: str):
    """Continuously watch the screen and respond to changes.

    Args:
        prompt: What the user wants to monitor/respond to
    """
    agent = get_default_agent()
    await agent.watch_screen_and_respond(prompt)
