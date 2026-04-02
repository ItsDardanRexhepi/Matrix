"""
Memory Manager — persistent key-value and conversation memory for agents.

Stores per-agent memory in the ``memory/`` directory as JSON files.
Provides:
- Key/value read and write (exposed via /memory/read and /memory/write)
- Conversation turn persistence (called by the ReAct loop after each turn)
- Context retrieval (recent turns injected into agent system prompt)
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = "memory"
MAX_CONTEXT_TURNS = 20


class MemoryManager:
    """File-backed memory store, one JSON file per agent."""

    def __init__(self, config: dict):
        self.memory_dir = Path(config.get("memory_dir", DEFAULT_MEMORY_DIR))
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}

    # ── Key / Value ───────────────────────────────────────────────

    def read(self, agent: str) -> dict:
        """Return the full memory dict for *agent*."""
        return self._load(agent)

    def write(self, agent: str, key: str, value: Any) -> None:
        """Set a single key in *agent*'s memory."""
        data = self._load(agent)
        data.setdefault("kv", {})[key] = value
        self._save(agent, data)

    def get(self, agent: str, key: str, default: Any = None) -> Any:
        """Get a single key from *agent*'s memory."""
        data = self._load(agent)
        return data.get("kv", {}).get(key, default)

    # ── Conversation Turns ────────────────────────────────────────

    async def save_turn(self, agent: str, user_message: str, agent_response: str) -> None:
        """Append a user/agent exchange to the conversation log."""
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
        self._save(agent, data)

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

    def _save(self, agent: str, data: dict) -> None:
        self._cache[agent] = data
        path = self._path(agent)
        try:
            path.write_text(json.dumps(data, indent=2, default=str))
        except OSError as exc:
            logger.error("Failed to save memory for %s: %s", agent, exc)
