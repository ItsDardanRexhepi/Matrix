"""A retried call that is answered from the first call's record happened once.

The dispute claim was made idempotent: a second claim by the same address is
answered with what was recorded, marked ``replay: True``, instead of a 400.
The replay carries no ``status``, so `ServiceRoutes._maybe_ripple` read it as
an executed action and published another ``feed.ripple`` "claim" to every
live subscriber. Measured before this change: two POSTs of one claim, two
announcements, one stored claim. The README's rule is "A record says what
happened", and what happened was one claim.

The class is wider than the dispute service: any method may answer a retry
this way, and the dispatcher's attestation and feed publish would read it as
settled too. Both surfaces now read ``replay`` first.
"""

from __future__ import annotations

import asyncio

from runtime.blockchain.services.dispute_resolution.service import DisputeResolution
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher


async def _resolved_claim_routes():
    from gateway.service_routes import ServiceRoutes

    routes = ServiceRoutes({})
    sent: list = []
    routes._broadcaster.publish_dict = lambda kind, payload: sent.append((kind, payload))
    svc = DisputeResolution(config={})
    routes._get_registry()._instances["dispute_resolution"] = svc
    d = await svc.file_dispute(
        claimant="0xclaimant", respondent="0xrespondent",
        category="contract_breach",
        evidence={"description": "milestone not delivered"},
        stake_amount=100.0,
    )
    d["status"] = "resolved"
    d["outcome"] = {"winner": "claimant", "juror_results": {}}
    return routes, sent, d


async def test_a_claim_posted_twice_is_announced_once():
    """THE REPRODUCTION, through the same `_call` both POSTs take."""
    routes, sent, d = await _resolved_claim_routes()
    first = await routes._call("dispute_resolution", "claim",
                               dispute_id=d["dispute_id"], claimant="0xclaimant")
    again = await routes._call("dispute_resolution", "claim",
                               dispute_id=d["dispute_id"], claimant="0xclaimant")
    assert again.get("replay") is True and first.get("replay") is not True
    ripples = [p for kind, p in sent if kind == "feed.ripple"]
    assert len(ripples) == 1, (
        f"one recorded claim was announced {len(ripples)} times: {ripples}")


async def test_the_first_claim_is_still_announced():
    """SCOPE PIN: skipping replays must not skip the claim itself."""
    routes, sent, d = await _resolved_claim_routes()
    await routes._call("dispute_resolution", "claim",
                       dispute_id=d["dispute_id"], claimant="0xclaimant")
    assert [kind for kind, _ in sent] == ["feed.ripple"]


class _Feed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):
        self.published.append(kwargs)


def _spied_dispatcher():
    d = ServiceDispatcher({})
    feed = _Feed()
    d._feed_engine = feed
    attested: list[str] = []
    declined: list[str] = []

    async def _attest(action, *a, **k):
        attested.append(action)

    async def _decline(action, *a, **k):
        declined.append(action)

    d._attest_action = _attest
    d._attest_refusal = _decline
    return d, feed, attested, declined


class _IdempotentDisputes:
    """A dispute service whose `file_dispute` answers a retry from its record,
    the way `DisputeResolution.claim` does."""

    def __init__(self) -> None:
        self.recorded: dict | None = None

    async def file_dispute(self, **params):
        if self.recorded is not None:
            return {"replay": True, **self.recorded}
        self.recorded = {"dispute_id": "dsp_1", "status": "filed"}
        return dict(self.recorded)


async def test_the_dispatcher_attests_and_publishes_a_replay_once():
    d, feed, attested, declined = _spied_dispatcher()
    d._get_registry()._instances["dispute_resolution"] = _IdempotentDisputes()
    params = {"claimant": "0xa", "respondent": "0xb", "category": "contract_breach",
              "evidence": {"description": "x"}, "stake_amount": 1.0}
    await d.execute("file_dispute", params=dict(params))
    await d.execute("file_dispute", params=dict(params))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert attested == ["file_dispute"], (
        f"a replay was attested as a second action: {attested}")
    assert len(feed.published) == 1, (
        f"a replay was published to the public feed again: {feed.published}")
    assert declined == [], "a replay is not a decline"


def test_only_an_explicit_replay_flag_is_a_replay():
    from runtime.blockchain.services.service_dispatcher import is_replay

    assert is_replay({"replay": True})
    for result in ({"replay": False}, {"replay": "true"}, {"replay": 1},
                   {}, None, [], "replay"):
        assert not is_replay(result), result
