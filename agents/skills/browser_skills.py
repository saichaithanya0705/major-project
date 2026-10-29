"""Portable instruction skills for browser tasks; no script execution.

The legacy registry's consumers and trust policy are deliberately unchanged.
External skills are enabled explicitly and pinned to their entire bounded tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agents.skills.manifest import SkillManifest, parse_skill_file, split_frontmatter
from agents.skills.registry import SkillEntry, SkillRegistry


def _reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _files(directory: Path) -> dict[str, bytes]:
    if _reparse(directory):
        raise ValueError("Skill folders must not be links or junctions.")
    root = directory.resolve()
    files: dict[str, bytes] = {}
    total = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        here = Path(current)
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if len(here.relative_to(root).parts) > 4:
            raise ValueError("Skill resources exceed the maximum directory depth.")
        for name in [*dirs, *names]:
            path = here / name
            if _reparse(path) or not path.resolve().is_relative_to(root):
                raise ValueError("Skill resources must stay inside their folder without links.")
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = here / name
            size = path.stat().st_size
            total += size
            if size > 65536 or total > 262144 or len(files) >= 80:
                raise ValueError("Skill resources exceed size/count limits.")
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _digest(files: dict[str, bytes]) -> str:
    value = hashlib.sha256()
    for name, data in sorted(files.items()):
        value.update(name.encode() + b"\0" + data + b"\0")
    return value.hexdigest()


def _standard(path: Path) -> tuple[SkillManifest, str | None]:
    raw = path.read_text(encoding="utf-8")
    if len(raw.encode()) > 65536:
        raise ValueError("SKILL.md exceeds 64 KiB.")
    front, _ = split_frontmatter(raw)
    manifest = parse_skill_file(path)
    if manifest.name != path.parent.name or not isinstance(front.get("name"), str):
        raise ValueError("Skill name must be explicit and match its folder.")
    description = front.get("description")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
        raise ValueError("Skill description must contain 1-1024 characters.")
    metadata = front.get("metadata", {})
    if not isinstance(metadata, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items()):
        raise ValueError("Standard metadata must contain string keys and values.")
    for key, limit in (("compatibility", 500), ("license", 1024)):
        if key in front and (not isinstance(front[key], str) or not 1 <= len(front[key]) <= limit):
            raise ValueError(f"Invalid standard {key} field.")
    allowed = front.get("allowed-tools")
    if allowed is not None and not isinstance(allowed, str):
        raise ValueError("allowed-tools must be a space-separated string.")
    return manifest, allowed


@dataclass
class _Instruction:
    manifest: SkillManifest
    digest: str
    allowed: str | None


class BrowserSkills:
    def __init__(self, project_root: Path, *, home: Path | None = None):
        self.root = Path(project_root).resolve()
        self.home = Path(home) if home is not None else Path.home()
        self.trust_path = self.home / ".jarvis" / "browser-skill-trust.json"
        self.errors: list[str] = []
        self.entries: dict[str, _Instruction] = {}
        self.active: dict[str, dict[str, bytes]] = {}
        self.allowed_tools: set[str] | None = None
        self._discover()

    def _trusted(self) -> dict:
        try:
            value = json.loads(self.trust_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _roots(self):
        configured = os.getenv("JARVIS_SKILLS_DIR", "").strip()
        return [Path(configured).expanduser() if configured else self.home / ".jarvis" / "skills",
                self.root / ".agents" / "skills", self.home / ".agents" / "skills", self.root / "skills"]

    def _discover(self):
        trusted, seen = self._trusted(), set()
        bundled = (self.root / "skills").resolve()
        for root in self._roots():
            if not root.is_dir() or root.resolve() in seen:
                continue
            seen.add(root.resolve())
            for path in sorted(root.glob("*/SKILL.md")):
                try:
                    # Existing structured document skills retain their legacy parser.
                    if parse_skill_file(path).is_structured:
                        continue
                    manifest, allowed = _standard(path)
                    key = str(path.parent.resolve())
                    is_bundled = path.parent.resolve().is_relative_to(bundled)
                    if not is_bundled and key not in trusted:
                        continue
                    fingerprint = _digest(_files(path.parent))
                    if not is_bundled and trusted.get(key) != fingerprint:
                        self.errors.append(f"{manifest.name}: edited external skill needs explicit re-enabling.")
                        continue
                    if manifest.name in self.entries:
                        self.errors.append(f"{manifest.name}: lower-precedence name collision ignored.")
                        continue
                    self.entries[manifest.name] = _Instruction(manifest, fingerprint, allowed)
                except (OSError, ValueError) as exc:
                    self.errors.append(f"{path.parent.name}: {exc}")

    def trust(self, path: Path) -> str:
        directory = Path(path).expanduser()
        if directory.is_file():
            directory = directory.parent
        _standard(directory / "SKILL.md")
        fingerprint = _digest(_files(directory))
        trusted = self._trusted()
        trusted[str(directory.resolve())] = fingerprint
        self.trust_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.trust_path.parent, prefix=".browser-skill-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(trusted, stream, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.trust_path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return fingerprint

    def catalog(self, task: str) -> str:
        registry = self._registry()
        selected = registry.relevant_skills(task, limit=5)
        base = registry.get("browser-operator")
        explicit = registry.explicit_skill(task)
        entries = {entry.name: entry for entry in [*selected, *([base] if base else []), *([explicit] if explicit else [])]}
        return "\n".join(f"{e.name}: {e.manifest.description}" for e in entries.values())[:6500]

    def _registry(self) -> SkillRegistry:
        return SkillRegistry([SkillEntry(e.manifest, "workspace", False) for e in self.entries.values()])

    def explicit_name(self, task: str) -> str | None:
        entry = self._registry().explicit_skill(task)
        return entry.name if entry else None

    def activate_for_task(self, task: str) -> dict[str, str]:
        """Activate the bounded base skill and one trusted task specialization."""
        instructions: dict[str, str] = {}
        if "browser-operator" in self.entries:
            instructions["browser-operator"] = self.activate("browser-operator")

        registry = self._registry()
        explicit = registry.explicit_skill(task)
        selected = explicit
        if selected is None:
            selected = next(
                (
                    entry
                    for entry in registry.relevant_skills(task, limit=5)
                    if entry.name != "browser-operator"
                ),
                None,
            )
        if selected is not None and selected.name not in instructions:
            instructions[selected.name] = self.activate(selected.name)
        return instructions

    def activate(self, name: str) -> str:
        if name not in self.active:
            entry = self.entries.get(name)
            if entry is None:
                raise ValueError("This browser skill is unavailable, invalid, or not enabled.")
            files = _files(entry.manifest.directory)
            if _digest(files) != entry.digest:
                raise ValueError("The skill changed before activation; reload it for the next task.")
            if entry.allowed is not None:
                from agents.browser.connected_gateway import TOOLS
                names = set(entry.allowed.split())
                if not names <= TOOLS:
                    raise ValueError("Unsupported allowed-tools; browser skills accept exact exposed tool names only.")
                self.allowed_tools = names if self.allowed_tools is None else self.allowed_tools & names
            self.active[name] = files
        _, body = split_frontmatter(self.active[name]["SKILL.md"].decode("utf-8"))
        return body.strip()

    def resource(self, name: str, relative_path: str) -> str:
        path = PurePosixPath(relative_path.replace("\\", "/"))
        if name not in self.active or path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in {"references", "assets"}:
            raise ValueError("Only references/assets inside an activated skill may be read.")
        data = self.active[name].get(path.as_posix())
        if data is None:
            raise ValueError("Skill resource not found.")
        try:
            return data.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError("This resource is not a text document.") from exc
