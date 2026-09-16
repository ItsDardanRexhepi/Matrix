"""The service funnel does not hand an exception to the client.

Every direct /api/v1/* service handler and every /api/v1/batch sub-call reaches a
service through ServiceRoutes._call. Its last clause was

    except Exception as exc:
        raise web.HTTPInternalServerError(text=json.dumps({"error": str(exc)}))

so whatever a service raised — an RPC URL with credentials in it, a provider's
quota message, a file path — was the body. RUN-5 built client_error for exactly
this and applied it to 13 sites; the funnel every route shares was not one of
them. It also answered 500 for a dependency that was simply unreachable, which
client_error classifies as 503.

The deliberate clauses above it are not touched and are asserted unchanged here:
a ValueError is a service's own validation sentence (400, shown), a
NotImplementedError is a refusal that names the missing capability (501, shown).
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes

SECRET = "SECRET https://user:hunter2@rpc.internal:8545"


class _Svc:
    def __init__(self, exc):
        self._exc = exc

    async def create_community(self, **kwargs):
        raise self._exc


class _Registry:
    def __init__(self, svc):
        self._svc = svc

    def get(self, name):
        return self._svc


async def _client_raising(exc):
    routes = ServiceRoutes(config={})
    routes._registry = _Registry(_Svc(exc))
    app = web.Application()
    routes.register_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


BODY = {"creator": "0xA", "name": "n"}


@pytest.mark.parametrize("exc,status", [
    (RuntimeError(SECRET), 500),
    (ConnectionRefusedError(SECRET), 503),
])
async def test_an_unexpected_service_exception_is_redacted(exc, status):
    client = await _client_raising(exc)
    try:
        resp = await client.post("/api/v1/groups", json=BODY)
        text = await resp.text()
        assert resp.status == status, f"{resp.status}: {text}"
        assert "hunter2" not in text and "SECRET" not in text, text
        assert json.loads(text)["ref"]
    finally:
        await client.close()


async def test_the_batch_path_carries_the_same_redaction():
    client = await _client_raising(RuntimeError(SECRET))
    try:
        resp = await client.post("/api/v1/batch", json={"requests": [
            {"id": "1", "method": "POST", "path": "/api/v1/groups", "body": BODY}]})
        text = await resp.text()
        assert resp.status == 200, text
        assert json.loads(text)["results"][0]["status"] == 500
        assert "hunter2" not in text and "SECRET" not in text, text
    finally:
        await client.close()


@pytest.mark.parametrize("exc,status,shown", [
    (ValueError("unsupported pair XYZ"), 400, "unsupported pair XYZ"),
    (NotImplementedError("community rules are not built"), 501,
     "community rules are not built"),
])
async def test_deliberate_refusals_still_say_why(exc, status, shown):
    client = await _client_raising(exc)
    try:
        resp = await client.post("/api/v1/groups", json=BODY)
        text = await resp.text()
        assert resp.status == status, text
        assert shown in text
    finally:
        await client.close()
