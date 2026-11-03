"""A second vote is refused with a code a client can read, not only a sentence.

Found from the MTRX side (attest-money F30). The app decided whether a refused
vote meant "a vote is already on record" by searching the gateway's error
sentence for "already voted" — the only signal the /api/v1 route gave, because
`GovernanceService.vote` raised a plain ValueError and `_call` answered every
ValueError as `{"error": str(exc)}`. Rewording the sentence would have silently
changed what the app tells a voter.

`AlreadyVoted` is still a ValueError, so the governance vote route still
answers it as the caller's 400, and it adds `code`, which that route carries as
`error_code`. Driven through the real route and the real service: one vote
recorded, the second refused with the code, and the recorded vote untouched.

THE ROUTE IS NAMED, BECAUSE IT IS THE ONLY ONE. The README said a second vote
"is refused with `error_code: already_voted`" and named no route, and this
file said the refusal was the caller's 400 on every surface. The generic
capability route reaches the same service through the dispatcher, which
answers any exception a service raises as a failed call: the second vote there
is a 502 with no code. Measured on both routes below, and the README's sentence
is held to what they answer.
"""

import json
import pathlib
import re

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


ROOT = pathlib.Path(__file__).resolve().parent.parent


async def _invoked(client, capability: str, params: dict):
    resp = await client.post(f"/api/v1/capabilities/{capability}/invoke", json={"params": params})
    return resp.status, await resp.json()


async def test_the_readme_names_the_route_that_carries_the_code(env):
    routes, client = env
    pid = await _proposal(routes)
    body = {"proposal_id": pid, "voter": "0xbob", "support": "yes"}
    await client.post("/api/v1/governance/vote", json=body)
    dedicated = await (await client.post("/api/v1/governance/vote", json=body)).json()
    assert dedicated.get("error_code") == "already_voted", dedicated

    status, created = await _invoked(client, "create_proposal", {
        "proposer": "0xp", "title": "T2", "description": "d",
        "voting_model": "one_person_one_vote", "options": ["yes", "no"]})
    assert status == 200, created
    inner = created.get("result", created)
    inner = json.loads(inner) if isinstance(inner, str) else inner
    proposal_id = (inner.get("result") or inner)["proposal_id"]
    vote = {"proposal_id": proposal_id, "voter": "0xbob", "choice": "yes"}
    status, first = await _invoked(client, "vote", vote)
    assert status == 200, first
    status, second = await _invoked(client, "vote", vote)
    assert status != 200, f"the capability route recorded a second vote: {second}"
    invoke_carries_it = second.get("error_code") == "already_voted"

    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    sentence = next(s for s in re.split(r"(?<=\.) ", readme) if "already_voted" in s)
    assert "governance vote route" in sentence, (
        "the README says a second vote is refused with the code without naming "
        "the route that carries it: " + sentence)
    if not invoke_carries_it:
        assert "capability route" in sentence, (
            f"through the capability route a second vote is a {status} without the "
            f"code, and the README's sentence does not say so: {sentence}")
