"""
Skills: reusable instructions and tools in the agentskills.io SKILL.md format.

Structured skills (``metadata.jarvis.kind: structured``) are run directly: the
model writes a JSON spec and the skill's script builds the result. Other skills
are offered to the coding CLI as instructions to read when relevant.
"""

from agents.skills.registry import SkillEntry, SkillRegistry, user_skills_dir

__all__ = ["SkillEntry", "SkillRegistry", "user_skills_dir"]
