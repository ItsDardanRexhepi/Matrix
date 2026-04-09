from __future__ import annotations

"""
AutoGPT Importer — converts AutoGPT agent configurations to 0pnMatrx format.

Parses AutoGPT's ai_settings.yaml, .env, and plugin configurations.
"""

import json
import logging
from pathlib import Path

from migration.base import BaseImporter, ImportedAgent

logger = logging.getLogger(__name__)


class AutoGPTImporter(BaseImporter):

    @property
    def framework_name(self) -> str:
        return "autogpt"

    def detect(self, source_path: str) -> bool:
        path = Path(source_path)
        indicators = [
            path / "ai_settings.yaml",
            path / "autogpt" / "agent.py",
            path / ".env" if (path / "autogpt").exists() else None,
        ]
        return any(f and f.exists() for f in indicators)

    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        path = Path(source_path)
        agents = []

        # Parse ai_settings.yaml
        settings_file = path / "ai_settings.yaml"
        if settings_file.exists():
            agent = self._parse_ai_settings(settings_file)
            if agent:
                agents.append(agent)

        # Check for multiple agent configs in auto_gpt_workspace
        workspace = path / "auto_gpt_workspace"
        if workspace.exists():
            for settings in workspace.rglob("ai_settings.yaml"):
                agent = self._parse_ai_settings(settings)
                if agent:
                    agents.append(agent)

        if not agents:
            agents.append(ImportedAgent(
                name="autogpt_agent",
                role="execution",
                system_prompt="Imported AutoGPT agent. Configure in identity.md.",
                source_framework="autogpt",
                warnings=["No ai_settings.yaml found — created default agent"],
            ))

        return agents

    def _parse_ai_settings(self, settings_path: Path) -> ImportedAgent | None:
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed, cannot parse ai_settings.yaml")
            return None

        try:
            data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to parse {settings_path}: {e}")
            return None

        if not isinstance(data, dict):
            return None

        ai_name = data.get("ai_name", "autogpt_agent").lower().replace(" ", "_")
        ai_role = data.get("ai_role", "")
        ai_goals = data.get("ai_goals", [])

        # Build system prompt from AutoGPT settings
        prompt_parts = []
        if ai_role:
            prompt_parts.append(f"Role: {ai_role}")
        if ai_goals:
            prompt_parts.append("Goals:")
            for i, goal in enumerate(ai_goals, 1):
                prompt_parts.append(f"  {i}. {goal}")

        system_prompt = "\n".join(prompt_parts) if prompt_parts else f"Imported AutoGPT agent: {ai_name}"

        # AutoGPT agents are always execution-oriented
        tools = [
            {"name": "bash", "source": "autogpt_commands"},
            {"name": "web_search", "source": "autogpt_commands"},
            {"name": "web_request", "source": "autogpt_commands"},
            {"name": "file_ops", "source": "autogpt_commands"},
        ]

        warnings = []
        # Check for plugins
        plugins_dir = settings_path.parent / "plugins"
        if plugins_dir.exists():
            for plugin in plugins_dir.iterdir():
                warnings.append(f"AutoGPT plugin '{plugin.name}' needs manual migration")

        return ImportedAgent(
            name=ai_name,
            role="execution",
            system_prompt=system_prompt,
            tools=tools,
            source_framework="autogpt",
            source_config=data,
            warnings=warnings,
        )
