"""`_maybe_ripple`'s docstring says "Reads never ripple." Three reads rippled.

The ripple publisher skips a call whose method name starts with an unambiguous
read prefix — `get_`, `list_`, `fetch_`, `is_`, and so on. `verify_` is
deliberately NOT one of them, and for a good reason: `verify_milestone` is a
consequential write. The consequence is that the verbs which are reads in this
codebase slip through, and three of them are bound to HTTP routes:

* `attestation.verify` — reads EAS through `EASClient.verify` and mutates
  nothing;
* `supply_chain.verify_authenticity` — reads `self._provenance` and returns a
  record it does not store;
* `did_identity.verify_credential` — looks the credential up in the vault and
  checks it.

All three return a dict, so the list-result guard does not catch them either,
and `feed.ripple` went out to the public `/api/v1/events/stream` carrying the
`ref` the caller asked about — an attestation uid, a product id, a credential
id — announcing a lookup as an action somebody took.

The caller-side comment carried its own stale claim: "Reached ONLY after a real
result, so an honest failure (which raised above) never ripples." `_maybe_ripple`
is reached for every value `_call` returns, refusals included; it is
`_maybe_ripple` itself that drops them, by reading the payload, and its own
docstring already says so four lines further down.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")

from gateway.service_routes import ServiceRoutes  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402


class _Spy:
    """Stands in for the broadcaster and records what would have gone out."""

    def __init__(self) -> None:
        self.published: list[tuple] = []

    def publish_dict(self, *args, **kwargs):
        self.published.append((args, kwargs))

    def attach_metrics(self, *_a, **_k):
        pass


@pytest.fixture
def routes_and_spy():
    routes = ServiceRoutes(SWEEP_CONFIG)
    spy = _Spy()
    routes._broadcaster = spy
    return routes, spy


READS = [
    ("attestation", "verify", {"attestation_uid": "0xuid"},
     {"uid": "0xuid", "verified": True, "schema": "0xschema"}),
    ("supply_chain", "verify_authenticity", {"product_id": "prod-1"},
     {"id": "auth_1", "status": "verified", "authentic": True}),
    ("did_identity", "verify_credential", {"credential_id": "cred-1"},
     {"id": "cred-1", "valid": True, "status": "verified"}),
]


@pytest.mark.parametrize("service,method,kwargs,result", READS,
                         ids=[f"{s}.{m}" for s, m, _, _ in READS])
def test_a_read_does_not_announce_itself_as_an_action(
        routes_and_spy, service, method, kwargs, result):
    routes, spy = routes_and_spy
    routes._maybe_ripple(service, method, kwargs, result)
    assert spy.published == [], (
        f"{service}.{method} reads and mutates nothing, and it published a "
        f"feed.ripple to the public event stream: {spy.published}")


def test_a_write_that_shares_the_verb_still_ripples(routes_and_spy):
    """The direction this must not move.

    `verify_` is not a read prefix because `verify_milestone`,
    `verify_buyer` and `snapshot_vote` are writes. Naming three operations as
    reads must not turn the verb into one.
    """
    routes, spy = routes_and_spy
    routes._maybe_ripple("real_estate", "verify_buyer",
                         {"wallet": "0xabc"}, {"status": "verified"})
    assert spy.published, "a consequential write stopped rippling"


def test_a_refusal_still_does_not_ripple(routes_and_spy):
    routes, spy = routes_and_spy
    routes._maybe_ripple("nft_services", "mint", {"owner": "0xabc"},
                         {"status": "not_deployed"})
    assert spy.published == []


def test_an_ordinary_write_still_ripples(routes_and_spy):
    routes, spy = routes_and_spy
    routes._maybe_ripple("nft_services", "mint", {"owner": "0xabc"},
                         {"status": "ok", "token_id": 7})
    assert spy.published, "the ripple stopped working"


def test_the_named_reads_are_reads_in_the_source():
    """Each entry names a method that mutates nothing — checked, not asserted."""
    import inspect

    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.services.did_identity.service import DIDService
    from runtime.blockchain.services.supply_chain.service import SupplyChainService

    for cls, name in ((AttestationService, "verify"),
                      (SupplyChainService, "verify_authenticity"),
                      (DIDService, "verify_credential")):
        body = inspect.getsource(getattr(cls, name))
        for mutation in ("self._provenance[", "self._credentials[",
                         ".append(", "send_raw_transaction", "sign_transaction"):
            assert mutation not in body, (
                f"{cls.__name__}.{name} is on the read list and mutates: {mutation}")


def test_the_caller_comment_does_not_claim_the_filtering_happens_above_it():
    import inspect

    src = inspect.getsource(ServiceRoutes._call)
    i = src.find("which raised above")
    if i != -1:
        assert "This said" in src[max(0, i - 400):i], (
            "_call still asserts that an honest failure raised before this "
            "point; the refusals this codebase returns reach _maybe_ripple, "
            "which is what drops them")
    assert "reaches the next line" in src, (
        "the comment does not say where the refusal filtering actually happens")
