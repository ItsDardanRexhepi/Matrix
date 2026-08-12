"""DAO proposals live-read: the gateway now emits the client's Proposal shape.

Was BLOCKED — no route returned number/proposer/votes/quorum in the shape the
MTRX DAO tab decodes. GET /api/v1/governance/daos/{daoId}/proposals now wires
through _call to governance.list_proposals_detailed, returning
proposal_id/title/description/status/votes_for/votes_against/quorum/end_time
(end_time as an ISO-8601 string the client date decoder accepts).
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def env():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield routes, c


async def test_dao_proposals_returns_client_shape(env):
    routes, client = env
    gov = routes._get_registry().get("governance")
    prop = await gov.create_proposal(
        proposer="0xabc",
        title="Fund the treasury",
        description="Allocate 10 ETH to grants",
        # CLUSTER A: this was token_weighted with a caller-declared weight of
        # 3.0, and the assertion below REQUIRED that weight to reach the tally.
        # It was pinning the defect, not guarding a behaviour — a client
        # declaring its own voting power and the server honouring it is exactly
        # what Cluster A step 1 removes. INVERTED rather than adjusted-to-green;
        # see the vote assertion below.
        voting_model="one_person_one_vote",
        options=["for", "against"],
    )
    pid = prop["proposal_id"]
    await gov.vote(proposal_id=pid, voter="0xv1", choice="for")

    resp = await client.get("/api/v1/governance/daos/dao1/proposals")
    assert resp.status == 200, await resp.text()
    data = (await resp.json())["data"]
    assert isinstance(data, list) and data, "expected a non-empty proposal list"

    row = next(r for r in data if r["proposal_id"] == pid)
    # Every field the client's Proposal struct decodes must be present + typed.
    assert row["title"] == "Fund the treasury"
    assert row["description"] == "Allocate 10 ETH to grants"
    assert isinstance(row["status"], str)
    # INVERTED (Cluster A). Was: `assert row["votes_for"] >= 3.0` with the
    # message "the for-vote weight must be tallied server-side" — asserting
    # that a CALLER-SUPPLIED weight of 3.0 reached the tally. That is the
    # forgeable-weight defect stated as a requirement. One voter is now worth
    # exactly one vote, and no caller-declared figure can change it.
    assert row["votes_for"] == 1.0, (
        "one voter must be worth one vote — if this is 3.0 again, a "
        "caller-declared weight is reaching the tally"
    )
    assert row["votes_against"] == 0.0
    assert isinstance(row["quorum"], (int, float))
    # end_time is an ISO-8601 string (client decoder needs a string, not epoch).
    assert isinstance(row["end_time"], str) and "T" in row["end_time"]


async def test_dao_proposals_empty_is_honest_empty_list(env):
    # No proposals -> an honest empty list, not a fabrication or a 500.
    routes, client = env
    resp = await client.get("/api/v1/governance/daos/dao1/proposals")
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"] == []
