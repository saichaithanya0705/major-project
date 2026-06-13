"""JARVIS screen-response runtime for GeminiModel objects."""

from __future__ import annotations

import time
from typing import Any

from PIL import Image

from agents.jarvis.policy import validate_jarvis_function_calls
from agents.jarvis.tool_declarations import JARVIS_FUNCTION_DECLARATIONS
from agents.jarvis.tools import JARVIS_TOOL_MAP
from models.model_status import set_model_label
from models.routing_prompt_parser import (
    extract_latest_request_from_router_prompt as _extract_latest_request,
)
from models.text_normalization import clean_text as _clean_text


async def generate_jarvis_response(
    model: Any,
    prompt: str,
    image: Image = None,
) -> dict[str, Any]:
    """
    Call the JARVIS model with full screen annotation capabilities.
    """
    print("[JARVIS] Processing with screenshot...")
    started = time.monotonic()
    await set_model_label(model.jarvis_model, context="jarvis_response")

    contents = [prompt]
    if image:
        contents.append(image)

    try:
        response = await model.client.aio.models.generate_content(
            model=model.jarvis_model,
            contents=contents,
            config=model.jarvis_config,
        )
    except Exception as exc:
        if (
            model._is_gemini_temporary_error(exc)
            and model.gemini_backup_model
            and model.gemini_backup_model != model.jarvis_model
        ):
            print(
                f"[JARVIS] Primary model unavailable; retrying with backup "
                f"{model.gemini_backup_model}"
            )
            response = await model.client.aio.models.generate_content(
                model=model.gemini_backup_model,
                contents=contents,
                config=model.jarvis_config,
            )
            model.jarvis_model = model.gemini_backup_model
        elif model._is_gemini_quota_error(exc):
            fallback_response = await model._try_openrouter_tool_fallback(
                label="JARVIS",
                system_prompt=(
                    "You are JARVIS, a screen annotation assistant. "
                    "Use the available tools when annotation or direct response is needed."
                ),
                user_prompt=prompt,
                function_declarations=JARVIS_FUNCTION_DECLARATIONS,
                image=image,
                temperature=0.2,
                max_tokens=1800,
                purpose="jarvis",
            )
            if fallback_response is not None:
                response = fallback_response
            else:
                fallback_text = await model._try_openrouter_text_fallback(
                    label="JARVIS",
                    system_prompt=(
                        "You are JARVIS fallback. Give a concise response to the user request."
                    ),
                    user_prompt=_extract_latest_request(prompt),
                    temperature=0.2,
                    max_tokens=700,
                    purpose="jarvis",
                    image=image,
                )
                if fallback_text:
                    return {
                        "response": None,
                        "summary": _clean_text(
                            f"Gemini quota reached. {fallback_text}",
                            "Gemini quota reached. Please retry shortly.",
                            max_len=420,
                        ),
                    }
        else:
            raise
    elapsed = time.monotonic() - started
    print(
        f"[JARVIS] Model call completed in {elapsed:.2f}s "
        f"(thinking_budget={model.jarvis_thinking_budget})"
    )

    parts = response.candidates[0].content.parts
    function_calls = [part.function_call for part in parts if part.function_call]
    summary_text = None
    validated_calls = []

    if function_calls:
        validated_calls = validate_jarvis_function_calls(function_calls, JARVIS_TOOL_MAP)
        for tool_name, args in validated_calls:
            print(f"\n[JARVIS] Function: {tool_name}")
            print(f"[JARVIS] Arguments: {args}")

            if tool_name == "direct_response":
                summary_text = args.get("text") or summary_text

            tool = JARVIS_TOOL_MAP.get(tool_name)
            if tool:
                tool(**args)
            else:
                raise Exception(f"[JARVIS] Invalid tool: {tool_name}")
    else:
        print("[JARVIS] No function call in response")
        if response.text:
            print(response.text)
            summary_text = response.text

    return {
        "response": response,
        "summary": _clean_text(summary_text, "", max_len=420),
        "function_calls": validated_calls,
    }
