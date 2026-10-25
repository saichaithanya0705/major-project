"""
Skill discovery, trust tiers, and request matching.

Skills are found in:
- ``skills/`` in this repository (tier ``bundled``),
- ``JARVIS_SKILLS_DIR`` (default ``~/.jarvis/skills``): folders you write
  yourself (tier ``workspace``) and folders installed by the importer, which
  carry a ``.jarvis-source.json`` provenance file (tier ``imported``).

When names collide, workspace beats bundled beats imported. Scripts of an
imported skill only run if its scripts were approved at import time.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agents.skills.manifest import SkillManifest, SkillParseError, parse_skill_file

BUNDLED_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
PROVENANCE_FILE = ".jarvis-source.json"
_TIER_PRIORITY = {"workspace": 0, "bundled": 1, "imported": 2}
_MAX_SEARCH_DEPTH = 4

_CREATE_INTENT = re.compile(
    r"\b(?:create|make|generate|build|write|prepare|draft|produce|design|compile|export|"
    r"put together|turn\b.*\binto|save\b.*\bas|convert\b.*\b(?:to|into))\b",
    re.IGNORECASE,
)
_EXPLICIT_SKILL = re.compile(
    r"(?:\b(?:use|using|with|run)\s+(?:the\s+|my\s+)?(?P<a>[a-z0-9][a-z0-9-]*)\s+skill\b|"
    r"(?:^|\s)/(?P<b>[a-z0-9][a-z0-9-]*)\b|\bskill:(?P<c>[a-z0-9][a-z0-9-]*)\b)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and any are as at be by can do for from get how i in into is it me my of on or our please "
    "should so that the this to up use using want when with you your".split()
)


def user_skills_dir() -> Path:
    configured = os.getenv("JARVIS_SKILLS_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".jarvis" / "skills"


@dataclass(frozen=True)
class SkillEntry:
    manifest: SkillManifest
    tier: str
    scripts_approved: bool
    source: str = ""

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def can_run_scripts(self) -> bool:
        return self.tier in {"bundled", "workspace"} or self.scripts_approved


def _skill_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("SKILL.md")):
        relative = path.relative_to(root)
        if len(relative.parts) - 1 > _MAX_SEARCH_DEPTH or any(part.startswith(".") for part in relative.parts):
            continue
        found.append(path)
    return found


def _read_provenance(skill_dir: Path) -> dict | None:
    provenance = skill_dir / PROVENANCE_FILE
    if not provenance.is_file():
        return None
    try:
        data = json.loads(provenance.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS and len(word) > 2}


class SkillRegistry:
    def __init__(self, entries: list[SkillEntry], errors: list[str] | None = None) -> None:
        self._entries = {entry.name: entry for entry in entries}
        self.errors = list(errors or [])

    @classmethod
    def discover(cls, *, bundled_dir: Path | None = None, user_dir: Path | None = None) -> "SkillRegistry":
        candidates: list[SkillEntry] = []
        errors: list[str] = []
        for root, default_tier in ((bundled_dir or BUNDLED_SKILLS_DIR, "bundled"), (user_dir or user_skills_dir(), "workspace")):
            for path in _skill_files(root):
                try:
                    manifest = parse_skill_file(path)
                except (OSError, SkillParseError) as exc:
                    errors.append(f"{path}: {exc}")
                    continue
                provenance = _read_provenance(path.parent) if default_tier == "workspace" else None
                if provenance is None:
                    candidates.append(SkillEntry(manifest, default_tier, scripts_approved=False))
                else:
                    candidates.append(
                        SkillEntry(
                            manifest,
                            "imported",
                            scripts_approved=bool(provenance.get("scripts_approved")),
                            source=str(provenance.get("source") or ""),
                        )
                    )
        candidates.sort(key=lambda entry: _TIER_PRIORITY[entry.tier])
        chosen: dict[str, SkillEntry] = {}
        for entry in candidates:
            chosen.setdefault(entry.name, entry)
        return cls(list(chosen.values()), errors)

    def all(self) -> list[SkillEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.name)

    def get(self, name: str) -> SkillEntry | None:
        return self._entries.get(name.lower())

    def explicit_skill(self, task: str) -> SkillEntry | None:
        """A skill the user named: "use the pptx skill", "/pptx", or "skill:pptx"."""
        for match in _EXPLICIT_SKILL.finditer(task or ""):
            name = (match.group("a") or match.group("b") or match.group("c") or "").lower()
            if name in self._entries:
                return self._entries[name]
        return None

    def structured_skill_for(self, task: str) -> SkillEntry | None:
        """The structured skill a creation request asks for, by its earliest trigger."""
        explicit = self.explicit_skill(task)
        if explicit is not None and explicit.manifest.is_structured:
            return explicit
        if not _CREATE_INTENT.search(task or ""):
            return None
        best: tuple[int, SkillEntry] | None = None
        for entry in self._entries.values():
            if not entry.manifest.is_structured:
                continue
            for pattern in entry.manifest.triggers:
                match = pattern.search(task)
                if match and (best is None or match.start() < best[0]):
                    best = (match.start(), entry)
        return best[1] if best else None

    def relevant_skills(self, task: str, *, limit: int = 5) -> list[SkillEntry]:
        """Instruction skills whose name or description overlaps the task."""
        task_words = _words(task)
        scored = []
        for entry in self._entries.values():
            if entry.manifest.is_structured:
                continue
            name_words = _words(entry.name.replace("-", " "))
            score = 2 * len(task_words & name_words) + len(task_words & _words(entry.manifest.description))
            if score >= 2:
                scored.append((score, entry.name, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _, _, entry in scored[:limit]]
