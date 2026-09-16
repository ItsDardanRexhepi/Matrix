"""P5-1 regression tests: governance vote binds to the wallet the request is bound to.

A vote must be attributed to the wallet the security middleware bound for the
request — not a spoofable ``voter`` body field. That binding is a session's
identity when a session is presented; without one it is the X-Wallet-Address
header or a body wallet/from/sender/account field, which the caller writes, so
the vote is authenticated only in the session case. The fixture here binds the
identity directly. When an identity is
bound, it wins over the body; with no identity the body voter is a testnet/dev
fallback; with neither, the request is an honest 400.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from gateway.security_gate import bind_request_security


@pytest.fixture
async def env():
    routes = ServiceRoutes(config={})
    app = web.Application()

    @web.middleware
    async def _bind_wallet(request, handler):
        w = request.headers.get("X-Test-Wallet")
        if w:
            bind_request_security(identity=w)
        return await handler(request)

    app.middlewares.append(_bind_wallet)
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield routes, c


def _spy_vote(routes, captured):
    async def spy(service, method, **kwargs):
        if method == "vote":
            captured.update(kwargs)
        return {"status": "cast", **kwargs}
    routes._call = spy  # type: ignore[assignment]


async def test_bound_wallet_wins_over_body_voter(env):
    """The fixture binds an identity with no session, the way the real
    middleware binds a caller-written X-Wallet-Address header or a body field.
    What wins over the body `voter` is the BOUND value; it is authenticated
    only when a session put it there."""
    routes, client = env
    captured: dict = {}
    _spy_vote(routes, captured)
    resp = await client.post(
        "/api/v1/governance/vote",
        headers={"X-Test-Wallet": "0xBOUND"},
        json={"proposal_id": "p1", "voter": "0xSPOOF", "support": "yes"},
    )
    assert resp.status == 200, await resp.text()
    assert captured.get("voter") == "0xBOUND", "the bound wallet must win, not the body voter"


async def test_body_voter_used_when_nothing_is_bound(env):
    """Not "when unauthenticated": the request above is unauthenticated too.
    The body voter is reached only when NO identity was bound at all."""
    routes, client = env
    captured: dict = {}
    _spy_vote(routes, captured)
    resp = await client.post(
        "/api/v1/governance/vote",
        json={"proposal_id": "p1", "voter": "0xbob", "support": "yes"},
    )
    assert resp.status == 200, await resp.text()
    assert captured.get("voter") == "0xbob", "the body voter is the testnet fallback"


async def test_no_identity_at_all_is_honest_400(env):
    routes, client = env
    resp = await client.post(
        "/api/v1/governance/vote",
        json={"proposal_id": "p1", "support": "yes"},
    )
    assert resp.status == 400, await resp.text()
    assert "voter" in (await resp.json()).get("error", "").lower()
