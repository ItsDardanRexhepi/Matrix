from __future__ import annotations

"""
File Operations Tool — read, write, append, list, mkdir, delete, search.

All operations are restricted to the configured workspace directory.
Returns file contents, success/failure, and directory listings with
file sizes and modification times.
"""

import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_READ_SIZE = 500_000


class FileOpsTool:
    name = "file_ops"
    schema = {
        "name": "file_ops",
        "description": "File operations: read, write, append, list, mkdir, delete, or search files in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read", "write", "append", "list", "mkdir", "delete", "search"],
                    "description": "The file operation to perform",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path (relative to workspace)",
                },
                "content": {
                    "type": "string",
                    "description": "Content for write/append operations",
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

    def _safe_resolve(self, path: str) -> Path | None:
        target = (self.workspace / path).resolve()
        if not str(target).startswith(str(self.workspace)):
            return None
        return target

    async def execute(
        self,
        operation: str,
        path: str,
        content: str | None = None,
        pattern: str | None = None,
    ) -> str:
        target = self._safe_resolve(path)
        if target is None:
            return "Error: path is outside the workspace"

        ops = {
            "read": lambda: self._read(target),
            "write": lambda: self._write(target, content or ""),
            "append": lambda: self._append(target, content or ""),
            "list": lambda: self._list(target),
            "mkdir": lambda: self._mkdir(target),
            "delete": lambda: self._delete(target),
            "search": lambda: self._search(target, pattern or ""),
        }

        handler = ops.get(operation)
        if not handler:
            return f"Error: unknown operation '{operation}'"
        return handler()

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

    def _append(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} bytes to {path.name}"

    def _list(self, path: Path) -> str:
        if not path.exists():
            return f"Error: directory not found: {path.name}"
        if not path.is_dir():
            return f"Error: not a directory: {path.name}"

        entries = sorted(path.iterdir())
        lines = []
        for entry in entries[:200]:
            try:
                stat = entry.stat()
                size = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                prefix = "d" if entry.is_dir() else "f"
                lines.append(f"{prefix} {size:>10}  {mtime}  {entry.name}")
            except OSError:
                lines.append(f"? {'?':>10}  {'?':>16}  {entry.name}")

        if len(entries) > 200:
            lines.append(f"... and {len(entries) - 200} more")

        return "\n".join(lines) if lines else "(empty directory)"

    def _mkdir(self, path: Path) -> str:
        path.mkdir(parents=True, exist_ok=True)
        return f"Created directory: {path.name}"

    def _delete(self, path: Path) -> str:
        if not path.exists():
            return f"Error: not found: {path.name}"
        if path.is_dir():
            return "Error: cannot delete directories (safety restriction)"
        path.unlink()
        return f"Deleted: {path.name}"

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
