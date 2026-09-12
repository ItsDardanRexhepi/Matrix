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
import secrets
import time
from dataclasses import dataclass
from typing import Any

from runtime.db.database import Database

logger = logging.getLogger(__name__)

MAX_CONTEXT_TURNS = 20
MAX_AGENT_TURNS = 200


#: How long an erased conversation id stays in the erasure log
#: (``conversation_erasures``) before it is pruned. A turn admitted to an
#: unclaimed conversation that runs longer than this across ANY erasure whose
#: log entry has since been pruned is refused, since the log can no longer say
#: whether its conversation was among those erased.
ERASURE_LOG_SECONDS = 3600.0


@dataclass(frozen=True)
class ConversationClaim:
    """The claim a chat turn was admitted under: *session_id* held by *owner*
    ("" when unclaimed) through the claim *claim_id* ("" when unclaimed, or a
    claim stored before claims had ids), with *erasure_seq*, the store's
    erasure sequence number at admission.

    Writes a turn makes — the conversation and the scoped agent memory — land
    only while this claim still stands (``MemoryManager.claim_stands``).
    Comparing the owner alone is not enough: account deletion erases the
    claim, and the same subject signing in again makes a new claim with the
    same owner string. Comparing ``(owner, claim_id)`` alone is not enough for
    an UNCLAIMED conversation: a claim made and erased while the turn ran
    leaves ``("", "")`` again, so an unclaimed claim also requires that no
    erasure since *erasure_seq* erased the conversation."""
    session_id: str
    owner: str
    claim_id: str
    erasure_seq: int = 0


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
        # access reloads them — including the owner, which lives in its own
        # table (conversation_owners) from the moment it is claimed, whether or
        # not the conversation has any stored turns yet. The cached owner is a
        # copy of that row, never the only record of it.
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

    #: The scope of an anonymous conversation's agent memory and protocol
    #: state: ``conv:<session_id>``. An account's scope is its subject — a SIWE
    #: address (``0x…``, the address a signature recovered to) or
    #: ``apple:<sub>`` — and neither begins with this prefix, so no session id
    #: a caller chooses can name an account's scope. They were one namespace:
    #: an anonymous caller who sent an account's subject as its session id was
    #: shown that account's memory and wrote into it.
    CONVERSATION_SCOPE_PREFIX = "conv:"

    @classmethod
    def conversation_scope(cls, session_id: str) -> str:
        """The memory scope of the conversation *session_id* for a caller who
        has no account."""
        return f"{cls.CONVERSATION_SCOPE_PREFIX}{session_id}"

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
                        scope: str = "", *, claim: ConversationClaim | None = None) -> bool:
        """Append a user/agent exchange to the conversation log of *agent*
        within *scope* (the caller's account or conversation).

        With *claim* — the claim the turn was admitted under — the exchange is
        written only if that claim still stands, checked in the same
        transaction as the write. A turn whose account was deleted while it
        ran is not written back into the account's scope, whether or not the
        subject has signed in again since. Returns whether it was written."""
        agent = self.memory_key(agent, scope)
        await self._ensure_agent_loaded(agent)
        ts = time.time()
        entry = {"user": user_message, "agent": agent_response, "ts": ts}
        if claim is not None:
            return await self._save_turn_under_claim(agent, entry, claim)
        turns = self._turn_cache.setdefault(agent, [])
        seq = len(turns)
        turns.append(entry)

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
        return True

    async def _save_turn_under_claim(self, key: str, entry: dict, claim: ConversationClaim) -> bool:
        """The *claim* check and the write as ONE transaction, the log read
        from the store inside it (the cache may have been evicted while the
        write waited on the lock)."""

        def work(conn):
            if not self._stands_in(conn, claim):
                return None
            rows = conn.execute(
                "SELECT user_msg, agent_msg, ts FROM agent_turns WHERE agent = ? ORDER BY seq ASC",
                (key,)).fetchall()
            turns = [{"user": r[0], "agent": r[1], "ts": r[2]} for r in rows] + [entry]
            if len(turns) > MAX_AGENT_TURNS:
                turns = turns[-MAX_AGENT_TURNS:]
                conn.execute("DELETE FROM agent_turns WHERE agent = ?", (key,))
                conn.executemany(
                    "INSERT INTO agent_turns (agent, seq, user_msg, agent_msg, ts) VALUES (?, ?, ?, ?, ?)",
                    [(key, i, t["user"], t["agent"], t["ts"]) for i, t in enumerate(turns)])
            else:
                conn.execute(
                    "INSERT INTO agent_turns (agent, seq, user_msg, agent_msg, ts) VALUES (?, ?, ?, ?, ?)",
                    (key, len(rows), entry["user"], entry["agent"], entry["ts"]))
            return turns

        turns = await self.db.run_in_transaction(work)
        if turns is None:
            logger.info("a turn's conversation claim no longer stands; its memory was not written")
            return False
        # No await since the commit: an erasure cannot have run in between.
        if key in self._loaded_agents:
            self._turn_cache[key] = turns
        return True

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
                                owner: str | None = None, *,
                                expect_claim: ConversationClaim | None = None) -> bool:
        """Replace the stored conversation for *session_id* with *messages*.

        The owner is the durable claim (``conversation_owners``), read inside
        the same transaction as the write. *owner* claims an unclaimed
        conversation; it never replaces another account's claim. With
        *expect_claim*, the write happens only if the claim the turn was
        admitted under still stands (``claim_stands``). A turn whose
        conversation was erased (account deletion) or claimed by someone else
        while it ran is refused rather than written back into it; so is one
        whose conversation was erased and claimed again by the same subject,
        and one admitted while the conversation was unclaimed whose
        conversation was claimed and erased meanwhile, which leaves it
        unclaimed again. (An ``expect_owner`` that compared the owner string
        alone had no caller, and was that very comparison; it is gone.)

        Returns whether anything was written. Replace is DELETE + INSERT in
        ONE transaction: done in two lock acquisitions, a request queued on
        the lock read the conversation with no rows and no owner in between.
        """
        rows = [(m.get("role", ""), m.get("content", "")) for m in messages]

        def work(conn):
            current = self._owner_in(conn, session_id)
            if expect_claim is not None and (
                    expect_claim.session_id != session_id or not self._stands_in(conn, expect_claim)):
                return None
            if owner and current and owner != current:
                return None
            effective = current or (owner or "")
            if effective and not current:
                conn.execute(
                    "INSERT INTO conversation_owners (session_id, owner, claimed_at, claim_id) VALUES (?, ?, ?, ?)",
                    (session_id, effective, time.time(), secrets.token_hex(16)))
            conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
            if rows:
                now = time.time()
                conn.executemany(
                    """
                    INSERT INTO conversation_turns (session_id, seq, role, content, ts, owner)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [(session_id, i, role, content, now, effective)
                     for i, (role, content) in enumerate(rows)],
                )
            return effective

        effective = await self.db.run_in_transaction(work)
        if effective is None:
            # What the cache showed is no longer what the store holds.
            self._forget_conversation(session_id)
            logger.info("conversation %s changed owner while a turn ran; the turn was not stored",
                        session_id)
            return False
        self._conv_owner[session_id] = effective
        self._conv_cache.pop(session_id, None)
        self._conv_cache[session_id] = list(messages)
        self._loaded_conversations.add(session_id)
        self._evict_conversations(keep=session_id)
        return True

    def load_conversation(self, session_id: str) -> list[dict]:
        """Return cached conversation messages, lazy-loading from SQLite if needed."""
        self._load_conversation_sync(session_id)
        return list(self._conv_cache.get(session_id, []))

    def conversation_owner(self, session_id: str) -> str:
        """The account *session_id* belongs to, "" when nobody has claimed it."""
        self._load_conversation_sync(session_id)
        return self._conv_owner.get(session_id, "")

    def conversation_claim(self, session_id: str) -> ConversationClaim:
        """The claim *session_id* has now, read from the store (not the
        cache): what a turn is admitted under and must still find when it
        writes. The claim row and the erasure sequence number are read with
        nothing in between (sync, no await)."""
        conn = self.db._require_conn()
        owner, claim_id = self._claim_in(conn, session_id)
        seq, _ = self._erasure_state_in(conn)
        return ConversationClaim(session_id=session_id, owner=owner, claim_id=claim_id, erasure_seq=seq)

    def claim_stands(self, claim: ConversationClaim) -> bool:
        """Whether *claim* still stands (store) — the one test every write of
        a turn and the loop's start make."""
        return self._stands_in(self.db._require_conn(), claim)

    def claim_conversation(self, session_id: str, owner: str) -> str:
        """Bind an unclaimed conversation to *owner*; return the owner it has.

        The claim is written to ``conversation_owners`` NOW, rows or not. It
        used to reach disk only through existing turn rows, so a conversation
        with none — a signed-in caller's first turn, model call in flight —
        was owned by an evictable cache entry alone: evicted, the turn was
        saved ownerless and the next anonymous caller naming the id was handed
        it. The primary key makes the first claim win in the store."""
        self._load_conversation_sync(session_id)
        if not owner or self._conv_owner.get(session_id):
            return self._conv_owner.get(session_id, "")
        self.db.execute_sync(
            "INSERT OR IGNORE INTO conversation_owners (session_id, owner, claimed_at, claim_id) "
            "VALUES (?, ?, ?, ?)",
            (session_id, owner, time.time(), secrets.token_hex(16)),
        )
        held = self._owner_in(self.db._require_conn(), session_id)
        self._conv_owner[session_id] = held
        self.db.execute_sync(
            "UPDATE conversation_turns SET owner = ? "
            "WHERE session_id = ? AND (owner IS NULL OR owner = '')",
            (held, session_id),
        )
        return held

    async def erase_owner(self, owner: str) -> list[str]:
        """Delete every conversation owned by *owner* and every scoped agent
        memory written for it — what account deletion must be able to do.

        Returns the conversation ids erased, so a caller holding its own copy
        of those conversations (the gateway's working set) can drop it too.
        The conversations and their claims go in one transaction; a turn of
        the account still running no longer finds the claim it was admitted
        under — not even if the subject has signed in again and claimed the
        conversation anew — so neither its conversation nor its scoped memory
        is written (save_conversation's *expect_claim*, save_turn's *claim*).
        Nor is an anonymous turn admitted before the account claimed the
        conversation: the same transaction logs the erased ids under a new
        erasure sequence number (``conversation_erasures``, pruned after
        ``conversation_erasure_log_seconds``), so the unclaimed state the
        erasure leaves is not the one that turn was admitted under."""
        if not owner:
            return []

        def work(conn):
            ids = {r[0] for r in conn.execute(
                "SELECT session_id FROM conversation_owners WHERE owner = ?", (owner,))}
            ids |= {r[0] for r in conn.execute(
                "SELECT DISTINCT session_id FROM conversation_turns WHERE owner = ?", (owner,))}
            conn.execute("DELETE FROM conversation_turns WHERE owner = ?", (owner,))
            for sid in ids:
                conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM conversation_owners WHERE owner = ?", (owner,))
            # Deleting the claim leaves the conversation unclaimed: the state a
            # turn admitted before the claim was admitted under. The erasure
            # takes the next sequence number and logs what it erased, so that
            # turn no longer stands (_stands_in).
            if ids:
                now = time.time()
                seq = self._erasure_state_in(conn)[0] + 1
                conn.execute("UPDATE conversation_erasure_state SET seq = ? WHERE id = 1", (seq,))
                conn.executemany(
                    "INSERT OR IGNORE INTO conversation_erasures (seq, session_id, erased_at) VALUES (?, ?, ?)",
                    [(seq, sid, now) for sid in ids])
                self._prune_erasure_log_in(conn, now)
            return ids

        erased = await self.db.run_in_transaction(work)
        erased |= {s for s, o in self._conv_owner.items() if o == owner}
        for sid in erased:
            self._forget_conversation(sid)
        await self.erase_scoped_memory(owner)
        # The memory the account's conversations wrote before it claimed them
        # (anonymous turns, scoped to the conversation) goes with them.
        for sid in erased:
            await self.erase_scoped_memory(self.conversation_scope(sid))
        return sorted(erased)

    async def erase_scoped_memory(self, scope: str) -> None:
        """Delete every agent memory scoped to exactly *scope*
        (``agent@scope``, for every agent).

        Matched on the whole scope, not on the key's ending: "ends with
        ``@apple:x``" also named ``trinity@conv:notes@apple:x`` — an anonymous
        conversation whose id happens to end in the account's subject."""
        if not scope:
            return
        where = "instr(agent, '@') > 0 AND substr(agent, instr(agent, '@') + 1) = ?"
        await self.db.execute(f"DELETE FROM agent_turns WHERE {where}", (scope,))
        await self.db.execute(f"DELETE FROM agent_memory WHERE {where}", (scope,))
        keys = {k for k in list(self._turn_cache) + list(self._kv_cache)
                if "@" in k and k.split("@", 1)[1] == scope}
        for key in keys:
            self._turn_cache.pop(key, None)
            self._kv_cache.pop(key, None)
            self._loaded_agents.discard(key)

    async def load_conversation_async(self, session_id: str) -> list[dict]:
        """Async load — fetches from SQLite if not cached."""
        self._load_conversation_sync(session_id)
        return list(self._conv_cache.get(session_id, []))

    @staticmethod
    def _owner_in(conn, session_id: str) -> str:
        """The durable owner of *session_id* ("" when unclaimed)."""
        row = conn.execute(
            "SELECT owner FROM conversation_owners WHERE session_id = ?", (session_id,)).fetchone()
        return str(row[0] or "") if row else ""

    @staticmethod
    def _claim_in(conn, session_id: str) -> tuple[str, str]:
        """The durable ``(owner, claim_id)`` of *session_id* (``("", "")``
        when unclaimed)."""
        row = conn.execute(
            "SELECT owner, claim_id FROM conversation_owners WHERE session_id = ?", (session_id,)).fetchone()
        return (str(row[0] or ""), str(row[1] or "")) if row else ("", "")

    @staticmethod
    def _erasure_state_in(conn) -> tuple[int, int]:
        """``(seq, pruned_through)``: the last erasure's sequence number, and
        the highest sequence number whose log entries have been pruned."""
        row = conn.execute(
            "SELECT seq, pruned_through FROM conversation_erasure_state WHERE id = 1").fetchone()
        return (int(row[0]), int(row[1])) if row else (0, 0)

    @classmethod
    def _stands_in(cls, conn, claim: ConversationClaim) -> bool:
        """Whether *claim* still stands in the store *conn* reads.

        The claim row must be the one the turn was admitted under: same owner
        and same claim id (every claim gets a fresh random id, so erasing a
        claim and claiming again does not restore it). A claim with an owner
        needs nothing more. An UNCLAIMED claim ("", "") cannot be told from
        the state a claim's erasure leaves, so it also needs that no erasure
        since the turn's admission erased this conversation — and when the log
        that would say so has been pruned past the admission, it is refused."""
        if cls._claim_in(conn, claim.session_id) != (claim.owner, claim.claim_id):
            return False
        if claim.owner:
            return True
        seq, pruned_through = cls._erasure_state_in(conn)
        if seq == claim.erasure_seq:
            return True
        if seq < claim.erasure_seq or pruned_through > claim.erasure_seq:
            return False
        return conn.execute(
            "SELECT 1 FROM conversation_erasures WHERE session_id = ? AND seq > ? LIMIT 1",
            (claim.session_id, claim.erasure_seq)).fetchone() is None

    def _prune_erasure_log_in(self, conn, now: float) -> int:
        """Drop erasure log entries older than the retention window; a claim
        admitted before the newest dropped entry no longer stands."""
        retention = float(self.config.get("conversation_erasure_log_seconds", ERASURE_LOG_SECONDS))
        row = conn.execute(
            "SELECT MAX(seq) FROM conversation_erasures WHERE erased_at < ?", (now - retention,)).fetchone()
        through = int(row[0]) if row and row[0] is not None else 0
        if not through:
            return 0
        dropped = conn.execute("DELETE FROM conversation_erasures WHERE seq <= ?", (through,)).rowcount
        conn.execute(
            "UPDATE conversation_erasure_state SET pruned_through = MAX(pruned_through, ?) WHERE id = 1",
            (through,))
        return dropped

    async def prune_erasure_log(self) -> int:
        """Prune the erasure log (see ``_stands_in``): erased conversation ids
        are kept for ``conversation_erasure_log_seconds`` (default one hour),
        then dropped. Run by every erasure and by the gateway's periodic
        sweep. Returns the number of entries dropped."""
        return await self.db.run_in_transaction(lambda conn: self._prune_erasure_log_in(conn, time.time()))

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
        # The owner from its own table: it exists before the first stored turn.
        self._conv_owner[session_id] = self._owner_in(self.db._require_conn(), session_id)
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

