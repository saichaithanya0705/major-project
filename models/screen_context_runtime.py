"""Screen-context extraction runtime for GeminiModel objects."""

from __future__ import annotations

import json
import time
from typing import Any

from PIL import Image

from models.routing_payload_parser import parse_json_object as _parse_json_object_from_text
from models.routing_payload_parser import ScreenContextPayload
from models.screen_context_policy import normalize_screen_context_payload as _normalize_screen_context_payload
from models.text_normalization import clean_text as _clean_text


async def generate_screen_context(
    model: Any,
    user_request: str,
    image: Image = None,
    focus: str = "",
) -> ScreenContextPayload:
    """
    Run one multimodal pass to extract concrete screen context for routing.
    """
    print("[ScreenJudge] Capturing context from screenshot...")
    started = time.monotonic()
    focus_text = _clean_text(focus, "", max_len=200)
    judge_prompt = (
        "You are Screen Judge for a computer-use orchestrator.\n"
        "Analyze the screenshot and extract only high-signal routing context.\n"
        "Return JSON ONLY, no markdown.\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "summary": "short factual summary",\n'
        '  "repo_url": "github/git url if visible else empty string",\n'
        '  "local_url": "localhost/127.0.0.1 URL if visible else empty string",\n'
        '  "recommended_agent": "cua_cli|cua_vision|browser|jarvis|direct",\n'
        '  "recommended_task": "single concrete next step task",\n'
        '  "hints": "short extra details useful for routing"\n'
        "}\n\n"
        f"User request: {user_request}\n"
        f"Extraction focus: {focus_text if focus_text else 'general execution context'}\n"
        "Do not invent URLs. If uncertain, leave fields empty."
    )

    contents = [judge_prompt]
    if image is not None:
        contents.append(image)

    try:
        response = await model.client.aio.models.generate_content(
            model=model.screen_judge_model,
            contents=contents,
            config=model.screen_judge_config,
        )
    except Exception as exc:
        if (
            model._is_gemini_temporary_error(exc)
            and model.gemini_backup_model
            and model.gemini_backup_model != model.screen_judge_model
        ):
            print(
                f"[ScreenJudge] Primary model unavailable; retrying with backup "
                f"{model.gemini_backup_model}"
            )
            response = await model.client.aio.models.generate_content(
                model=model.gemini_backup_model,
                contents=contents,
                config=model.screen_judge_config,
            )
            model.screen_judge_model = model.gemini_backup_model
        elif model._is_gemini_quota_error(exc):
            fallback_text = await model._try_openrouter_text_fallback(
                label="ScreenJudge",
                system_prompt=(
                    "You are Screen Judge for a computer-use orchestrator.\n"
                    "Analyze the screenshot when one is attached.\n"
                    "Return JSON only with fields: summary, repo_url, local_url,"
                    " recommended_agent, recommended_task, hints.\n"
                    "If you are uncertain, keep fields empty and explain uncertainty in"
                    " summary."
                ),
                user_prompt=(
                    f"User request: {user_request}\n"
                    f"Focus: {focus_text if focus_text else 'general execution context'}\n"
                    "Extract only high-signal routing context."
                ),
                temperature=0.1,
                max_tokens=420,
                purpose="screen",
                image=image,
                response_format={"type": "json_object"},
            )
            if fallback_text:
                parsed = _parse_json_object_from_text(fallback_text)
                normalized = _normalize_screen_context_payload(
                    parsed,
                    user_request=user_request,
                )
                if not normalized.get("summary"):
                    normalized["summary"] = _clean_text(
                        fallback_text,
                        "Gemini screen context hit quota. Used text-only fallback.",
                        max_len=420,
                    )
                normalized["model"] = f"{model.openrouter_model} (openrouter_fallback)"
                return normalized
            raise
        else:
            raise
    elapsed = time.monotonic() - started
    print(f"[ScreenJudge] Completed in {elapsed:.2f}s")

    raw_text = ""
    if hasattr(response, "text") and response.text:
        raw_text = str(response.text)
    else:
        try:
            raw_text = json.dumps(response.to_dict())
        except Exception:
            raw_text = ""

    parsed = _parse_json_object_from_text(raw_text)
    normalized = _normalize_screen_context_payload(parsed, user_request=user_request)
    if not normalized.get("summary"):
        normalized["summary"] = _clean_text(raw_text, "Screen context captured.", max_len=420)
    normalized["model"] = model.screen_judge_model
    return normalized
