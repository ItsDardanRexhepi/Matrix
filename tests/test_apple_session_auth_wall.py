"""T2 / path A — the Apple session is a credential at the auth wall.

What the register measured before this change (entry::APP-PROD-REACH,
entry::D005-DECIDED-A, entry::TWINS-CRITICAL):

  * The iOS app signs in through POST /api/v1/auth/apple and stores the token
    it gets back as its Authorization Bearer. The auth wall accepted ONLY the
    operator key, so every key-gated route the app calls answered 401 — the
    app could not function against a hosted gateway.
  * Identity on /api/v1/* came from a header or body field the caller wrote.
  * On the public chat surfaces any caller could name ``agent: "neo"`` — the
    execution engine with the platform-key tools — because the agent was a
    body field, not a privilege.
  * ``WalletSessionStore.get()`` returned expired sessions; only the rate
    limiter compared ``expires_at`` itself.
  * ``isNewUser`` was always true and ``walletAddress`` always "" — computed
    from a ``get_by_address`` the store never had.

These tests drive the real middlewares and handlers through aiohttp's test
client. The model is stubbed at ``react_loop.run`` so a chat that reaches the
loop is observable without a provider. 19 of the 24 fail at the previous head;
the five that say "still" are regression guards and pass on both sides.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KEY = "test-operator-key"
AUTH_CONFIG = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": KEY}}
APP_ROUTE = "/api/v1/capabilities"           # GET, in the app's allowlist
OPERATOR_ROUTE = "/api/v1/contracts/deploy"  # exists, never called by the app


def _server() -> GatewayServer:
    # A fresh SQLite per server: the sweep config's store persists across runs,
    # and "first sign-in" is only true once per database.
    scratch = tempfile.mkdtemp(prefix="opnmatrx-t2-")
    config = {**AUTH_CONFIG, "memory_dir": scratch,
              "database": {**AUTH_CONFIG.get("database", {}), "path": f"{scratch}/t2.db"}}
    server = GatewayServer(config)
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    return server


async def _apple_session(server: GatewayServer, sub: str = "sub-1", ttl: float = 3600) -> str:
    """Issue the session /api/v1/auth/apple would issue, without Apple."""
    token = f"session-{sub}-{ttl}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=f"apple:{sub}",
                                     issued_at=now, expires_at=now + ttl)
    return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── the wall ─────────────────────────────────────────────────────────────────

async def test_anonymous_is_still_refused_on_a_key_gated_route():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.get(APP_ROUTE)
        assert resp.status == 401


async def test_the_apple_bearer_reaches_a_route_the_app_calls():
    """Before: 401 on every one of these. The route's own answer (200, or a
    503 when its service is unconfigured) is not the point — the wall is."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.get(APP_ROUTE, headers=_bearer(token))
        assert resp.status not in (401, 403), await resp.text()


async def test_the_apple_bearer_is_refused_on_an_operator_route():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.post(OPERATOR_ROUTE, json={}, headers=_bearer(token))
        assert resp.status == 403
        body = await resp.json()
        assert body["error"] == "forbidden"


async def test_the_apple_bearer_is_refused_on_shared_agent_memory():
    """/memory/read is called by the app and exists on the server — and stays
    closed to a user session: it reads an agent's memory shared by every user."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.post("/memory/read", json={"agent": "neo"}, headers=_bearer(token))
        assert resp.status == 403


async def test_the_operator_key_still_opens_everything():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        for route, method in ((APP_ROUTE, "GET"), (OPERATOR_ROUTE, "POST"), ("/memory/read", "POST")):
            resp = await client.request(method, route, json={"agent": "neo"} if method == "POST" else None,
                                        headers=_bearer(KEY))
            assert resp.status not in (401, 403), (route, resp.status)


async def test_an_expired_session_is_no_credential():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, ttl=-1)
        assert server.wallet_sessions.get(token) is None
        assert token not in server.wallet_sessions
        resp = await client.get(APP_ROUTE, headers=_bearer(token))
        assert resp.status == 401


async def test_x_wallet_session_header_is_accepted_like_the_bearer():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.get(APP_ROUTE, headers={"X-Wallet-Session": token})
        assert resp.status not in (401, 403)


# ── the agent is a privilege, not a body field ───────────────────────────────

async def test_anonymous_bridge_chat_naming_neo_is_refused():
    """THE CONTROL from the M2 plan: before, this dispatched to Neo."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/bridge/v1/chat",
                                 json={"message": "hi", "agent": "neo", "session_id": "s1"})
        assert resp.status == 403, await resp.text()
        assert not server.react_loop.run.called


async def test_anonymous_bridge_chat_reaches_trinity():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/bridge/v1/chat", json={"message": "hi", "session_id": "s1"})
        assert resp.status == 200, await resp.text()
        (context,), _ = server.react_loop.run.call_args
        assert context.agent_name == "trinity"


async def test_the_apple_session_may_not_name_neo_either():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server)
        resp = await client.post("/bridge/v1/chat", headers=_bearer(token),
                                 json={"message": "hi", "agent": "neo", "session_id": "s1"})
        assert resp.status == 403
        assert not server.react_loop.run.called


async def test_the_operator_may_name_neo():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/bridge/v1/chat", headers=_bearer(KEY),
                                 json={"message": "hi", "agent": "neo", "session_id": "s1"})
        assert resp.status == 200, await resp.text()
        (context,), _ = server.react_loop.run.call_args
        assert context.agent_name == "neo"


async def test_public_chat_refuses_neo_without_the_operator_key():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/chat", json={"message": "hi", "agent": "neo"})
        assert resp.status == 403
        assert not server.react_loop.run.called


async def test_an_unknown_agent_name_is_still_a_400_not_a_403():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post("/chat", json={"message": "hi", "agent": "zeus"})
        assert resp.status == 400


async def test_bridge_chat_apple_id_comes_from_the_session_not_the_body():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, sub="real-sub")
        resp = await client.post("/bridge/v1/chat", headers=_bearer(token),
                                 json={"message": "hi", "session_id": "s1", "apple_id": "forged-sub"})
        assert resp.status == 200
        (context,), _ = server.react_loop.run.call_args
        assert context.metadata["user_context"]["apple_id"] == "real-sub"


# ── identity is derived from the session ─────────────────────────────────────

class _FakeRequest:
    def __init__(self, headers: dict, body: dict, method="POST", path="/api/v1/nft/mint"):
        self.headers = headers
        self.method = method
        self.path = path
        self._body = body
        self.query = {}

    async def json(self):
        return self._body


async def _bound_context(server: GatewayServer, headers: dict, body: dict) -> dict:
    """What the Morpheus gate sees: the bound context's ``wallet`` is the identity."""
    from gateway.security_gate import current_request_security
    seen = {}

    async def handler(_request):
        seen.update(current_request_security() or {})
        return "handled"

    assert await server._security_context_middleware(_FakeRequest(headers, body), handler) == "handled"
    return seen


async def test_security_context_takes_the_session_subject_over_a_forged_header_and_body():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        token = await _apple_session(server, sub="sub-9")
        seen = await _bound_context(server,
                                    {"Authorization": f"Bearer {token}", "X-Wallet-Address": "0xATTACKER",
                                     "X-Apple-Id": "forged"},
                                    {"wallet": "0xATTACKER", "apple_id": "forged"})
        assert seen.get("wallet") == "apple:sub-9"
        assert seen.get("apple_id") == "sub-9"


async def test_without_a_session_the_operators_header_names_the_user_it_acts_for():
    """An operator integration names the user it acts for: no session, the key,
    and the header speaks. (Development — auth off — is the operator.)"""
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        seen = await _bound_context(server, {"Authorization": f"Bearer {KEY}", "X-Wallet-Address": "0xSELF"}, {})
        assert seen.get("wallet") == "0xSELF"
        seen = await _bound_context(server, {"Authorization": f"Bearer {KEY}"}, {"wallet": "0xBODY"})
        assert seen.get("wallet") == "0xBODY"


# The docs say an X-Wallet-Address header or a wallet body field is consulted
# only when no session is presented AND the request carries the operator key.
# Two readers consulted it for anyone: this middleware (every POST /api/v1/*,
# including the public /api/v1/auth/apple and /api/v1/iap/*), and
# _caller_identity, which the public POST /security/appattest/attest used as
# the identity its attestation is verified for.

@pytest.mark.parametrize("path", ["/api/v1/nft/mint", "/api/v1/auth/apple", "/api/v1/iap/verify"])
async def test_an_anonymous_header_or_body_names_nobody(path):
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        from gateway.security_gate import current_request_security
        seen: dict = {}

        async def handler(_request):
            seen.update(current_request_security() or {})
            return "handled"

        request = _FakeRequest({"X-Wallet-Address": "0xVICTIM", "X-Apple-Id": "victim-sub"},
                               {"wallet": "0xVICTIM", "from": "0xVICTIM", "apple_id": "victim-sub"}, path=path)
        assert await server._security_context_middleware(request, handler) == "handled"
        assert not seen.get("wallet"), seen
        assert not seen.get("apple_id"), seen


async def test_the_public_attest_route_takes_no_identity_from_the_wallet_header():
    server = _server()
    calls: list[dict] = []

    class _Verifier:
        async def verify_attestation(self, **kwargs):
            calls.append(kwargs)
            return {"verified": False, "reason": "stub"}

    server._app_attest = _Verifier()
    server._security_backend = "stub"
    async with TestClient(TestServer(server.create_app())) as client:
        body = {"key_id": "k", "attestation_obj_b64": "b", "challenge": "c"}
        r = await client.post("/security/appattest/attest", json=body, headers={"X-Wallet-Address": "0xVICTIM"})
        assert r.status == 200, await r.text()
        token = await _apple_session(server, sub="sub-attest")
        r = await client.post("/security/appattest/attest", json=body,
                              headers={**_bearer(token), "X-Wallet-Address": "0xVICTIM"})
        assert r.status == 200, await r.text()
    assert [c["identity"] for c in calls] == ["", "apple:sub-attest"], calls


async def test_a_linked_wallet_becomes_the_identity_of_the_apple_session():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        token = await _apple_session(server, sub="sub-2")
        await server.apple_users.link_wallet("sub-2", "0xLINKED")
        seen = await _bound_context(server, {"Authorization": f"Bearer {token}"}, {})
        assert seen.get("wallet") == "0xLINKED"
        assert seen.get("apple_id") == "sub-2"


async def test_social_follow_takes_the_follower_from_the_session():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, sub="sub-3")
        await server.apple_users.link_wallet("sub-3", "0xFOLLOWER")
        resp = await client.post("/social/follow", headers={**_bearer(token), "X-Wallet-Address": "0xFORGED"},
                                 json={"address": "0xFOLLOWEE"})
        assert resp.status == 200, await resp.text()
        following = server._follow_store()
        assert "0xFOLLOWEE".lower() in [a.lower() for a in await following.following("0xFOLLOWER")]
        assert not await following.following("0xFORGED")


# ── the Apple user is persisted ──────────────────────────────────────────────

async def test_first_sign_in_is_reported_once():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        assert await server.apple_users.touch("sub-7") is True
        assert await server.apple_users.touch("sub-7") is False
        assert server.apple_users.wallet_for("sub-7") == ""
        await server.apple_users.link_wallet("sub-7", "0xW")
        assert server.apple_users.wallet_for("sub-7") == "0xW"


async def test_apple_users_survive_a_restart_of_the_store():
    from runtime.auth.session_store import AppleUserStore
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        await server.apple_users.touch("sub-8")
        await server.apple_users.link_wallet("sub-8", "0xP")
        fresh = AppleUserStore(server.react_loop.memory.db)
        await fresh.initialize()
        assert fresh.wallet_for("sub-8") == "0xP"
        assert await fresh.touch("sub-8") is False


async def test_siwe_verify_while_holding_an_apple_session_links_the_wallet():
    """Drives the real /auth/nonce → sign → /auth/verify path with a throwaway key."""
    eth_account = pytest.importorskip("eth_account")
    from eth_account.messages import encode_defunct
    acct = eth_account.Account.create()
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _apple_session(server, sub="sub-link")
        resp = await client.post("/auth/nonce", json={"address": acct.address})
        assert resp.status == 200, await resp.text()
        challenge = await resp.json()
        signed = acct.sign_message(encode_defunct(text=challenge["message"]))
        signature = signed.signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature
        resp = await client.post("/auth/verify", headers=_bearer(token), json={
            "address": acct.address, "message": challenge["message"],
            "signature": signature, "nonce": challenge["nonce"]})
        assert resp.status == 200, await resp.text()
        assert server.apple_users.wallet_for("sub-link") == acct.address


# ── the public access policy ─────────────────────────────────────────────────

def test_an_empty_agent_name_is_refused_but_the_internal_path_is_not():
    from runtime.access_policy import default_agent_access
    assert default_agent_access(None, "web_search")[0] is True
    allowed, reason = default_agent_access("", "web_search")
    assert allowed is False and reason


# ── the allowlist is derived and current ─────────────────────────────────────

def test_every_session_route_exists_on_the_gateway():
    from gateway.session_routes import EXCLUDED_FROM_SESSION, USER_SESSION_ROUTES
    server = _server()
    canonical = {r.canonical.rstrip("/") or "/" for r in server.create_app().router.resources()}
    missing = sorted((USER_SESSION_ROUTES | EXCLUDED_FROM_SESSION) - canonical)
    assert not missing, f"stale entries in gateway/session_routes.py: {missing}"


def test_the_committed_allowlist_matches_the_app():
    client_tree = ROOT.parent / "MTRX"
    if not client_tree.exists():
        pytest.skip("MTRX checkout not present (CI): the committed allowlist is used as is")
    result = subprocess.run([sys.executable, "scripts/generate_session_routes.py", "--check"],
                            cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr or result.stdout
