from pathlib import Path

import pytest


def loader(root, home):
    from agents.skills.browser_skills import BrowserSkills
    return BrowserSkills(root, home=home)


def write_skill(root, name="browser-custom", description="Browser research task", extra=""):
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\nRead the current page and verify the result.", encoding="utf-8")
    return path


def test_standard_skill_requires_explicit_trust_and_can_activate_without_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_SKILLS_DIR", raising=False)
    home = tmp_path / "home"
    path = write_skill(tmp_path / ".agents" / "skills")
    skills = loader(tmp_path, home)
    assert "browser-custom" not in skills.catalog("browser research")
    digest = skills.trust(path.parent)
    assert len(digest) == 64
    fresh = loader(tmp_path, home)
    assert "browser-custom" in fresh.catalog("browser research")
    assert "verify" in fresh.activate("browser-custom")


def test_changed_content_needs_reenable_but_active_body_is_pinned(tmp_path):
    path = write_skill(tmp_path / ".agents" / "skills")
    skills = loader(tmp_path, tmp_path / "home")
    skills.trust(path.parent)
    active = loader(tmp_path, tmp_path / "home")
    original = active.activate("browser-custom")
    path.write_text(path.read_text() + "\nChanged", encoding="utf-8")
    assert active.activate("browser-custom") == original
    assert "browser-custom" not in loader(tmp_path, tmp_path / "home").catalog("browser research")


def test_untrusted_collision_does_not_hide_bundled_skill(tmp_path):
    write_skill(tmp_path / "skills", "browser-operator")
    write_skill(tmp_path / ".agents" / "skills", "browser-operator", "UNTRUSTED REPLACEMENT")
    skills = loader(tmp_path, tmp_path / "home")
    assert "UNTRUSTED" not in skills.catalog("browser")
    assert "verify" in skills.activate("browser-operator")


def test_standard_validation_and_tool_constraints(tmp_path):
    path = write_skill(tmp_path / "skills", extra="allowed-tools: browser_snapshot browser_click\nmetadata:\n  version: '1.0'\n")
    skills = loader(tmp_path, tmp_path / "home")
    skills.activate("browser-custom")
    assert skills.allowed_tools == {"browser_snapshot", "browser_click"}
    path.write_text(path.read_text().replace("browser_click", "browser_evaluate"), encoding="utf-8")
    with pytest.raises(ValueError, match="tool|unsupported"):
        loader(tmp_path, tmp_path / "home").activate("browser-custom")


@pytest.mark.parametrize("extra", ["metadata:\n  nested:\n    key: value\n", "allowed-tools: 'Bash(*)'\n"])
def test_nonportable_or_unsupported_fields_are_diagnosed(tmp_path, extra):
    write_skill(tmp_path / "skills", extra=extra)
    skills = loader(tmp_path, tmp_path / "home")
    with pytest.raises(ValueError):
        skills.activate("browser-custom")


def test_references_are_pinned_and_cannot_escape(tmp_path):
    path = write_skill(tmp_path / "skills")
    refs = path.parent / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("Read only this guide", encoding="utf-8")
    skills = loader(tmp_path, tmp_path / "home")
    skills.activate("browser-custom")
    (refs / "guide.md").write_text("Changed", encoding="utf-8")
    assert skills.resource("browser-custom", "references/guide.md") == "Read only this guide"
    with pytest.raises(ValueError):
        skills.resource("browser-custom", "../../private.txt")
    with pytest.raises(ValueError):
        skills.resource("browser-custom", "scripts/run.py")


def test_new_browser_discovery_does_not_change_legacy_cli_roots(tmp_path):
    from agents.skills.registry import SkillRegistry
    write_skill(tmp_path / ".agents" / "skills")
    assert not SkillRegistry.discover(bundled_dir=tmp_path / "empty", user_dir=tmp_path / "legacy").all()
    skills = loader(tmp_path, tmp_path / "home")
    assert "browser-custom" not in skills.catalog("novel task")


def test_folder_name_and_full_description_are_validated(tmp_path):
    path = write_skill(tmp_path / "skills")
    path.write_text(path.read_text().replace("name: browser-custom", "name: different-name"), encoding="utf-8")
    skills = loader(tmp_path, tmp_path / "home")
    assert skills.errors and "browser-custom" not in skills.catalog("browser")


def test_browser_task_activates_base_then_relevant_bundled_specialization():
    root = Path(__file__).resolve().parents[1]

    instructions = loader(root, root / "nonexistent-home").activate_for_task(
        "Fill this application form with the details I provide"
    )

    assert list(instructions) == ["browser-operator", "browser-form-fill"]
