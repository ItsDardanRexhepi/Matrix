"""RUN-4 — a failing payload must not be dressed as an HTTP success.

`_ok()` used to return HTTP 200 with `{"status":"ok","data":...}` unconditionally,
including when `data` itself said `{"status":"error"}`. The transport claimed
success while the payload reported failure, and every client believes the
transport:

  * `sdk/client.py` checks only `resp.status != 200`
  * Swift `getEnveloped` decodes the outer envelope and discards its status
  * 9 `sdk-js` methods check nothing at all

So a caller received an error dictionary and proceeded as if the call worked.
On iOS that meant a failed transfer closed the send sheet and cleared the form
(NEW-21).

These tests pin BOTH directions, because the dangerous half of this fix is
over-firing: a domain outcome like `rejected` or `failed` is a real answer the
caller asked for, and turning those into HTTP failures would break working
flows.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
def routes():
    return ServiceRoutes(config={})


def _decode(resp_body: str) -> dict:
    return json.loads(resp_body)


# ── failures must surface as real HTTP codes ───────────────────────────────

@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"status": "error"}, 422),
        ({"status": "error", "error_category": "validation"}, 400),
        ({"status": "error", "error_category": "bad_request"}, 400),
        ({"status": "error", "error_category": "not_found"}, 404),
        ({"status": "error", "error_category": "forbidden"}, 403),
        ({"status": "error", "error_category": "not_implemented"}, 501),
        ({"status": "error", "error_category": "service_unavailable"}, 503),
        ({"status": "error", "error_category": "service_error"}, 502),
        ({"status": "error", "error_category": "timeout"}, 504),
        ({"status": "unavailable"}, 503),
        # an unavailable payload stays 503 even if it carries a category
        ({"status": "unavailable", "error_category": "validation"}, 503),
    ],
)
def test_failure_payload_gets_a_real_http_status(routes, payload, expected):
    resp = routes._ok(dict(payload))
    assert resp.status == expected, (
        f"{payload} should map to HTTP {expected}, got {resp.status}. "
        "A failing payload returned at 200 is invisible to every SDK."
    )


def test_failure_response_preserves_the_service_detail(routes):
    """Callers must lose nothing they had before the status change."""
    payload = {
        "status": "error",
        "error": "insufficient balance",
        "error_category": "validation",
        "requested": "5.0",
    }
    resp = routes._ok(dict(payload))
    body = _decode(resp.body.decode())
    assert resp.status == 400
    assert body["status"] == "error"
    assert body["data"] == payload, "the service's own detail was dropped"


# ── successes and DOMAIN outcomes must keep working ────────────────────────

@pytest.mark.parametrize(
    "status",
    # Every one of these is a legitimate answer the caller asked for. A rejected
    # claim or a failed transaction is a RESULT, not a transport error. Turning
    # them into HTTP failures is the opposite mistake to the one RUN-4 fixes,
    # and it would break flows that work today.
    ["submitted", "active", "pending", "completed", "verified",
     "registered", "updated", "rejected", "failed", "skipped", "ok"],
)
def test_domain_outcomes_are_not_treated_as_failures(routes, status):
    resp = routes._ok({"status": status, "id": "x"})
    assert resp.status == 200, (
        f"inner status {status!r} is a domain outcome, not a transport failure — "
        "returning non-200 for it would break a working flow"
    )
    assert _decode(resp.body.decode())["status"] == "ok"


def test_non_dict_and_statusless_payloads_are_unaffected(routes):
    """Lists, scalars, and dicts without a status stay 200."""
    for payload in ([], [1, 2, 3], {"wallet": "0xabc"}, {"count": 0}):
        resp = routes._ok(payload)
        assert resp.status == 200
        assert _decode(resp.body.decode()) == {"status": "ok", "data": payload}


# ── end-to-end through a real route ────────────────────────────────────────

async def test_a_failing_service_action_returns_non_200_end_to_end():
    """The whole point: a real request whose service fails must not read 200."""
    routes_obj = ServiceRoutes(config={})
    app = web.Application()
    routes_obj.register_routes(app)

    async with TestClient(TestServer(app)) as client:
        # A wallet the aggregator cannot serve. Whatever the outcome, the one
        # thing forbidden is HTTP 200 carrying an inner failure.
        resp = await client.get("/api/v1/portfolio/positions/0xdeadbeef")
        if resp.status == 200:
            body = await resp.json()
            inner = body.get("data")
            inner_status = inner.get("status") if isinstance(inner, dict) else None
            assert inner_status not in ("error", "unavailable"), (
                "HTTP 200 with an inner failure — the exact RUN-4 shape"
            )
