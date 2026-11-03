"""The sponsorship cap reads a malformed number as a refusal, and its ledger
says what went wrong, refuses what it cannot store, and lets go of its files.

THE DEFECTS (pre-existing on The Matrix ``main``):

  * ``daily_cap_usd: "NaN"`` parsed as a cap, and no amount is ever greater
    than NaN, so it allowed any spend — three $1e9 reservations in a row —
    while a cap that is not a number at all was already read as zero;
    infinity and a negative cap were the same kind of nonsense;
  * a ``SponsorshipPolicy`` built with a cap and no ledger path opened a
    SQLite file literally named ``None`` in the working directory and then
    failed on a missing table;
  * when another writer held the ledger, ``BEGIN IMMEDIATE`` timed out and
    the handler's ``ROLLBACK`` raised "cannot rollback - no transaction is
    active", which replaced the real error;
  * every ledger connection was left open (the ``with`` block commits; it
    does not close);
  * ``/api/v1/paymaster/sign`` priced a request before reading the
    allowlist, so an action the allowlist refuses was answered 503 "gas
    price unavailable" whenever the price feed was down — a refusal the
    client is told to retry.
"""
from __future__ import annotations

import sqlite3

import pytest

from runtime.blockchain import sponsorship
from runtime.blockchain.sponsorship import SponsorshipPolicy, policy_settings


def _cfg(cap):
    return {"paymaster": {"policy": {"daily_cap_usd": cap}}}


@pytest.mark.parametrize("cap", ["NaN", "nan", float("nan"), "inf", float("inf"), "-5", -1])
def test_a_cap_that_is_not_a_finite_amount_is_zero(cap):
    """[control] NaN, infinity and a negative cap enforced nothing."""
    _allowed, parsed = policy_settings(_cfg(cap))
    assert parsed == 0.0


def test_a_nan_cap_refuses_spend(tmp_path):
    """[control] Three $1e9 reservations were allowed under "NaN"."""
    cfg = {**_cfg("NaN"), "database": {"path": str(tmp_path / "m.db")}}
    policy = SponsorshipPolicy.from_config(cfg)
    decision = policy.authorize_and_reserve("transfer", identity="0x" + "a1" * 20, est_usd=1e9)
    assert decision.allowed is False and decision.code == "daily_cap_exceeded"


def test_a_cap_without_a_ledger_is_refused_at_construction(tmp_path, monkeypatch):
    """[control] A file named None appeared in the working directory."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="ledger"):
        SponsorshipPolicy(daily_cap_usd=5)
    assert not (tmp_path / "None").exists()


def test_a_locked_ledger_says_it_is_locked(tmp_path):
    """[control] The lock timeout came back as "cannot rollback"."""
    policy = SponsorshipPolicy(daily_cap_usd=5, db_path=tmp_path / "l.db")
    policy._busy_timeout = 0.05
    holder = sqlite3.connect(str(tmp_path / "l.db"), isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            policy.authorize_and_reserve("transfer", identity="0x" + "a1" * 20, est_usd=1.0)
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_the_ledger_lets_go_of_its_connections(tmp_path):
    """[control] Each ledger operation left its connection open."""
    policy = SponsorshipPolicy(daily_cap_usd=50, db_path=tmp_path / "c.db")
    opened = []
    real = policy._connect

    def connect():
        conn = real()
        opened.append(conn)
        return conn
    policy._connect = connect
    d = policy.authorize_and_reserve("transfer", identity="0x" + "a1" * 20, est_usd=1.0)
    policy.commit(d.reservation_id)
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


async def test_a_refused_action_is_refused_before_it_is_priced(aiohttp_client, tmp_path, monkeypatch):
    """[control] With the price feed down, an action the allowlist refuses
    was answered 503 instead of 403."""
    from gateway.service_routes import ServiceRoutes
    from tests.test_gateway import _build_mock_server
    from tests.test_paymaster_route import _BODY, PAYMASTER, SIGNER_KEY, _config

    async def no_price(*_a, **_k):
        raise RuntimeError("price feed down")
    monkeypatch.setattr(ServiceRoutes, "_estimate_sponsorship_usd", no_price)
    monkeypatch.setattr(sponsorship, "classify_user_operation", lambda *_a, **_k: ["approve"])
    cfg = _config(tmp_path, paymaster={
        "address": PAYMASTER, "signer_key": SIGNER_KEY,
        "policy": {"allowed_actions": ["transfer"], "daily_cap_usd": 50}})
    cfg["database"] = {"path": str(tmp_path / "s.db")}
    server = _build_mock_server(cfg)
    server._app_attest = None
    server._security_backend = "noop"
    client = await aiohttp_client(server.create_app())
    resp = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert resp.status == 403, (resp.status, await resp.text())
    assert (await resp.json())["code"] == "action_not_allowed"
