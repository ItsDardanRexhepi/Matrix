"""One wallet is one caller, whatever case its address is written in.

THE DEFECT. An Ethereum address is hex, and hex letters have two cases, so one
wallet has many spellings: all lower case, all upper case, the EIP-55 checksum
form, and every mix of them, with an upper- or lower-case ``x`` in the prefix.
Sign-In with Ethereum proves control of the key behind the address in any of
them (``runtime/auth/siwe.py`` compares without regard to case, as it should).
The gateway then kept the spelling the caller sent: ``/auth/verify`` stored the
session under it, the wallet linked to an Apple user was stored as sent, the
identity derived from a session was returned as stored, and the dispatcher and
the gateway handed it to the security seam as it arrived. So one wallet could
hold sessions under as many identities as it has spellings, and every decision
keyed on who is calling (the platform's own, and the security core's behind
the seam) saw several callers where there is one. A refusal attached to one
spelling did not reach a session signed in under another.

THE RULE PINNED HERE. Wherever the platform names a caller it uses one spelling
of a wallet address: ``0x`` and the forty hex digits in lower case, the spelling
the sponsorship meter already keyed on (runtime/auth/identity.py, the one place
the rule is written):

  1. the session ``/auth/verify`` creates, whatever case the address was sent in
  2. the wallet linked to an Apple user, and so that session's identity
  3. a session or a link stored before this rule, read back in the one spelling
  4. an identity the operator states (header or body), on the HTTP gate, the
     chat context and the App Attest challenge and attestation
  5. the context handed to the seam at the tool boundary, the caller identity a
     tool is given, and the identity at the hand-off's gate
  6. the sponsorship meter, which folded case but kept a ``0X`` prefix as a
     second spender, so a capital X bought a second budget
  7. SCOPE PIN: what is not a hex address (``apple:<sub>``, a label, ``""``) is
     left exactly as it was

Nothing here says what the security core does with the identity; it pins that
the platform hands it one.

§CC, measured: against the base tree (117cf8f), 9 failed and 2 passed, on the
no-op backend and with the core installed. The two that passed are the scope
pins. Each of the nine failed on the spelling it was handed back: the address
as the caller wrote it, and for the sponsorship meter, a ``0X`` spelling drawing
on a second budget. After the change, 11 passed, on both backends.
"""

from __future__ import annotations

import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer, make_mocked_request  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from runtime.security import CALLER_IDENTITY_KEY  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

eth_account = pytest.importorskip("eth_account")
from eth_account.messages import encode_defunct  # noqa: E402

KEY = "test-operator-key"
AUTH_CONFIG = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": KEY}}

# One wallet, written four ways. ONE is the one spelling.
ONE = "0x" + "ab" * 20
CHECKSUM = "0xABaBaBaBABabABabAbAbABAbABabababaBaBABaB"
UPPER = "0x" + "AB" * 20
UPPER_X = "0X" + "ab" * 20
SPELLINGS = (CHECKSUM, UPPER, UPPER_X, ONE)


def _server() -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-spelling-")
    config = {**AUTH_CONFIG, "memory_dir": scratch,
              "database": {**AUTH_CONFIG.get("database", {}), "path": f"{scratch}/s.db"}}
    server = GatewayServer(config)
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    return server


def _request(headers: dict, method: str = "POST", path: str = "/chat"):
    return make_mocked_request(method, path, headers=headers)


async def _sign_in(client, account, spelling: str, headers: dict | None = None) -> dict:
    """The real /auth/nonce -> sign -> /auth/verify path, with the address in
    *spelling* on /auth/verify."""
    resp = await client.post("/auth/nonce", json={"address": account.address})
    assert resp.status == 200, await resp.text()
    challenge = await resp.json()
    signature = account.sign_message(encode_defunct(text=challenge["message"])).signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature
    resp = await client.post("/auth/verify", headers=headers or {}, json={
        "address": spelling, "message": challenge["message"],
        "signature": signature, "nonce": challenge["nonce"]})
    assert resp.status == 200, await resp.text()
    return await resp.json()


def _spellings_of(address: str) -> tuple[str, ...]:
    body = address[2:]
    return ("0x" + body.lower(), "0x" + body.upper(), "0X" + body.lower(), address)


# ── 1. a session created in any spelling names the one caller ─────────────


async def test_sign_in_in_any_case_is_one_caller():
    account = eth_account.Account.create()
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        identities, answered = set(), set()
        for spelling in _spellings_of(account.address):
            issued = await _sign_in(client, account, spelling)
            answered.add(issued["address"])
            request = _request({"X-Wallet-Session": issued["token"]})
            identities.add(server._session_identity(request))
            identities.add(server._caller_identity(request))
            identities.add(server._session_subject(request))
    assert identities == {account.address.lower()}, identities
    assert answered == {account.address.lower()}, answered


# ── 2. the wallet linked to an Apple user ─────────────────────────────────


async def test_a_wallet_linked_in_another_case_is_the_same_caller():
    account = eth_account.Account.create()
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = "apple-session-link"
        now = time.time()
        await server.wallet_sessions.add(token=token, address="apple:sub-link",
                                         issued_at=now, expires_at=now + 3600)
        await _sign_in(client, account, "0X" + account.address[2:].upper(),
                       headers={"Authorization": f"Bearer {token}"})
        assert server.apple_users.wallet_for("sub-link") == account.address.lower()
        request = _request({"Authorization": f"Bearer {token}"})
        assert server._session_identity(request) == account.address.lower()


# ── 3. what was stored before the rule is read back in the one spelling ───


async def test_a_session_and_a_link_stored_before_are_read_back_in_one_spelling():
    from runtime.auth.session_store import AppleUserStore, WalletSessionStore
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        db = server.react_loop.memory.db
        now = time.time()
        await db.execute(
            "INSERT INTO wallet_sessions (token, address, issued_at, expires_at) VALUES (?, ?, ?, ?)",
            ("stored-before", CHECKSUM, now, now + 3600))
        await db.execute(
            "INSERT INTO apple_users (sub, first_seen, last_seen, wallet_address) VALUES (?, ?, ?, ?)",
            ("sub-before", now, now, UPPER_X))
        sessions, users = WalletSessionStore(db), AppleUserStore(db)
        await sessions.initialize()
        await users.initialize()
        assert sessions.get("stored-before")["address"] == ONE
        assert users.wallet_for("sub-before") == ONE


async def test_a_session_added_through_the_store_is_kept_in_one_spelling():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        now = time.time()
        for n, spelling in enumerate(SPELLINGS):
            await server.wallet_sessions.add(token=f"t{n}", address=spelling,
                                             issued_at=now, expires_at=now + 3600)
            await server.apple_users.link_wallet(f"sub-{n}", spelling)
        assert {server.wallet_sessions.get(f"t{n}")["address"] for n in range(4)} == {ONE}
        assert {server.apple_users.wallet_for(f"sub-{n}") for n in range(4)} == {ONE}


# ── 4. an identity the operator states ────────────────────────────────────


async def test_an_identity_the_operator_states_has_the_one_spelling():
    from gateway.security_gate import current_request_security
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        for spelling in SPELLINGS:
            op = {"Authorization": f"Bearer {KEY}", "X-Wallet-Address": spelling}
            assert server._caller_identity(_request(op)) == ONE, spelling

            ctx = server._chat_user_context(
                _request({"Authorization": f"Bearer {KEY}"}), session_id="s",
                agent="trinity", body={"wallet": spelling})
            assert ctx["wallet_address"] == ONE, (spelling, ctx)

            class _Req:
                headers = {"Authorization": f"Bearer {KEY}"}
                method, path, query = "POST", "/api/v1/nft/mint", {}

                async def json(self):
                    return {"wallet": spelling}

            seen = {}

            async def handler(_request):
                seen.update(current_request_security() or {})
                return "handled"

            assert await server._security_context_middleware(_Req(), handler) == "handled"
            assert seen.get("wallet") == ONE, (spelling, seen)


async def test_the_app_attest_challenge_and_attestation_are_bound_to_one_spelling():
    calls = []

    class _Verifier:
        async def new_challenge(self, identity):
            calls.append(("challenge", identity))
            return "c0ffee"

        async def verify_attestation(self, **kwargs):
            calls.append(("attest", kwargs["identity"]))
            return {"verified": False, "reason": "stub"}

    server = _server()
    server._app_attest = _Verifier()
    server._security_backend = "stub"
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.get("/security/appattest/challenge", params={"identity": CHECKSUM})
        assert r.status == 200, await r.text()
        body = {"key_id": "k", "attestation_obj_b64": "b", "challenge": "c"}
        r = await client.post("/security/appattest/attest", json=body,
                              headers={"Authorization": f"Bearer {KEY}", "X-Wallet-Address": UPPER})
        assert r.status == 200, await r.text()
        r = await client.post("/security/appattest/attest", json={**body, "identity": UPPER_X})
        assert r.status == 200, await r.text()
    assert calls == [("challenge", ONE), ("attest", ONE), ("attest", ONE)], calls


# ── 5. what the seam and the tools are handed ─────────────────────────────


class _Recorder:
    def __init__(self):
        self.contexts: list[dict] = []

    def __call__(self, agent, tool, action=None, context=None):
        self.contexts.append(dict(context or {}))
        return True, ""


async def test_the_tool_boundary_and_the_tool_are_handed_one_spelling(monkeypatch):
    from runtime.blockchain.sponsorship import resolve_caller_identity
    from runtime.tools import dispatcher as mod

    rec = _Recorder()
    monkeypatch.setattr(mod, "agent_access_allowed", rec)
    d = mod.ToolDispatcher({})
    handed: list[tuple] = []

    async def stub(query: str = "", caller_identity: str = "", **extra):
        handed.append((caller_identity, resolve_caller_identity()))
        return "ok"

    d._tools["web_search"] = stub
    for spelling in SPELLINGS:
        out = await d.dispatch("web_search", {"query": "q"}, agent_name="trinity",
                               caller_identity=spelling, caller_source="agent",
                               caller_kind="session")
        assert out.ok, out.model_text
    assert {c.get(CALLER_IDENTITY_KEY) for c in rec.contexts} == {ONE}, rec.contexts
    assert set(handed) == {(ONE, ONE)}, handed


async def test_the_handoffs_gate_and_the_http_gate_are_handed_one_spelling(monkeypatch):
    import runtime.security as seam
    from gateway.security_gate import bind_request_security, current_request_security
    from runtime.agents.handoff import AgentHandoff

    contexts: list[dict] = []

    class _Gate:
        async def evaluate(self, request, context):
            contexts.append(dict(context))
            return {"allow": False, "reason": "recorded"}

    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: _Gate())
    handoff = AgentHandoff({}, None)
    for spelling in SPELLINGS:
        await handoff.as_tool("send", {}, caller_identity=spelling)
        bind_request_security(identity=spelling)
        assert current_request_security()["wallet"] == ONE, spelling
    assert {c.get(CALLER_IDENTITY_KEY) for c in contexts} == {ONE}, contexts


# ── 6. the sponsorship meter ──────────────────────────────────────────────


def test_a_capital_x_does_not_buy_a_second_sponsorship_budget(tmp_path):
    from runtime.blockchain.sponsorship import SponsorshipPolicy
    policy = SponsorshipPolicy.from_config({
        "blockchain": {"paymaster": {"policy": {"allowed_actions": ["transfer"],
                                                "daily_cap_usd": 50}}},
        "database": {"path": str(tmp_path / "spend.db")},
    })
    first = policy.authorize_and_reserve("transfer", identity=ONE, est_usd=50.0)
    assert first.allowed
    policy.commit(first.reservation_id)
    for spelling in (CHECKSUM, UPPER, UPPER_X, " " + ONE + " "):
        again = policy.authorize_and_reserve("transfer", identity=spelling, est_usd=1.0)
        assert not again.allowed, f"{spelling!r} drew on a second budget"
        assert policy.spent_today(spelling) == policy.spent_today(ONE)


# ── 7. scope pins: what is not an address is left as it was ───────────────


NOT_ADDRESSES = ("apple:sub-Mixed-Case", "operator-label", "0xLINKED",
                 "0x" + "ab" * 19, "0x" + "ab" * 21, "")


async def test_what_is_not_an_address_is_left_as_it_was(monkeypatch):
    from gateway.security_gate import bind_request_security, current_request_security
    from runtime.tools import dispatcher as mod

    rec = _Recorder()
    monkeypatch.setattr(mod, "agent_access_allowed", rec)
    d = mod.ToolDispatcher({})

    async def stub(query: str = "", **extra):
        return "ok"

    d._tools["web_search"] = stub
    for value in NOT_ADDRESSES:
        await d.dispatch("web_search", {"query": "q"}, agent_name="trinity",
                         caller_identity=value, caller_source="agent", caller_kind="session")
        bind_request_security(identity=value)
        assert current_request_security()["wallet"] == value
    assert [c.get(CALLER_IDENTITY_KEY, "") for c in rec.contexts[::2]] == list(NOT_ADDRESSES)


async def test_an_apple_session_without_a_wallet_is_still_its_subject():
    server = _server()
    async with TestClient(TestServer(server.create_app())):
        now = time.time()
        await server.wallet_sessions.add(token="apple-only", address="apple:Sub-Case",
                                         issued_at=now, expires_at=now + 3600)
        request = _request({"Authorization": "Bearer apple-only"})
        assert server._session_identity(request) == "apple:Sub-Case"
        assert server._session_subject(request) == "apple:Sub-Case"
