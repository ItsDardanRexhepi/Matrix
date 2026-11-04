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

#: The state-changing operations a session reaches only through the
#: dispatchers (no route of theirs is on the session allowlist), with the
#: method's parameter naming who acts. The first fix held the 29 routes'
#: operations and left these: a session cancelled another user's listing and
#: subscription, rewrote their profile and posted under their name through
#: /bridge/v1/action and capability invoke.
DISPATCHED = {
    ("agent_identity", "sell_training_data"): "seller",
    ("agent_identity", "trade_model_access"): "seller",
    ("brand_rewards", "distribute_reward"): "user",
    ("cashback", "claim_cashback"): "user",
    ("cross_border", "bridge_transfer"): "sender",
    ("dao_management", "join_dao"): "member",
    ("dao_management", "leave_dao"): "member",
    ("dex", "remove_liquidity"): "provider",
    ("dispute_resolution", "request_arbitration"): "claimant",
    ("fundraising", "buy_carbon_credit"): "buyer",
    ("fundraising", "buy_renewable_cert"): "buyer",
    ("fundraising", "invest_green_bond"): "investor",
    ("fundraising", "retire_carbon_credit"): "holder",
    ("gaming", "attest_achievement"): "player",
    ("gaming", "create_prediction_market"): "creator",
    ("gaming", "enter_tournament"): "player",
    ("gaming", "mint_game_asset"): "player",
    ("gaming", "trade_item"): "seller",
    ("governance", "approve_multisig"): "signer",
    ("governance", "parameter_change"): "proposer",
    ("governance", "propose_multisig"): "proposer",
    ("marketplace", "cancel_listing"): "seller",
    ("nft_services", "mint_soulbound"): "issuer",
    ("nft_services", "process_sale"): "buyer",
    ("privacy", "generate_zk_proof"): "prover",
    ("rwa_tokenization", "claim_income"): "holder",
    ("rwa_tokenization", "fractional_buy"): "buyer",
    ("securities_exchange", "buy"): "buyer",
    ("securities_exchange", "sell"): "seller",
    ("social", "create_token_gate"): "creator",
    ("social", "follow_wallet"): "follower",
    ("social", "publish_post"): "author",
    ("social", "send_encrypted_message"): "sender",
    ("social", "setup_monetization"): "creator",
    ("social", "update_profile"): "address",
    ("staking", "claim_rewards"): "staker",
    ("subscriptions", "cancel"): "user",
    ("subscriptions", "create_plan"): "provider",
}
HELD = {**METHOD_FIELD, **DISPATCHED}

#: Operations whose acting party is not a parameter: the method holds a
#: dispatched call to the record's owner on the ``caller_identity`` the
#: dispatcher threads (the owner field of the record it reads).
BOUND_BY_THE_METHOD = {
    ("agent_identity", "deregister_agent"): "owner",
    ("agent_identity", "update_agent"): "owner",
    ("insurance", "cancel_policy"): "holder",
    ("insurance", "file_claim"): "holder",
    ("insurance", "renew_coverage"): "holder",
    ("ip_royalties", "grant_license"): "owner",
    ("ip_royalties", "license_ip"): "owner",
    ("nft_services", "configure_royalty"): "the party that configured it",
}

#: Parameters that name who an operation is addressed to, not who acts, and
#: stay as the request writes them.
COUNTERPARTIES = {
    ("dispute_resolution", "file_dispute"): {"respondent"},
    ("x402_payments", "create_payment"): {"recipient"},
    ("agent_identity", "sell_training_data"): {"buyer"},
    ("agent_identity", "trade_model_access"): {"buyer"},
    ("cross_border", "bridge_transfer"): {"recipient"},
    ("dispute_resolution", "request_arbitration"): {"respondent"},
    ("gaming", "trade_item"): {"buyer"},
    ("insurance", "cancel_policy"): {"caller"},
    ("insurance", "file_claim"): {"caller"},
    ("insurance", "renew_coverage"): {"caller"},
    ("ip_royalties", "grant_license"): {"licensee"},
    ("ip_royalties", "license_ip"): {"licensee"},
    ("nft_services", "configure_royalty"): {"recipient"},
    ("nft_services", "mint_soulbound"): {"recipient"},
    ("nft_services", "process_sale"): {"seller"},
    ("social", "follow_wallet"): {"target"},
    ("social", "send_encrypted_message"): {"recipient"},
}

#: Words a method names an acting or addressed party by.
ACTOR_WORDS = frozenset({
    "owner", "creator", "user", "seller", "buyer", "staker", "sender", "from", "from_address",
    "holder", "author", "wallet", "account", "address", "trader", "voter", "contributor",
    "provider", "borrower", "lender", "issuer", "claimant", "juror", "prover", "developer",
    "manufacturer", "agent_id", "payer", "subscriber", "member", "depositor", "investor",
    "delegator", "delegate", "proposer", "participant", "player", "recipient", "to",
    "user_address", "wallet_address", "caller", "actor", "operator", "renter", "licensee",
    "licensor", "bidder", "follower", "voter_address", "beneficiary", "customer", "merchant",
    "minter", "signer", "initiator", "requester", "respondent", "target",
})


def _actions():
    """One dispatchable action for each operation above, with its field."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    out = {}
    for action, pair in sorted(ACTION_MAP.items()):
        if pair in HELD and pair not in out.values():
            out[action] = pair
    return {a: HELD[p] for a, p in out.items()}


def test_every_operation_here_is_held_by_the_table():
    """The table holds every operation the routes above run and every
    dispatched one, under the method's own name for the field."""
    from runtime.access_policy import SESSION_ACTS_AS
    missing = {p: f for p, f in HELD.items() if f not in SESSION_ACTS_AS.get(p, ())}
    assert missing == {}, missing
    assert _actions(), "precondition: some action runs a held operation"


def _method(pair):
    import importlib
    import inspect

    from runtime.blockchain.services import registry as reg
    table = next(v for name in dir(reg) for v in [getattr(reg, name)]
                 if isinstance(v, dict) and v
                 and all(isinstance(k, str) and isinstance(x, tuple) for k, x in v.items()))
    modpath, cls = table[pair[0]]
    fn = getattr(getattr(importlib.import_module(modpath, package=reg._PACKAGE), cls), pair[1], None)
    return fn, (set(inspect.signature(fn).parameters) if fn else set())


def test_every_state_change_a_session_may_dispatch_names_who_acts():
    """[control] Every state-changing operation a session may dispatch whose
    method names a party is held: by the table, under that parameter, or by
    the method itself on the dispatcher's ``caller_identity``; a party the
    operation is addressed to is listed as such. At the previous commit 42
    pairs were none of these."""
    from gateway.session_routes import session_refused_route
    from runtime import access_policy as ap
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP, _STATE_MODIFYING_ACTIONS
    refused = (set(ap.REFUSED_TO_A_SESSION) | set(ap.REFUSED_ON_REQUEST) | set(ap.HANDS_THE_CALL_TO)
               | set(ap.BOUND_TO_THE_CALLER) | set(ap.HELD_FOR_A_SESSION))
    unbound, seen = {}, set()
    for action in sorted(_STATE_MODIFYING_ACTIONS):
        pair = ACTION_MAP.get(action)
        if pair is None or pair in seen or pair in refused or session_refused_route(action):
            continue
        seen.add(pair)
        fn, params = _method(pair)
        if fn is None:
            continue
        named = params & ACTOR_WORDS
        by_table = set(ap.SESSION_ACTS_AS.get(pair, ()))
        by_method = "caller_identity" in params and pair in BOUND_BY_THE_METHOD
        free = COUNTERPARTIES.get(pair, set())
        left = named - by_table - free - ({"caller_identity"} if by_method else set())
        if left and not by_method:
            unbound[pair] = sorted(left)
        assert not by_table or by_table & params, (pair, by_table, params)
        assert free <= params, (pair, free - params)
    assert unbound == {}, unbound
    for pair in BOUND_BY_THE_METHOD:
        _fn, params = _method(pair)
        assert "caller_identity" in params, pair


OWNED_BY_B = {"agent_id": "ag_1", "did": "did:x:1", "owner": B, "status": "active",
              "agent_name": "n", "capabilities": [], "metadata": {}, "registered_at": 1,
              "updated_at": 1, "version": 1, "erc_standard": "ERC-8004", "network": "test"}


def _agents():
    from runtime.blockchain.services.agent_identity.service import AgentIdentityService
    svc = AgentIdentityService({})
    svc._agents["ag_1"] = dict(OWNED_BY_B)
    return svc


@pytest.mark.parametrize("method, params", [
    ("update_agent", {"updates": {"metadata": {"v": 2}}}),
    ("deregister_agent", {}),
])
async def test_an_agent_is_changed_only_by_its_owner(method, params):
    """[control] A dispatched call by another identity, or by none, is refused
    and changes nothing; the owner's goes through; the platform's own call
    (no caller behind it) is unchanged."""
    for identity in (A, ""):
        svc = _agents()
        out = await getattr(svc, method)("ag_1", **params, caller_identity=identity,
                                         caller_source="authenticated")
        assert out.get("error_category") == "forbidden", out
        assert svc._agents["ag_1"] == OWNED_BY_B
    svc = _agents()
    out = await getattr(svc, method)("ag_1", **params, caller_identity=B.upper().replace("0X", "0x"),
                                     caller_source="authenticated")
    assert out.get("error_category") != "forbidden", out
    svc = _agents()
    out = await getattr(svc, method)("ag_1", **params)
    assert out.get("error_category") != "forbidden", out


class _Registry:
    def __init__(self, record):
        self.record = record

    async def get(self, ip_id):
        return self.record


def _ip():
    from types import SimpleNamespace

    from runtime.blockchain.services.ip_royalties.service import IPRoyaltyService
    svc = IPRoyaltyService({})
    svc._registry = _Registry({"ip_id": "ip_1", "owner": B, "ip_type": "patent", "title": "t"})
    svc._web3 = SimpleNamespace(available=True, is_placeholder=lambda _c: False)
    svc._ip_registry_contract = "0x" + "11" * 20
    return svc


@pytest.mark.parametrize("method, params", [
    ("license_ip", {"terms": {"license_type": "non_exclusive"}}),
    ("grant_license", {}),
])
async def test_a_license_is_the_owners_to_grant(method, params):
    """[control] Through a dispatcher or the licensing route, a caller other
    than the IP's owner, or none, is refused before a license is recorded; the
    owner grants; the platform's own call is unchanged."""
    from runtime.blockchain.services.ownership import OwnershipError
    for identity in (A, ""):
        svc = _ip()
        with pytest.raises(OwnershipError):
            await getattr(svc, method)("ip_1", C, **params, caller_identity=identity,
                                       caller_source="authenticated")
        assert svc._licenses == {}
    svc = _ip()
    out = await getattr(svc, method)("ip_1", C, **params, caller_identity=B, caller_source="route")
    assert out.get("licensee") == C and len(svc._licenses) == 1
    svc = _ip()
    out = await getattr(svc, method)("ip_1", C, **params)
    assert out.get("licensee") == C


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
