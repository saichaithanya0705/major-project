"""
SKILL.md parsing for the agentskills.io format used by OpenJarvis, Hermes,
OpenClaw, Claude Code, and opencode.

Frontmatter fields from the spec (``name``, ``description``, ``license``,
``compatibility``, ``metadata``, ``allowed-tools``) are read as-is. Jarvis
settings live under ``metadata.jarvis``; OpenJarvis' ``required_capabilities``
(top level or under ``metadata.openjarvis``) is honored for trust checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9]))*$")
DANGEROUS_CAPABILITIES = frozenset({"shell:execute", "network:listen", "filesystem:write"})


class SkillParseError(ValueError):
    pass


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str
    body: str
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def jarvis(self) -> dict[str, Any]:
        value = self.metadata.get("jarvis")
        return value if isinstance(value, dict) else {}

    @property
    def is_structured(self) -> bool:
        return self.jarvis.get("kind") == "structured" and bool(self.jarvis.get("entrypoint"))

    @property
    def triggers(self) -> tuple[re.Pattern[str], ...]:
        patterns = self.jarvis.get("triggers") or []
        compiled = []
        for pattern in patterns if isinstance(patterns, list) else []:
            try:
                compiled.append(re.compile(str(pattern), re.IGNORECASE))
            except re.error:
                continue
        return tuple(compiled)

    @property
    def dangerous_capabilities(self) -> tuple[str, ...]:
        return tuple(cap for cap in self.required_capabilities if cap in DANGEROUS_CAPABILITIES)


def split_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        return {}, raw
    rest = raw[3:].lstrip("\r\n")
    end = re.search(r"\r?\n---[ \t]*(?:\r?\n|$)", rest)
    if not end:
        return {}, raw
    try:
        frontmatter = yaml.safe_load(rest[: end.start()]) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Invalid YAML frontmatter: {exc}") from exc
    if not isinstance(frontmatter, dict):
        raise SkillParseError("Frontmatter must be a mapping")
    return frontmatter, rest[end.end():]


def parse_skill_file(path: Path) -> SkillManifest:
    raw = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(raw)
    name = str(frontmatter.get("name") or path.parent.name).strip()
    description = str(frontmatter.get("description") or "").strip()
    if not _NAME_PATTERN.match(name) or len(name) > MAX_NAME_LENGTH:
        raise SkillParseError(
            f"Skill name {name!r} must be 1-{MAX_NAME_LENGTH} lowercase letters, digits, or single hyphens"
        )
    if not description:
        raise SkillParseError(f"Skill {name!r} has no description")
    metadata = frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else {}
    openjarvis = metadata.get("openjarvis") if isinstance(metadata.get("openjarvis"), dict) else {}
    capabilities = frontmatter.get("required_capabilities") or openjarvis.get("required_capabilities") or []
    return SkillManifest(
        name=name,
        description=description[:MAX_DESCRIPTION_LENGTH],
        body=body.strip(),
        path=path,
        metadata=metadata,
        required_capabilities=tuple(str(cap) for cap in capabilities if cap) if isinstance(capabilities, list) else (),
    )
