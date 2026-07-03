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


# ── (a) compute/storage routes reach the real privacy service ──────────

async def test_decentralized_store_reaches_privacy_service(client):
    resp = await client.post(
        "/api/v1/compute/store",
        json={"owner": "0xabc", "data": "0xdeadbeef", "storage_type": "ipfs"},
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    record = body["data"]
    assert record["status"] == "stored"
    assert record["uploader"] == "0xabc"
    assert record["data_hash"] == "0xdeadbeef"
    assert record["storage_provider"] == "ipfs"
    assert record["cid"]  # real synthetic content id, not fabricated success


async def test_ipfs_pin_reaches_privacy_service(client):
    resp = await client.post(
        "/api/v1/compute/ipfs/pin",
        json={"cid": "0xhash", "name": "my-pin", "owner": "0xabc"},
    )
    assert resp.status == 200, await resp.text()
    record = (await resp.json())["data"]
    assert record["status"] == "pinned"
    assert record["data_hash"] == "0xhash"
    assert record["pin_name"] == "my-pin"
    assert record["uploader"] == "0xabc"


async def test_ipfs_pin_owner_is_optional(client):
    # The route only requires ``cid``; a missing owner maps to an empty
    # uploader rather than raising, so the leg never 500s on a valid pin.
    resp = await client.post("/api/v1/compute/ipfs/pin", json={"cid": "0xhash"})
    assert resp.status == 200, await resp.text()
    assert (await resp.json())["data"]["uploader"] == ""


async def test_arweave_store_reaches_privacy_service(client):
    resp = await client.post(
        "/api/v1/compute/arweave/store",
        json={"owner": "0xabc", "data": "0xpayload", "content_type": "image/png"},
    )
    assert resp.status == 200, await resp.text()
    record = (await resp.json())["data"]
    assert record["status"] == "stored"
    assert record["uploader"] == "0xabc"
    assert record["data_hash"] == "0xpayload"
    assert record["content_type"] == "image/png"
    assert record["arweave_tx"]


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
