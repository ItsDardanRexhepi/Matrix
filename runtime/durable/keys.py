"""The idempotency store: ``idempotency_keys`` (database migration 10).

A client that sends ``Idempotency-Key`` with a state-changing request is saying
"this is one command, however many times it reaches you". The first request
under a key binds the key to its run; every later request under it gets that
first request's answer and runs nothing.

WHAT A KEY IS SCOPED TO. The stored ``key`` is a sha256 of the surface, the
caller the gate saw and the client's key — never the raw key — so one caller's
key never answers for another caller, and a key reused on another surface is a
different key.

THE FOUR ANSWERS a claim can give, besides binding a fresh key:

* ``hit`` — same request, and its answer is recorded: return that answer.
* ``conflict`` — the key was used for a DIFFERENT request (another action or
  other parameters): refuse, run nothing.
* ``in_flight`` — same request, and no answer is recorded: it is still running,
  or the process running it died after its effect call began. Run nothing; the
  run's own state says which.
* ``expired`` — same request, answered more than 24 hours ago: the answer is no
  longer held (it may name addresses, so it is not kept), and the request is
  still not run a second time.

A request that ended before its effect call began (a gate that refused it, an
action that does not exist, parameters that do not bind, a journal that could
not be written) does not bind its key: the key is released in the same
transaction that ends the run, and a retry under it is a first request.

Every function here takes a connection already inside a transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

#: The caller-supplied key: 8-64 characters of A-Z a-z 0-9 _ . : - (a UUID fits).
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")

#: How long a recorded answer is kept for replay. The key itself is kept.
ANSWER_KEPT_S = 24 * 3600.0

MISS = "miss"
HIT = "hit"
CONFLICT = "conflict"
IN_FLIGHT = "in_flight"
EXPIRED = "expired"

#: Field names whose values are withheld from a recorded answer. Names that are
#: secrets by definition — never a word like "token" or "key", which the
#: services use for a token symbol or a public key.
SECRET_FIELDS: frozenset[str] = frozenset({
    "private_key", "privatekey", "seed_phrase", "seed", "mnemonic", "secret",
    "client_secret", "password", "passphrase", "api_key", "apikey",
    "access_token", "refresh_token", "session_token", "auth_token", "bearer",
})
WITHHELD = "[withheld]"


@dataclass(frozen=True)
class Claim:
    outcome: str
    key: str
    run_id: str
    status: int | None = None
    response: str | None = None


def valid_client_key(raw: Any) -> bool:
    return isinstance(raw, str) and KEY_PATTERN.fullmatch(raw) is not None


def scoped_key(surface: str, actor_scope: str, client_key: str) -> str:
    material = f"{surface}\n{actor_scope}\n{client_key}".encode("utf-8", "surrogatepass")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def request_digest(request: Any) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8", "surrogatepass")).hexdigest()


def claim(conn: sqlite3.Connection, *, key: str, request_digest: str, run_id: str,
          now: float) -> Claim:
    """Bind *key* to *run_id* if it is unused (``miss``); otherwise say what the
    key is already bound to, and bind nothing."""
    row = conn.execute(
        "SELECT run_id, request_digest, status, response, expires_at "
        "FROM idempotency_keys WHERE key = ?", (key,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO idempotency_keys (key, run_id, first_seen, request_digest, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, run_id, now, request_digest, now + ANSWER_KEPT_S))
        return Claim(MISS, key, run_id)
    bound, digest, status, response, expires_at = (
        row[0], row[1], row[2], row[3], row[4])
    if digest != request_digest:
        return Claim(CONFLICT, key, bound)
    if status is not None and (response is None or now > float(expires_at)):
        return Claim(EXPIRED, key, bound, int(status))
    if status is not None:
        return Claim(HIT, key, bound, int(status), response)
    return Claim(IN_FLIGHT, key, bound)


def record_response(conn: sqlite3.Connection, *, key: str, run_id: str, status: int,
                    body: str) -> bool:
    """Record the answer the first request got. Only the request that bound the
    key can record it, and only once."""
    cur = conn.execute(
        "UPDATE idempotency_keys SET status = ?, response = ?, response_digest = ? "
        "WHERE key = ? AND run_id = ? AND status IS NULL",
        (int(status), body, hashlib.sha256(body.encode("utf-8", "surrogatepass")).hexdigest(),
         key, run_id))
    return cur.rowcount == 1


def release(conn: sqlite3.Connection, *, key: str, run_id: str) -> bool:
    """Unbind a key whose run never began its effect call."""
    cur = conn.execute(
        "DELETE FROM idempotency_keys WHERE key = ? AND run_id = ? AND status IS NULL",
        (key, run_id))
    return cur.rowcount == 1


def release_for_run(conn: sqlite3.Connection, run_id: str) -> int:
    cur = conn.execute(
        "DELETE FROM idempotency_keys WHERE run_id = ? AND status IS NULL", (run_id,))
    return cur.rowcount


def drop_expired_answers(conn: sqlite3.Connection, *, now: float) -> int:
    """Clear the answers kept past their 24 hours. The rows stay."""
    cur = conn.execute(
        "UPDATE idempotency_keys SET response = NULL "
        "WHERE response IS NOT NULL AND expires_at < ?", (now,))
    return cur.rowcount


def withhold_secrets(value: Any) -> Any:
    """*value* with every secret-named field's value replaced by ``[withheld]``,
    at any depth, including inside a string that is itself a JSON object or
    array (the bridge's ``data`` is the dispatcher's JSON string). A value with
    nothing to withhold comes back unchanged — the same object, the same string."""
    if isinstance(value, dict):
        out: dict = {}
        changed = False
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SECRET_FIELDS and v not in (None, ""):
                out[k] = WITHHELD
                changed = True
            else:
                nv = withhold_secrets(v)
                changed = changed or nv is not v
                out[k] = nv
        return out if changed else value
    if isinstance(value, list):
        items = [withhold_secrets(v) for v in value]
        return items if any(a is not b for a, b in zip(items, value)) else value
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        cleaned = withhold_secrets(parsed)
        return value if cleaned is parsed else json.dumps(cleaned)
    return value
