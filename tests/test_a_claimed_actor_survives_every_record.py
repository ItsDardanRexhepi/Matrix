"""A CLAIM ABOUT WHO ACTED SURVIVES EVERY RECORD, ON BOTH SURFACES.

Two changes met at a merge. One made the actor the identity the entry point
resolved and kept the value the body wrote as `actor_claimed` — a claim about
who acted, carried on the attestation, on the refusal record and on the feed,
because the most interesting line in a trail is one caller naming another. The
other added the third record, for a transaction that was SENT and not
confirmed, on the dispatcher and on the /api/v1 surface, and wrote the /api/v1
decline record "with the same sentence, level and fields" as the dispatcher's
refusal. Each was true on its own branch. Together, the three records the
second branch wrote carried no claim: a broadcast under a disagreeing claimed
actor was logged as if the claim had never been made, and the /api/v1 decline
said "same fields" while missing one. Measured on the merged tree before this
change: the dispatcher's broadcast record was called without the claim it had
in hand; `ServiceRoutes._record_decline` and `_record_broadcast` had no
parameter to receive one.

The rule is one sentence: whichever of the three answers a record gives, it
names the resolved actor, and it names the claimed one when the two disagree.
"""

from __future__ import annotations

import logging

import pytest

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.services.service_dispatcher import (
    RECORD_BROADCAST,
    ServiceDispatcher,
    _record_verdict,
)

_HASH = "0x" + "ab" * 32
_SENT = {"status": "submitted", "tx_hash": _HASH, "service": "tba"}


def _dispatcher():
    d = ServiceDispatcher({})

    class _Silent:
        async def ingest(self, **kwargs):
            pass

    d._feed_engine = _Silent()
    return d


@pytest.fixture
def routes():
    return ServiceRoutes(config={})


def _lines(caplog, sentence: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if sentence in r.getMessage()]


# ── the dispatcher's third record ─────────────────────────────────────────


async def test_the_dispatcher_hands_its_broadcast_record_the_claim(monkeypatch):
    """THE CALL SITE. The resolved identity is 0xSESSION; the body wrote 0xCLAIMED;
    the service answers with a bare broadcast. The broadcast record must receive
    both — the refusal and the attestation already do, one branch up."""
    assert _record_verdict(_SENT) == RECORD_BROADCAST, "premise changed"
    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _sent(self, **params):
        return dict(_SENT)

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _sent)
    d = _dispatcher()
    seen: list[dict] = []

    async def _spy(action, service_name, params, result, **fields):
        seen.append(fields)

    d._record_broadcast = _spy
    await d.execute(
        "create_tba",
        params={"token_contract": "0x" + "1" * 40, "token_id": 1, "wallet": "0xCLAIMED"},
        caller_identity="0xSESSION",
    )
    assert seen, "no broadcast record was written for a bare broadcast"
    assert seen[-1].get("actor") == "0xSESSION", seen
    assert seen[-1].get("actor_claimed") == "0xCLAIMED", (
        f"the broadcast record was written without the claim in hand: {seen}")


async def test_the_dispatcher_broadcast_line_names_the_claim(caplog):
    d = _dispatcher()
    with caplog.at_level(logging.INFO):
        await d._record_broadcast(
            "create_tba", "tba", {}, _SENT,
            actor="0xSESSION", actor_source="authenticated", actor_claimed="0xCLAIMED",
        )
    lines = _lines(caplog, "ACTION BROADCAST")
    assert lines, caplog.records
    assert "actor=0xSESSION" in lines[0] and "claimed=0xCLAIMED" in lines[0], lines[0]
    assert _HASH in lines[0], lines[0]


async def test_the_dispatcher_does_not_repeat_a_claim_that_matches(caplog):
    """NEGATIVE CONTROL. `claimed=` is a disagreement, not a second copy of the
    actor. The dispatcher clears the claim when it equals the resolved identity
    before any record is written; the record must not add the word back."""
    d = _dispatcher()
    with caplog.at_level(logging.INFO):
        await d._record_broadcast(
            "create_tba", "tba", {}, _SENT,
            actor="0xSESSION", actor_source="authenticated", actor_claimed="",
        )
    line = _lines(caplog, "ACTION BROADCAST")[0]
    assert "claimed=" not in line, line


# ── the /api/v1 surface's two records ─────────────────────────────────────


def test_the_api_v1_decline_record_carries_the_claim(routes, caplog):
    """Nothing binds an identity for a bare ServiceRoutes app, so the actor is
    "" and the body's `owner` is a claim — the exact shape a decline should
    record, since it is the one where the claim is all there is."""
    with caplog.at_level(logging.INFO, logger="gateway.service_routes"):
        routes._maybe_ripple(
            "ip_royalties", "register_ip", {"owner": "0xowner", "name": "Widget"},
            {"status": "not_deployed", "service": "ip_royalties"},
        )
    lines = _lines(caplog, "ACTION DECLINED")
    assert lines, "a refusal on the /api/v1 path left no decline record"
    assert "claimed=0xowner" in lines[0], (
        f"the decline record dropped the claim the request made: {lines[0]}")


def test_the_api_v1_broadcast_record_carries_the_claim(routes, caplog):
    assert _record_verdict(_SENT) == RECORD_BROADCAST, "premise changed"
    with caplog.at_level(logging.INFO, logger="gateway.service_routes"):
        routes._maybe_ripple("bridge", "cross_chain_bridge", {"sender": "0xabc"}, _SENT)
    lines = _lines(caplog, "ACTION BROADCAST")
    assert lines, "a broadcast on the /api/v1 path left no record"
    assert "claimed=0xabc" in lines[0] and _HASH in lines[0], lines[0]


def test_the_api_v1_records_carry_no_claim_when_none_was_made(routes, caplog):
    with caplog.at_level(logging.INFO, logger="gateway.service_routes"):
        routes._maybe_ripple("ip_royalties", "register_ip", {"name": "Widget"},
                             {"status": "not_deployed", "service": "ip_royalties"})
        routes._maybe_ripple("bridge", "cross_chain_bridge", {"amount": 1}, _SENT)
    for sentence in ("ACTION DECLINED", "ACTION BROADCAST"):
        line = _lines(caplog, sentence)[0]
        assert "claimed=" not in line, line


# ── "the same sentence, level and fields" is a claim; this holds it ───────


@pytest.mark.parametrize("claimed", ["", "0xCLAIMED"])
async def test_the_two_surfaces_write_the_same_decline(caplog, claimed):
    """`_record_decline`'s docstring says it is the dispatcher's refusal record,
    sentence for sentence, so that one grep finds a decline whichever surface
    refused it. Written with identical inputs, the two lines must be identical —
    with the claim and without it, with an actor and with none."""
    d = _dispatcher()
    refused = {"status": "not_deployed", "service": "tba"}
    for actor in ("0xSESSION", ""):
        caplog.clear()
        with caplog.at_level(logging.INFO):
            await d._attest_refusal("create_tba", "tba", {}, refused,
                                    actor=actor, actor_source="", actor_claimed=claimed)
            ServiceRoutes._record_decline("tba", "create_tba", refused,
                                          actor=actor, actor_claimed=claimed)
        lines = _lines(caplog, "ACTION DECLINED")
        assert len(lines) == 2, lines
        assert lines[0] == lines[1], f"the two surfaces' decline records differ:\n{lines[0]}\n{lines[1]}"
        levels = {r.levelno for r in caplog.records if "ACTION DECLINED" in r.getMessage()}
        assert levels == {logging.INFO}, levels


@pytest.mark.parametrize("claimed", ["", "0xCLAIMED"])
async def test_the_two_surfaces_write_the_same_broadcast(caplog, claimed):
    d = _dispatcher()
    for actor in ("0xSESSION", ""):
        caplog.clear()
        with caplog.at_level(logging.INFO):
            await d._record_broadcast("create_tba", "tba", {}, _SENT,
                                      actor=actor, actor_source="", actor_claimed=claimed)
            ServiceRoutes._record_broadcast("tba", "create_tba", _SENT,
                                            actor=actor, actor_claimed=claimed)
        lines = _lines(caplog, "ACTION BROADCAST")
        assert len(lines) == 2, lines
        assert lines[0] == lines[1], f"the two surfaces' broadcast records differ:\n{lines[0]}\n{lines[1]}"
