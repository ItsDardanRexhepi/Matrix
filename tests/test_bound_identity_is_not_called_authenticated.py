"""The wallet the security middleware binds is a BOUND identity, not an
authenticated one, and the text that describes it says so.

`GatewayServer._security_context_middleware` binds, for every POST /api/v1/*,
the presented session's identity; with no session, the X-Wallet-Address header;
with neither, a body `wallet`, `from`, `sender` or `account` field, or
`params.from` (gateway/server.py). Only the first is authenticated. Without a
session the identity is whatever the request wrote, from a caller holding the
operator key or on a gateway running with auth off.

The paymaster route's 403 told such a caller "sender does not match the
authenticated caller" about a header it had written itself, and comments on the
fractionalize and capability-invoke routes said the middleware authenticated
the wallet, and that a body-supplied address is never promoted. The first test
shows a body field promoted, and refused against, with no session and no
header. The others pin the corrected text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("eth_account")
pytest.importorskip("eth_abi")

from tests.test_paymaster_sponsors_what_it_signs import (  # noqa: E402
    RECIPIENT, _body, _client, _execute,
)

REPO = Path(__file__).resolve().parents[1]
HEADER_WALLET = "0x" + "11" * 20
BODY_SENDER = "0x" + "22" * 20


@pytest.mark.asyncio
async def test_a_body_wallet_is_promoted_to_the_identity_with_no_session_or_header(
        aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path)
    r = await client.post("/api/v1/paymaster/sign", json=_body(
        _execute(RECIPIENT, 1, b""), sender=BODY_SENDER, wallet=HEADER_WALLET))
    assert r.status == 403, (
        "a body `wallet` was not bound as the identity: the route compared the "
        f"body sender with nothing ({r.status} {await r.text()})")


@pytest.mark.asyncio
async def test_the_paymaster_refusal_does_not_call_a_written_header_authenticated(
        aiohttp_client, tmp_path):
    client = await _client(aiohttp_client, tmp_path)
    r = await client.post("/api/v1/paymaster/sign",
                          json=_body(_execute(RECIPIENT, 1, b""), sender=BODY_SENDER),
                          headers={"X-Wallet-Address": HEADER_WALLET})
    assert r.status == 403, await r.text()
    error = (await r.json())["error"]
    assert "authenticated" not in error, (
        f"no session was presented; the identity is the header the caller wrote: {error!r}")
    assert "bound" in error, error


# Each phrase was written about current_request_security()["wallet"]. The
# files are where it was, and where the same identity is described downstream.
FALSE_PHRASES = {
    "gateway/service_routes.py": [
        "authenticated caller", "middleware authenticated",
        "authenticated identity always wins", "never promoted",
        "never to a self-asserted address",
    ],
    "runtime/capabilities/registry.py": [
        "authenticated identity always wins", "AUTHENTICATED wallet address",
        "no\n        # authenticated caller",
    ],
    "runtime/blockchain/sponsorship.py": [
        "Bind the authenticated caller", "the authenticated HTTP request",
    ],
    "runtime/blockchain/services/nft_services/service.py": [
        "the caller the route authenticated", "is the authenticated wallet",
    ],
    "runtime/blockchain/services/nft_services/rights.py": [
        "The AUTHENTICATED wallet address",
    ],
    "runtime/blockchain/services/service_dispatcher.py": [
        "The AUTHENTICATED wallet address",
    ],
    "runtime/tools/dispatcher.py": [
        "the authenticated address the HTTP and bridge entry",
    ],
}


@pytest.mark.parametrize("path", sorted(FALSE_PHRASES))
def test_the_bound_identity_is_not_described_as_authenticated(path):
    text = (REPO / path).read_text()
    found = [p for p in FALSE_PHRASES[path] if p in text]
    assert not found, f"{path} still says: {found}"
