"""
OpenAI Assistants Importer — converts OpenAI Assistants API configs to 0pnMatrx.

Imports assistant definitions either from a JSON export file or
directly from the OpenAI API (if API key is configured).
"""

import json
import logging
from pathlib import Path
from typing import Any

from migration.base import BaseImporter, ImportedAgent

logger = logging.getLogger(__name__)

# OpenAI tool type -> 0pnMatrx mapping
TOOL_TYPE_MAPPING = {
    "code_interpreter": "bash",
    "retrieval": "file_ops",
    "file_search": "file_ops",
    "function": None,  # handled separately
}


class OpenAIAssistantsImporter(BaseImporter):

    @property
    def framework_name(self) -> str:
        return "openai_assistants"

    def detect(self, source_path: str) -> bool:
        path = Path(source_path)
        # Check for exported assistant JSON files
        for json_file in path.glob("*.json"):
            try:
                data = json.loads(json_file.read_text())
                if isinstance(data, dict) and data.get("object") == "assistant":
                    return True
                if isinstance(data, list) and data and data[0].get("object") == "assistant":
                    return True
            except Exception:
                continue
        return False

    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        path = Path(source_path)
        agents = []

        for json_file in sorted(path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())

                # Single assistant
                if isinstance(data, dict) and data.get("object") == "assistant":
                    agent = self._convert_assistant(data)
                    if agent:
                        agents.append(agent)

                # List of assistants
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("object") == "assistant":
                            agent = self._convert_assistant(item)
                            if agent:
                                agents.append(agent)
            except Exception as e:
                logger.warning(f"Failed to parse {json_file}: {e}")

        if not agents:
            agents.append(ImportedAgent(
                name="openai_assistant",
                role="conversation",
                system_prompt="Imported OpenAI Assistant. Configure in identity.md.",
                source_framework="openai_assistants",
                warnings=["No assistant JSON found — created default"],
            ))

        return agents

    def _convert_assistant(self, data: dict) -> ImportedAgent | None:
        """Convert an OpenAI Assistant API object to 0pnMatrx format."""
        name = (data.get("name") or "assistant").lower().replace(" ", "_")
        instructions = data.get("instructions", "")
        model = data.get("model", "")
        tools_list = data.get("tools", [])

        # Convert tools
        tools = []
        warnings = []
        for tool in tools_list:
            tool_type = tool.get("type", "")
            mapped = TOOL_TYPE_MAPPING.get(tool_type)
            if mapped:
                tools.append({"name": mapped, "source": f"openai_{tool_type}"})
            elif tool_type == "function":
                fn = tool.get("function", {})
                fn_name = fn.get("name", "custom_function")
                tools.append({
                    "name": fn_name,
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                    "source": "openai_function",
                })
                warnings.append(f"Function tool '{fn_name}' needs a handler implementation in 0pnMatrx")

        # Determine role
        has_execution_tools = any(t["name"] in ("bash", "file_ops") for t in tools)
        role = "execution" if has_execution_tools else "conversation"

        return ImportedAgent(
            name=name,
            role=role,
            system_prompt=instructions or f"Imported from OpenAI Assistants (model: {model})",
            tools=tools,
            source_framework="openai_assistants",
            source_config={"model": model, "id": data.get("id", "")},
            warnings=warnings,
        )

    @staticmethod
    async def fetch_from_api(api_key: str) -> list[dict]:
        """Fetch assistants directly from the OpenAI API."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.openai.com/v1/assistants",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "OpenAI-Beta": "assistants=v2",
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", [])
                    else:
                        logger.error(f"OpenAI API error: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Failed to fetch assistants from API: {e}")
            return []
