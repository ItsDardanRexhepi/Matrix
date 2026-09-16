"""NEW-89 on the twin route: POST /api/v1/groups refuses `rules` too.

POST /api/v1/groups and POST /api/v1/social/community/create both call
social.create_community, which stores creator/name/description/token_gate and has
no rules concept at all. NEW-89 made the community route answer 501 when a caller
sends `rules`, because a 200 would leave the caller believing their rules govern a
community that enforces nothing. The groups route kept forwarding the four fields
it knew and answered 200 with the rules silently gone — the same dropped intent,
one route over, and reachable again through POST /api/v1/batch.

The tests drive both routes with the same bodies, so a guard that exists on only
one of them fails here rather than in a finding.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes

TWINS = ("/api/v1/groups", "/api/v1/social/community/create")


@pytest.fixture
async def env():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield routes, c


@pytest.mark.parametrize("path", TWINS)
async def test_rules_are_refused_not_dropped(env, path):
    routes, client = env
    calls = []
    real_call = routes._call

    async def spy(service, method, **kw):
        calls.append((service, method, kw))
        return await real_call(service, method, **kw)

    routes._call = spy
    resp = await client.post(path, json={
        "creator": "0xA", "name": "Builders", "rules": {"no_spam": True}})
    text = await resp.text()
    assert resp.status == 501, f"{path} -> {resp.status}: {text}"
    assert json.loads(text)["error"] == "not_implemented"
    assert "rules" in text
    assert calls == [], f"{path} created a community after refusing its rules: {calls}"


@pytest.mark.parametrize("path", TWINS)
async def test_both_still_create_without_rules(env, path):
    _routes, client = env
    resp = await client.post(path, json={"creator": "0xA", "name": "Builders"})
    assert resp.status == 200, await resp.text()


@pytest.mark.parametrize("key", ["token_gate", "tokenGate"])
@pytest.mark.parametrize("path", TWINS)
async def test_both_forward_the_token_gate_in_either_spelling(env, path, key):
    """Sibling axis: the community route read only `token_gate`, so a camelCase
    `tokenGate` was dropped there while the groups route honoured it."""
    routes, client = env
    seen = {}

    async def spy(service, method, **kw):
        seen.update(kw)
        return {"status": "created"}

    routes._call = spy
    gate = {"token": "0xT", "min_balance": 1}
    resp = await client.post(path, json={"creator": "0xA", "name": "B", key: gate})
    assert resp.status == 200, await resp.text()
    assert seen.get("token_gate") == gate, (path, key, seen)


async def test_the_batch_path_reaches_the_same_refusal(env):
    _routes, client = env
    resp = await client.post("/api/v1/batch", json={"requests": [{
        "id": "1", "method": "POST", "path": "/api/v1/groups",
        "body": {"creator": "0xA", "name": "Builders", "rules": ["be kind"]},
    }]})
    assert resp.status == 200, await resp.text()
    result = (await resp.json())["results"][0]
    assert result["status"] == 501, result
