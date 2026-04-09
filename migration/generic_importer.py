from __future__ import annotations

"""
Generic Importer — import agents from any framework with standard config.

Accepts JSON or YAML agent definitions with a simple schema:
- name: agent name
- system_prompt / instructions: the system prompt
- tools: list of tool names or definitions
- model: model name (informational)
"""

import json
import logging
from pathlib import Path

from migration.base import BaseImporter, ImportedAgent

logger = logging.getLogger(__name__)


class GenericImporter(BaseImporter):

    @property
    def framework_name(self) -> str:
        return "generic"

    def detect(self, source_path: str) -> bool:
        """Generic importer accepts any directory with JSON/YAML agent configs."""
        path = Path(source_path)
        if not path.exists():
            return False

        for ext in ("*.json", "*.yaml", "*.yml"):
            for f in path.glob(ext):
                try:
                    content = f.read_text(encoding="utf-8")
                    if any(kw in content.lower() for kw in ["system_prompt", "instructions", "agent"]):
                        return True
                except Exception:
                    continue
        return False

    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        path = Path(source_path)
        agents = []

        # Process JSON files
        for json_file in sorted(path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                extracted = self._parse_config(data, json_file.name)
                agents.extend(extracted)
            except Exception as e:
                logger.warning(f"Failed to parse {json_file}: {e}")

        # Process YAML files
        for yaml_file in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
            try:
                import yaml
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                extracted = self._parse_config(data, yaml_file.name)
                agents.extend(extracted)
            except ImportError:
                logger.debug("PyYAML not installed, skipping YAML files")
                break
            except Exception as e:
                logger.warning(f"Failed to parse {yaml_file}: {e}")

        if not agents:
            agents.append(ImportedAgent(
                name="imported_agent",
                role="execution",
                system_prompt="Imported agent. Configure system prompt in identity.md.",
                source_framework="generic",
                warnings=["No agent definitions found in config files"],
            ))

        return agents

    def _parse_config(self, data: any, filename: str) -> list[ImportedAgent]:
        """Parse a generic config (dict or list of dicts)."""
        if isinstance(data, dict):
            # Check if it's a single agent def
            if any(k in data for k in ["system_prompt", "instructions", "name"]):
                agent = self._convert_agent(data, filename)
                return [agent] if agent else []

            # Check if it has an agents list
            if "agents" in data:
                agents_data = data["agents"]
                if isinstance(agents_data, list):
                    return [a for d in agents_data if (a := self._convert_agent(d, filename))]
                elif isinstance(agents_data, dict):
                    results = []
                    for name, cfg in agents_data.items():
                        if isinstance(cfg, dict):
                            cfg.setdefault("name", name)
                            agent = self._convert_agent(cfg, filename)
                            if agent:
                                results.append(agent)
                    return results

        elif isinstance(data, list):
            return [a for d in data if isinstance(d, dict) and (a := self._convert_agent(d, filename))]

        return []

    def _convert_agent(self, data: dict, filename: str) -> ImportedAgent | None:
        """Convert a generic agent dict to ImportedAgent."""
        name = data.get("name", data.get("agent_name", filename.split(".")[0]))
        name = str(name).lower().replace(" ", "_")

        system_prompt = (
            data.get("system_prompt")
            or data.get("instructions")
            or data.get("prompt")
            or data.get("description", "")
        )

        # Parse tools
        tools = []
        warnings = []
        raw_tools = data.get("tools", [])
        if isinstance(raw_tools, list):
            for tool in raw_tools:
                if isinstance(tool, str):
                    tools.append({"name": tool, "source": "generic"})
                elif isinstance(tool, dict):
                    tools.append(tool)

        # Determine role
        role = data.get("role", "execution")
        if role not in ("execution", "conversation", "guidance"):
            if any(kw in role.lower() for kw in ["chat", "converse", "talk"]):
                role = "conversation"
            elif any(kw in role.lower() for kw in ["guide", "mentor", "advise"]):
                role = "guidance"
            else:
                role = "execution"

        # Skills
        skills = []
        raw_skills = data.get("skills", [])
        if isinstance(raw_skills, list):
            for skill in raw_skills:
                if isinstance(skill, dict):
                    skills.append(skill)

        return ImportedAgent(
            name=name,
            role=role,
            system_prompt=system_prompt or f"Imported agent: {name}",
            tools=tools,
            skills=skills,
            source_framework=data.get("framework", "generic"),
            source_config=data,
            warnings=warnings,
        )
