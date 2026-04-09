from __future__ import annotations

"""
Skill Loader — discovers and loads skills from the skills/ directory.

Supports both YAML-defined skills and Python-file skills.
Each skill becomes a callable tool registered in the dispatcher.
Handles import errors gracefully — logs failures, continues with the rest.
"""

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class Skill:
    """A loaded skill that can be registered as a tool."""

    def __init__(self, name: str, description: str, parameters: dict, handler: Callable[..., Awaitable[str]]):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._handler = handler

    def as_tool_handler(self) -> Callable[..., Awaitable[str]]:
        return self._handler

    def to_tool_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class SkillLoader:
    """Loads skill definitions from Python files and YAML files in a directory."""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: list[Skill] = []

    def load_all(self) -> list[Skill]:
        """Load all skills from the skills directory."""
        if not self.skills_dir.exists():
            logger.debug(f"Skills directory not found: {self.skills_dir}")
            return []

        self.skills = []

        # Load Python skill files
        for path in sorted(self.skills_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                skill = self._load_python_skill(path)
                if skill:
                    self.skills.append(skill)
                    logger.info(f"Loaded Python skill: {skill.name}")
            except Exception as e:
                logger.error(f"Failed to load skill {path.name}: {e}")

        # Load YAML skill files
        for path in sorted(self.skills_dir.glob("*.yaml")):
            try:
                skill = self._load_yaml_skill(path)
                if skill:
                    self.skills.append(skill)
                    logger.info(f"Loaded YAML skill: {skill.name}")
            except Exception as e:
                logger.error(f"Failed to load YAML skill {path.name}: {e}")

        return self.skills

    def _load_python_skill(self, path: Path) -> Skill | None:
        """
        Load a Python skill file. The file must define:
        - SKILL_NAME: str
        - SKILL_DESCRIPTION: str
        - SKILL_PARAMETERS: dict (JSON schema)
        - async def execute(**kwargs) -> str
        """
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        name = getattr(module, "SKILL_NAME", None)
        description = getattr(module, "SKILL_DESCRIPTION", "")
        parameters = getattr(module, "SKILL_PARAMETERS", {"type": "object", "properties": {}})
        handler = getattr(module, "execute", None)

        if not name or not handler:
            logger.warning(f"Skill {path.name} missing SKILL_NAME or execute function")
            return None

        return Skill(name=name, description=description, parameters=parameters, handler=handler)

    def _load_yaml_skill(self, path: Path) -> Skill | None:
        """Load a YAML skill definition."""
        try:
            import yaml
        except ImportError:
            logger.debug("PyYAML not installed, skipping YAML skills")
            return None

        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return None

        name = data.get("name")
        description = data.get("description", "")
        trigger = data.get("trigger", "")
        steps = data.get("steps", [])

        if not name:
            return None

        # Create a handler that returns the skill's steps as instructions
        async def yaml_handler(**kwargs) -> str:
            lines = [f"Executing skill '{name}':"]
            for i, step in enumerate(steps, 1):
                action = step.get("action", "")
                desc = step.get("description", "")
                lines.append(f"  {i}. [{action}] {desc}")
            return "\n".join(lines)

        parameters = {"type": "object", "properties": {"input": {"type": "string", "description": "Input for the skill"}}}

        return Skill(name=name, description=description, parameters=parameters, handler=yaml_handler)

    def find_matching(self, user_input: str) -> Skill | None:
        """Find the first skill that matches the user's input."""
        input_lower = user_input.lower()
        for skill in self.skills:
            if skill.name.lower() in input_lower:
                return skill
        return None
