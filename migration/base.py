"""
Base Importer — abstract base class for all framework importers.

Each importer converts a source framework's agent definition into
0pnMatrx's agent format: identity.md, tools, skills, and config.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportedAgent:
    """Result of importing an agent from another framework."""
    name: str
    role: str  # "execution", "conversation", or "guidance"
    system_prompt: str
    tools: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    source_framework: str = ""
    source_config: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class BaseImporter(ABC):
    """Abstract base class for framework importers."""

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace)

    @property
    @abstractmethod
    def framework_name(self) -> str:
        ...

    @abstractmethod
    def detect(self, source_path: str) -> bool:
        """Detect if the source path contains a project from this framework."""
        ...

    @abstractmethod
    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        """Import all agents from the source project."""
        ...

    def write_agent(self, agent: ImportedAgent) -> Path:
        """Write an imported agent to the 0pnMatrx agents directory."""
        agent_dir = self.workspace / "agents" / agent.name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write identity.md
        identity = f"""# {agent.name}

## Role
{agent.role}

## System Prompt
{agent.system_prompt}

## Source
Imported from {agent.source_framework}
"""
        (agent_dir / "identity.md").write_text(identity, encoding="utf-8")

        # Write tools config
        if agent.tools:
            (agent_dir / "tools.json").write_text(
                json.dumps(agent.tools, indent=2), encoding="utf-8"
            )

        # Write skills
        for skill in agent.skills:
            skill_name = skill.get("name", "imported_skill")
            skill_path = self.workspace / "skills" / f"{skill_name}.yaml"
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml
            skill_path.write_text(yaml.dump(skill, default_flow_style=False), encoding="utf-8")

        # Write import metadata
        meta = {
            "source_framework": agent.source_framework,
            "source_config": agent.source_config,
            "warnings": agent.warnings,
        }
        (agent_dir / "import_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        logger.info(f"Wrote imported agent '{agent.name}' to {agent_dir}")
        return agent_dir

    def import_and_write(self, source_path: str) -> list[Path]:
        """Import agents from source and write them to the workspace."""
        agents = self.import_agents(source_path)
        paths = []
        for agent in agents:
            path = self.write_agent(agent)
            paths.append(path)
        return paths
