from __future__ import annotations

"""
CrewAI Importer — converts CrewAI crew and agent definitions to 0pnMatrx.

Parses CrewAI's Python-based agent/crew configs, YAML configs,
and converts the multi-agent setup to 0pnMatrx hivemind format.
"""

import ast
import json
import logging
from pathlib import Path

from migration.base import BaseImporter, ImportedAgent

logger = logging.getLogger(__name__)


class CrewAIImporter(BaseImporter):

    @property
    def framework_name(self) -> str:
        return "crewai"

    def detect(self, source_path: str) -> bool:
        path = Path(source_path)
        for py_file in path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if "crewai" in content or "from crewai" in content:
                    return True
            except Exception:
                continue

        # Check for CrewAI YAML config
        for yaml_file in path.rglob("*.yaml"):
            try:
                content = yaml_file.read_text(encoding="utf-8", errors="ignore")
                if "agents:" in content and ("role:" in content or "goal:" in content):
                    return True
            except Exception:
                continue

        return False

    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        path = Path(source_path)
        agents = []

        # Try YAML config first (CrewAI v2 style)
        yaml_agents = self._parse_yaml_configs(path)
        if yaml_agents:
            agents.extend(yaml_agents)

        # Parse Python source files
        for py_file in sorted(path.rglob("*.py")):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if "crewai" not in content:
                    continue
                extracted = self._extract_from_python(content, py_file.name)
                agents.extend(extracted)
            except Exception as e:
                logger.warning(f"Failed to parse {py_file}: {e}")

        # Deduplicate by name
        seen = set()
        unique = []
        for agent in agents:
            if agent.name not in seen:
                seen.add(agent.name)
                unique.append(agent)
        agents = unique

        if not agents:
            agents.append(ImportedAgent(
                name="crewai_agent",
                role="execution",
                system_prompt="Imported CrewAI agent. Configure in identity.md.",
                source_framework="crewai",
                warnings=["No CrewAI agent definitions found — created default"],
            ))

        return agents

    def _parse_yaml_configs(self, path: Path) -> list[ImportedAgent]:
        """Parse CrewAI YAML agent configurations."""
        agents = []
        try:
            import yaml
        except ImportError:
            return agents

        for yaml_file in path.rglob("*.yaml"):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue

                # CrewAI agents config format
                agent_configs = data.get("agents", [])
                if isinstance(agent_configs, list):
                    for cfg in agent_configs:
                        agent = self._convert_yaml_agent(cfg)
                        if agent:
                            agents.append(agent)
                elif isinstance(agent_configs, dict):
                    for name, cfg in agent_configs.items():
                        if isinstance(cfg, dict):
                            cfg["name"] = cfg.get("name", name)
                            agent = self._convert_yaml_agent(cfg)
                            if agent:
                                agents.append(agent)
            except Exception as e:
                logger.debug(f"YAML parse skip {yaml_file}: {e}")

        return agents

    def _convert_yaml_agent(self, cfg: dict) -> ImportedAgent | None:
        """Convert a CrewAI YAML agent config to ImportedAgent."""
        if not isinstance(cfg, dict):
            return None

        name = cfg.get("name", cfg.get("role", "crew_agent")).lower().replace(" ", "_")
        role_desc = cfg.get("role", "")
        goal = cfg.get("goal", "")
        backstory = cfg.get("backstory", "")

        prompt_parts = []
        if role_desc:
            prompt_parts.append(f"Role: {role_desc}")
        if goal:
            prompt_parts.append(f"Goal: {goal}")
        if backstory:
            prompt_parts.append(f"Backstory: {backstory}")

        # Determine 0pnMatrx role
        role_lower = (role_desc + " " + goal).lower()
        if any(kw in role_lower for kw in ["execute", "code", "develop", "build", "deploy"]):
            agent_role = "execution"
        elif any(kw in role_lower for kw in ["guide", "mentor", "review", "security", "risk"]):
            agent_role = "guidance"
        else:
            agent_role = "conversation"

        tools = []
        for tool_name in cfg.get("tools", []):
            tools.append({"name": str(tool_name), "source": "crewai"})

        return ImportedAgent(
            name=name,
            role=agent_role,
            system_prompt="\n".join(prompt_parts) or f"CrewAI agent: {name}",
            tools=tools,
            source_framework="crewai",
            source_config=cfg,
        )

    def _extract_from_python(self, source: str, filename: str) -> list[ImportedAgent]:
        """Extract CrewAI agent definitions from Python source."""
        agents = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return agents

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name != "Agent":
                continue

            # Extract keyword arguments
            kwargs = {}
            for kw in node.keywords:
                if isinstance(kw.value, ast.Constant):
                    kwargs[kw.arg] = kw.value.value
                elif isinstance(kw.value, ast.List):
                    kwargs[kw.arg] = [
                        elt.value if isinstance(elt, ast.Constant) else str(elt)
                        for elt in kw.value.elts
                    ]

            if not kwargs:
                continue

            name = kwargs.get("role", kwargs.get("name", f"crew_{len(agents)+1}"))
            name = str(name).lower().replace(" ", "_")

            prompt_parts = []
            if "role" in kwargs:
                prompt_parts.append(f"Role: {kwargs['role']}")
            if "goal" in kwargs:
                prompt_parts.append(f"Goal: {kwargs['goal']}")
            if "backstory" in kwargs:
                prompt_parts.append(f"Backstory: {kwargs['backstory']}")

            agents.append(ImportedAgent(
                name=name,
                role="execution",
                system_prompt="\n".join(prompt_parts) or f"CrewAI agent from {filename}",
                source_framework="crewai",
                source_config=kwargs,
            ))

        return agents
