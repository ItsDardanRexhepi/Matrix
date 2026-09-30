"""The idempotency store: ``idempotency_keys`` (database migration 11) and the
first answers this process gave.

A client that sends ``Idempotency-Key`` on ``POST /bridge/v1/action`` promises
that every request under that key is the same request. The key is scoped — a
sha256 of the surface, the caller the gate saw and the client's key — so one
caller's key never reaches another caller's run, and the raw key is never
written.

The first request under a key binds it to its run, in the transaction that
opens the run; a replay finds the binding and runs nothing. What it is answered
depends on the run:

* the run is still open → ``in progress``;
* the run ended → the FIRST answer, byte for byte, when this process still
  holds it; otherwise an answer saying the run's state and that the first
  answer is not held — never a second run;
* the key was bound to a different action or different parameters →
  ``conflict``.

WHAT IS STORED. The table holds the key digest, the run, a digest of the first
answer and when the key was bound: no raw address, no raw parameter, no answer.
The first answer itself is held in memory (``AnswerCache``), by the process
that gave it, for 24 hours or until 4,096 newer answers push it out — which is
why an answer can be "not held" after a restart. A key is never released once
its run's call began, so a replay can never act twice; it is released only with
a run that ended before its call began (ABORT), because such a request acted on
nothing and binding its key would refuse a retry that is safe.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from runtime.durable.journal import Tx

#: Longest client key accepted; a longer one is refused, not truncated.
MAX_CLIENT_KEY = 255
ANSWER_TTL_S = 24 * 60 * 60.0
ANSWER_CACHE_SIZE = 4096


def valid_client_key(client_key: Any) -> bool:
    """1-255 printable ASCII characters, no leading or trailing space."""
    return (isinstance(client_key, str) and 0 < len(client_key) <= MAX_CLIENT_KEY
            and client_key == client_key.strip()
            and all(32 <= ord(c) < 127 for c in client_key))


def scoped(surface: str, scope: str, client_key: str) -> str:
    """The key as stored: sha256 over the surface, the caller's scope and the
    client's key, each length-prefixed so no two triples collide."""
    h = hashlib.sha256()
    for part in (surface, scope, client_key):
        raw = part.encode("utf-8", "surrogatepass")
        h.update(len(raw).to_bytes(4, "big"))
        h.update(raw)
    return h.hexdigest()


def lookup(source: Any, key: str) -> tuple[str, str] | None:
    """``(run_id, response_digest)`` bound to *key*, or None."""
    sql = "SELECT run_id, response_digest FROM idempotency_keys WHERE key = ?"
    rows = source.rows(sql, (key,)) if isinstance(source, Tx) else source.fetchall_sync(sql, (key,))
    return (rows[0][0], rows[0][1]) if rows else None


def bind(tx: Tx, *, key: str, run_id: str, now: float) -> bool:
    """Bind *key* to *run_id*. False when another request already holds it."""
    return tx.execute("INSERT OR IGNORE INTO idempotency_keys (key, run_id, response_digest, "
                      "created_at) VALUES (?, ?, '', ?)", (key, run_id, now)) == 1


def answered(tx: Tx, *, key: str, run_id: str, response_digest: str) -> None:
    tx.run("UPDATE idempotency_keys SET response_digest = ? WHERE key = ? AND run_id = ?",
           (response_digest, key, run_id))


def release(tx: Tx, *, key: str, run_id: str) -> None:
    """Give *key* back — only while it is still bound to *run_id*."""
    tx.run("DELETE FROM idempotency_keys WHERE key = ? AND run_id = ?", (key, run_id))


class AnswerCache:
    """The first answer given under each key, in memory: bounded in number and
    in age, oldest pushed out first."""

    def __init__(self, *, size: int = ANSWER_CACHE_SIZE, ttl_s: float = ANSWER_TTL_S,
                 clock=time.time) -> None:
        self._size = size
        self._ttl = ttl_s
        self._clock = clock
        self._held: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def put(self, key: str, answer: str) -> None:
        self._held[key] = (answer, self._clock() + self._ttl)
        self._held.move_to_end(key)
        while len(self._held) > self._size:
            self._held.popitem(last=False)

    def get(self, key: str) -> str | None:
        found = self._held.get(key)
        if found is None:
            return None
        if found[1] < self._clock():
            del self._held[key]
            return None
        return found[0]

    def __len__(self) -> int:
        return len(self._held)
