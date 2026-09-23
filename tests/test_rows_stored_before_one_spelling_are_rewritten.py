"""Rows the platform stored before the one-spelling rule are rewritten in it.

THE DEFECT. The platform now names a wallet in one spelling, `0x` and its digits
in lower case (runtime/auth/identity.py). Before that rule, a SIWE session was
stored under the address as it was sent to /auth/verify, usually the EIP-55
checksum form, and everything keyed on the account was keyed on that spelling:
the conversations it claimed (conversation_owners, conversation_turns.owner),
its own `user:<subject>` conversation, its scoped agent memory
(`<agent>@<subject>`), the devices it registered (push_tokens.owner), its IAP
entitlements (user_key), and the wallet-keyed stores (follows, plugin
purchases). The session and Apple-user stores were read back in the new
spelling; nothing else was. So after an upgrade, the account was refused its own
conversation (403 "this conversation belongs to another account"), and deleting
the account answered 200 while its conversation claim, its memory and its
devices stayed stored, because the deletion looked them up in the new spelling.

THE RULE. Schema migration 8 rewrites every identity the platform stored in its
own database in the one spelling, once, when the gateway opens it:
  (a) columns that hold a caller: wallet_sessions.address,
      apple_users.wallet_address, conversation_owners.owner,
      conversation_turns.owner, push_tokens.owner and .wallet, the IAP
      user_key columns
  (b) ids that name an account: `user:<address>` conversation ids, wherever a
      conversation id is stored (claims, turns, first-boot marks, the erasure
      log, the devices filed under one)
  (c) agent memory keys scoped to an account (`<agent>@<address>`, and
      `<agent>@conv:user:<address>`)
  (d) wallet-keyed stores: the follow graph, plugin purchases
  (e) the sponsorship ledger, which is its own database file and rewrites its
      spenders when it is opened: its old meter kept a `0X` address apart
      from the same address with `0x`, so that spend no longer counted
      against the caller's one budget
  (f) an account's own conversation id, `user:<address>`, is read in the one
      spelling wherever a caller names a conversation, so a client still
      holding the old spelling of its id reaches the rewritten conversation
Where the one spelling is already taken (one wallet that signed in under two
spellings before the rule), the rows merge: a conversation's turns and an
agent's turns follow each other, numbered on from the last one already held
the way the platform numbers turns (from 0), the newer of two memory values
for the same key stays, a duplicate follow, first-boot mark or erasure-log row
goes, and a conversation claimed under the same id by two different accounts is
left as it is. Values that are not hex addresses are never touched:
`apple:<sub>`, labels, and anonymous conversation ids, whose case is the
caller's to choose.

§CC, measured: against 6d9bc9c, with this file added, 5 failed and 1 passed,
on the no-op backend and with the core installed. The one that passed is the
scope pin (ids that are not addresses are left as they are). The five failed on
the behaviour: every row stayed in the checksum spelling and two spellings of
one wallet stayed two; through the gateway the account's own conversation
answered 403 "this conversation belongs to another account", and its deletion
answered 200 and left the conversation claims, the scoped memory, the agent
turns and the device in place; the sponsorship ledger did not count a 0X
spender's spend against the one budget. After the change, 6 passed on both
backends.

§CC, second round: the first round's merge test seeded every turn with seq 1,
and the platform numbers turns from 0 (runtime/memory/manager.py), so the
merge it passed was not the one the gateway performs. Measured against da81d60
with the seeds numbered from 0 and the four controls at the end of this file
added: 4 failed and 6 passed. The merge test and the ordering test failed with
"UNIQUE constraint failed" on (session_id, seq) and on (agent, seq), the
migration rolled back and the database stayed at schema 7; the gateway could
not open such a database at all; and a migration step raising something other
than a database error was raised without the rollback being logged. With the
seq fix alone, the same erasure recorded under both spellings stayed two rows.
After the change, 10 passed.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

CHK = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
LOW = CHK.lower()
OTHER_CHK = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
OTHER = OTHER_CHK.lower()
ANON_SID = "conv-" + CHK      # an anonymous id the caller chose; its case is its own


def _database_before_the_rule(path, monkeypatch):
    """A database at schema 7, the last schema before the rule, as the gateway
    left it."""
    import runtime.db.database as database

    with monkeypatch.context() as m:
        m.setattr(database, "MIGRATIONS", [x for x in database.MIGRATIONS if x[0] <= 7])
        db = database.Database({"database": {"path": str(path)}})
        assert db.schema_version == 7
        db._conn.close()


def _seed(path, rows):
    conn = sqlite3.connect(str(path))
    with conn:
        for sql, params in rows:
            conn.execute(sql, params)
    conn.close()


def _open(path):
    from runtime.db.database import Database
    return Database({"database": {"path": str(path)}})


def _all(db, sql, params=()):
    return [tuple(r) for r in db._conn.execute(sql, params).fetchall()]


_PUSH = ("CREATE TABLE IF NOT EXISTS push_tokens (device_token TEXT PRIMARY KEY, "
         "session_id TEXT, wallet TEXT, platform TEXT, bundle_id TEXT, updated_at REAL, owner TEXT)")
_FOLLOWS = ("CREATE TABLE IF NOT EXISTS social_follows (follower TEXT, followee TEXT, "
            "created_at REAL, PRIMARY KEY (follower, followee))")
_PURCHASES = ("CREATE TABLE IF NOT EXISTS plugin_purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "wallet_address TEXT NOT NULL, plugin_id TEXT NOT NULL, price_paid REAL DEFAULT 0.0, "
              "stripe_session TEXT, purchased_at REAL NOT NULL, UNIQUE(wallet_address, plugin_id))")
_ENTITLEMENTS = ("CREATE TABLE IF NOT EXISTS iap_entitlements (original_transaction_id TEXT PRIMARY KEY, "
                 "user_key TEXT, product_id TEXT, tier TEXT, status TEXT, purchase_date REAL, "
                 "expires_date REAL, environment TEXT, updated_at REAL)")


def _account_rows(subject, *, session_token="tok-1", now=None):
    now = now or time.time()
    uid = f"user:{subject}"
    return [
        ("INSERT INTO wallet_sessions VALUES (?, ?, ?, ?)", (session_token, subject, now, now + 86400)),
        ("INSERT INTO apple_users VALUES (?, ?, ?, ?)", ("apple-sub-1", now, now, subject)),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", ("conv-probe", subject, now, "claim-1")),
        ("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)", ("conv-probe", 0, "user", "hi", now, subject)),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid, subject, now, "claim-2")),
        ("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)", (uid, 0, "user", "mine", now, subject)),
        ("INSERT INTO first_boot VALUES (?, ?)", (uid, now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@{subject}", "name", '"Ada"', now)),
        ("INSERT INTO agent_turns VALUES (?, ?, ?, ?, ?)", (f"trinity@{subject}", 0, "u", "a", now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@conv:{uid}", "k", '"v"', now)),
        (_PUSH, ()),
        ("INSERT INTO push_tokens VALUES (?, ?, ?, ?, ?, ?, ?)",
         ("device-1", uid, subject, "ios", "b", now, subject)),
        (_FOLLOWS, ()),
        ("INSERT INTO social_follows VALUES (?, ?, ?)", (subject, OTHER_CHK, now)),
        (_PURCHASES, ()),
        ("INSERT INTO plugin_purchases (wallet_address, plugin_id, purchased_at) VALUES (?, ?, ?)",
         (subject, "plugin-1", now)),
        (_ENTITLEMENTS, ()),
        ("INSERT INTO iap_entitlements (original_transaction_id, user_key, tier, status) VALUES (?, ?, ?, ?)",
         ("otx-1", subject, "pro", "active")),
    ]


def test_every_identity_the_platform_stored_is_rewritten_in_the_one_spelling(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    _database_before_the_rule(path, monkeypatch)
    _seed(path, _account_rows(CHK))

    db = _open(path)
    assert db.schema_version >= 8
    uid = f"user:{LOW}"
    assert _all(db, "SELECT address FROM wallet_sessions") == [(LOW,)]
    assert _all(db, "SELECT wallet_address FROM apple_users") == [(LOW,)]
    assert sorted(_all(db, "SELECT session_id, owner FROM conversation_owners")) == [
        ("conv-probe", LOW), (uid, LOW)]
    assert sorted(_all(db, "SELECT session_id, seq, owner FROM conversation_turns")) == [
        ("conv-probe", 0, LOW), (uid, 0, LOW)]
    assert _all(db, "SELECT session_id FROM first_boot") == [(uid,)]
    assert sorted(_all(db, "SELECT agent, key FROM agent_memory")) == sorted([
        (f"trinity@conv:{uid}", "k"), (f"trinity@{LOW}", "name")])
    assert _all(db, "SELECT agent FROM agent_turns") == [(f"trinity@{LOW}",)]
    assert _all(db, "SELECT session_id, wallet, owner FROM push_tokens") == [(uid, LOW, LOW)]
    assert _all(db, "SELECT follower, followee FROM social_follows") == [(LOW, OTHER)]
    assert _all(db, "SELECT wallet_address FROM plugin_purchases") == [(LOW,)]
    assert _all(db, "SELECT user_key FROM iap_entitlements") == [(LOW,)]


def test_one_wallet_stored_under_two_spellings_merges_into_one(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    _database_before_the_rule(path, monkeypatch)
    now = time.time()
    uid_chk, uid_low = f"user:{CHK}", f"user:{LOW}"
    _seed(path, [
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_low, LOW, now, "c-low")),
        ("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)", (uid_low, 0, "user", "first", now, LOW)),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_chk, CHK, now, "c-chk")),
        ("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)", (uid_chk, 0, "user", "second", now, CHK)),
        ("INSERT INTO first_boot VALUES (?, ?)", (uid_low, now)),
        ("INSERT INTO first_boot VALUES (?, ?)", (uid_chk, now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@{LOW}", "name", '"old"', now - 10)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@{CHK}", "name", '"new"', now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@{CHK}", "city", '"Lagos"', now)),
        ("INSERT INTO agent_turns VALUES (?, ?, ?, ?, ?)", (f"trinity@{LOW}", 0, "u1", "a1", now)),
        ("INSERT INTO agent_turns VALUES (?, ?, ?, ?, ?)", (f"trinity@{CHK}", 0, "u2", "a2", now)),
        (_FOLLOWS, ()),
        ("INSERT INTO social_follows VALUES (?, ?, ?)", (LOW, OTHER, now)),
        ("INSERT INTO social_follows VALUES (?, ?, ?)", (CHK, OTHER_CHK, now)),
        # a claim under the account's id by another account is left as it is
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (f"user:{OTHER_CHK}", "apple:someone", now, "c-x")),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (f"user:{OTHER}", OTHER, now, "c-y")),
    ])

    db = _open(path)
    assert sorted(_all(db, "SELECT session_id, owner FROM conversation_owners")) == sorted([
        (uid_low, LOW), (f"user:{OTHER_CHK}", "apple:someone"), (f"user:{OTHER}", OTHER)])
    assert _all(db, "SELECT seq, content FROM conversation_turns WHERE session_id = ? ORDER BY seq",
                (uid_low,)) == [(0, "first"), (1, "second")]
    assert _all(db, "SELECT session_id FROM first_boot") == [(uid_low,)]
    assert sorted(_all(db, "SELECT agent, key, value FROM agent_memory")) == [
        (f"trinity@{LOW}", "city", '"Lagos"'), (f"trinity@{LOW}", "name", '"new"')]
    assert _all(db, "SELECT seq, user_msg FROM agent_turns ORDER BY seq") == [(0, "u1"), (1, "u2")]
    assert _all(db, "SELECT follower, followee FROM social_follows") == [(LOW, OTHER)]


def test_ids_that_are_not_addresses_are_left_as_they_are(tmp_path, monkeypatch):
    """SCOPE PIN: an Apple subject, a label, and an anonymous conversation id
    that happens to contain an address keep their case."""
    path = tmp_path / "m.db"
    _database_before_the_rule(path, monkeypatch)
    now = time.time()
    _seed(path, [
        ("INSERT INTO wallet_sessions VALUES (?, ?, ?, ?)", ("t", "apple:AbC", now, now + 60)),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (ANON_SID, "apple:AbC", now, "c")),
        ("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)", (ANON_SID, 0, "user", "x", now, "")),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", (f"trinity@conv:{ANON_SID}", "k", '"v"', now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", ("trinity@apple:AbC", "k", '"v"', now)),
        ("INSERT INTO agent_memory VALUES (?, ?, ?, ?)", ("Trinity", "k", '"v"', now)),
    ])
    db = _open(path)
    assert _all(db, "SELECT address FROM wallet_sessions") == [("apple:AbC",)]
    assert _all(db, "SELECT session_id, owner FROM conversation_owners") == [(ANON_SID, "apple:AbC")]
    assert _all(db, "SELECT session_id FROM conversation_turns") == [(ANON_SID,)]
    assert sorted(_all(db, "SELECT agent FROM agent_memory")) == sorted([
        (f"trinity@conv:{ANON_SID}",), ("trinity@apple:AbC",), ("Trinity",)])


# ── the reviewer's scenario, through the gateway ──────────────────────────


def _gateway(tmp_path, db_path):
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    config = {**SWEEP_CONFIG,
              "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "test-operator-key"},
              "memory_dir": str(tmp_path),
              "database": {**SWEEP_CONFIG.get("database", {}), "path": str(db_path)}}
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub",
                                     metadata={}))
    return server


async def test_an_account_from_before_the_rule_keeps_its_conversation(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    path = tmp_path / "g.db"
    _database_before_the_rule(path, monkeypatch)
    _seed(path, _account_rows(CHK, session_token="tok-before"))

    server = _gateway(tmp_path, path)
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": "hello again", "session_id": "conv-probe"},
                              headers={"X-Wallet-Session": "tok-before"})
        body = await r.text()
        assert r.status != 403 and "belongs to another account" not in body, (r.status, body)
        r = await client.post("/chat", json={"message": "and my own", "session_id": f"user:{CHK}"},
                              headers={"X-Wallet-Session": "tok-before"})
        body = await r.text()
        assert r.status != 403 and "belongs to another account" not in body, (r.status, body)

    check = sqlite3.connect(str(path))
    try:
        accounts = {row[0] for row in check.execute(
            "SELECT session_id FROM conversation_owners WHERE session_id LIKE 'user:%'")}
    finally:
        check.close()
    assert accounts == {f"user:{LOW}"}, f"the account's own conversation split in two: {accounts}"


def test_the_sponsorship_ledger_counts_a_0X_spender_against_the_one_budget(tmp_path):
    """(e)"""
    import runtime.blockchain.sponsorship as sponsorship

    path = tmp_path / "sponsorship_spend.db"
    now = time.time()
    conn = sqlite3.connect(str(path))
    with conn:
        conn.executescript(sponsorship._SCHEMA)
        conn.execute("INSERT INTO sponsorship_spend VALUES (?, ?, ?, ?, ?, ?)",
                     ("r1", "0X" + CHK[2:].upper(), "send", 7.5, sponsorship.SPEND_STATES.SPENT, now))
    conn.close()

    policy = sponsorship.SponsorshipPolicy(allowed_actions=None, daily_cap_usd=10.0, db_path=path)
    with policy._connect() as conn:
        assert policy._spent(conn, sponsorship.canonical_identity(CHK), now) == 7.5


async def test_deleting_an_account_from_before_the_rule_deletes_what_it_stored(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    path = tmp_path / "g.db"
    _database_before_the_rule(path, monkeypatch)
    _seed(path, _account_rows(CHK, session_token="tok-before"))

    server = _gateway(tmp_path, path)
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.delete("/api/v1/auth/account", headers={"X-Wallet-Session": "tok-before"})
        assert r.status == 200, await r.text()

    check = sqlite3.connect(str(path))
    try:
        left = {
            "claims": check.execute("SELECT session_id, owner FROM conversation_owners").fetchall(),
            "turns": check.execute("SELECT session_id FROM conversation_turns").fetchall(),
            "memory": check.execute("SELECT agent FROM agent_memory").fetchall(),
            "agent turns": check.execute("SELECT agent FROM agent_turns").fetchall(),
            "devices": check.execute("SELECT device_token FROM push_tokens").fetchall(),
            "sessions": check.execute("SELECT token FROM wallet_sessions").fetchall(),
        }
    finally:
        check.close()
    assert all(v == [] for v in left.values()), left


# ── turns the platform itself numbered, under two spellings ─────────────────
#
# The platform numbers a conversation's turns and an agent's turns from 0
# (runtime/memory/manager.py: enumerate(rows), and seq = len(turns)). A merge
# that appends the moved rows after the target's last seq must start at
# MAX(seq) + 1; starting at MAX(seq) lands the first moved row on the target's
# last row, and the table's (key, seq) primary key refuses it.


def _turn_rows(session_id, owner, contents, now):
    return [("INSERT INTO conversation_turns VALUES (?, ?, ?, ?, ?, ?)",
             (session_id, i, "user", c, now, owner)) for i, c in enumerate(contents)]


def _agent_turn_rows(agent, pairs, now):
    return [("INSERT INTO agent_turns VALUES (?, ?, ?, ?, ?)", (agent, i, u, a, now))
            for i, (u, a) in enumerate(pairs)]


def test_turns_numbered_as_the_platform_numbers_them_merge_in_order_under_both_spellings(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    _database_before_the_rule(path, monkeypatch)
    now = time.time()
    uid_chk, uid_low = f"user:{CHK}", f"user:{LOW}"
    _seed(path, [
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_low, LOW, now, "c-low")),
        *_turn_rows(uid_low, LOW, ["l0", "l1", "l2"], now),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_chk, CHK, now, "c-chk")),
        *_turn_rows(uid_chk, CHK, ["c0", "c1"], now),
        *_agent_turn_rows(f"trinity@{LOW}", [("u0", "a0"), ("u1", "a1")], now),
        *_agent_turn_rows(f"trinity@{CHK}", [("v0", "b0"), ("v1", "b1"), ("v2", "b2")], now),
        # the same conversation erased under both spellings in one erasure
        ("INSERT INTO conversation_erasures (seq, session_id, erased_at) VALUES (?, ?, ?)", (4, uid_low, now)),
        ("INSERT INTO conversation_erasures (seq, session_id, erased_at) VALUES (?, ?, ?)", (4, uid_chk, now)),
    ])

    db = _open(path)
    assert db.schema_version >= 8
    assert _all(db, "SELECT seq, content FROM conversation_turns ORDER BY seq") == [
        (0, "l0"), (1, "l1"), (2, "l2"), (3, "c0"), (4, "c1")]
    assert _all(db, "SELECT DISTINCT session_id FROM conversation_turns") == [(uid_low,)]
    assert _all(db, "SELECT seq, user_msg FROM agent_turns ORDER BY seq") == [
        (0, "u0"), (1, "u1"), (2, "v0"), (3, "v1"), (4, "v2")]
    assert _all(db, "SELECT DISTINCT agent FROM agent_turns") == [(f"trinity@{LOW}",)]
    assert _all(db, "SELECT session_id, seq FROM conversation_erasures") == [(uid_low, 4)]


def test_a_wallet_with_turns_under_one_spelling_only_keeps_its_numbering(tmp_path, monkeypatch):
    """SCOPE PIN: nothing to append after, so the moved rows keep their seqs."""
    path = tmp_path / "m.db"
    _database_before_the_rule(path, monkeypatch)
    now = time.time()
    _seed(path, [
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (f"user:{CHK}", CHK, now, "c-chk")),
        *_turn_rows(f"user:{CHK}", CHK, ["c0", "c1"], now),
        *_agent_turn_rows(f"trinity@{CHK}", [("v0", "b0"), ("v1", "b1")], now),
    ])
    db = _open(path)
    assert _all(db, "SELECT session_id, seq FROM conversation_turns ORDER BY seq") == [
        (f"user:{LOW}", 0), (f"user:{LOW}", 1)]
    assert _all(db, "SELECT agent, seq FROM agent_turns ORDER BY seq") == [
        (f"trinity@{LOW}", 0), (f"trinity@{LOW}", 1)]


async def test_the_gateway_opens_a_database_holding_one_wallet_under_two_spellings_with_turns_on_both(tmp_path, monkeypatch):
    """The upgrade the migration exists for: the gateway opens the database,
    the schema advances, and the account reaches its merged conversation."""
    from aiohttp.test_utils import TestClient, TestServer

    path = tmp_path / "g.db"
    _database_before_the_rule(path, monkeypatch)
    now = time.time()
    uid_chk, uid_low = f"user:{CHK}", f"user:{LOW}"
    _seed(path, [
        ("INSERT INTO wallet_sessions VALUES (?, ?, ?, ?)", ("tok-chk", CHK, now, now + 86400)),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_low, LOW, now, "c-low")),
        *_turn_rows(uid_low, LOW, ["l0", "l1"], now),
        ("INSERT INTO conversation_owners VALUES (?, ?, ?, ?)", (uid_chk, CHK, now, "c-chk")),
        *_turn_rows(uid_chk, CHK, ["c0", "c1"], now),
        *_agent_turn_rows(f"trinity@{LOW}", [("u0", "a0")], now),
        *_agent_turn_rows(f"trinity@{CHK}", [("v0", "b0")], now),
    ])

    server = _gateway(tmp_path, path)          # raised before the fix: the migration aborted
    assert server.react_loop.memory.db.schema_version >= 8
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": "still mine", "session_id": uid_chk},
                              headers={"X-Wallet-Session": "tok-chk"})
        body = await r.text()
        assert r.status != 403 and "belongs to another account" not in body, (r.status, body)

    check = sqlite3.connect(str(path))
    try:
        turns = check.execute(
            "SELECT session_id, seq FROM conversation_turns ORDER BY seq").fetchall()
    finally:
        check.close()
    assert [s for s, _ in turns] == [uid_low] * len(turns)
    assert [q for _, q in turns] == list(range(len(turns)))


def test_a_migration_step_that_raises_is_rolled_back_and_logged_whatever_it_raises(tmp_path, monkeypatch, caplog):
    """A callable step's Python error is handled like a database error: the
    transaction is rolled back, the failure is logged, the error still
    propagates, and the schema stays where it was."""
    import logging

    import runtime.db.database as database

    def boom(conn):
        conn.execute("CREATE TABLE half_done (x INTEGER)")
        raise ValueError("step failed half way")

    path = tmp_path / "r.db"
    with monkeypatch.context() as m:
        m.setattr(database, "MIGRATIONS", [*database.MIGRATIONS, (999, "a step that raises", [boom])])
        with caplog.at_level(logging.ERROR, logger="runtime.db.database"):
            with pytest.raises(ValueError):
                database.Database({"database": {"path": str(path)}})
    assert any("Migration v999 failed; rolled back" in r.getMessage() for r in caplog.records)

    db = _open(path)
    assert db.schema_version == max(v for v, _, _ in database.MIGRATIONS)
    assert _all(db, "SELECT name FROM sqlite_master WHERE name = 'half_done'") == []
