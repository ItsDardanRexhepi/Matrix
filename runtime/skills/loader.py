"""
Skill Loader — discovers and loads agent skills from the skills directory.

Skills are YAML-defined capabilities that extend what agents can do.
Each skill has a name, description, trigger conditions, and an execution handler.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class Skill:
    """A loaded skill definition."""

    def __init__(self, name: str, description: str, trigger: str, steps: list[dict]):
        self.name = name
        self.description = description
        self.trigger = trigger
        self.steps = steps

    def matches(self, user_input: str) -> bool:
        """Check if the user input matches this skill's trigger."""
        if self.trigger.startswith("/"):
            return user_input.strip().lower().startswith(self.trigger.lower())
        return self.trigger.lower() in user_input.lower()

    def to_prompt(self) -> str:
        """Convert the skill's steps into a system prompt for the agent."""
        lines = [f"Execute the '{self.name}' skill:"]
        for i, step in enumerate(self.steps, 1):
            action = step.get("action", "")
            description = step.get("description", "")
            lines.append(f"{i}. [{action}] {description}")
        return "\n".join(lines)


class SkillLoader:
    """Loads skill definitions from YAML files in a directory."""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: list[Skill] = []

    def load_all(self) -> list[Skill]:
        """Load all .yaml skill files from the skills directory."""
        if not self.skills_dir.exists():
            logger.debug(f"Skills directory not found: {self.skills_dir}")
            return []

        self.skills = []
        for path in sorted(self.skills_dir.glob("*.yaml")):
            try:
                skill = self._load_file(path)
                if skill:
                    self.skills.append(skill)
                    logger.info(f"Loaded skill: {skill.name}")
            except Exception as e:
                logger.error(f"Failed to load skill {path.name}: {e}")

        return self.skills

    def _load_file(self, path: Path) -> Skill | None:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)

        if not isinstance(data, dict):
            return None

        name = data.get("name")
        description = data.get("description", "")
        trigger = data.get("trigger", "")
        steps = data.get("steps", [])

        if not name or not trigger:
            logger.warning(f"Skill {path.name} missing name or trigger, skipping")
            return None

        return Skill(name=name, description=description, trigger=trigger, steps=steps)

    def find_matching(self, user_input: str) -> Skill | None:
        """Find the first skill that matches the user's input."""
        for skill in self.skills:
            if skill.matches(user_input):
                return skill
        return None
