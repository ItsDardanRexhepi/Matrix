"""SQLite-backed memory manager for 0pnMatrx agents.

The public interface is intentionally identical to the previous
file-backed implementation so the rest of the codebase does not need to
care that we now write to SQLite. Specifically:

- :meth:`read`, :meth:`get` are sync (with an in-process cache)
- :meth:`write`, :meth:`save_turn`, :meth:`save_conversation`,
  :meth:`mark_first_boot_sent` are async
- :meth:`get_context`, :meth:`load_conversation`,
  :meth:`is_first_boot_sent` are sync reads served from cache

Concurrency is handled by SQLite WAL mode, so we no longer keep per-agent
asyncio locks. The in-process cache is best-effort: if two coroutines
race to write the same key, the last write wins both in cache and on
disk, which is acceptable for our usage.

The previous implementation stored data as ``memory/<agent>.json`` and
``memory/conversations/<session>.json``. We do **not** migrate old files;
on first boot the new database simply starts empty.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from runtime.db.database import Database

logger = logging.getLogger(__name__)

MAX_CONTEXT_TURNS = 20
MAX_AGENT_TURNS = 200


class MemoryManager:
    """File-shaped persistent memory backed by SQLite."""

    def __init__(self, config: dict):
        self.config = config

        # Back-compat: callers (and existing tests) often pass
        # ``{"memory_dir": ...}``. If that key is present and the new
        # ``database.path`` key isn't, route the SQLite file under the
        # legacy memory directory.
        from pathlib import Path
        if "database" not in config and "memory_dir" in config:
            db_path = str(Path(config["memory_dir"]) / "0pnmatrx.db")
            db_config = dict(config)
            db_config["database"] = {"path": db_path}
        else:
            db_config = config

        self.db = Database(db_config)

        # Caches — populated lazily on first read.
        self._kv_cache: dict[str, dict] = {}        # agent -> {key: value}
        self._turn_cache: dict[str, list[dict]] = {}  # agent -> [{user, agent, ts}, ...]
        self._conv_cache: dict[str, list[dict]] = {}  # session -> [{role, content}, ...]
        self._first_boot_cache: set[str] | None = None
        self._loaded_agents: set[str] = set()
        self._loaded_conversations: set[str] = set()

        # Back-compat: some legacy code paths still reference memory_dir.
        # Keep it pointed at the directory containing the SQLite file so
        # health checks (which probe writability) still work.
        self.memory_dir = Path(self.db.db_path).parent

    # ── Lifecycle ──────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Open the database and run migrations.

        Must be awaited once on startup. Safe to call multiple times.
        """
        await self.db.initialize()

    async def close(self) -> None:
        await self.db.close()

    # ── Key / Value ────────────────────────────────────────────────

    def read(self, agent: str) -> dict:
        """Return the full memory dict for *agent*.

        Returns a dict shaped ``{"kv": {...}, "turns": [...]}`` to match
        the legacy on-disk format.
        """
        self._load_agent_sync(agent)
        kv = self._kv_cache.get(agent, {}).copy()
        turns = list(self._turn_cache.get(agent, []))
        return {"kv": kv, "turns": turns}

    async def write(self, agent: str, key: str, value: Any) -> None:
        """Set a single key in *agent*'s memory."""
        await self._ensure_agent_loaded(agent)
        self._kv_cache.setdefault(agent, {})[key] = value
        await self.db.execute(
            """
            INSERT INTO agent_memory (agent, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agent, key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (agent, key, json.dumps(value, default=str), time.time()),
        )

    def get(self, agent: str, key: str, default: Any = None) -> Any:
        """Get a single key from *agent*'s memory.

        Lazy-loads the agent's row from SQLite on first access — sync,
        because the underlying connection is sync.
        """
        self._load_agent_sync(agent)
        return self._kv_cache.get(agent, {}).get(key, default)

    async def get_async(self, agent: str, key: str, default: Any = None) -> Any:
        """Async variant that guarantees the agent is loaded from disk."""
        await self._ensure_agent_loaded(agent)
        return self._kv_cache.get(agent, {}).get(key, default)

    # ── Conversation Turns (per-agent log) ─────────────────────────

    async def save_turn(self, agent: str, user_message: str, agent_response: str) -> None:
        """Append a user/agent exchange to the conversation log."""
        await self._ensure_agent_loaded(agent)
        turns = self._turn_cache.setdefault(agent, [])
        seq = len(turns)
        ts = time.time()
        turns.append({"user": user_message, "agent": agent_response, "ts": ts})

        # Trim cache to last MAX_AGENT_TURNS
        if len(turns) > MAX_AGENT_TURNS:
            self._turn_cache[agent] = turns[-MAX_AGENT_TURNS:]
            # Re-number on disk too — easier than partial deletes.
            await self.db.execute("DELETE FROM agent_turns WHERE agent = ?", (agent,))
            await self.db.executemany(
                """
                INSERT INTO agent_turns (agent, seq, user_msg, agent_msg, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (agent, i, t["user"], t["agent"], t["ts"])
                    for i, t in enumerate(self._turn_cache[agent])
                ],
            )
        else:
            await self.db.execute(
                """
                INSERT INTO agent_turns (agent, seq, user_msg, agent_msg, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                (agent, seq, user_message, agent_response, ts),
            )

    def get_context(self, agent: str) -> str:
        """Return conversation context with smart summarisation.

        Keeps the last 5 turns verbatim for precision and summarises
        older turns into a brief narrative.  Extracts user facts
        (wallet addresses, goals, preferences) into a persistent block.
        """
        self._load_agent_sync(agent)
        turns = self._turn_cache.get(agent, [])
        if not turns:
            return ""

        parts: list[str] = []

        # Extract user facts from all turns
        facts = self._extract_user_facts(turns)
        if facts:
            fact_lines = [f"  {k}: {v}" for k, v in facts.items()]
            parts.append("[User Facts]\n" + "\n".join(fact_lines))

        # Summarise older turns (beyond last 5)
        if len(turns) > 5:
            older = turns[:-5]
            summary = self._summarise_turns(older)
            if summary:
                parts.append(f"[Earlier in this conversation]\n{summary}")

        # Last 5 turns verbatim
        recent = turns[-5:]
        lines: list[str] = []
        for t in recent:
            lines.append(f"User: {t['user']}")
            lines.append(f"Agent: {t['agent']}")
        parts.append("\n".join(lines))

        return "\n\n".join(parts)

    @staticmethod
    def _extract_user_facts(turns: list[dict]) -> dict[str, str]:
        """Extract key facts the user stated about themselves."""
        import re

        facts: dict[str, str] = {}
        for t in turns:
            user_msg = t.get("user", "")
            if not user_msg:
                continue

            # Wallet addresses (0x...)
            wallet_match = re.search(r"0x[a-fA-F0-9]{40}", user_msg)
            if wallet_match:
                facts["wallet"] = wallet_match.group(0)

            # Goals ("I want to...", "My goal is...")
            goal_match = re.search(
                r"(?:i want to|my goal is|i(?:'m| am) trying to|i need to)\s+(.{10,80})",
                user_msg,
                re.IGNORECASE,
            )
            if goal_match:
                facts["goal"] = goal_match.group(1).rstrip(".,!?")

            # Risk preferences
            risk_match = re.search(
                r"(?:i(?:'m| am) (?:not )?comfortable with|"
                r"i don(?:'t| not) want to risk|"
                r"my risk tolerance is)\s+(.{5,60})",
                user_msg,
                re.IGNORECASE,
            )
            if risk_match:
                facts["risk_preference"] = risk_match.group(1).rstrip(".,!?")

            # Budget / amount limits
            budget_match = re.search(
                r"(?:budget|limit|maximum|at most|no more than)\s+\$?([\d,]+(?:\.\d+)?)",
                user_msg,
                re.IGNORECASE,
            )
            if budget_match:
                facts["budget"] = "$" + budget_match.group(1)

        return facts

    @staticmethod
    def _summarise_turns(turns: list[dict]) -> str:
        """Produce a brief narrative summary of older turns."""
        if not turns:
            return ""

        topics: list[str] = []
        actions_taken: list[str] = []
        declines: list[str] = []

        topic_keywords = {
            "loan": "DeFi loans", "stake": "staking", "swap": "token swaps",
            "nft": "NFTs", "deploy": "contract deployment", "dao": "DAOs",
            "insurance": "insurance", "balance": "balance checks",
            "price": "price queries", "identity": "identity",
            "governance": "governance", "vote": "voting",
        }

        for t in turns:
            user_msg = (t.get("user", "") or "").lower()
            agent_msg = (t.get("agent", "") or "").lower()

            for keyword, topic in topic_keywords.items():
                if keyword in user_msg and topic not in topics:
                    topics.append(topic)

            if "successfully" in agent_msg or "completed" in agent_msg:
                for keyword, topic in topic_keywords.items():
                    if keyword in agent_msg and topic not in actions_taken:
                        actions_taken.append(topic)

            if "no" in user_msg[:20] or "don't" in user_msg or "cancel" in user_msg:
                declines.append(user_msg[:50])

        parts: list[str] = []
        if topics:
            parts.append(f"User asked about: {', '.join(topics[:5])}")
        if actions_taken:
            parts.append(f"Completed: {', '.join(actions_taken[:3])}")
        if declines:
            parts.append(f"Declined {len(declines)} suggestion(s)")

        return ". ".join(parts) + "." if parts else ""

    # ── Per-session conversation persistence ───────────────────────

    async def save_conversation(self, session_id: str, messages: list[dict]) -> None:
        """Replace the stored conversation for *session_id* with *messages*."""
        self._conv_cache[session_id] = list(messages)
        self._loaded_conversations.add(session_id)
        # Replace strategy: delete then bulk insert. Simple and correct.
        await self.db.execute(
            "DELETE FROM conversation_turns WHERE session_id = ?",
            (session_id,),
            commit=False,
        )
        if messages:
            await self.db.executemany(
                """
                INSERT INTO conversation_turns (session_id, seq, role, content, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (session_id, i, m.get("role", ""), m.get("content", ""), time.time())
                    for i, m in enumerate(messages)
                ],
            )
        else:
            # No rows to insert, but we still need to commit the DELETE.
            await self.db.execute("SELECT 1", commit=True)

    def load_conversation(self, session_id: str) -> list[dict]:
        """Return cached conversation messages, lazy-loading from SQLite if needed."""
        self._load_conversation_sync(session_id)
        return list(self._conv_cache.get(session_id, []))

    async def load_conversation_async(self, session_id: str) -> list[dict]:
        """Async load — fetches from SQLite if not cached."""
        if session_id in self._loaded_conversations:
            return list(self._conv_cache.get(session_id, []))
        rows = await self.db.fetchall(
            """
            SELECT role, content FROM conversation_turns
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        msgs = [{"role": r["role"], "content": r["content"]} for r in rows]
        self._conv_cache[session_id] = msgs
        self._loaded_conversations.add(session_id)
        return list(msgs)

    # ── First-boot tracking ────────────────────────────────────────

    async def mark_first_boot_sent(self, session_id: str) -> None:
        await self._ensure_first_boot_loaded()
        if self._first_boot_cache is None:
            self._first_boot_cache = set()
        self._first_boot_cache.add(session_id)
        await self.db.execute(
            """
            INSERT INTO first_boot (session_id, sent_at)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET sent_at = excluded.sent_at
            """,
            (session_id, time.time()),
        )

    def is_first_boot_sent(self, session_id: str) -> bool:
        self._load_first_boot_sync()
        return session_id in (self._first_boot_cache or set())

    # ── Internal loaders ───────────────────────────────────────────

    def _load_agent_sync(self, agent: str) -> None:
        """Lazy-load *agent*'s rows into the in-process cache.

        Synchronous because the underlying SQLite connection is sync.
        Safe to call from both sync and async code paths.
        """
        if agent in self._loaded_agents:
            return
        kv_rows = self.db.fetchall_sync(
            "SELECT key, value FROM agent_memory WHERE agent = ?",
            (agent,),
        )
        kv: dict[str, Any] = {}
        for row in kv_rows:
            try:
                kv[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                kv[row["key"]] = row["value"]
        self._kv_cache[agent] = kv

        turn_rows = self.db.fetchall_sync(
            """
            SELECT seq, user_msg, agent_msg, ts FROM agent_turns
            WHERE agent = ?
            ORDER BY seq ASC
            """,
            (agent,),
        )
        self._turn_cache[agent] = [
            {"user": r["user_msg"], "agent": r["agent_msg"], "ts": r["ts"]}
            for r in turn_rows
        ]
        self._loaded_agents.add(agent)

    def _load_first_boot_sync(self) -> None:
        if self._first_boot_cache is not None:
            return
        rows = self.db.fetchall_sync("SELECT session_id FROM first_boot")
        self._first_boot_cache = {r["session_id"] for r in rows}

    def _load_conversation_sync(self, session_id: str) -> None:
        if session_id in self._loaded_conversations:
            return
        rows = self.db.fetchall_sync(
            """
            SELECT role, content FROM conversation_turns
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        self._conv_cache[session_id] = [
            {"role": r["role"], "content": r["content"]} for r in rows
        ]
        self._loaded_conversations.add(session_id)

    async def _ensure_agent_loaded(self, agent: str) -> None:
        if agent in self._loaded_agents:
            return
        kv_rows = await self.db.fetchall(
            "SELECT key, value FROM agent_memory WHERE agent = ?",
            (agent,),
        )
        kv: dict[str, Any] = {}
        for row in kv_rows:
            try:
                kv[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                kv[row["key"]] = row["value"]
        self._kv_cache[agent] = kv

        turn_rows = await self.db.fetchall(
            """
            SELECT seq, user_msg, agent_msg, ts FROM agent_turns
            WHERE agent = ?
            ORDER BY seq ASC
            """,
            (agent,),
        )
        self._turn_cache[agent] = [
            {"user": r["user_msg"], "agent": r["agent_msg"], "ts": r["ts"]}
            for r in turn_rows
        ]
        self._loaded_agents.add(agent)

    async def _ensure_first_boot_loaded(self) -> None:
        if self._first_boot_cache is not None:
            return
        rows = await self.db.fetchall("SELECT session_id FROM first_boot")
        self._first_boot_cache = {r["session_id"] for r in rows}
