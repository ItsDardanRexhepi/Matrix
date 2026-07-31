"""P1-1 regression tests: gateway routes call the correct service/method.

Covers the two confirmed audit defects:

  (a) The compute/storage routes (``/api/v1/compute/store``,
      ``/api/v1/compute/ipfs/pin``, ``/api/v1/compute/arweave/store``)
      previously called a non-existent ``compute`` service with the wrong
      parameter names, which produced a misleading 404. They must reach the
      real ``privacy`` service methods and return a real record.

  (b) The oracle price route (``/api/v1/oracle/price/{pair}``) previously
      passed an invalid ``oracle_type="price"``; a non-eth-usd pair must now
      return a real result or an honest 400 — never a 500.

The tests drive the real HTTP path (``_call`` -> security gate -> registry ->
service method) so a service-name or param-name regression fails loudly.
"""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


# ── (a) compute/storage routes reach the REAL external clients ─────────
#
# NEW-48: these four tests used to assert on the fabrications' output —
# record["status"] == "stored"/"pinned", record["cid"], record["arweave_tx"].
# They were green because the fake was reliable, which is the worst reason for
# a test to pass: it pinned the lie in place, and any honest fix would have
# looked like a regression.
#
# Rewritten to assert the honest post-delegation behaviour. The storage legs
# now reach DecentralizedStorageService, which is credential-gated; with no key
# configured it names the exact missing config key. That string is producible
# ONLY by the real client, so it is positive proof control reached it.

async def test_decentralized_store_reaches_the_real_storage_client(client):
    resp = await client.post(
        "/api/v1/compute/store",
        json={"owner": "0xabc", "data": "0xdeadbeef", "storage_type": "ipfs",
              "content": "hello"},
    )
    body = await resp.json()
    blob = json.dumps(body)
    assert "bafy" not in blob, f"fabricated CID still returned: {blob[:200]}"
    assert "filecoin_api_key" in blob or "not_deployed" in blob, (
        f"no evidence the real storage client ran: {blob[:300]}"
    )


async def test_ipfs_pin_reaches_the_real_storage_client(client):
    resp = await client.post(
        "/api/v1/compute/ipfs/pin",
        json={"cid": "0xhash", "name": "my-pin", "owner": "0xabc", "content": "hello"},
    )
    body = await resp.json()
    blob = json.dumps(body)
    assert '"cid": "Qm' not in blob, f"fabricated CID still returned: {blob[:200]}"
    assert "filecoin_api_key" in blob or "not_deployed" in blob


async def test_ipfs_pin_owner_is_optional(client):
    """The route still only REQUIRES ``cid`` — a missing owner must not 500.

    This half of the original test was about route robustness, not about the
    fabrication, so it survives. It no longer asserts uploader == "" (a field
    of the fake); it asserts the leg does not blow up.
    """
    resp = await client.post("/api/v1/compute/ipfs/pin", json={"cid": "0xhash"})
    assert resp.status != 500, await resp.text()


async def test_arweave_store_is_honestly_unavailable(client):
    """Was: asserted record["arweave_tx"] — a random string for data never
    uploaded. No Arweave client exists on the platform (NEW-48)."""
    resp = await client.post(
        "/api/v1/compute/arweave/store",
        json={"owner": "0xabc", "data": "0xpayload", "content_type": "image/png"},
    )
    assert resp.status == 501, await resp.text()
    assert "arweave_tx" not in json.dumps(await resp.json())


# ── (b) oracle price route: never a 500 for a non-eth-usd pair ──────────

async def test_oracle_price_unsupported_pair_is_honest_400_not_500(client):
    # A pair with no configured Chainlink feed must be an honest client error,
    # not a server fault. Before the fix this raised ValueError -> 500.
    resp = await client.get("/api/v1/oracle/price/NOPE-NOPE")
    assert resp.status == 400, await resp.text()
    assert resp.status != 500
    body = await resp.json()
    assert "error" in body


async def test_oracle_price_never_returns_500_for_arbitrary_pairs(client):
    # Sweep a range of non-eth-usd pairs; none may 500. A configured pair with
    # no reachable RPC honestly surfaces a non-200, but never a 500 masquerade.
    for pair in ("NOPE-NOPE", "FOO-BAR", "ZZZ-USD"):
        resp = await client.get(f"/api/v1/oracle/price/{pair}")
        assert resp.status != 500, f"{pair} -> 500: {await resp.text()}"
