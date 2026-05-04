"""
Vision Agent - Desktop control via screen understanding + mouse/keyboard.

This agent can see the user's screen and interact with it by clicking elements,
typing, and using keyboard shortcuts. It uses a vision model to understand
what's on screen and decide what actions to take.
"""
import time

from dotenv import load_dotenv
from PIL import Image

from agents.cua_vision.tools import (
    reset_state,
    clear_stop_request,
    capture_active_window,
    get_active_window_title,
    execute_tool_call,
)
from integrations.audio import tts_speak
from agents.cua_vision.single_call import OpenRouterFallbackError, SingleCallVisionEngine
from agents.cua_vision.tool_declarations import VISION_FUNCTION_DECLARATIONS
from agents.cua_vision.prompts import (
    LOOK_AT_SCREEN_PROMPT,
    WATCH_SCREEN_PROMPT,
)
from agents.cua_vision.image import image_change, reset_image_state

load_dotenv()


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
            await self._interact_with_screen(task)
            return {
                "success": True,
                "result": "Task completed",
                "error": None
            }
        except OpenRouterFallbackError as e:
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "result": None,
                "error": str(e)
            }

    async def _interact_with_screen(self, task: str):
        """Run the primary single-call execution loop for screen interaction."""
        print('[VisionAgent] Starting single-call screen interaction...')
        engine = SingleCallVisionEngine(self)
        await engine.run(task)

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
        screenshot = capture_active_window()

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
                execute_tool_call(function_call.name, function_call.args)
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
