"""DOMAIN 21 — creator_platforms mints tokens and publishes to third-party
platforms with the PLATFORM'S OWN credentials.

Like domain 20's carbon retirement, the counterparty for these records is
outside the platform. A minted token and a permanent Arweave entry are
representations other people rely on, and stopping new false ones does not
retract the old.

21-A  `services.creator_platforms.enabled` had ZERO READERS while the shipped
      example config writes it `false`. Measured at 3ff5a029: 42 of 44 services
      have that key with zero readers; 13 are set false by the example. All
      three actions are in ACTION_MAP and _STATE_MODIFYING_ACTIONS, and
      `available=False` in catalog.py does not unreach them.
21-B  The caller picked which contract the platform paymaster signed against,
      and named the byline and target publication.
21-C  "minted" was returned on broadcast alone; "published" on any 2xx without
      reading whether the gateway named anything; and a fault AFTER the request
      reached the third party returned the CREDENTIAL-GATED refusal shape.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.creator_platforms._guards import (
    publish_unknown,
    require_creator_platforms_enabled,
    resolve_attributed_party,
    resolve_edition_address,
    settle_publish,
)
from runtime.blockchain.services.creator_platforms.service import (
    CreatorPlatformsService,
)
from runtime.blockchain.services.service_dispatcher import _outcome_is_real

_CREDS = {
    "sound_edition_address": "0xLEGIT_OPERATOR_EDITION",
    "mirror_api_key": "k", "mirror_author": "operator",
    "paragraph_api_key": "k", "paragraph_publication": "operator-pub",
}


def _cfg(enabled):
    body = dict(_CREDS)
    if enabled is not None:
        body["enabled"] = enabled
    return {"services": {"creator_platforms": body}}


_METHODS = ["mint_sound", "publish_mirror_post", "publish_paragraph_post"]


# ─────────────────────────────── 21-A ───────────────────────────────

@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.parametrize("enabled", [False, None, "true", 1, "yes"])
@pytest.mark.asyncio
async def test_every_action_refuses_unless_enabled_is_exactly_true(method, enabled):
    """THE REPRODUCTION: the shipped example config sets `false` and nothing
    read it. Fails CLOSED — absent means refuse, and only the boolean True
    opts in (the string "true" and the int 1 are not an operator decision)."""
    svc = CreatorPlatformsService(_cfg(enabled))
    out = await getattr(svc, method)(title="t", body="b")
    assert "enabled must be set to true" in str(out.get("missing", ""))
    assert _outcome_is_real(out) is False


@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.asyncio
async def test_the_gate_lets_an_opted_in_operator_through(method):
    """§AQ's other direction: a gate that refuses valid callers is its own
    defect. Proven by reaching a DIFFERENT refusal — the credential gate —
    which also proves the harness reaches the code under test."""
    svc = CreatorPlatformsService(_cfg(True))
    out = await getattr(svc, method)(title="t", body="b")
    assert "enabled must be set to true" not in str(out.get("missing", ""))


def test_the_gate_is_registered_under_a_domain_qualified_name():
    """A short name would sweep in every unrelated `_require_enabled` — the
    measured false positive that manufactured two findings in domain 19."""
    from tests import refusal_primitives
    assert "require_creator_platforms_enabled" in refusal_primitives.REFUSAL_PRIMITIVES
    assert "require_enabled" not in refusal_primitives.REFUSAL_PRIMITIVES


# ─────────────────────────────── 21-B ───────────────────────────────

def test_a_caller_cannot_choose_the_contract_the_platform_signs_against():
    """Seven census lenses reached this independently. The value was ALSO the
    branch selector, so accepting it switched on on-chain signing for an
    operator who had configured API access only."""
    with pytest.raises(PermissionError, match="not the operator-configured"):
        resolve_edition_address({"edition_address": "0xATTACKER"}, "0xLEGIT")


def test_a_caller_cannot_substitute_for_a_configured_edition():
    with pytest.raises(PermissionError):
        resolve_edition_address({"edition_address": "0xATTACKER"}, "0xLEGIT_OPERATOR")


def test_the_operator_configured_edition_is_what_is_returned():
    assert resolve_edition_address({}, "0xLEGIT") == "0xLEGIT"
    # Naming the SAME edition the operator configured is not an attack.
    assert resolve_edition_address({"edition_address": "0xLEGIT"}, "0xLEGIT") == "0xLEGIT"


@pytest.mark.parametrize("key,what", [("author", "author"), ("publication", "publication")])
def test_a_caller_cannot_name_the_byline_or_the_target_publication(key, what):
    """Mirror entries are PERMANENT ON ARWEAVE. Caller-supplied, this let one
    caller publish under another party's name, irreversibly, to readers who
    cannot see this platform's records."""
    with pytest.raises(PermissionError, match="not the operator-configured"):
        resolve_attributed_party({key: "victim"}, key, "operator", what)


@pytest.mark.asyncio
async def test_the_refusal_happens_before_anything_is_signed_or_sent():
    """A guard that refuses AFTER the external call has gone out is not a
    guard. 21-E changed this from RAISING to RETURNING — see
    test_a_hijack_attempt_is_recorded_as_a_refusal for why — so the assertion
    is now on the returned shape, and the guard still runs before any signing.
    """
    svc = CreatorPlatformsService(_cfg(True))
    out = await svc.mint_sound(edition_address="0xATTACKER", to="0xATTACKER",
                               quantity=999999)
    assert out.get("refused") is True
    assert "not the operator-configured" in str(out.get("reason", ""))
    assert "tx_hash" not in out, "a refusal must not carry evidence of a send"


# ─────────────────────────────── 21-C ───────────────────────────────

def test_a_confirmed_publish_keeps_its_audit_record():
    """BOTH DIRECTIONS. `_outcome_is_real`'s first clause is
    `settled is False or value_moved is False -> not real`, and it outranks
    everything. Stamping `value_moved: False` on a confirmed publish — true of
    money — would erase the record of a post that really exists. That is an
    under-claim manufactured inside the fix for under-claims."""
    rec = settle_publish(base={}, method="m", service_name="s",
                         id_value="ar_123", id_field="arweave_tx_id",
                         response_body={"id": "ar_123"})
    assert rec["status"] == "published"
    assert rec["settled"] is True
    assert "value_moved" not in rec
    assert _outcome_is_real(rec) is True


def test_a_2xx_that_names_nothing_is_not_a_confirmation():
    rec = settle_publish(base={}, method="m", service_name="s",
                         id_value=None, id_field="arweave_tx_id",
                         response_body={})
    assert rec["status"] == "pending"
    assert rec["settled"] is False
    assert rec["arweave_tx_id"] is None
    assert rec.get("disclosure")
    assert _outcome_is_real(rec) is False


def test_a_fault_after_dispatch_is_not_a_credential_refusal():
    """THE UNDER-CLAIM HALF, and the worse one. This returned the
    CREDENTIAL-GATED shape — telling an operator to configure an API key about
    a post that may be live on Arweave forever. An over-claim is visible to the
    claimant; an under-claim is visible to nobody."""
    rec = publish_unknown(base={}, endpoint="https://gw/tx",
                          exc=RuntimeError("read timeout"))
    assert rec["status"] == "pending"
    assert rec["dispatched"] is True
    assert rec["settled"] is False
    assert "may be live" in rec["disclosure"]
    assert "not_deployed" not in str(rec.get("status"))
    assert _outcome_is_real(rec) is False


def test_metadata_only_is_classified_and_is_not_an_outcome():
    """`mint_sound`'s off-chain path runs a GraphQL READ and mints nothing. It
    returned "ok" — a REAL-outcome status — under an action named
    `mint_sound`."""
    from runtime.blockchain.services.service_dispatcher import (
        _NON_OUTCOME_STATUSES, _REAL_OUTCOME_STATUSES,
    )
    assert "metadata_only" in _NON_OUTCOME_STATUSES
    assert "metadata_only" not in _REAL_OUTCOME_STATUSES
    assert _outcome_is_real({"status": "metadata_only", "settled": False}) is False


def test_the_mint_awaits_a_receipt():
    """19-C's lesson, fourth instance of the orphaned-real-mechanism pattern:
    `wait_for_receipt` existed on Web3Manager the whole time."""
    import inspect
    from runtime.blockchain.services.creator_platforms import service as mod
    src = inspect.getsource(mod.CreatorPlatformsService.mint_sound)
    assert "wait_for_receipt" in src
    assert '"status": "pending"' in src or "'status': 'pending'" in src


# ─────────────────────────────── 21-D ───────────────────────────────
# A defect in 21-A itself, found by driving the guard against hostile config
# shapes rather than reading it.

_MALFORMED = [
    ("services is a list", {"services": []}),
    ("services is a string", {"services": "x"}),
    ("service body is a string", {"services": {"creator_platforms": "on"}}),
    ("service body is a list", {"services": {"creator_platforms": [1]}}),
    ("config is not a dict", "nope"),
    ("config is None", None),
    ("services is None", {"services": None}),
    ("empty config", {}),
]


@pytest.mark.parametrize("label,cfg", _MALFORMED, ids=[m[0] for m in _MALFORMED])
def test_a_malformed_config_refuses_with_the_disclosure_and_never_raises(label, cfg):
    """MEASURED before 21-D: `services` as a string, or a service body that is
    a string or a list, produced `AttributeError: 'str' object has no attribute
    'get'`.

    That still failed closed in EFFECT — nothing minted — but it destroyed what
    the gate exists to deliver. 21-A's product is the DISCLOSURE naming the key
    to set; an operator with a malformed config got an opaque traceback
    instead. §AC at the guard layer: an AttributeError is indistinguishable
    from any other bug, so the one shape that tells the operator what to do is
    exactly the shape they do not get.
    """
    out = require_creator_platforms_enabled("creator_platforms", cfg, "mint_sound")
    assert out is not None, "a config we cannot read did not say enabled:true"
    assert "enabled must be set to true" in str(out.get("missing", ""))


@pytest.mark.parametrize("truthy", ["true", "True", 1, [1], {"a": 1}])
def test_only_the_boolean_true_opts_in(truthy):
    """Opting a token-minting service in is an operator decision, and a truthy
    value is not a decision."""
    cfg = {"services": {"creator_platforms": {"enabled": truthy}}}
    assert require_creator_platforms_enabled("creator_platforms", cfg, "m") is not None


def test_21D_did_not_narrow_the_permit_set():
    """§AQ class 3, asserted explicitly because this is the class both prior
    §AQ instances skipped: hardening the traversal must not stop admitting the
    operator who legitimately opted in."""
    cfg = {"services": {"creator_platforms": {"enabled": True}}}
    assert require_creator_platforms_enabled("creator_platforms", cfg, "m") is None


# ─────────────────────────────── 21-E ───────────────────────────────
# Three defects in 21-B/21-C, found by round 2's adversarial lenses.

@pytest.mark.parametrize("method,kwargs", [
    ("mint_sound", {"edition_address": "0xATTACKER"}),
    ("publish_mirror_post", {"title": "T", "body": "b", "author": "victim"}),
    ("publish_paragraph_post", {"title": "T", "body": "b", "publication": "victim"}),
])
@pytest.mark.asyncio
async def test_a_hijack_attempt_is_recorded_as_a_refusal(method, kwargs):
    """MEASURED through the real ServiceDispatcher before 21-E: a RAISED
    refusal unwinds past the attestation block, so `execute` reported
    `{"status": "error", "error_category": "service_error", "degraded": true}`
    and wrote ZERO attestations — while a RETURNED refusal in the same run
    produced ATTEST_REFUSAL.

    So the guards that exist to stop a caller hijacking a byline, a publication
    or the contract the platform signs against LEFT NO RECORD THAT THE ATTEMPT
    HAPPENED, and reported it as an internal fault of ours. An audit trail must
    show that the system DECLINED, and a hijack attempt is exactly the event it
    must show."""
    svc = CreatorPlatformsService(_cfg(True))
    out = await getattr(svc, method)(**kwargs)          # must NOT raise
    assert out.get("refused") is True
    assert _outcome_is_real(out) is False


@pytest.mark.parametrize("exc,expected", [
    (ConnectionRefusedError("refused"), "not_sent"),
    (TypeError("Object of type set is not JSON serializable"), "not_sent"),
    (TimeoutError("read timeout"), "unknown"),
])
def test_the_exception_type_decides_whether_the_request_was_sent(exc, expected):
    """21-C read no exception type, so ONE `except Exception` manufactured both
    errors: a proven non-dispatch was reported as "may be live", and a 4xx was
    reported as unknown."""
    from runtime.blockchain.services.creator_platforms._guards import (
        classify_transport_fault,
    )
    assert classify_transport_fault(exc) == expected


@pytest.mark.parametrize("code,expected", [(401, "rejected"), (422, "rejected"), (503, "unknown")])
def test_a_4xx_is_knowable_and_a_5xx_is_not(code, expected):
    from runtime.blockchain.services.creator_platforms._guards import (
        classify_transport_fault,
    )

    class _Resp:
        status_code = code

    class _Err(Exception):
        response = _Resp()

    assert classify_transport_fault(_Err()) == expected


@pytest.mark.asyncio
async def test_a_proven_non_dispatch_does_not_claim_the_post_may_be_live():
    """Caller-triggerable: any unserialisable value in `subtitle` minted an
    unresolvable "may be live" record, poisoning the very signal 21-C added."""
    svc = CreatorPlatformsService(_cfg(True))
    out = await svc.publish_paragraph_post(title="T", body="b", subtitle={1, 2})
    assert out["status"] == "failed"
    assert out["dispatched"] is False
    assert "retrying is safe" in out["disclosure"]
    assert "may be live" not in out["disclosure"]


def test_the_mint_has_the_dispatched_unknown_shape_too():
    """§AK.2 inside 21-C: the shape was built for exactly this and wired at
    both publishers and not at the one action with an irreversible on-chain
    effect."""
    import inspect
    from runtime.blockchain.services.creator_platforms import service as mod
    src = inspect.getsource(mod.CreatorPlatformsService.mint_sound)
    assert "classify_transport_fault" in src
    assert "no idempotency key" in src
