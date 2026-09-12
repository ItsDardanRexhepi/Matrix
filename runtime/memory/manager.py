"""SQLite-backed memory manager for 0pnMatrx agents.

The public interface is intentionally identical to the previous
file-backed implementation so the rest of the codebase does not need to
care that we now write to SQLite. Specifically:

- :meth:`read`, :meth:`get` are sync (with an in-process cache)
- :meth:`write`, :meth:`save_turn`, :meth:`save_conversation`,
  :meth:`mark_first_boot_sent` are async
- :meth:`get_context`, :meth:`load_conversation` are sync reads served from
  a bounded cache (least recently used keys are dropped and reload from disk);
  :meth:`is_first_boot_sent` is a sync primary-key lookup

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

        # Caches — populated lazily on first read, write-through to SQLite, and
        # BOUNDED in the number of keys. Every key here is caller-named: a
        # conversation id, or ``agent@scope`` where an anonymous caller's scope
        # IS its conversation id. Unbounded, each id any caller ever named held
        # an entry for the life of the process. Dict order is recency (an
        # access re-inserts the key); past the cap the least recently used key
        # is dropped, which loses nothing: the rows are on disk and the next
        # access reloads them — including the owner, because a claim is written
        # to disk when it is made (claim_conversation), not only at next save.
        self._kv_cache: dict[str, dict] = {}        # agent -> {key: value}
        self._turn_cache: dict[str, list[dict]] = {}  # agent -> [{user, agent, ts}, ...]  (recency order)
        self._conv_cache: dict[str, list[dict]] = {}  # session -> [{role, content}, ...]  (recency order)
        self._conv_owner: dict[str, str] = {}         # session -> owner subject ("" = nobody yet)
        self._loaded_agents: set[str] = set()
        self._loaded_conversations: set[str] = set()
        self._conversation_cap = max(1, int(config.get("conversation_cache", 1024)))
        self._agent_cap = max(1, int(config.get("agent_memory_cache", 1024)))

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

    @staticmethod
    def memory_key(agent: str, scope: str = "") -> str:
        """Agent memory is namespaced by the caller: ``agent@scope``.

        Keyed by agent name alone, every user's turns — and the [User Facts]
        extracted from them — reached every other user's prompt (§D3.6). The
        bare agent key is the shared, unscoped memory (operator-curated and
        legacy rows); it is rendered only for unscoped callers.
        """
        return f"{agent}@{scope}" if scope else agent

    async def save_turn(self, agent: str, user_message: str, agent_response: str,
                        scope: str = "") -> None:
        """Append a user/agent exchange to the conversation log of *agent*
        within *scope* (the caller's account or conversation)."""
        agent = self.memory_key(agent, scope)
        await self._ensure_agent_loaded(agent)
        turns = self._turn_cache.setdefault(agent, [])
        seq = len(turns)
        ts = time.time()
        turns.append({"user": user_message, "agent": agent_response, "ts": ts})

        # Trim cache to last MAX_AGENT_TURNS
        if len(turns) > MAX_AGENT_TURNS:
            kept = turns[-MAX_AGENT_TURNS:]
            self._turn_cache[agent] = kept
            # Re-number on disk too — easier than partial deletes. `kept`, not
            # the cache entry: the entry may be evicted while this awaits.
            await self.db.execute("DELETE FROM agent_turns WHERE agent = ?", (agent,))
            await self.db.executemany(
                """
                INSERT INTO agent_turns (agent, seq, user_msg, agent_msg, ts)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (agent, i, t["user"], t["agent"], t["ts"])
                    for i, t in enumerate(kept)
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

    def get_context(self, agent: str, scope: str = "") -> str:
        """Return conversation context with smart summarisation, for *agent*
        within *scope* only.

        Keeps the last 5 turns verbatim for precision and summarises
        older turns into a brief narrative.  Extracts user facts
        (wallet addresses, goals, preferences) into a persistent block.
        """
        agent = self.memory_key(agent, scope)
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

    async def save_conversation(self, session_id: str, messages: list[dict],
                                owner: str | None = None) -> None:
        """Replace the stored conversation for *session_id* with *messages*.

        *owner* is the account the conversation belongs to (C2b); None keeps
        the owner already known for the session ("" when nobody has claimed it).
        """
        if owner is None:
            owner = self._conv_owner.get(session_id, "")
        self._conv_owner[session_id] = owner
        self._conv_cache.pop(session_id, None)
        self._conv_cache[session_id] = list(messages)
        self._loaded_conversations.add(session_id)
        self._evict_conversations(keep=session_id)
        # Replace strategy: delete then bulk insert. Simple and correct.
        await self.db.execute(
            "DELETE FROM conversation_turns WHERE session_id = ?",
            (session_id,),
            commit=False,
        )
        if messages:
            await self.db.executemany(
                """
                INSERT INTO conversation_turns (session_id, seq, role, content, ts, owner)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (session_id, i, m.get("role", ""), m.get("content", ""), time.time(), owner)
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

    def conversation_owner(self, session_id: str) -> str:
        """The account *session_id* belongs to, "" when nobody has claimed it."""
        self._load_conversation_sync(session_id)
        return self._conv_owner.get(session_id, "")

    def claim_conversation(self, session_id: str, owner: str) -> None:
        """Bind an ownerless conversation to *owner*.

        Written to the stored rows NOW, not at the next save: the cache is
        bounded, and a claim held only in an evictable entry would revert to
        ownerless when the entry is dropped — for instance when the claiming
        turn's model call failed, so no save ever carried the owner. A
        conversation with no stored rows has nothing to write; its claim gates
        continuation in memory and reaches disk with its first save."""
        self._load_conversation_sync(session_id)
        if owner and not self._conv_owner.get(session_id):
            self._conv_owner[session_id] = owner
            self.db.execute_sync(
                "UPDATE conversation_turns SET owner = ? "
                "WHERE session_id = ? AND (owner IS NULL OR owner = '')",
                (owner, session_id),
            )

    async def erase_owner(self, owner: str) -> list[str]:
        """Delete every conversation owned by *owner* and every scoped agent
        memory written for it — what account deletion must be able to do.

        Returns the conversation ids erased, so a caller holding its own copy
        of those conversations (the gateway's working set) can drop it too."""
        if not owner:
            return []
        rows = await self.db.fetchall(
            "SELECT DISTINCT session_id FROM conversation_turns WHERE owner = ?", (owner,))
        erased = {r["session_id"] for r in rows}
        erased |= {s for s, o in self._conv_owner.items() if o == owner}
        await self.db.execute("DELETE FROM conversation_turns WHERE owner = ?", (owner,))
        for sid in erased:
            self._forget_conversation(sid)
        suffix = f"@{owner}"
        keys = {k for k in list(self._turn_cache) + list(self._kv_cache) if k.endswith(suffix)}
        keys |= {self.memory_key(a, owner) for a in ("neo", "trinity", "morpheus")}
        for key in keys:
            await self.db.execute("DELETE FROM agent_turns WHERE agent = ?", (key,))
            await self.db.execute("DELETE FROM agent_memory WHERE agent = ?", (key,))
            self._turn_cache.pop(key, None)
            self._kv_cache.pop(key, None)
            self._loaded_agents.discard(key)
        return sorted(erased)

    async def load_conversation_async(self, session_id: str) -> list[dict]:
        """Async load — fetches from SQLite if not cached."""
        if session_id in self._loaded_conversations:
            self._touch_conversation(session_id)
            return list(self._conv_cache.get(session_id, []))
        rows = await self.db.fetchall(
            """
            SELECT role, content, owner FROM conversation_turns
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        msgs = [{"role": r["role"], "content": r["content"]} for r in rows]
        self._conv_cache[session_id] = msgs
        if rows:
            self._conv_owner[session_id] = str(rows[0]["owner"] or "")
        self._loaded_conversations.add(session_id)
        self._evict_conversations(keep=session_id)
        return list(msgs)

    # ── First-boot tracking ────────────────────────────────────────

    # Looked up per session against the primary key rather than held as a set
    # of every session ever greeted (which grew by one caller-named id per
    # conversation for the life of the process).

    async def mark_first_boot_sent(self, session_id: str) -> None:
        await self.db.execute(
            """
            INSERT INTO first_boot (session_id, sent_at)
            VALUES (?, ?)
            ON CONFLICT(session_id) DO UPDATE SET sent_at = excluded.sent_at
            """,
            (session_id, time.time()),
        )

    def is_first_boot_sent(self, session_id: str) -> bool:
        return bool(self.db.fetchall_sync(
            "SELECT 1 FROM first_boot WHERE session_id = ? LIMIT 1", (session_id,)))

    # ── Internal loaders ───────────────────────────────────────────

    def _load_agent_sync(self, agent: str) -> None:
        """Lazy-load *agent*'s rows into the in-process cache.

        Synchronous because the underlying SQLite connection is sync.
        Safe to call from both sync and async code paths.
        """
        if agent in self._loaded_agents:
            self._touch_agent(agent)
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
        self._evict_agents(keep=agent)


    # ── Bounded caches: recency and eviction ──────────────────────

    def _touch_conversation(self, session_id: str) -> None:
        if session_id in self._conv_cache:
            self._conv_cache[session_id] = self._conv_cache.pop(session_id)

    def _forget_conversation(self, session_id: str) -> None:
        self._conv_cache.pop(session_id, None)
        self._conv_owner.pop(session_id, None)
        self._loaded_conversations.discard(session_id)

    def _evict_conversations(self, keep: str) -> None:
        """Drop least-recently-used conversations past the cap (never *keep*)."""
        while len(self._conv_cache) > self._conversation_cap:
            oldest = next(iter(self._conv_cache))
            if oldest == keep:
                break
            self._forget_conversation(oldest)

    def _touch_agent(self, agent: str) -> None:
        if agent in self._turn_cache:
            self._turn_cache[agent] = self._turn_cache.pop(agent)

    def _evict_agents(self, keep: str) -> None:
        """Drop least-recently-used ``agent@scope`` memories past the cap."""
        while len(self._turn_cache) > self._agent_cap:
            oldest = next(iter(self._turn_cache))
            if oldest == keep:
                break
            self._turn_cache.pop(oldest, None)
            self._kv_cache.pop(oldest, None)
            self._loaded_agents.discard(oldest)

    def _load_conversation_sync(self, session_id: str) -> None:
        if session_id in self._loaded_conversations:
            self._touch_conversation(session_id)
            return
        rows = self.db.fetchall_sync(
            """
            SELECT role, content, owner FROM conversation_turns
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        self._conv_cache[session_id] = [
            {"role": r["role"], "content": r["content"]} for r in rows
        ]
        if rows:
            self._conv_owner[session_id] = str(rows[0]["owner"] or "")
        self._loaded_conversations.add(session_id)
        self._evict_conversations(keep=session_id)

    async def _ensure_agent_loaded(self, agent: str) -> None:
        if agent in self._loaded_agents:
            self._touch_agent(agent)
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
        self._evict_agents(keep=agent)

