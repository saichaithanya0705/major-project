"""
Run a coding CLI once and return its final reply.

Used to ask a signed-in CLI (Claude Code, Codex CLI, Copilot CLI) a question in
answer-only mode, without the terminal transcript and process tracking that
CLIAgent adds for desktop tasks.
"""

from __future__ import annotations

import asyncio
import json

from agents.cua_cli.backends.base import (
    BackendRequest,
    CodingBackend,
    NormalizationState,
)
from agents.cua_cli.response_parser import parse_stream_json_response


class BackendAnswerError(RuntimeError):
    """The CLI ran but did not produce a usable answer."""


async def run_backend_for_answer(backend: CodingBackend, request: BackendRequest, *, timeout: float) -> str:
    invocation = backend.invocation(request)
    process = await asyncio.create_subprocess_exec(
        *invocation.argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=invocation.cwd,
        env=invocation.env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(invocation.stdin_text.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise BackendAnswerError(f"{backend.display_name} timed out after {timeout:.0f} seconds.") from None

    state = NormalizationState()
    events: list[dict] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            events.extend(backend.normalize_event(raw, state))
    stderr_text = stderr.decode("utf-8", errors="replace")
    events.extend(backend.finalize(state, process.returncode or 0, stderr_text))

    parsed = parse_stream_json_response(
        stdout="\n".join(json.dumps(event) for event in events),
        stderr=stderr_text,
        returncode=process.returncode or 0,
    )
    answer = str(parsed.get("output") or "").strip()
    if not answer:
        raise BackendAnswerError(str(parsed.get("error") or f"{backend.display_name} returned no answer."))
    return answer
