"""RUN-2 — /api/v1/contracts/deploy must not claim to have deployed anything.

The handler was byte-identical to _handle_contract_convert and dispatched to the
same ``contract_conversion.convert``. The service has no ``deploy`` method; no
part of the path touched a chain, a wallet, or a signer. A client POSTing here
received HTTP 200 with ``status: ok`` and a generated contract, and concluded a
deployment had happened. It had not — 100% of the time.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes

BODY = {
    "source_code": "contract Rental\nstate landlord: address",
    "source_lang": "pseudocode",
    "target_chain": "base",
}


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_deploy_returns_501(client):
    resp = await client.post("/api/v1/contracts/deploy", json=BODY)
    assert resp.status == 501, (
        f"expected 501 Not Implemented, got {resp.status}. A 2xx here reads as "
        "a completed deployment."
    )


async def test_deploy_does_not_report_success_or_return_a_contract(client):
    """The body must not look like a deployment result."""
    resp = await client.post("/api/v1/contracts/deploy", json=BODY)
    payload = await resp.json()

    assert payload.get("status") == "not_implemented"
    # None of the fields a caller would read as evidence of deployment.
    for field in ("contract_address", "tx_hash", "deployment", "audit", "generated_code"):
        assert field not in payload, (
            f"response still carries {field!r} — that is what made the old "
            "behaviour convincing"
        )
    assert "convert" in payload.get("see", ""), "should point at the real capability"


async def test_deploy_and_convert_no_longer_return_the_same_thing(client):
    """The original defect in one assertion: two routes, one response."""
    deploy = await client.post("/api/v1/contracts/deploy", json=BODY)
    convert = await client.post("/api/v1/contracts/convert", json=BODY)
    assert deploy.status != convert.status, (
        "/contracts/deploy and /contracts/convert still answer identically — "
        "which is exactly RUN-2"
    )


async def test_sdk_wrapper_refuses_rather_than_pretending():
    """The SDK method must not silently route to conversion either."""
    import inspect

    from sdk.client import MatrixClient

    doc = inspect.getdoc(MatrixClient.deploy_contract) or ""
    assert "NOT IMPLEMENTED" in doc, (
        "the wrapper's docstring must not promise deployment — it was the most "
        "convincing part of the illusion"
    )

    client = MatrixClient.__new__(MatrixClient)
    with pytest.raises(NotImplementedError):
        await client.deploy_contract("contract X")
