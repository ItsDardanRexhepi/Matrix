"""D1 — Route sweep detector.

Walks EVERY route the gateway registers and fails on two families of defect
that no unit test was catching, because no unit test called these routes at all:

  1. **Error-shaped bodies.** A response whose body contains ``has no attribute``,
     ``object is not``, ``Traceback`` or ``NoneType`` is a Python exception that
     leaked to the client (RUN-5, RUN-6). It is never a legitimate payload.

  2. **Envelope inversion.** An HTTP 200 whose *inner* payload carries
     ``status: error`` / ``status: unavailable`` (RUN-4). The transport says
     "fine", the payload says "broken", and every SDK believes the transport.

The route list is taken from ``docs/ROUTES.md`` — the generated table that CI
already keeps in sync — so a route added without a doc regen is a separate,
already-detected failure, and a route added *with* one is swept automatically.

This sweep is deliberately shallow: it proves a route does not *explode*, not
that it is correct. Its job is to make a whole class of bug impossible to ship
unnoticed.

Note on coverage asymmetry: the external audit swept the 72 GET routes by hand.
The ~140 POST routes were entirely unswept and are the larger surface. GET and
POST results are reported separately (see ``test_report_sweep_coverage``) so
that number stays visible rather than being averaged away.
"""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gateway.server import GatewayServer

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
ROUTES_MD = ROOT / "docs" / "ROUTES.md"

# The sweep makes ~200 calls from one client in a few seconds, which trips the
# production rate limiter and turns every response into a 429. A 429 is not a
# result: it means the request never reached the handler, so a "green" sweep
# under rate limiting proves nothing at all. Raise the ceilings for the harness
# only — this configures the test server, it does not change product defaults.
SWEEP_CONFIG = {
    "gateway": {
        "rate_limit_rpm": 100_000,
        "rate_limit_burst": 100_000,
        "rate_limit_rpm_authenticated": 100_000,
        "rate_limit_burst_authenticated": 100_000,
        "rate_limit_rpm_wallet": 100_000,
        "rate_limit_burst_wallet": 100_000,
        "rate_limit_rpm_anonymous": 100_000,
        "rate_limit_burst_anonymous": 100_000,
    }
}

# Substrings that can only be an escaped internal error. Matched case-sensitively
# on the raw body: these are Python-runtime spellings, not prose a handler writes.
ERROR_SHAPES = (
    "has no attribute",
    "object is not",
    "Traceback",
    "NoneType",
)

# Plausible values for path templates. A route that 404s or 400s on a made-up id
# is fine — the sweep is looking for explosions, not for business success.
PARAM_VALUES = {
    "wallet": "0x1111111111111111111111111111111111111111",
    "address": "0x1111111111111111111111111111111111111111",
    "owner": "0x1111111111111111111111111111111111111111",
    "uid": "0x" + "ab" * 32,
    "job_id": "job_1",
    "plan_id": "plan_1",
    "id": "1",
    "capability_id": "send_payment",
    "token_id": "1",
    "chain_id": "84532",
}
DEFAULT_PARAM = "test-id-1"

# Bodies for POST/PUT/PATCH. Handlers that require specific keys should answer
# 400 (an honest refusal); that is a pass. Only an explosion is a failure.
GENERIC_BODY = {
    "address": "0x1111111111111111111111111111111111111111",
    "wallet": "0x1111111111111111111111111111111111111111",
    "sender": "0x1111111111111111111111111111111111111111",
    "recipient": "0x2222222222222222222222222222222222222222",
    "amount": "1",
    "name": "sweep-probe",
    "description": "route sweep probe",
    "source_code": "contract Probe\nstate owner: address",
    "source_lang": "pseudocode",
    "message": "hello",
    "text": "hello",
    "query": "hello",
}


def _parse_routes_md() -> list[tuple[str, str, str]]:
    """Return [(method, path, handler)] from the generated route table."""
    if not ROUTES_MD.is_file():
        pytest.skip(f"{ROUTES_MD} missing — run scripts/generate_route_table.py")
    rows: list[tuple[str, str, str]] = []
    for line in ROUTES_MD.read_text().splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Method", "---"):
            continue
        method, path, handler = cells[0], cells[1].strip("`"), cells[2].strip("`")
        if not path.startswith("/"):
            continue
        rows.append((method.upper(), path, handler))
    assert rows, "parsed zero routes out of ROUTES.md — parser or table shape changed"
    return rows


def _fill(path: str) -> str:
    """Substitute {placeholders} with plausible values."""
    def sub(m: re.Match) -> str:
        name = m.group(1).split(":")[0]
        return PARAM_VALUES.get(name, DEFAULT_PARAM)

    return re.sub(r"\{([^}]+)\}", sub, path)


ROUTES = _parse_routes_md()
# Routes excluded from the sweep, each with a reason. Keep this list SHORT and
# justified — every entry is a hole in the detector.
SKIP_PATHS = {
    "/ws": "websocket upgrade, not a request/response route",
    "/bridge/v1/ws": "websocket upgrade",
    # NEW-6 is FIXED (see tests/test_route_500_fixes.py) — the handler no longer
    # raises. This route is skipped because the SWEEP cannot judge it, not
    # because it is broken: an SSE stream never completes, so a request/response
    # client always ends in ClientPayloadError regardless of correctness. Judging
    # it here would mean either a permanent false positive or an assertion so
    # loose it proves nothing. Its correctness is asserted directly against
    # EventBroadcaster.register instead, including a guard on the handler's call
    # shape so the signature cannot drift again.
    "/social/feed/stream": "server-sent events; a request/response sweep cannot consume a stream that never ends",
}
SWEEPABLE = [r for r in ROUTES if r[1] not in SKIP_PATHS and r[0] != "HEAD"]


@pytest.fixture
async def client():
    server = GatewayServer({})
    app = server.create_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.fixture(scope="module")
def sweep_results():
    """Call every route ONCE and cache (status, body) for all assertions.

    Sweeping once rather than per-assertion halves the wall-clock and, more
    importantly, keeps the status-code census below consistent with the bodies
    the leak/envelope tests judge.
    """
    import asyncio

    async def run() -> dict[tuple[str, str], tuple[int, str]]:
        out: dict[tuple[str, str], tuple[int, str]] = {}
        server = GatewayServer(SWEEP_CONFIG)
        app = server.create_app()
        async with TestClient(TestServer(app)) as c:
            for method, path, _ in SWEEPABLE:
                try:
                    resp = await asyncio.wait_for(
                        _call(c, method, path), timeout=_CONNECT_TIMEOUT_S
                    )
                    # STREAMING ENDPOINTS NEVER CLOSE — that is their contract.
                    # `await resp.text()` reads to EOF, so on an SSE route it
                    # blocks until the harness gives up. Read a bounded prefix
                    # instead: enough to judge the status line and any error
                    # envelope, without waiting for a stream that will not end.
                    if _is_streaming(resp, path):
                        chunk = await asyncio.wait_for(
                            resp.content.read(_STREAM_PREFIX_BYTES),
                            timeout=_STREAM_READ_TIMEOUT_S,
                        )
                        resp.close()
                        body = chunk.decode("utf-8", "replace")
                    else:
                        body = await asyncio.wait_for(
                            resp.text(), timeout=_BODY_TIMEOUT_S
                        )
                    out[(method, path)] = (resp.status, body)
                except asyncio.TimeoutError:
                    # A HANG IS A FINDING, and a DIFFERENT one from a raise.
                    # -2 keeps it distinguishable from -1 so a hung route is not
                    # triaged as an exception, and so a future timeout cannot be
                    # silently absorbed into the raise bucket.
                    out[(method, path)] = (
                        -2, f"TIMED OUT after {_BODY_TIMEOUT_S}s with no complete response"
                    )
                except Exception as exc:  # a raised exception IS a finding
                    out[(method, path)] = (-1, f"RAISED {type(exc).__name__}: {exc}")
        return out

    return asyncio.run(run())


# ── sweep timeouts ───────────────────────────────────────────────────────
# The sweep previously had NO client-side timeout. `GET /api/v1/events/stream`
# is a Server-Sent Events endpoint: it holds the connection open by design, so
# `await resp.text()` — which reads to EOF — waited 302 SECONDS and then failed.
# Five minutes of CI wall-clock, and a red that says nothing about the route.
#
# This is an environmental property of the TEST, not a defect in the code under
# test. The route behaves exactly as an SSE endpoint should; the harness asked
# it a question with no answer.
_CONNECT_TIMEOUT_S = 10.0
_BODY_TIMEOUT_S = 10.0
_STREAM_READ_TIMEOUT_S = 3.0
_STREAM_PREFIX_BYTES = 4096

_STREAMING_PATHS = ("/stream",)


def _is_streaming(resp, path: str) -> bool:
    """A route is streaming if it says so, or if its path is known to be.

    Content-type first, because that is the route's own declaration; the path
    suffix is the fallback for a handler that streams without labelling itself.
    """
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" in ctype or "application/x-ndjson" in ctype:
        return True
    return any(s in path for s in _STREAMING_PATHS)


async def _call(client: TestClient, method: str, path: str):
    url = _fill(path)
    headers = {"Authorization": "Bearer sweep-test-key"}
    if method == "GET":
        return await client.get(url, headers=headers)
    if method == "DELETE":
        return await client.delete(url, headers=headers)
    return await client.request(method, url, json=dict(GENERIC_BODY), headers=headers)


def _inner_status(body: str) -> str | None:
    """Return the inner payload's status, if the body is an {ok, data} envelope."""
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    data = parsed.get("data")
    if isinstance(data, dict) and isinstance(data.get("status"), str):
        return data["status"]
    return None


# ── xfail burn-down (finding IDs, strict=True) ─────────────────────────────
#
# These routes are KNOWN broken, each tied to a finding. xfail(strict=True)
# means the moment a fix lands the route passes, the test XPASSes, and a strict
# xpass is a FAILURE — so the marker cannot outlive the bug it documents. That
# is the burn-down: the count only goes down, and it goes down by force.
# A new breakage cannot hide behind these, because it would appear as a plain
# (unmarked) failure on some other route.
# RUN-6 CLOSED: positions repointed to the real method, history and
# intent/summary now 501 (neither is derivable from anything the platform has).
# Their 6 markers XPASSed strictly — a failure — and were removed here. That is
# the burn-down working: the marker could not outlive the bug.
_XFAIL_LEAK: dict[str, str] = {}
_XFAIL_INVERT: dict[str, str] = {}
# NEW-6..9 all CLOSED. Every one turned out to be code failing at something it
# was trying to do — signature drift (NEW-6, NEW-9), missing error handling
# (NEW-7), a wrong status plus a leaked exception (NEW-8). None warranted a 501.
# Their markers XPASSed strictly and were removed.
_XFAIL_RAISE: dict[str, str] = {}


def _sweep_params(xfail_map: dict[str, str]):
    """Build the parametrize list, xfail-marking the known-broken routes."""
    out = []
    for m, p, _ in SWEEPABLE:
        marks = (
            [pytest.mark.xfail(strict=True, reason=xfail_map[p])]
            if p in xfail_map else []
        )
        out.append(pytest.param(m, p, marks=marks, id=f"{m}:{p}"))
    return out


@pytest.mark.parametrize("method,path", _sweep_params(_XFAIL_LEAK))
def test_route_does_not_leak_internal_errors(sweep_results, method, path):
    """No route may return a body containing an escaped Python error."""
    status, body = sweep_results[(method, path)]
    leaked = [s for s in ERROR_SHAPES if s in body]
    assert not leaked, (
        f"{method} {_fill(path)} -> HTTP {status} leaked {leaked}\n"
        f"body: {body[:400]}"
    )


@pytest.mark.parametrize("method,path", _sweep_params(_XFAIL_INVERT))
def test_route_does_not_invert_envelope(sweep_results, method, path):
    """No route may answer HTTP 200 while its payload reports failure (RUN-4)."""
    status, body = sweep_results[(method, path)]
    if status != 200:
        return  # an honest non-200 is exactly what we want
    inner = _inner_status(body)
    assert inner not in ("error", "unavailable"), (
        f"{method} {_fill(path)} -> HTTP 200 with inner status={inner!r}. "
        "The transport says success and the payload says failure; "
        "every SDK believes the transport."
    )


@pytest.mark.parametrize("method,path", _sweep_params(_XFAIL_RAISE))
def test_route_does_not_raise_or_500(sweep_results, method, path):
    """No route may raise, or answer 500, on a plausible request.

    String-matching on the body is not enough on its own: a handler that blows
    up *before* writing a body (e.g. mid-stream) produces a transport error with
    none of the ERROR_SHAPES in it. `/social/feed/stream` is exactly that case —
    it raises `TypeError: EventBroadcaster.register() got an unexpected keyword
    argument 'ip'` server-side and the client only sees a truncated payload.
    """
    status, body = sweep_results[(method, path)]
    assert status != -1, (
        f"{method} {_fill(path)} raised instead of responding: {body[:300]}"
    )
    # A HANG IS ITS OWN FINDING. Before the harness had a timeout this surfaced
    # as -1 after 302 seconds, i.e. as a raise — the wrong diagnosis and a
    # five-minute one. A route that never answers is a defect distinct from a
    # route that throws, and it must not be absorbed into the raise bucket.
    assert status != -2, (
        f"{method} {_fill(path)} did not answer within the sweep timeout: {body[:300]}\n"
        "If this route legitimately streams, it must declare a streaming "
        "content-type (text/event-stream) so the harness reads a bounded prefix "
        "instead of waiting for an end that never comes."
    )
    assert status != 500, (
        f"{method} {_fill(path)} -> HTTP 500. An unhandled server error on a "
        f"plausible request is a defect, not a valid answer.\nbody: {body[:300]}"
    )


def test_report_sweep_coverage(sweep_results):
    """Emit GET/POST coverage and the status census separately.

    The census matters as much as the pass/fail: if every POST answered 400,
    the sweep would be bouncing off argument validation without ever reaching
    handler logic, and a green POST column would mean nothing. Printing the
    distribution keeps that self-deception visible.
    """
    by_method: dict[str, int] = {}
    census: dict[str, dict[int, int]] = {}
    for (method, path), (status, _) in sweep_results.items():
        by_method[method] = by_method.get(method, 0) + 1
        census.setdefault(method, {})[status] = census.setdefault(method, {}).get(status, 0) + 1

    print(f"\nRoute sweep coverage: {sum(by_method.values())} routes")
    for method in sorted(by_method):
        dist = ", ".join(f"{s}:{n}" for s, n in sorted(census[method].items()))
        print(f"  {method:<7} {by_method[method]:>3} routes   status census -> {dist}")
    print(f"  skipped {len(SKIP_PATHS)}: {', '.join(SKIP_PATHS)}")

    assert by_method.get("POST", 0) > 100, (
        "expected the POST surface to dominate; if this drops, the sweep has "
        "silently stopped covering POSTs"
    )
    # Guard against a VACUOUS sweep. A 429 means the request never reached the
    # handler at all, and 400/401/422 mean it bounced off argument or auth
    # validation. If those dominate, this detector is not exercising handler
    # logic and a green result is self-deception, not evidence.
    #
    # This guard is not hypothetical: the first version of this sweep shared one
    # client across ~200 calls, tripped the rate limiter, and reported 205/211
    # routes "clean" on the strength of 429s.
    for method, dist in census.items():
        total = sum(dist.values())
        throttled = dist.get(429, 0)
        assert throttled == 0, (
            f"{throttled}/{total} {method} routes returned 429 — the sweep is "
            "rate-limited and never reached the handlers. Raise SWEEP_CONFIG."
        )
        bounced = dist.get(400, 0) + dist.get(401, 0) + dist.get(422, 0)
        assert bounced < total, (
            f"every {method} bounced off validation/auth — the sweep never "
            "reached handler logic, so a passing result proves nothing. "
            "Enrich GENERIC_BODY until some requests execute."
        )
