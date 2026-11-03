"""A user session acts only as the identity it is bound to, wherever a request
names who acts.

THE DEFECT (pre-existing on The Matrix ``main``). The session allowlist lets
anyone with an Apple sign-in through the auth wall to routes whose handlers take
the acting party from the request body and hand it to the service as written:
``/api/v1/marketplace/list``'s ``seller``, ``/api/v1/marketplace/buy``'s
``buyer``, ``/api/v1/loyalty/redeem``'s ``user``, ``/api/v1/staking/stake``'s
``staker``, ``/api/v1/groups``' ``creator`` and the rest below. The identity the
security middleware bound for the session went to the security gate only, and
the gate does not decide who the service acts for. So a session listed an item
as somebody else's, spent somebody else's loyalty points, staked as somebody
else and founded a community in somebody else's name, and the dispatchers that
run the same operations by name (``/bridge/v1/action``, capability invoke,
Trinity's ``request_execution``) did the same with the same parameters. A few
handlers already held their party to the bound identity (a vote, an insurance
claim, a paymaster signature); these did not.

Every operation in ``runtime/access_policy.py`` ``SESSION_ACTS_AS`` now holds a
session to its own identity on every door: the request must name the session's
own identity in that field, in any spelling of it, and naming another, or none,
is refused before the service runs. The operator key still names the party it
acts for, as before.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_no_request_chooses_the_call_the_platform_key_signs as signing  # noqa: E402

A = "0x" + "a1" * 20      # the session's own address
B = "0x" + "b2" * 20      # somebody else
C = "0x" + "c3" * 20      # a counterparty

OWN = {"Authorization": "Bearer 0xOWN_SESSION"}        # a SIWE session for A
APPLE = {"Authorization": "Bearer 0xAPPLE_SESSION"}    # an Apple session, no wallet linked
OPERATOR = {"Authorization": "Bearer k"}

#: route, the body a client sends, the operation it runs, the field naming who acts.
ROUTES = [
    ("/api/v1/agent/register", {"agent_type": "x", "capabilities": []},
     ("agent_identity", "register_agent"), "owner"),
    ("/api/v1/dao/create", {"name": "d", "config": {}}, ("dao_management", "create_dao"), "creator"),
    ("/api/v1/defi/loan/create", {"collateral_token": "ETH", "collateral_amount": 1,
                                  "borrow_token": "USDC", "borrow_amount": 1},
     ("defi", "create_loan"), "borrower"),
    ("/api/v1/dex/swap", {"token_in": "ETH", "token_out": "USDC", "amount_in": 1}, ("dex", "swap"), "trader"),
    ("/api/v1/dispute/claim", {"dispute_id": "d1"}, ("dispute_resolution", "claim"), "claimant"),
    ("/api/v1/dispute/file", {"respondent": C, "dispute_type": "x", "description": "y"},
     ("dispute_resolution", "file_dispute"), "complainant"),
    ("/api/v1/dispute/vote", {"dispute_id": "d1", "vote": "for"}, ("dispute_resolution", "vote"), "juror"),
    ("/api/v1/fundraising/campaign/create", {"title": "t", "description": "d", "goal": 1, "milestones": []},
     ("fundraising", "create_campaign"), "creator"),
    ("/api/v1/fundraising/contribute", {"campaign_id": "c", "amount": 1},
     ("fundraising", "contribute"), "contributor"),
    ("/api/v1/gaming/register", {"game_data": {}}, ("gaming", "register_game"), "developer"),
    ("/api/v1/governance/proposal/create", {"title": "t", "description": "d"},
     ("governance", "create_proposal"), "proposer"),
    ("/api/v1/groups", {"name": "g"}, ("social", "create_community"), "creator"),
    ("/api/v1/identity/create", {}, ("did_identity", "create_did"), "owner"),
    ("/api/v1/identity/did/create", {}, ("did_identity", "create_did"), "owner"),
    ("/api/v1/insurance/policy/create", {"policy_type": "x", "coverage_amount": 1, "premium": 1},
     ("insurance", "create_policy"), "holder"),
    ("/api/v1/ip/register", {"ip_type": "x", "metadata": {}}, ("ip_royalties", "register_ip"), "creator"),
    ("/api/v1/licensing/ip", {"type": "x", "name": "n"}, ("ip_royalties", "register_ip"), "owner"),
    ("/api/v1/loyalty/redeem", {"points": 1, "reward_type": "x"}, ("loyalty", "redeem_points"), "user"),
    ("/api/v1/marketplace/buy", {"listing_id": "l"}, ("marketplace", "buy_item"), "buyer"),
    ("/api/v1/marketplace/list", {"item_type": "nft", "metadata": {}, "price": 1},
     ("marketplace", "list_item"), "seller"),
    ("/api/v1/nft/mint", {"collection_id": "c", "metadata": {}}, ("nft_services", "mint"), "creator"),
    ("/api/v1/payments/create", {"payee": C, "amount": 1, "token": "USDC", "purpose": "p"},
     ("x402_payments", "create_payment"), "payer"),
    ("/api/v1/rwa/tokenize", {"asset_type": "x", "asset_data": {}}, ("rwa_tokenization", "tokenize_asset"), "owner"),
    ("/api/v1/securities/create", {"name": "n", "security_type": "x", "total_supply": 1},
     ("securities_exchange", "create_security"), "issuer"),
    ("/api/v1/social/post", {"content": "c"}, ("social", "create_post"), "author"),
    ("/api/v1/staking/stake", {"token": "ETH", "amount": 1}, ("staking", "stake"), "staker"),
    ("/api/v1/staking/unstake", {"token": "ETH", "amount": 1}, ("staking", "unstake"), "staker"),
    ("/api/v1/subscriptions/subscribe", {"plan_id": "p", "payment_token": "USDC"},
     ("subscriptions", "subscribe"), "user"),
    ("/api/v1/supply-chain/register", {"product_data": {}}, ("supply_chain", "register_product"), "manufacturer"),
]
CASES = [pytest.param(r, b, p, f, id=r) for r, b, p, f in ROUTES]


class _Recorder:
    """Every service method the funnel reaches, under any name."""

    def __init__(self, service, calls):
        self._service, self._calls = service, calls

    def __getattr__(self, method):
        async def _run(**kwargs):
            self._calls.append((self._service, method, kwargs))
            return {"status": "ok", "recorded_by": "the test"}
        return _run


@pytest.fixture
def reached(monkeypatch):
    """What reached a service: through the /api/v1 funnel (the registry) or a
    dispatcher (ServiceDispatcher.execute), under a gate that allows everything,
    so a refusal can only be the door's."""
    from runtime.blockchain.services.registry import ServiceRegistry
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    calls: list = []

    class _Allow:
        async def initialize(self):
            return None

        async def evaluate(self, action, context):
            return {"allow": True}

    def get(self, name):
        return _Recorder(name, calls)

    async def execute(self, action, service=None, params=None, **kwargs):
        calls.append(("dispatch", action, dict(params or {})))
        return json.dumps({"status": "ok", "result": {"status": "recorded by the test"}})

    monkeypatch.setattr(ServiceRegistry, "get", get)
    monkeypatch.setattr(ServiceDispatcher, "execute", execute)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    return calls


async def _sessions(server):
    now = time.time()
    await server.wallet_sessions.add(token="0xOWN_SESSION", address=A,
                                     issued_at=now, expires_at=now + 3600)
    await server.wallet_sessions.add(token="0xAPPLE_SESSION", address="apple:sub",
                                     issued_at=now, expires_at=now + 3600)


@pytest.mark.parametrize("route, body, pair, field", CASES)
async def test_a_session_naming_somebody_else_reaches_no_service(reached, tmp_path, route, body, pair, field):
    """[control] Another address, as a SIWE session and as an Apple session
    with no wallet linked: refused at the funnel, before the service runs."""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _sessions(server)
        for headers in (OWN, APPLE):
            resp = await client.post(route, headers=headers, json={**body, field: B})
            assert resp.status == 403, (headers, resp.status, await resp.text())
    assert reached == [], f"{route} ran {reached}"


@pytest.mark.parametrize("route, body, pair, field", CASES)
async def test_a_session_naming_itself_reaches_the_service(reached, tmp_path, route, body, pair, field):
    """[guard] Its own address, in another spelling of it too, passes the door."""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _sessions(server)
        for own in (A, A.upper().replace("0X", "0x")):
            resp = await client.post(route, headers=OWN, json={**body, field: own})
            assert resp.status not in (401, 403), (own, resp.status, await resp.text())
    assert [c[:2] for c in reached] == [pair, pair], reached


@pytest.mark.parametrize("route, body, pair, field", CASES)
async def test_the_operator_still_names_the_party_it_acts_for(reached, tmp_path, route, body, pair, field):
    """[guard] The operator key is not held to an identity of its own."""
    from aiohttp.test_utils import TestClient, TestServer

    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(route, headers=OPERATOR, json={**body, field: B})
        assert resp.status not in (401, 403), (resp.status, await resp.text())
    assert [c[:2] for c in reached] == [pair], reached


#: The field naming who acts, as each operation's method takes it (a route may
#: read it from the body under another name: a dispute's ``complainant`` is the
#: method's ``claimant``, a payment's ``payer`` its ``agent_id``).
METHOD_FIELD = {pair: field for _r, _b, pair, field in ROUTES}
METHOD_FIELD.update({("dispute_resolution", "file_dispute"): "claimant",
                     ("x402_payments", "create_payment"): "agent_id"})


def _actions():
    """One dispatchable action for each operation above, with its field."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    out = {}
    for action, pair in sorted(ACTION_MAP.items()):
        if pair in METHOD_FIELD and pair not in out.values():
            out[action] = pair
    return {a: METHOD_FIELD[p] for a, p in out.items()}


def test_every_operation_here_is_held_by_the_table():
    """The table holds every operation the routes above run, under the
    method's own name for the field."""
    from runtime.access_policy import SESSION_ACTS_AS
    missing = {p: f for p, f in METHOD_FIELD.items() if f not in SESSION_ACTS_AS.get(p, ())}
    assert missing == {}, missing
    assert _actions(), "precondition: some action runs a held operation"


@pytest.mark.parametrize("action", sorted(_actions()))
async def test_no_dispatcher_runs_a_held_operation_for_somebody_else(reached, tmp_path, action):
    """[control] /bridge/v1/action, capability invoke and Trinity's
    request_execution: another address, no address and an Apple session with
    no wallet are refused; the session's own address is dispatched."""
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.session_routes import session_refused_route
    from runtime.tools.dispatcher import ToolDispatcher
    field = _actions()[action]
    # An action whose own route a session is refused stays refused whatever it
    # names (social.create_community behind /api/v1/social/community/create).
    kept = not session_refused_route(action)
    server = signing._server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _sessions(server)
        for headers, params in ((OWN, {field: B}), (OWN, {}), (APPLE, {field: A})):
            resp = await client.post("/bridge/v1/action", headers=headers,
                                     json={"action": action, "params": params, "session_id": "s1"})
            assert resp.status == 403, ("bridge", params, resp.status, await resp.text())
            resp = await client.post(f"/api/v1/capabilities/{action}/invoke", headers=headers,
                                     json={"params": params})
            assert resp.status in (403, 404), ("invoke", params, resp.status, await resp.text())
        assert reached == [], reached
        resp = await client.post("/bridge/v1/action", headers=OWN,
                                 json={"action": action, "params": {field: A}, "session_id": "s1"})
        assert resp.status == (200 if kept else 403), (resp.status, await resp.text())
    assert [c[1] for c in reached] == ([action] if kept else [])
    chat = ToolDispatcher({"workspace": "."})
    out = await chat.dispatch("request_execution", {"action": action, "params": {field: B}},
                              agent_name="trinity", caller_identity=A, caller_kind="session")
    assert out.ok is False and "[DENIED]" in out.model_text, out.model_text
    out = await chat.dispatch("request_execution", {"action": action, "params": {field: A}},
                              agent_name="trinity", caller_identity=A, caller_kind="session")
    assert ("[DENIED]" in out.model_text) is not kept, out.model_text
    assert [c[1] for c in reached] == ([action, action] if kept else [])
