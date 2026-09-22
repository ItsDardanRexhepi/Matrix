"""A secret that does not match is refused. It is not a crash.

``hmac.compare_digest`` raises ``TypeError`` when either side is a ``str``
holding a non-ASCII character, and when the two sides are not both ``str`` or
both bytes-like. Four places in this tree compared a value a caller wrote
against a secret with it, bare:

  ``QRCodeGenerator.verify_scan``      the QR payload's ``verification_hash``
  ``GatewayServer._is_operator``       the ``Authorization: Bearer`` / ``api_key``
  ``GatewayServer._rate_limit_middleware``   the same header, on public paths
  ``ZKPEligibility.verify_tier_proof`` the proof's commitment/challenge/response

MEASURED on the tree before this change:

  * ``verify_scan`` with ``"verification_hash": "é" * 32`` raised TypeError
    where a wrong-but-ASCII hash returned ``verified: False``. No route reaches
    it yet; the guard is so a future route cannot turn a bad input into a 500.
  * An ANONYMOUS request carrying ``Authorization: Bearer éé`` — or
    ``?api_key=%C3%A9`` — on a key-gated route answered **500** from the auth
    wall, not 401. The same header on a public path (``/health``) answered 500
    from the rate limiter. That one is reachable today, by anyone, on every
    route.
  * ``verify_tier_proof`` with a non-ASCII ``commitment`` raised TypeError
    where a wrong one returned False. Nothing in ACTION_MAP reaches it; the
    class is closed there too.

WHAT CHANGES. One comparison, ``runtime/auth/constant_time.py::digests_equal``,
answers False for anything that is not a pair of strings or a pair of
bytes-likes, and compares strings as their UTF-8 bytes — still constant-time,
and a configured key with a non-ASCII character in it now works rather than
500ing on its own operator. ``verify_scan`` additionally names a hash that is
not an ASCII string ``invalid`` (malformed), not ``suspicious`` (compared and
wrong), because a hex digest is ASCII by construction.

MEASURED: 22 failed, 5 passed before; 27 passed after. The five that pass
before are the genuine-code, wrong-ASCII-hash, real-operator-key, wrong-ASCII-key
and valid-proof regression guards; the eleven ``digests_equal`` cases fail
before because the module does not exist.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from runtime.blockchain.services.supply_chain.qr_codes import (  # noqa: E402
    QR_FORMAT_VERSION, QRCodeGenerator,
)
from tests.test_apple_session_auth_wall import APP_ROUTE, KEY, _bearer, _server  # noqa: E402

SECRET = "an-actual-per-deployment-secret-value"
NON_ASCII = "é" * 32


def _gen() -> QRCodeGenerator:
    return QRCodeGenerator({"supply_chain": {"qr_secret": SECRET}})


def _payload(**overrides) -> str:
    base = {"format": QR_FORMAT_VERSION, "product_id": "WIDGET-1",
            "verification_hash": "0" * 32, "generated_at": 1_700_000_000}
    base.update(overrides)
    return json.dumps(base)


# ── the QR verifier ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_non_ascii_verification_hash_is_invalid_not_a_type_error():
    """DEFECT-PROVER. Before: TypeError out of hmac.compare_digest."""
    result = await _gen().verify_scan(_payload(verification_hash=NON_ASCII))
    assert result["verified"] is False
    assert result["status"] == "invalid", result


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [7, 1.5, ["0" * 32], {"hash": "0" * 32}, True])
async def test_a_verification_hash_that_is_not_a_string_is_invalid(bad):
    """A hash is a hex string. Anything else is malformed, not "compared and
    wrong" — and never coerced with str() into something to compare."""
    result = await _gen().verify_scan(_payload(verification_hash=bad))
    assert result["verified"] is False
    assert result["status"] == "invalid", result


@pytest.mark.asyncio
async def test_the_cache_cross_check_is_guarded_too():
    """DEFECT-PROVER. A generated product has a cache entry, and the second
    compare_digest — against the cached hash — used to raise on the same input."""
    gen = _gen()
    issued = await gen.generate("WIDGET-1")
    assert issued["status"] == "generated"
    result = await gen.verify_scan(_payload(verification_hash=NON_ASCII,
                                            generated_at=issued["generated_at"]))
    assert result["verified"] is False
    assert result["status"] == "invalid"
    # Malformed is refused before either compare runs, so nothing was matched.
    assert not result.get("cache_match")


@pytest.mark.asyncio
async def test_a_genuine_code_still_verifies():
    """Regression guard."""
    gen = _gen()
    issued = await gen.generate("WIDGET-1")
    result = await gen.verify_scan(json.dumps(issued["qr_payload"]))
    assert result["verified"] is True and result["status"] == "valid"


@pytest.mark.asyncio
async def test_a_wrong_ascii_hash_is_still_suspicious_not_invalid():
    """Regression guard: a well-formed hash that does not match was compared,
    and the status says so."""
    gen = _gen()
    issued = await gen.generate("WIDGET-1")
    result = await gen.verify_scan(_payload(verification_hash="f" * 32,
                                            generated_at=issued["generated_at"]))
    assert result["verified"] is False and result["status"] == "suspicious"


# ── the auth wall and the rate limiter ───────────────────────────────────────

async def _raw(client, request: bytes) -> int:
    """Send *request* over a plain socket so no client-side header validation
    stands between the bytes and the server; return the status line's code."""
    reader, writer = await asyncio.open_connection(client.server.host, client.server.port)
    writer.write(request)
    await writer.drain()
    head = await reader.read(4096)
    writer.close()
    return int(head.split(b" ", 2)[1])


NON_ASCII_BEARER = (b"GET " + APP_ROUTE.encode() + b" HTTP/1.1\r\nHost: x\r\n"
                    b"Authorization: Bearer \xc3\xa9\xc3\xa9\r\nConnection: close\r\n\r\n")
NON_ASCII_QUERY = (b"GET " + APP_ROUTE.encode() + b"?api_key=%C3%A9 HTTP/1.1\r\n"
                   b"Host: x\r\nConnection: close\r\n\r\n")
NON_ASCII_BEARER_PUBLIC = (b"GET /health HTTP/1.1\r\nHost: x\r\n"
                           b"Authorization: Bearer \xc3\xa9\xc3\xa9\r\nConnection: close\r\n\r\n")


async def test_an_anonymous_non_ascii_bearer_is_401_at_the_wall_not_500():
    """DEFECT-PROVER, and the reachable one: before, 500."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _raw(client, NON_ASCII_BEARER) == 401


async def test_an_anonymous_non_ascii_api_key_query_is_401_not_500():
    """DEFECT-PROVER: the query-string spelling of the same credential."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _raw(client, NON_ASCII_QUERY) == 401


async def test_a_non_ascii_bearer_on_a_public_path_does_not_crash_the_rate_limiter():
    """DEFECT-PROVER: the wall passes a public path through, and the rate
    limiter made the same comparison. Before, /health answered 500."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert await _raw(client, NON_ASCII_BEARER_PUBLIC) == 200


async def test_the_operator_key_still_opens_the_route():
    """Regression guard."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(APP_ROUTE, headers=_bearer(KEY))
        assert resp.status not in (401, 403, 500)


async def test_a_wrong_ascii_key_is_still_401():
    """Regression guard."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(APP_ROUTE, headers=_bearer("not-the-key"))
        assert resp.status == 401


# ── the loyalty proof verifier ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_non_ascii_proof_field_is_refused_not_a_type_error():
    """DEFECT-PROVER for the fourth site."""
    from runtime.blockchain.services.loyalty.zkp_eligibility import ZKPEligibility

    zkp = ZKPEligibility({})
    proof = await zkp.generate_tier_proof("0xUSER", "prog-1")
    assert await zkp.verify_tier_proof({**proof, "commitment": NON_ASCII}) is False
    assert await zkp.verify_tier_proof({**proof, "response": 12345}) is False


@pytest.mark.asyncio
async def test_a_valid_proof_still_verifies():
    """Regression guard."""
    from runtime.blockchain.services.loyalty.zkp_eligibility import ZKPEligibility

    zkp = ZKPEligibility({})
    proof = await zkp.generate_tier_proof("0xUSER", "prog-1")
    assert await zkp.verify_tier_proof(proof) is True


# ── the one comparison ───────────────────────────────────────────────────────

@pytest.mark.parametrize("presented,expected,equal", [
    ("abc", "abc", True), ("abc", "abd", False), ("", "", True),
    ("é", "é", True), ("é", "e", False),           # non-ASCII no longer raises
    (b"abc", b"abc", True), (b"abc", b"abd", False),
    ("abc", b"abc", False), (None, "abc", False),  # mixed / missing: not equal
    (7, 7, False), (["a"], ["a"], False),
])
def test_digests_equal_answers_false_where_compare_digest_raised(presented, expected, equal):
    from runtime.auth.constant_time import digests_equal

    assert digests_equal(presented, expected) is equal
