"""A 401 means the credential is bad. An unmatched path is not a bad credential.

MEASURED on the tree before this change, through the real middleware chain
(``tests/test_apple_session_auth_wall.py``'s rig):

    GET  /api/v1/no/such/route     session 401   operator 404   anonymous 401
    POST /api/v1/capabilities      session 401   operator 405   anonymous 401
         (a route the session may reach — with the wrong method)
    GET  /api/v1/contracts/deploy  session 401   operator 405   anonymous 401
         (an operator route — with the wrong method)

``_auth_middleware`` looked up the matched route's canonical template; an
unmatched path or a wrong method has none, so a LIVE SESSION fell through to
the 401 written for a missing credential. The MTRX client clears its stored
token on every 401, so a typo, a route the client shipped before the server
did, or a trailing slash signed a valid user out.

WHAT CHANGES. With a live session and no matched route, the request goes to
the router's own handler, which answers what it answers the operator: 404 for
an unmatched path, 405 (with ``Allow``) for a wrong method. Nothing is
widened: the session still reaches only the routes ``gateway/session_routes.py``
lists (403 elsewhere); an anonymous caller — no credential, or an expired one —
still gets 401 on every non-public path, matched or not, and is told nothing
about which paths exist. The ``Allow`` header a 405 carries names methods that
are in the committed route table (``docs/ROUTES.md``); it discloses nothing the
repository does not.

SIBLING AXES CHECKED. ``POST /api/v1/batch`` resolves its items' routes itself
and answers an unmatched item 404 inside a 200 — but it is not on the session
allowlist (a session gets 403 on the batch route), so the class has one member
at the wall. ``_caller_kind`` and the public chat surfaces do not consult the
route table. The bridge (``gateway/bridge.py``) mounts fixed routes under
``/bridge/v1`` and has no wall of its own for unmatched paths.

MEASURED: 7 failed, 11 passed before; 18 passed after. The eleven that pass
before are the anonymous (six spellings), expired-session, garbage-token,
operator, 403 and reachable-route regression guards.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from tests.test_apple_session_auth_wall import (  # noqa: E402
    APP_ROUTE, KEY, OPERATOR_ROUTE, _apple_session, _bearer, _server,
)

NO_SUCH_PATH = "/api/v1/no/such/route"

#: (method, path, what the router answers) — every case is unmatched: no
#: resource matches the path, or one does and the method is not registered.
UNMATCHED = [
    ("GET", NO_SUCH_PATH, 404),
    ("GET", "/nope", 404),
    ("GET", APP_ROUTE + "/", 404),          # trailing-slash spelling of a session route
    ("POST", APP_ROUTE, 405),               # session route, wrong method
    ("GET", OPERATOR_ROUTE, 405),           # operator route, wrong method
    ("DELETE", "/api/v1/capabilities/categories", 405),
]


# ── the defect ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,router_answer", UNMATCHED)
async def test_a_live_session_on_an_unmatched_path_gets_the_router_answer_not_a_sign_out(
        method, path, router_answer):
    """DEFECT-PROVER, six ways. Before: 401 on every one of these."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.request(method, path, headers=_bearer(token))
        assert resp.status != 401, (
            f"{method} {path}: a live session was answered 401 — the client "
            "reads that as a bad token and signs the user out")
        assert resp.status == router_answer, (method, path, resp.status, await resp.text())


async def test_a_session_and_the_operator_get_the_same_answer_on_a_wrong_method():
    """The 405 is the router's, not the wall's: the same status and the same
    ``Allow`` header the operator gets."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        as_session = await client.post(APP_ROUTE, headers=_bearer(token))
        as_operator = await client.post(APP_ROUTE, headers=_bearer(KEY))
        assert as_session.status == as_operator.status == 405
        assert as_session.headers.get("Allow") == as_operator.headers.get("Allow")
        assert "GET" in (as_session.headers.get("Allow") or "")


# ── nothing widened ──────────────────────────────────────────────────────────

async def test_a_session_on_a_route_it_may_not_reach_is_still_refused_403():
    """Regression guard: a matched operator route with the right method is the
    403 it was — an unmatched path is not a way around the allowlist."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.post(OPERATOR_ROUTE, json={}, headers=_bearer(token))
        assert resp.status == 403
        assert (await resp.json())["error"] == "forbidden"


@pytest.mark.parametrize("method,path", [(m, p) for m, p, _ in UNMATCHED])
async def test_anonymous_on_an_unmatched_path_is_still_401(method, path):
    """Regression guard: with no credential the answer is 401 whether or not
    the path exists — an anonymous caller is not told which paths are real."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.request(method, path)
        assert resp.status == 401, (method, path, resp.status)


async def test_an_expired_session_on_an_unmatched_path_is_still_401():
    """Regression guard: an expired token is no credential, so it gets the
    missing-credential answer, not the router's."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, ttl=-1)
        resp = await client.get(NO_SUCH_PATH, headers=_bearer(token))
        assert resp.status == 401


async def test_a_garbage_bearer_on_an_unmatched_path_is_still_401():
    """Regression guard: a token the store never issued is a bad credential."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(NO_SUCH_PATH, headers=_bearer("not-a-session-not-the-key"))
        assert resp.status == 401


async def test_the_operator_on_an_unmatched_path_is_still_404():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(NO_SUCH_PATH, headers=_bearer(KEY))
        assert resp.status == 404


async def test_a_live_session_still_reaches_the_route_it_may_reach():
    """Regression guard: the matched, allowed case is unchanged."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.get(APP_ROUTE, headers=_bearer(token))
        assert resp.status not in (401, 403, 404, 405), await resp.text()
