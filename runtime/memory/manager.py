"""
Memory Manager — persistent key-value and conversation memory for agents.

Stores per-agent memory in the ``memory/`` directory as JSON files.
Provides:
- Key/value read and write (exposed via /memory/read and /memory/write)
- Conversation turn persistence (called by the ReAct loop after each turn)
- Context retrieval (recent turns injected into agent system prompt)
- Session conversation persistence (full chat histories per session)
- First-boot tracking (one-time welcome messages per session)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = "memory"
MAX_CONTEXT_TURNS = 20


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via a temp file + os.replace."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    os.replace(str(tmp), str(path))


class MemoryManager:
    """File-backed memory store, one JSON file per agent."""

    def __init__(self, config: dict):
        self.memory_dir = Path(config.get("memory_dir", DEFAULT_MEMORY_DIR))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}

        # Conversations sub-directory
        self._conv_dir = self.memory_dir / "conversations"
        self._conv_dir.mkdir(parents=True, exist_ok=True)

        # First-boot tracking file
        self._first_boot_path = self.memory_dir / "first_boot.json"

        # Per-agent async locks for read-modify-write safety
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        """Return (or create) an asyncio.Lock for the given key."""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    # ── Key / Value ───────────────────────────────────────────────

    def read(self, agent: str) -> dict:
        """Return the full memory dict for *agent*."""
        return self._load(agent)

    async def write(self, agent: str, key: str, value: Any) -> None:
        """Set a single key in *agent*'s memory."""
        async with self._lock_for(agent):
            data = self._load(agent)
            data.setdefault("kv", {})[key] = value
            await self._save(agent, data)

    def get(self, agent: str, key: str, default: Any = None) -> Any:
        """Get a single key from *agent*'s memory."""
        data = self._load(agent)
        return data.get("kv", {}).get(key, default)

    # ── Conversation Turns ────────────────────────────────────────

    async def save_turn(self, agent: str, user_message: str, agent_response: str) -> None:
        """Append a user/agent exchange to the conversation log."""
        async with self._lock_for(agent):
            data = self._load(agent)
            turns = data.setdefault("turns", [])
            turns.append({
                "user": user_message,
                "agent": agent_response,
                "ts": time.time(),
            })
            # Keep only the last 200 turns on disk
            if len(turns) > 200:
                data["turns"] = turns[-200:]
            await self._save(agent, data)

    def get_context(self, agent: str) -> str:
        """Return the most recent turns as a text block for prompt injection."""
        data = self._load(agent)
        turns = data.get("turns", [])
        if not turns:
            return ""
        recent = turns[-MAX_CONTEXT_TURNS:]
        lines = []
        for t in recent:
            lines.append(f"User: {t['user']}")
            lines.append(f"Agent: {t['agent']}")
        return "\n".join(lines)

    # ── Session Persistence ──────────────────────────────────────

    async def save_conversation(self, session_id: str, messages: list[dict]) -> None:
        """Save conversation messages to ``memory/conversations/{session_id}.json``."""
        async with self._lock_for(f"conv:{session_id}"):
            path = self._conv_dir / f"{session_id}.json"
            try:
                _atomic_write(path, json.dumps(messages, indent=2, default=str))
            except OSError as exc:
                logger.error("Failed to save conversation %s: %s", session_id, exc)

    def load_conversation(self, session_id: str) -> list[dict]:
        """Load conversation messages from disk. Returns ``[]`` if not found."""
        path = self._conv_dir / f"{session_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load conversation %s: %s", session_id, exc)
        return []

    async def mark_first_boot_sent(self, session_id: str) -> None:
        """Record that the first-boot message has been sent for *session_id*."""
        async with self._lock_for("__first_boot__"):
            sent = self._load_first_boot_set()
            sent.add(session_id)
            try:
                _atomic_write(self._first_boot_path, json.dumps(sorted(sent), indent=2))
            except OSError as exc:
                logger.error("Failed to save first_boot.json: %s", exc)

    def is_first_boot_sent(self, session_id: str) -> bool:
        """Return ``True`` if the first-boot message was already sent for *session_id*."""
        return session_id in self._load_first_boot_set()

    def _load_first_boot_set(self) -> set[str]:
        """Load the first-boot session IDs from disk."""
        if self._first_boot_path.exists():
            try:
                data = json.loads(self._first_boot_path.read_text())
                if isinstance(data, list):
                    return set(data)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load first_boot.json: %s", exc)
        return set()

    # ── Internal ──────────────────────────────────────────────────

    def _path(self, agent: str) -> Path:
        safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in agent)
        return self.memory_dir / f"{safe}.json"

    def _load(self, agent: str) -> dict:
        if agent in self._cache:
            return self._cache[agent]
        path = self._path(agent)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self._cache[agent] = data
                return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load memory for %s: %s", agent, exc)
        data: dict = {"kv": {}, "turns": []}
        self._cache[agent] = data
        return data

    async def _save(self, agent: str, data: dict) -> None:
        self._cache[agent] = data
        path = self._path(agent)
        try:
            _atomic_write(path, json.dumps(data, indent=2, default=str))
        except OSError as exc:
            logger.error("Failed to save memory for %s: %s", agent, exc)
