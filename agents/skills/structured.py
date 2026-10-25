"""
Run a structured skill: the model writes a JSON spec, the skill's script builds the file.

This is how a small local model produces documents reliably: it only has to
fill in a schema the skill documents, and tested code does the layout. A spec
that fails validation is retried once with the errors; a second failure
escalates to the stronger brain providers.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

import jsonschema

from agents.cua_cli.workspace_policy import extract_path_candidates_from_task
from agents.skills.registry import SkillEntry

SpecGenerator = Callable[[str, str, bool], Awaitable[str]]

SCRIPT_TIMEOUT_SECONDS = 120
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_FOLDER_WORDS = {"desktop": "Desktop", "downloads": "Downloads", "documents": "Documents"}


class SkillRunError(RuntimeError):
    pass


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in the model reply.")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("The model reply is not a JSON object.")
    return value


def validation_errors(spec: dict[str, Any], schema: dict[str, Any], limit: int = 6) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(spec), key=lambda error: list(error.path))
    return [f"{'/'.join(str(p) for p in error.path) or '(root)'}: {error.message}" for error in errors[:limit]]


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return (slug[:60].rstrip("-") or "jarvis-output")


def resolve_output_path(task: str, title: str, extension: str) -> Path:
    """Where to save: an explicit file or folder in the task, a named home folder, else JARVIS_OUTPUT_DIR."""
    for candidate in extract_path_candidates_from_task(task):
        path = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if path.suffix.lower() == extension and path.parent.is_dir():
            return path
        if path.is_dir():
            return _unique(path / f"{_slug(title)}{extension}")
    lowered = task.lower()
    for word, folder in _FOLDER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered) and (Path.home() / folder).is_dir():
            return _unique(Path.home() / folder / f"{_slug(title)}{extension}")
    configured = os.getenv("JARVIS_OUTPUT_DIR", "").strip()
    base = Path(configured).expanduser() if configured else Path.home() / "Documents" / "Jarvis"
    return _unique(base / f"{_slug(title)}{extension}")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise SkillRunError(f"Could not find a free file name next to {path}")


def spec_prompts(entry: SkillEntry, schema: dict[str, Any], task: str, problems: list[str]) -> tuple[str, str]:
    system = (
        f"You write the JSON input for the '{entry.name}' skill.\n\n"
        f"{entry.manifest.body}\n\n"
        f"JSON Schema the input must satisfy:\n{json.dumps(schema)}\n\n"
        "Reply with ONE JSON object that satisfies the schema. No Markdown fences, no commentary."
    )
    user = f"User request:\n{task}"
    if problems:
        user += "\n\nYour previous JSON was rejected:\n- " + "\n- ".join(problems) + "\nReturn corrected JSON."
    return system, user


async def generate_valid_spec(entry: SkillEntry, schema: dict[str, Any], task: str, generate: SpecGenerator) -> dict[str, Any]:
    problems: list[str] = []
    for attempt in range(3):
        # Attempts: local model, local model with the errors, then a stronger model.
        system, user = spec_prompts(entry, schema, task, problems)
        reply = await generate(system, user, attempt == 2)
        try:
            spec = extract_json_object(reply)
        except (ValueError, json.JSONDecodeError) as exc:
            problems = [str(exc)]
            continue
        problems = validation_errors(spec, schema)
        if not problems:
            return spec
    raise SkillRunError(f"Could not produce valid input for the {entry.name} skill: " + "; ".join(problems))


async def run_entrypoint(entry: SkillEntry, spec: dict[str, Any], output: Path) -> dict[str, Any]:
    if not entry.can_run_scripts:
        raise SkillRunError(
            f"The {entry.name} skill was imported without approving its scripts. "
            f"Re-import it with --with-scripts after reviewing {entry.manifest.directory / 'scripts'}."
        )
    entrypoint = (entry.manifest.directory / str(entry.manifest.jarvis["entrypoint"])).resolve()
    if entry.manifest.directory.resolve() not in entrypoint.parents or not entrypoint.is_file():
        raise SkillRunError(f"Skill entrypoint {entrypoint} is missing or outside the skill folder.")
    with tempfile.TemporaryDirectory(prefix="jarvis-skill-") as scratch:
        spec_path = Path(scratch) / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(entrypoint), "--spec", str(spec_path), "--output", str(output),
            cwd=str(entry.manifest.directory),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=SCRIPT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise SkillRunError(f"The {entry.name} skill script timed out.") from None
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[-800:]
        raise SkillRunError(f"The {entry.name} skill script failed: {detail or f'exit code {process.returncode}'}")
    try:
        result = json.loads(stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        result = {}
    result.setdefault("path", str(output))
    return result


async def run_structured_skill(entry: SkillEntry, task: str, *, generate: SpecGenerator) -> dict[str, Any]:
    """Run a structured skill and return a CLIAgent-style result."""
    schema_path = entry.manifest.directory / str(entry.manifest.jarvis.get("schema") or "schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        spec = await generate_valid_spec(entry, schema, task, generate)
        extension = str(entry.manifest.jarvis.get("output_extension") or "")
        output = resolve_output_path(task, str(spec.get("title") or entry.name), extension)
        built = await run_entrypoint(entry, spec, output)
    except (OSError, json.JSONDecodeError, SkillRunError) as exc:
        return {"success": False, "result": None, "error": str(exc), "skill": entry.name}
    path = str(built["path"])
    return {
        "success": True,
        "result": f"Created {path} with the {entry.name} skill.",
        "error": None,
        "skill": entry.name,
        "output_file_path": path,
        "tool_calls": [
            {
                "tool_name": "write_file",
                "tool_id": f"skill-{entry.name}",
                "parameters": {"file_path": path},
                "result": json.dumps(built),
                "status": "success",
            }
        ],
    }
