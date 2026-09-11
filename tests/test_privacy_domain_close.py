"""NEW-48 — privacy domain close: 3 delegations, 3 removals.

Every test here fails against the pre-fix bodies and passes after. The
delegation tests assert POSITIVE PROOF that the real twin runs — not merely
that the fabrication is gone — because the domain's central lesson is that the
presence of real code says nothing about what actually executes.

THE FABRICATIONS, for the record:

    decentralized_store  cid = f"bafy{uuid4().hex[:48]}"     status "stored"
    pin_to_ipfs          cid = f"Qm{uuid4().hex[:44]}"       status "pinned"
    submit_compute_job   id  = f"cjob_{uuid4().hex[:16]}"    status "submitted"
    private_vote         choice_hash = random, choice DISCARDED, no tally
    confidential_compute result_hash = random, nothing computed
    store_on_arweave     arweave_tx  = f"ar_{uuid4().hex}"   nothing uploaded

None of them contacted a provider. Each built a dict and returned it.

WHY THE DELEGATION PROOF LOOKS LIKE IT DOES: with no credentials configured
(the state of any test checkout), the real clients return the canonical
not-deployed response naming the exact missing config key —
`services.storage.filecoin_api_key`, `services.compute.*`. That string is
producible ONLY by the real client. A fabrication cannot emit it, and neither
can an empty stub. So asserting on it is positive proof that control reached
`StorageService` / `ComputeService`, which is precisely what a
"the fake is gone" assertion would fail to establish.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from runtime.blockchain.services.privacy.service import PrivacyService


def _claims_fabricated_success(payload: object) -> list[str]:
    """Every way a payload claims work that was never done."""
    if not isinstance(payload, dict):
        raise TypeError(
            f"needs a dict, got {type(payload).__name__} — parse the envelope "
            "first. ServiceDispatcher.execute returns a JSON STRING, and "
            "asserting on it unparsed is vacuous (this has bitten twice)."
        )
    claims = []
    if payload.get("status") in ("stored", "pinned", "submitted", "cast", "completed", "ok"):
        claims.append(f"status={payload['status']!r}")
    for key in ("cid", "arweave_tx", "choice_hash", "result_hash"):
        if payload.get(key):
            claims.append(f"{key}={payload[key]!r}")
    return claims


def _dispatch(raw: object) -> dict:
    """Parse ServiceDispatcher.execute's JSON-string envelope."""
    assert isinstance(raw, str), (
        f"dispatcher.execute returned {type(raw).__name__}; expected a JSON "
        "string. Shape changed — these assertions no longer look at what they "
        "think they do."
    )
    env = json.loads(raw)
    assert isinstance(env, dict)
    return env


# ── DELEGATIONS: positive proof the real twin runs ─────────────────────────


@pytest.mark.parametrize(
    "method,kwargs,missing_key",
    [
        ("decentralized_store", {"uploader": "0xA", "content": "hello"},
         "services.storage.filecoin_api_key"),
        ("pin_to_ipfs", {"uploader": "0xA", "content": "hello"},
         "services.storage.filecoin_api_key"),
    ],
)
async def test_storage_delegation_reaches_the_real_client(method, kwargs, missing_key):
    """The call lands in StorageService, proven by its credential-gate string.

    `not_deployed_response(..., extra={"missing": "services.storage.
    filecoin_api_key"})` is emitted only by StorageService._gate. Neither the
    old fabrication nor a stub can produce it.
    """
    svc = PrivacyService({})
    result = await getattr(svc, method)(**kwargs)

    assert result["status"] == "not_deployed", f"did not reach the real client: {result!r}"
    assert result["missing"] == missing_key, (
        f"reached something, but not the Filecoin client: {result!r}"
    )
    assert result["delegated_to"] == "storage.store_filecoin"
    assert not _claims_fabricated_success(result)
    # The fabricated CID shapes must be absent.
    assert "cid" not in result or not str(result.get("cid", "")).startswith(("bafy", "Qm"))


async def test_compute_delegation_reaches_the_real_client():
    svc = PrivacyService({})
    result = await svc.submit_compute_job(requester="0xA", job_type="render")

    assert result["status"] == "not_deployed", f"did not reach ComputeService: {result!r}"
    assert result["delegated_to"] == "compute.submit_compute_job"
    assert "compute" in str(result.get("missing", "")).lower() or result.get("service") == "compute"
    assert not _claims_fabricated_success(result)
    assert not str(result.get("id", "")).startswith("cjob_")


async def test_storage_delegation_is_actually_invoked_not_just_shaped():
    """Strongest form: intercept the twin and prove it was called.

    A response that merely *looks* like the gate response could be
    hand-written. This replaces the real method with a probe and asserts the
    delegation calls it with the caller's bytes.
    """
    svc = PrivacyService({})
    calls = []

    class _Probe:
        async def store_filecoin(self, **params):
            calls.append(params)
            return {"status": "ok", "Hash": "bafyREAL", "Name": "x", "Size": "5"}

    svc._storage_svc = _Probe()
    result = await svc.decentralized_store(uploader="0xA", content="hello")

    assert len(calls) == 1, f"the real client was NOT called: {calls!r}"
    assert calls[0]["content"] == "hello", "the caller's bytes were not forwarded"
    assert result["Hash"] == "bafyREAL", "the twin's real output was not returned"


async def test_delegation_refuses_without_content_instead_of_inventing_it():
    """A data_hash alone cannot be uploaded — the honest answer says so.

    The old signature accepted only `data_hash`, which is the tell: you cannot
    upload a hash. Rather than synthesise bytes, the delegation refuses.
    """
    svc = PrivacyService({})
    result = await svc.pin_to_ipfs(uploader="0xA", data_hash="0xdeadbeef")

    assert result["status"] == "not_deployed"
    assert "content" in result["error"]
    assert not _claims_fabricated_success(result)


# ── REMOVALS: no path obtains a success-shaped result ──────────────────────


@pytest.mark.parametrize("method", ["private_vote", "confidential_compute", "store_on_arweave"])
def test_removed_methods_are_gone_from_the_service(method):
    assert not hasattr(PrivacyService, method), (
        f"{method} still exists on PrivacyService — a caller can still reach it"
    )


@pytest.mark.parametrize("action", ["private_vote", "confidential_compute", "arweave_store"])
def test_removed_actions_are_not_dispatchable(action):
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP,
        ACTION_TO_FEED_EVENT,
        _STATE_MODIFYING_ACTIONS,
    )

    assert action not in ACTION_MAP, "still routable via platform_action"
    assert action not in _STATE_MODIFYING_ACTIONS
    assert action not in ACTION_TO_FEED_EVENT, (
        "still emits a feed event — the platform would broadcast an action "
        "that cannot happen"
    )


@pytest.mark.parametrize("action", ["private_vote", "confidential_compute", "arweave_store"])
async def test_dispatching_a_removed_action_fails(action):
    """Drive the dispatcher the way the tool surface does, and parse first."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    env = _dispatch(await ServiceDispatcher({}).execute(action=action, params={}))

    assert env["status"] == "error", f"{action} still works: {env!r}"
    assert "unknown action" in env["error"].lower()


@pytest.mark.parametrize("cap_id", ["private_vote", "confidential_compute", "arweave_store"])
def test_removed_capabilities_are_not_advertised(cap_id):
    from runtime.capabilities import catalog

    assert catalog.get_by_id(cap_id) is None


@pytest.mark.parametrize("action", ["private_vote", "confidential_compute", "arweave_store"])
def test_the_model_is_not_told_removed_actions_work(action):
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    guide = INTENT_ACTION_MAP[action]
    assert guide.get("unavailable") is True
    assert "action_name" not in guide, "the model can still dispatch it"
    assert "NOT AVAILABLE" in guide["description"]
    assert guide["keywords"], "keywords dropped — the request now matches nothing"


# ── HTTP surface ───────────────────────────────────────────────────────────


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_arweave_route_answers_501_and_stores_nothing(client):
    resp = await client.post(
        "/api/v1/compute/arweave/store",
        json={"owner": "0xabc", "data": "0xpayload", "content_type": "image/png"},
    )
    assert resp.status == 501, f"expected 501, got {resp.status}"
    body = await resp.json()
    assert not _claims_fabricated_success(body.get("data", {}))
    assert "arweave_tx" not in json.dumps(body)


@pytest.mark.parametrize(
    "path,body",
    [
        # Bodies satisfy each handler's OWN _require list, read from the
        # handler. The first draft sent one generic body to both; each route
        # 400'd on a missing required field before reaching the fabrication,
        # so both assertions passed against the pre-fix code for free — a
        # vacuous pass in the file whose subject is vacuous success.
        ("/api/v1/compute/store",
         {"owner": "0xabc", "data": "0xpayload", "storage_type": "ipfs", "content": "hello"}),
        ("/api/v1/compute/ipfs/pin",
         {"cid": "0xpayload", "owner": "0xabc", "content": "hello"}),
    ],
)
async def test_storage_routes_no_longer_return_a_fabricated_cid(client, path, body):
    """The route is kept and now reaches the real client through the seam."""
    resp = await client.post(path, json=body)
    payload = await resp.json()
    blob = json.dumps(payload)

    # Guard against the vacuity above: the request must actually be accepted.
    assert resp.status != 400, (
        f"{path} rejected the body before reaching the handler — this test "
        f"would pass without proving anything: {blob[:200]}"
    )
    assert "bafy" not in blob, f"fabricated Filecoin CID still returned: {blob[:200]}"
    assert '"cid": "Qm' not in blob, f"fabricated IPFS CID still returned: {blob[:200]}"
    # Positive proof the real client was reached, not merely that the fake left.
    assert "filecoin_api_key" in blob or "not_deployed" in blob, (
        f"no evidence the real storage client ran: {blob[:300]}"
    )
