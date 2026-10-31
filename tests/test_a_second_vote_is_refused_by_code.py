"""A second vote is refused with a code a client can read, not only a sentence.

Found from the MTRX side (attest-money F30). The app decided whether a refused
vote meant "a vote is already on record" by searching the gateway's error
sentence for "already voted" — the only signal the /api/v1 route gave, because
`GovernanceService.vote` raised a plain ValueError and `_call` answered every
ValueError as `{"error": str(exc)}`. Rewording the sentence would have silently
changed what the app tells a voter.

`AlreadyVoted` is still a ValueError (still the caller's 400 on every surface)
and adds `code`, which the route carries as `error_code`. Driven through the
real route and the real service: one vote recorded, the second refused with the
code, and the recorded vote untouched.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def env():
    routes = ServiceRoutes(config={"governance": {"total_eligible_voters": 10}})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield routes, c


async def _proposal(routes) -> str:
    gov = routes._get_registry().get("governance")
    p = await gov.create_proposal("0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    return p["proposal_id"]


async def test_the_second_vote_is_refused_with_the_already_voted_code(env):
    routes, client = env
    pid = await _proposal(routes)
    body = {"proposal_id": pid, "voter": "0xbob", "support": "yes"}

    first = await client.post("/api/v1/governance/vote", json=body)
    assert first.status == 200, await first.text()
    record = (await first.json())["data"]
    assert record["vote_id"], record

    second = await client.post("/api/v1/governance/vote", json=body)
    assert second.status == 400, await second.text()
    refusal = await second.json()
    assert refusal.get("error_code") == "already_voted", refusal
    assert refusal.get("error"), "the sentence is still there for a person"


async def test_other_refusals_carry_no_code(env):
    """SCOPE PIN. Only a refusal that names a code gets one; an invalid choice
    is a plain 400 with its sentence, as before."""
    routes, client = env
    pid = await _proposal(routes)

    resp = await client.post("/api/v1/governance/vote", json={
        "proposal_id": pid, "voter": "0xbob", "support": "maybe"})

    assert resp.status == 400, await resp.text()
    assert "error_code" not in await resp.json()
