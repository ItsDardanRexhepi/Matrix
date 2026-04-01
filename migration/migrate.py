#!/usr/bin/env python3
"""
Migration CLI — import agents from other frameworks into 0pnMatrx.

Usage:
    python -m migration.migrate --source /path/to/project [--framework langchain|autogpt|openai|crewai|auto]
    python -m migration.migrate --detect /path/to/project
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from migration.langchain_importer import LangChainImporter
from migration.autogpt_importer import AutoGPTImporter
from migration.openai_assistants_importer import OpenAIAssistantsImporter
from migration.crewai_importer import CrewAIImporter
from migration.generic_importer import GenericImporter

logger = logging.getLogger(__name__)

IMPORTERS = {
    "langchain": LangChainImporter,
    "autogpt": AutoGPTImporter,
    "openai": OpenAIAssistantsImporter,
    "crewai": CrewAIImporter,
    "generic": GenericImporter,
}


def detect_framework(source_path: str, workspace: str = ".") -> str | None:
    """Auto-detect which framework a project uses."""
    for name, cls in IMPORTERS.items():
        if name == "generic":
            continue
        importer = cls(workspace)
        if importer.detect(source_path):
            return name

    # Fall back to generic
    generic = GenericImporter(workspace)
    if generic.detect(source_path):
        return "generic"
    return None


def run_import(source_path: str, framework: str = "auto", workspace: str = ".") -> dict:
    """
    Run the import process.

    Args:
        source_path: Path to the source project
        framework: Framework name or "auto" for auto-detection
        workspace: 0pnMatrx workspace directory

    Returns:
        dict with import results
    """
    if framework == "auto":
        detected = detect_framework(source_path, workspace)
        if not detected:
            return {"error": "Could not detect framework. Use --framework to specify."}
        framework = detected
        print(f"Detected framework: {framework}")

    if framework not in IMPORTERS:
        return {"error": f"Unknown framework: {framework}. Available: {', '.join(IMPORTERS.keys())}"}

    importer_cls = IMPORTERS[framework]
    importer = importer_cls(workspace)

    agents = importer.import_agents(source_path)
    paths = []
    for agent in agents:
        path = importer.write_agent(agent)
        paths.append(str(path))
        print(f"  Imported: {agent.name} ({agent.role})")
        if agent.warnings:
            for w in agent.warnings:
                print(f"    Warning: {w}")

    return {
        "framework": framework,
        "agents_imported": len(agents),
        "agents": [
            {
                "name": a.name,
                "role": a.role,
                "tools": len(a.tools),
                "warnings": a.warnings,
            }
            for a in agents
        ],
        "paths": paths,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Import agents from other frameworks into 0pnMatrx"
    )
    parser.add_argument("--source", required=True, help="Path to the source project")
    parser.add_argument(
        "--framework",
        default="auto",
        choices=list(IMPORTERS.keys()) + ["auto"],
        help="Source framework (default: auto-detect)",
    )
    parser.add_argument("--workspace", default=".", help="0pnMatrx workspace directory")
    parser.add_argument("--detect", action="store_true", help="Only detect framework, don't import")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.detect:
        result = detect_framework(args.source, args.workspace)
        if result:
            print(f"Detected: {result}")
        else:
            print("No supported framework detected")
        sys.exit(0 if result else 1)

    result = run_import(args.source, args.framework, args.workspace)
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"\nImported {result['agents_imported']} agent(s) from {result['framework']}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
