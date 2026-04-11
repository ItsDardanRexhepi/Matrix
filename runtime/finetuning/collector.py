"""Fine-tuning data collector backed by SQLite.

Records every conversation turn as a potential training example,
supports quality ratings, and exports high-quality examples in JSONL
format for Anthropic or OpenAI fine-tuning APIs.

Collection is opt-in: set ``finetuning.collect: true`` in
``openmatrix.config.json`` to enable recording.
"""

from __future__ import annotations

import json
import logging
import random
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS finetuning_examples (
    id                  TEXT PRIMARY KEY,
    agent               TEXT NOT NULL,
    user_message        TEXT NOT NULL,
    agent_response      TEXT NOT NULL,
    tool_calls          TEXT NOT NULL DEFAULT '[]',
    rating              INTEGER DEFAULT 0,
    flags               TEXT NOT NULL DEFAULT '[]',
    session_id          TEXT NOT NULL DEFAULT '',
    created_at          REAL NOT NULL,
    included_in_training INTEGER NOT NULL DEFAULT 0
)
"""

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_finetuning_agent_rating
    ON finetuning_examples (agent, rating)
"""


class FinetuningCollector:
    """Collects and manages fine-tuning training examples."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._initialized = False

    async def initialize(self) -> None:
        """Create the finetuning_examples table if it doesn't exist."""
        if self._initialized:
            return
        await self._db.execute(_SCHEMA_SQL, commit=True)
        await self._db.execute(_INDEX_SQL, commit=True)
        self._initialized = True

    async def record_example(
        self,
        agent: str,
        user_message: str,
        agent_response: str,
        tool_calls: list[dict] | None = None,
        session_id: str = "",
    ) -> str:
        """Record a conversation turn as a potential training example.

        Returns the example ID.
        """
        await self.initialize()
        example_id = uuid.uuid4().hex[:16]
        await self._db.execute(
            """
            INSERT INTO finetuning_examples
                (id, agent, user_message, agent_response, tool_calls,
                 session_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                example_id,
                agent,
                user_message,
                agent_response,
                json.dumps(tool_calls or []),
                session_id,
                time.time(),
            ),
            commit=True,
        )
        logger.debug("Recorded fine-tuning example %s for agent=%s", example_id, agent)
        return example_id

    async def rate_example(
        self,
        example_id: str,
        rating: int,
        flags: list[str] | None = None,
    ) -> None:
        """Rate an example (1-5) with optional quality flags.

        Supported flags: ``incorrect``, ``incomplete``, ``excellent``,
        ``perfect_tone``, ``wrong_tool``, ``hallucination``.
        """
        rating = max(1, min(5, rating))
        await self._db.execute(
            "UPDATE finetuning_examples SET rating = ?, flags = ? WHERE id = ?",
            (rating, json.dumps(flags or []), example_id),
            commit=True,
        )

    async def get_training_set(
        self,
        agent: str | None = None,
        min_rating: int = 4,
        limit: int = 1000,
    ) -> list[dict]:
        """Return high-quality examples formatted for fine-tuning."""
        await self.initialize()
        if agent:
            rows = await self._db.fetchall(
                """
                SELECT * FROM finetuning_examples
                WHERE agent = ? AND rating >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent, min_rating, limit),
            )
        else:
            rows = await self._db.fetchall(
                """
                SELECT * FROM finetuning_examples
                WHERE rating >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (min_rating, limit),
            )
        return [dict(row) for row in rows]

    async def export_jsonl(
        self,
        agent: str,
        output_path: str,
        min_rating: int = 4,
    ) -> int:
        """Export examples in fine-tuning JSONL format.

        Each line is a JSON object with a ``messages`` array suitable
        for the Anthropic or OpenAI fine-tuning API.

        Returns the number of examples exported.
        """
        examples = await self.get_training_set(agent=agent, min_rating=min_rating, limit=50_000)
        if not examples:
            logger.info("No examples to export for agent=%s (min_rating=%d)", agent, min_rating)
            return 0

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with path.open("w", encoding="utf-8") as fh:
            for ex in examples:
                record = {
                    "messages": [
                        {"role": "system", "content": f"You are {agent}, an AI agent on the 0pnMatrx platform."},
                        {"role": "user", "content": ex["user_message"]},
                        {"role": "assistant", "content": ex["agent_response"]},
                    ],
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        # Mark exported examples
        ids = [ex["id"] for ex in examples]
        for eid in ids:
            await self._db.execute(
                "UPDATE finetuning_examples SET included_in_training = 1 WHERE id = ?",
                (eid,),
                commit=False,
            )
        await self._db.execute("SELECT 1", commit=True)  # flush

        logger.info("Exported %d examples for agent=%s to %s", count, agent, output_path)
        return count

    async def get_stats(self) -> dict:
        """Return collection statistics by agent and rating distribution."""
        await self.initialize()
        rows = await self._db.fetchall(
            """
            SELECT agent,
                   COUNT(*) as total,
                   SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) as high_quality,
                   SUM(CASE WHEN rating = 0 THEN 1 ELSE 0 END) as unrated,
                   AVG(CASE WHEN rating > 0 THEN rating ELSE NULL END) as avg_rating
            FROM finetuning_examples
            GROUP BY agent
            """,
        )
        stats: dict[str, Any] = {"agents": {}, "ready_for_finetuning": False}
        total_high = 0
        for row in rows:
            r = dict(row)
            agent_name = r["agent"]
            high_quality = r["high_quality"] or 0
            total_high += high_quality
            stats["agents"][agent_name] = {
                "total_examples": r["total"],
                "high_quality": high_quality,
                "unrated": r["unrated"] or 0,
                "avg_rating": round(r["avg_rating"] or 0, 2),
                "ready": high_quality >= 100,
            }
        stats["ready_for_finetuning"] = total_high >= 100
        return stats
