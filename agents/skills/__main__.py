"""
Manage Jarvis skills.

    python -m agents.skills list
    python -m agents.skills show pptx
    python -m agents.skills import hermes:arxiv
    python -m agents.skills import openjarvis               # everything from a local OpenJarvis install
    python -m agents.skills import github:owner/repo/skills --name my-skill --with-scripts
    python -m agents.skills remove my-skill
"""

from __future__ import annotations

import argparse
import shutil
import sys

from agents.skills.importer import SkillImportError, import_skills
from agents.skills.registry import SkillRegistry


def _list(_: argparse.Namespace) -> int:
    registry = SkillRegistry.discover()
    for entry in registry.all():
        kind = "structured" if entry.manifest.is_structured else "instructions"
        scripts = "" if entry.can_run_scripts or not (entry.manifest.directory / "scripts").exists() else " [scripts not approved]"
        print(f"{entry.name:28} {entry.tier:9} {kind:12} {entry.manifest.description[:70]}{scripts}")
    for error in registry.errors:
        print(f"! {error}", file=sys.stderr)
    return 0


def _show(args: argparse.Namespace) -> int:
    entry = SkillRegistry.discover().get(args.name)
    if entry is None:
        print(f"No skill named {args.name!r}.", file=sys.stderr)
        return 1
    print(f"{entry.name} ({entry.tier}{', ' + entry.source if entry.source else ''})\n{entry.manifest.path}\n")
    print(entry.manifest.body)
    return 0


def _import(args: argparse.Namespace) -> int:
    try:
        outcomes = import_skills(
            args.source,
            name=args.name,
            with_scripts=args.with_scripts,
            confirm_dangerous=args.yes_dangerous,
            force=args.force,
        )
    except SkillImportError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    failed = 0
    for outcome in outcomes:
        if outcome.imported:
            print(f"+ {outcome.name} -> {outcome.target}")
        else:
            failed += 1
            print(f"- {outcome.name}: {outcome.skipped_reason}")
        for warning in outcome.warnings:
            print(f"    {warning}")
    return 1 if failed and failed == len(outcomes) else 0


def _remove(args: argparse.Namespace) -> int:
    entry = SkillRegistry.discover().get(args.name)
    if entry is None or entry.tier != "imported":
        print(f"No imported skill named {args.name!r}. Only imported skills can be removed here.", file=sys.stderr)
        return 1
    shutil.rmtree(entry.manifest.directory)
    print(f"Removed {entry.manifest.directory}")
    return 0


def _trust_browser(args: argparse.Namespace) -> int:
    from pathlib import Path
    from agents.skills.browser_skills import BrowserSkills
    try:
        digest = BrowserSkills(Path(__file__).resolve().parents[2]).trust(Path(args.path))
    except (OSError, ValueError) as exc:
        print(f"Could not enable browser skill: {exc}", file=sys.stderr)
        return 1
    print(f"Browser skill enabled for content {digest[:12]}. Scripts remain disabled.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agents.skills", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List installed skills").set_defaults(run=_list)
    trust = commands.add_parser("trust-browser", help="Explicitly enable an instruction skill for browser tasks")
    trust.add_argument("path", help="Skill folder or SKILL.md to review and enable")
    trust.set_defaults(run=_trust_browser)
    show = commands.add_parser("show", help="Print a skill's instructions")
    show.add_argument("name")
    show.set_defaults(run=_show)
    importer = commands.add_parser("import", help="Import skills from a folder, GitHub, Hermes, OpenClaw, or OpenJarvis")
    importer.add_argument("source")
    importer.add_argument("--name", help="Only import the skill with this name")
    importer.add_argument("--with-scripts", action="store_true", help="Also copy and allow the skill's scripts (review them first)")
    importer.add_argument("--yes-dangerous", action="store_true", help="Allow skills that request shell/network/filesystem capabilities")
    importer.add_argument("--force", action="store_true", help="Replace an already imported skill")
    importer.set_defaults(run=_import)
    remove = commands.add_parser("remove", help="Remove an imported skill")
    remove.add_argument("name")
    remove.set_defaults(run=_remove)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
