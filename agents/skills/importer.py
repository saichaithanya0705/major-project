"""
Import skills from other ecosystems into ``JARVIS_SKILLS_DIR/imported``.

Sources:
- a local folder (one skill or a tree of skills),
- ``github:owner/repo[/path][@ref]`` or a github.com URL,
- ``hermes:<name>`` from NousResearch/hermes-agent,
- ``openclaw:<owner>/<name>`` from openclaw/skills,
- ``openjarvis[:<name>]`` from a local OpenJarvis install
  (``$OPENJARVIS_HOME``, ``$XDG_DATA_HOME/openjarvis``, or ``~/.openjarvis``).

Safety rules follow OpenJarvis: scripts are not copied unless approved, symlinks
are rejected, and skills declaring dangerous capabilities need confirmation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agents.skills.manifest import SkillParseError, parse_skill_file
from agents.skills.registry import PROVENANCE_FILE, user_skills_dir

HERMES_REPO = "NousResearch/hermes-agent"
OPENCLAW_REPO = "openclaw/skills"
MAX_SKILL_BYTES = 20 * 1024 * 1024
MAX_SKILL_FILES = 500
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".js", ".mjs", ".ts", ".rb", ".pl", ".exe"}
_GITHUB_URL = re.compile(r"^https?://github\.com/(?P<repo>[\w.-]+/[\w.-]+?)(?:\.git)?(?:/tree/(?P<ref>[^/]+)(?:/(?P<path>.+))?)?/?$")
_GITHUB_SPEC = re.compile(r"^github:(?P<repo>[\w.-]+/[\w.-]+)(?:/(?P<path>[^@]+))?(?:@(?P<ref>.+))?$")


class SkillImportError(RuntimeError):
    pass


@dataclass
class ImportOutcome:
    name: str
    target: Path | None = None
    imported: bool = False
    skipped_reason: str = ""
    scripts_imported: bool = False
    warnings: list[str] = field(default_factory=list)


def openjarvis_home() -> Path:
    if os.getenv("OPENJARVIS_HOME"):
        return Path(os.environ["OPENJARVIS_HOME"]).expanduser()
    if os.getenv("XDG_DATA_HOME"):
        candidate = Path(os.environ["XDG_DATA_HOME"]).expanduser() / "openjarvis"
        if candidate.exists():
            return candidate
    return Path.home() / ".openjarvis"


def _is_script(path: Path, skill_root: Path) -> bool:
    relative = path.relative_to(skill_root)
    return relative.parts[0] == "scripts" or path.suffix.lower() in SCRIPT_SUFFIXES


def _check_tree(skill_dir: Path) -> None:
    total = 0
    files = 0
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            raise SkillImportError(f"{path} is a symlink; imported skills must not point outside their folder.")
        if path.is_file():
            files += 1
            total += path.stat().st_size
    if files > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
        raise SkillImportError(f"{skill_dir} is too large ({files} files, {total} bytes).")


def _skill_dirs(root: Path, name: str | None) -> list[Path]:
    if (root / "SKILL.md").is_file():
        candidates = [root]
    else:
        candidates = sorted({path.parent for path in root.rglob("SKILL.md") if ".git" not in path.parts})
    if name:
        candidates = [path for path in candidates if path.name == name or _manifest_name(path) == name]
    return candidates


def _manifest_name(skill_dir: Path) -> str:
    try:
        return parse_skill_file(skill_dir / "SKILL.md").name
    except (OSError, SkillParseError):
        return ""


def install_skill_dir(
    skill_dir: Path,
    *,
    source: str,
    origin: str,
    with_scripts: bool = False,
    confirm_dangerous: bool = False,
    force: bool = False,
    target_root: Path | None = None,
) -> ImportOutcome:
    try:
        manifest = parse_skill_file(skill_dir / "SKILL.md")
    except (OSError, SkillParseError) as exc:
        return ImportOutcome(name=skill_dir.name, skipped_reason=f"invalid SKILL.md: {exc}")
    outcome = ImportOutcome(name=manifest.name)
    if manifest.dangerous_capabilities and not confirm_dangerous:
        outcome.skipped_reason = (
            f"requests dangerous capabilities {list(manifest.dangerous_capabilities)}; "
            "re-run with --yes-dangerous only if you trust the source"
        )
        return outcome
    try:
        _check_tree(skill_dir)
    except SkillImportError as exc:
        outcome.skipped_reason = str(exc)
        return outcome

    target = (target_root or user_skills_dir()) / "imported" / re.sub(r"[^\w.-]+", "-", source) / manifest.name
    outcome.target = target
    if target.exists():
        if not force:
            outcome.skipped_reason = f"already installed at {target} (use --force to replace)"
            return outcome
        shutil.rmtree(target)

    script_files = [path for path in skill_dir.rglob("*") if path.is_file() and _is_script(path, skill_dir)]
    for path in skill_dir.rglob("*"):
        if not path.is_file() or ".git" in path.relative_to(skill_dir).parts:
            continue
        if not with_scripts and path in script_files:
            continue
        destination = target / path.relative_to(skill_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    if script_files and not with_scripts:
        outcome.warnings.append(f"{len(script_files)} script file(s) not imported; review them and re-import with --with-scripts to enable.")
    if manifest.is_structured and not with_scripts:
        outcome.warnings.append("This is a structured skill; it cannot run until its scripts are imported.")

    (target / PROVENANCE_FILE).write_text(
        json.dumps(
            {
                "source": source,
                "origin": origin,
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "scripts_approved": bool(with_scripts and script_files),
                "dangerous_capabilities": list(manifest.dangerous_capabilities),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    outcome.imported = True
    outcome.scripts_imported = bool(with_scripts and script_files)
    return outcome


def _clone(repo: str, ref: str | None, destination: Path) -> None:
    if not shutil.which("git"):
        raise SkillImportError("git is required to import skills from GitHub.")
    command = ["git", "clone", "--depth", "1", "--quiet"]
    if ref:
        command += ["--branch", ref]
    command += [f"https://github.com/{repo}.git", str(destination)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise SkillImportError(f"git clone of {repo} failed: {completed.stderr.strip()[-400:]}")


@dataclass(frozen=True)
class SourceSpec:
    kind: str  # "github" or "local"
    location: str  # owner/repo or a filesystem path
    label: str  # folder name under imported/: hermes, openclaw, openjarvis, <owner>, local
    subpath: str | None = None
    ref: str | None = None
    name: str | None = None


def resolve_source(spec: str) -> SourceSpec:
    if spec.startswith("hermes:"):
        return SourceSpec("github", HERMES_REPO, "hermes", subpath="skills", name=spec.split(":", 1)[1] or None)
    if spec.startswith("openclaw:"):
        owner_and_name = spec.split(":", 1)[1].strip("/")
        if owner_and_name.count("/") != 1:
            raise SkillImportError("Use openclaw:<owner>/<skill-name>.")
        return SourceSpec("github", OPENCLAW_REPO, "openclaw", subpath=f"skills/{owner_and_name}")
    if spec == "openjarvis" or spec.startswith("openjarvis:"):
        name = spec.split(":", 1)[1] if ":" in spec else ""
        return SourceSpec("local", str(openjarvis_home() / "skills"), "openjarvis", name=name or None)
    match = _GITHUB_SPEC.match(spec) or _GITHUB_URL.match(spec)
    if match:
        repo = match.group("repo")
        return SourceSpec("github", repo, repo.split("/")[0], subpath=match.group("path"), ref=match.group("ref"))
    return SourceSpec("local", spec, "local")


def import_skills(
    spec: str,
    *,
    name: str | None = None,
    with_scripts: bool = False,
    confirm_dangerous: bool = False,
    force: bool = False,
    target_root: Path | None = None,
) -> list[ImportOutcome]:
    source = resolve_source(spec)
    wanted = name or source.name
    with tempfile.TemporaryDirectory(prefix="jarvis-skill-import-") as scratch:
        if source.kind == "github":
            root = Path(scratch) / "repo"
            _clone(source.location, source.ref, root)
            origin = f"https://github.com/{source.location}"
            if source.ref:
                origin += f"/tree/{source.ref}"
            if source.subpath:
                root = root / source.subpath
                origin += f"/{source.subpath}"
        else:
            root = Path(source.location).expanduser()
            origin = str(root.resolve()) if root.exists() else str(root)
        if not root.exists():
            raise SkillImportError(f"{root} does not exist.")
        skill_dirs = [path for path in _skill_dirs(root, wanted) if "skill-cache" not in path.parts]
        if not skill_dirs:
            raise SkillImportError(f"No SKILL.md found in {origin}" + (f" named {wanted!r}" if wanted else "") + ".")
        return [
            install_skill_dir(
                skill_dir,
                source=source.label,
                origin=origin,
                with_scripts=with_scripts,
                confirm_dangerous=confirm_dangerous,
                force=force,
                target_root=target_root,
            )
            for skill_dir in skill_dirs
        ]
