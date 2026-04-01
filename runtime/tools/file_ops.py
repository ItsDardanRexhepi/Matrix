"""
File Operations Tool — read, write, list, and search files.

All file operations are restricted to the workspace directory.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 500_000


class FileOpsTool:
    name = "file_ops"
    schema = {
        "name": "file_ops",
        "description": "Read, write, list, or search files in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read", "write", "list", "search"],
                    "description": "The file operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path (relative to workspace)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for write operation)",
                },
                "pattern": {
                    "type": "string",
                    "description": "Search pattern (for search operation)",
                },
            },
            "required": ["operation", "path"],
        },
    }

    def __init__(self, config: dict):
        self.workspace = Path(config.get("workspace", ".")).resolve()

    async def execute(
        self,
        operation: str,
        path: str,
        content: str | None = None,
        pattern: str | None = None,
    ) -> str:
        target = (self.workspace / path).resolve()

        if not str(target).startswith(str(self.workspace)):
            return "Error: path is outside the workspace"

        if operation == "read":
            return self._read(target)
        elif operation == "write":
            return self._write(target, content or "")
        elif operation == "list":
            return self._list(target)
        elif operation == "search":
            return self._search(target, pattern or "")
        else:
            return f"Error: unknown operation '{operation}'"

    def _read(self, path: Path) -> str:
        if not path.exists():
            return f"Error: file not found: {path.name}"
        if not path.is_file():
            return f"Error: not a file: {path.name}"

        size = path.stat().st_size
        if size > MAX_READ_SIZE:
            return f"Error: file too large ({size} bytes, max {MAX_READ_SIZE})"

        return path.read_text(encoding="utf-8", errors="replace")

    def _write(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Written: {path.name} ({len(content)} bytes)"

    def _list(self, path: Path) -> str:
        if not path.exists():
            return f"Error: directory not found: {path.name}"
        if not path.is_dir():
            return f"Error: not a directory: {path.name}"

        entries = sorted(path.iterdir())
        lines = []
        for entry in entries[:200]:
            prefix = "d " if entry.is_dir() else "f "
            lines.append(f"{prefix}{entry.name}")

        if len(entries) > 200:
            lines.append(f"... and {len(entries) - 200} more")

        return "\n".join(lines) if lines else "(empty directory)"

    def _search(self, path: Path, pattern: str) -> str:
        if not pattern:
            return "Error: search pattern is required"

        results = []
        search_dir = path if path.is_dir() else path.parent

        for filepath in search_dir.rglob("*"):
            if not filepath.is_file():
                continue
            try:
                text = filepath.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.lower() in line.lower():
                        rel = filepath.relative_to(self.workspace)
                        results.append(f"{rel}:{i}: {line.strip()}")
            except Exception:
                continue

            if len(results) >= 100:
                break

        return "\n".join(results) if results else f"No matches for '{pattern}'"
