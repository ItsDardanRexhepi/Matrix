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

The same identity reaches ServiceDispatcher through POST
/api/v1/capabilities/{id}/invoke as `caller_identity`. The dispatcher refuses
only `params["caller_identity"]`; it cannot tell a session's identity from a
body `wallet` or `params.from` the middleware promoted. The capability-invoke
tests below drive the whole gateway, middleware included, with no session and
no header, and read the grantor the rights record names.

A third pass, after 3123fec, found the same claim worded without the word
"authenticated", which the earlier sweeps keyed on: "Derived, not asserted." in
the middleware that does the body fallback (gateway/server.py); "identity is
derived, never asserted" in the tool dispatcher's log line; "The HTTP and bridge
entry points derive identity from the session" in tests/test_cd_sibling_axes_fixes.py;
"On the gateway route that caller is authenticated" in
tests/test_insurance_claim_preconditions.py; and test names and docstrings that
say a body or an "unauthenticated" call "cannot assert an identity" when what
they exercise is the dispatcher overwriting one key, `params["caller_identity"]`.
Those are corrected and listed below. This is still a text check: it catches
these phrases coming back, not a new wording of the same claim.

A fourth pass, after 0c34aa7, followed the same `caller_identity` down the
tool path. runtime/react_loop.py threads user_context["wallet_address"] to the
tool dispatcher and called it "the trusted caller identity ... from the
gateway-bound context"; runtime/tools/dispatcher.py said it injects "the
TRUSTED value". On /chat that field is the request body's `wallet`, session or
not (gateway/server.py handle_chat); the session's identity is not consulted.
The chat-path tests below drive the real /chat with an Apple session and a
body wallet, then hand that value to the real dispatcher through the
platform_action tool and read the grantor. Two sites in files the earlier
passes edited also still carried the claim: a test name in
tests/test_insurance_claim_route.py and "whoever was authenticated" in
tests/test_sponsorship_policy_is_enforced.py.
"""

from __future__ import annotations

import json
import re
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


BODY_WALLET = "0x" + "ab" * 20
PARAMS_FROM = "0x" + "cd" * 20
_RIGHTS = {"commercial": {"granted": True, "holder": RECIPIENT}}


async def _set_by(client, body: dict) -> str:
    r = await client.post("/api/v1/capabilities/set_nft_rights/invoke", json=body)
    assert r.status == 200, f"{r.status} {await r.text()}"
    inner = (await r.json())["result"]
    inner = json.loads(inner) if isinstance(inner, str) else inner
    assert inner["status"] == "ok", inner
    return inner["result"]["set_by"]


@pytest.mark.asyncio
async def test_a_body_wallet_becomes_the_grantor_on_the_capability_route(
        aiohttp_client, tmp_path):
    """No session, no header: the top-level body `wallet` is recorded as the
    party that granted the right. The dispatcher's overwrite of
    `params["caller_identity"]` does not reach this, because the value arrives
    as the threaded `caller_identity` itself."""
    client = await _client(aiohttp_client, tmp_path)
    set_by = await _set_by(client, {
        "wallet": BODY_WALLET,
        "params": {"collection": "0xCollection", "token_id": 5, "rights": _RIGHTS},
    })
    assert set_by == BODY_WALLET, set_by


@pytest.mark.asyncio
async def test_params_from_becomes_the_threaded_identity_on_the_capability_route(
        aiohttp_client, tmp_path, monkeypatch):
    """No session, no header, no top-level field: `params.from` is promoted, so
    the `caller_identity` the dispatcher receives IS a value taken from
    `params`. (set_rights declares no `from`, so this call then fails as a 400;
    what is read here is the identity the dispatcher was handed.)"""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    seen: list = []
    real = ServiceDispatcher.execute

    async def spy(self, action, service=None, params=None, *, caller_identity="",
                  caller_source=""):
        seen.append((action, caller_identity))
        return await real(self, action, service, params,
                          caller_identity=caller_identity, caller_source=caller_source)

    monkeypatch.setattr(ServiceDispatcher, "execute", spy)
    client = await _client(aiohttp_client, tmp_path)
    await client.post("/api/v1/capabilities/set_nft_rights/invoke", json={
        "params": {"collection": "0xCollection", "token_id": 6, "rights": _RIGHTS,
                   "from": PARAMS_FROM},
    })
    assert seen == [("set_nft_rights", PARAMS_FROM)], seen


@pytest.mark.asyncio
async def test_params_caller_identity_is_still_not_the_grantor(aiohttp_client, tmp_path):
    """What the dispatcher does refuse: with nothing bound, a
    `params["caller_identity"]` is overwritten and the record says unknown."""
    client = await _client(aiohttp_client, tmp_path)
    set_by = await _set_by(client, {
        "params": {"collection": "0xCollection", "token_id": 7, "rights": _RIGHTS,
                   "caller_identity": PARAMS_FROM},
    })
    assert set_by == "", set_by


# ── what the grantor comparison does and does not stop ──────────────────
#
# RightsManagement.set_rights and RoyaltyEnforcement.configure_royalty refuse a
# change unless the caller's identity equals the recorded setter. The comments
# on both now say whom that stops: a session caller, whose identity the request
# cannot override, and not a caller with no session, who can write the setter's
# address into the body. These drive both cases through the gateway.

SESSION_A = "0x" + "a1" * 20
SESSION_B = "0x" + "b2" * 20


async def _session_client(aiohttp_client, tmp_path):
    from tests.test_paymaster_sponsors_what_it_signs import _config
    from tests.test_gateway import _build_mock_server

    server = _build_mock_server(_config(tmp_path))
    server._app_attest = None
    server._security_backend = "noop"
    sessions = {"tok-a": {"address": SESSION_A}, "tok-b": {"address": SESSION_B}}
    server.wallet_sessions.get = lambda token, default=None: sessions.get(token, default)
    return await aiohttp_client(server.create_app())


async def _invoke(client, capability: str, params: dict, *, token: str = "", **top):
    headers = {"X-Wallet-Session": token} if token else {}
    r = await client.post(f"/api/v1/capabilities/{capability}/invoke",
                          json={"params": params, **top}, headers=headers)
    payload = await r.json()
    inner = payload.get("result")
    inner = json.loads(inner) if isinstance(inner, str) else (inner or {})
    return inner


def _rights(token_id: int, holder: str) -> dict:
    return {"collection": "0xCollection", "token_id": token_id,
            "rights": {"commercial": {"granted": True, "holder": holder}}}


def _refused(inner: dict) -> bool:
    result = inner.get("result") or {}
    return result.get("refused") is True and "cannot be changed" in str(result.get("reason"))


@pytest.mark.asyncio
async def test_a_session_caller_cannot_rewrite_another_sessions_grant(aiohttp_client, tmp_path):
    client = await _session_client(aiohttp_client, tmp_path)
    first = await _invoke(client, "set_nft_rights", _rights(11, SESSION_A), token="tok-a")
    assert first.get("status") == "ok" and first["result"]["set_by"] == SESSION_A, first
    second = await _invoke(client, "set_nft_rights", _rights(11, SESSION_B),
                           token="tok-b", wallet=SESSION_A)
    assert _refused(second), (
        "a session caller wrote the first grantor's address into the body and "
        f"rewrote the grant: {second}")


@pytest.mark.asyncio
async def test_a_caller_with_no_session_can_name_the_grantor_and_rewrite(aiohttp_client, tmp_path):
    """The limit the corrected comments state: with no session the identity is
    the body `wallet`, so naming the original grantor passes the comparison."""
    client = await _session_client(aiohttp_client, tmp_path)
    first = await _invoke(client, "set_nft_rights", _rights(12, SESSION_A), token="tok-a")
    assert first.get("status") == "ok", first
    second = await _invoke(client, "set_nft_rights", _rights(12, SESSION_B), wallet=SESSION_A)
    assert second.get("status") == "ok", second
    assert second["result"]["rights"]["commercial"]["holder"] == SESSION_B, second
    assert second["result"]["set_by"] == SESSION_A, second


def _royalty(token_id: int, recipient: str) -> dict:
    return {"collection": "0xCollection", "token_id": token_id,
            "recipient": recipient, "bps": 500}


@pytest.mark.asyncio
async def test_royalty_session_caller_is_stopped_and_a_written_identity_is_not(
        aiohttp_client, tmp_path):
    client = await _session_client(aiohttp_client, tmp_path)
    first = await _invoke(client, "configure_nft_royalty", _royalty(13, SESSION_A), token="tok-a")
    assert first.get("status") == "ok", first
    by_b = await _invoke(client, "configure_nft_royalty", _royalty(13, SESSION_B),
                         token="tok-b", wallet=SESSION_A)
    assert _refused(by_b), by_b
    written = await _invoke(client, "configure_nft_royalty", _royalty(13, SESSION_B),
                            wallet=SESSION_A)
    assert not _refused(written), written
    assert written["result"]["recipient"] == SESSION_B, written
    assert written["result"]["set_by"] == SESSION_A, written
    # 17-J's label: the body-written identity is recorded as "authenticated".
    assert written["result"]["set_by_source"] == "authenticated", written


# ── the chat path: the threaded identity is the chat body's wallet ──────────
#
# runtime/react_loop.py threads user_context["wallet_address"] to the tool
# dispatcher as caller_identity. On /chat, gateway/server.py handle_chat builds
# that field from the request body's `wallet` (or `wallet_address`), session or
# not, and the session's identity is not consulted. Through the platform_action
# tool it reaches the real ServiceDispatcher and is recorded as the grantor.
# Trinity may not execute state-changing actions herself (they go through
# runtime/agents/handoff.py with no identity), so the record is what a Neo
# dispatch writes; Neo takes the operator key on /chat.

CHAT_BODY_WALLET = "0x" + "ef" * 20
LINKED_WALLET = "0x" + "77" * 20


@pytest.mark.asyncio
async def test_the_chat_route_threads_the_body_wallet_not_the_sessions_identity():
    from aiohttp.test_utils import TestClient, TestServer
    from tests.test_apple_session_auth_wall import _apple_session, _bearer, _server

    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, sub="chat-sub")
        await server.apple_users.link_wallet("chat-sub", LINKED_WALLET)
        r = await client.post("/chat", headers=_bearer(token), json={
            "message": "hi", "session_id": "s-chat", "wallet": CHAT_BODY_WALLET})
        assert r.status == 200, await r.text()
        (context,), _ = server.react_loop.run.call_args
        assert context.metadata["user_context"]["wallet_address"] == CHAT_BODY_WALLET
        server.react_loop.run.reset_mock()
        r = await client.post("/chat", headers=_bearer(token), json={
            "message": "hi", "session_id": "s-chat"})
        assert r.status == 200, await r.text()
        (context,), _ = server.react_loop.run.call_args
        assert context.metadata["user_context"]["wallet_address"] == "", (
            "the session's linked wallet is not what /chat threads; only the body is")


@pytest.mark.asyncio
async def test_a_threaded_body_wallet_becomes_the_grantor_through_the_tool_path():
    """The value the react loop threads, handed to the real ServiceDispatcher
    as the platform_action tool: recorded as the party that set the right."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
    from runtime.tools.dispatcher import ToolDispatcher

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools = {"platform_action": ServiceDispatcher({}).execute}
    d._schemas = {}
    outcome = await d.dispatch(
        "platform_action",
        {"action": "set_nft_rights",
         "params": {"collection": "0xCollection", "token_id": 8, "rights": _RIGHTS}},
        agent_name="neo", caller_identity=CHAT_BODY_WALLET, caller_source="agent")
    assert outcome.ok, outcome
    inner = json.loads(outcome.model_text)
    assert inner["status"] == "ok", inner
    assert inner["result"]["set_by"] == CHAT_BODY_WALLET, inner


# Each phrase was written about current_request_security()["wallet"], or about
# the `caller_identity` it becomes downstream. The files are where it was, and
# where the same identity is described. Text is compared with line breaks and
# comment markers folded to single spaces, so a phrase survives re-wrapping.
FALSE_PHRASES = {
    "gateway/service_routes.py": [
        "authenticated caller", "middleware authenticated",
        "authenticated identity always wins", "never promoted",
        "never to a self-asserted address",
    ],
    "gateway/server.py": [
        "the authenticated wallet header",
        "Derived, not asserted.",
        "Follower = X-Wallet-Address.",
    ],
    "docs/api-reference.md": [
        "Identity is derived, never asserted.",
    ],
    "runtime/capabilities/registry.py": [
        "authenticated identity always wins", "AUTHENTICATED wallet address",
        "no authenticated caller",
        "a body-supplied value would be a self-asserted address",
        "the spoofing primitive the dispatcher-side injection exists to refuse",
    ],
    "runtime/blockchain/sponsorship.py": [
        "Bind the authenticated caller", "the authenticated HTTP request",
    ],
    "runtime/blockchain/services/nft_services/service.py": [
        "the caller the route authenticated", "is the authenticated wallet",
    ],
    "runtime/blockchain/services/nft_services/rights.py": [
        "The AUTHENTICATED wallet address",
        "never to a fabricated or self-asserted address",
        "carried no authenticated identity",
    ],
    "runtime/blockchain/services/nft_services/royalty_enforcement.py": [
        "now requires an authenticated caller",
    ],
    "runtime/blockchain/services/service_dispatcher.py": [
        "The AUTHENTICATED wallet address",
        "AUTHENTICATED caller's wallet address",
        "Never taken from ``params``",
        "THE AUTHENTICATED VALUE OVERWRITES",
        'an unauthenticated call records "unknown", never a self-asserted address',
        "the authenticated identity is the FALLBACK",
        "outranks the authenticated caller",
        "no authenticated identity: the record says",
    ],
    "runtime/blockchain/services/insurance/service.py": [
        "/api/v1/insurance/claim ENFORCING. The handler binds",
        "caller/holder/creator to the authenticated identity",
    ],
    "runtime/blockchain/services/insurance/_guards.py": [
        "ONLY the threaded `caller_identity` may be trusted",
        'a caller authenticated as "mallory"',
    ],
    "runtime/blockchain/services/ownership.py": [
        "An unauthenticated caller is therefore refused",
    ],
    "runtime/tools/dispatcher.py": [
        "the authenticated address the HTTP and bridge entry",
        "identity is derived, never asserted",
        "inject the TRUSTED value the caller passed in",
    ],
    "runtime/react_loop.py": [
        "The trusted caller identity travels the same way the trusted agent name does",
        "from the gateway-bound context, never from the model's arguments",
    ],
    "tests/test_caller_identity_is_not_dropped.py": [
        "The wallet the gateway authenticated",
        "does not record the authenticated caller",
        "a caller with no authenticated identity wrote their own",
        "The authenticated value wins over the body, always.",
        "one authenticated HTTP route naming the grantor",
        "the wallet the security middleware already authenticated",
        "async def test_capability_route_body_cannot_assert_an_identity",
        'an unauthenticated invoke must record "unknown" and never the address the body claims',
        "the capability route let a body-supplied address become",
        "async def test_params_cannot_assert_an_identity_when_unauthenticated",
        "async def test_params_cannot_override_an_authenticated_identity",
        "has no authenticated caller starts raising",
    ],
    "tests/test_cd_sibling_axes_fixes.py": [
        "the identity class: derived, never asserted",
        "The HTTP and bridge entry points derive identity from the session.",
    ],
    "tests/test_insurance_claim_preconditions.py": [
        "On the gateway route that caller is authenticated",
    ],
    "tests/test_insurance_caller_cannot_assert_its_own_identity.py": [
        'caller authenticated as "mallory"',
        "async def test_an_unauthenticated_caller_cannot_assert_an_identity",
        "an unauthenticated call is a refusal, never a fallback to the self-asserted value",
    ],
    "tests/test_sponsorship_policy_is_enforced.py": [
        "A dispatch with no authenticated caller must not inherit",
        "it to whoever was authenticated",
    ],
    "tests/test_nft_royalty_authority.py": [
        'distinguish "nobody was authenticated" from "we did not look"',
    ],
    "tests/test_insurance_claim_route.py": [
        "async def test_an_authenticated_identity_beats_a_body_supplied_holder",
        "middleware authenticated for THIS request",
        "enforced upstream by the security middleware",
        "authenticated mallory",
        "holder overrode the authenticated identity",
    ],
    "tests/test_fractionalize_owner_is_not_dropped.py": [
        "the authenticated wallet must win over the body",
    ],
    "tests/test_p5_identity.py": [
        "binds to the authenticated wallet",
        "the security middleware authenticated",
        "the authenticated wallet must win, not the body voter",
    ],
}


def _folded(text: str) -> str:
    text = re.sub(r"[ \t]*\n[ \t]*(?:#[ \t]*)?", " ", text)
    return re.sub(r"[ \t]+", " ", text)


@pytest.mark.parametrize("path", sorted(FALSE_PHRASES))
def test_the_bound_identity_is_not_described_as_authenticated(path):
    text = _folded((REPO / path).read_text())
    found = [p for p in FALSE_PHRASES[path] if p in text]
    assert not found, f"{path} still says: {found}"
