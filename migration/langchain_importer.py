"""
LangChain Importer — converts LangChain agents to 0pnMatrx format.

Parses LangChain agent configs, chain definitions, and tool setups
to produce 0pnMatrx-compatible agent definitions.
"""

import ast
import json
import logging
from pathlib import Path

from migration.base import BaseImporter, ImportedAgent

logger = logging.getLogger(__name__)

# LangChain tool names -> 0pnMatrx tool mappings
TOOL_MAPPING = {
    "serpapi": "web_search",
    "google-search": "web_search",
    "ddg-search": "web_search",
    "wikipedia": "web_search",
    "python_repl": "bash",
    "terminal": "bash",
    "shell": "bash",
    "requests_get": "web_request",
    "requests_post": "web_request",
    "human": None,  # no mapping needed
    "llm-math": None,
}


class LangChainImporter(BaseImporter):

    @property
    def framework_name(self) -> str:
        return "langchain"

    def detect(self, source_path: str) -> bool:
        """Detect if this is a LangChain project."""
        path = Path(source_path)
        if not path.exists():
            return False

        # Check for LangChain imports in Python files
        for py_file in path.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if "langchain" in content or "from langchain" in content:
                    return True
            except Exception:
                continue

        # Check requirements
        req_file = path / "requirements.txt"
        if req_file.exists() and "langchain" in req_file.read_text():
            return True

        return False

    def import_agents(self, source_path: str) -> list[ImportedAgent]:
        """Import LangChain agents from Python source files."""
        path = Path(source_path)
        agents = []

        for py_file in sorted(path.rglob("*.py")):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if "langchain" not in content:
                    continue

                extracted = self._extract_agent_config(content, py_file.name)
                if extracted:
                    agents.append(extracted)
            except Exception as e:
                logger.warning(f"Failed to parse {py_file}: {e}")

        if not agents:
            # Create a default agent from the project
            agents.append(ImportedAgent(
                name="langchain_agent",
                role="execution",
                system_prompt="Imported LangChain agent. Configure system prompt in identity.md.",
                source_framework="langchain",
                warnings=["No agent definition found — created default agent"],
            ))

        return agents

    def _extract_agent_config(self, source: str, filename: str) -> ImportedAgent | None:
        """Extract agent configuration from LangChain Python source."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        system_prompt = ""
        tools = []
        agent_name = filename.replace(".py", "")
        warnings = []

        for node in ast.walk(tree):
            # Look for system message / prompt template strings
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value
                if len(val) > 50 and any(kw in val.lower() for kw in ["you are", "assistant", "system", "your role"]):
                    if len(val) > len(system_prompt):
                        system_prompt = val

            # Look for tool instantiations
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                func_lower = func_name.lower()
                if "tool" in func_lower or func_lower in TOOL_MAPPING:
                    mapped = TOOL_MAPPING.get(func_lower)
                    if mapped:
                        tools.append({"name": mapped, "source": func_name})
                    elif mapped is None:
                        pass  # explicitly unmapped
                    else:
                        tools.append({"name": func_name, "source": "langchain"})
                        warnings.append(f"Tool '{func_name}' has no direct 0pnMatrx mapping — manual setup may be needed")

            # Look for AgentType or agent_type assignments
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and "agent" in target.id.lower():
                        if isinstance(node.value, ast.Constant):
                            agent_name = str(node.value.value).lower().replace(" ", "_")

        if not system_prompt and not tools:
            return None

        # Determine role based on tools
        role = "conversation"
        if any(t["name"] in ("bash", "web_request") for t in tools):
            role = "execution"

        return ImportedAgent(
            name=agent_name,
            role=role,
            system_prompt=system_prompt or f"Imported from LangChain ({filename})",
            tools=tools,
            source_framework="langchain",
            source_config={"source_file": filename},
            warnings=warnings,
        )
