#!/usr/bin/env python3
"""
0pnMatrx SDK — Migration Example

Demonstrates importing agents from other frameworks.
"""

import sys
sys.path.insert(0, ".")

from migration.migrate import run_import, detect_framework


def main():
    source_path = sys.argv[1] if len(sys.argv) > 1 else "."

    # Auto-detect framework
    print(f"Scanning {source_path}...")
    framework = detect_framework(source_path)
    if framework:
        print(f"Detected: {framework}")
    else:
        print("No known framework detected. Using generic importer.")
        framework = "generic"

    # Run import
    result = run_import(source_path, framework)
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"\nImported {result['agents_imported']} agent(s):")
    for agent in result["agents"]:
        print(f"  - {agent['name']} ({agent['role']}, {agent['tools']} tools)")
        for w in agent.get("warnings", []):
            print(f"    Warning: {w}")


if __name__ == "__main__":
    main()
