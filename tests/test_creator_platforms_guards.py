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
    rec = settle_publish(base={}, id_value="ar_123",
                         id_field="arweave_tx_id",
                         response_body={"id": "ar_123"})
    assert rec["status"] == "published"
    assert rec["settled"] is True
    assert "value_moved" not in rec
    assert _outcome_is_real(rec) is True


def test_a_2xx_that_names_nothing_is_not_a_confirmation():
    rec = settle_publish(base={}, id_value=None,
                         id_field="arweave_tx_id", response_body={})
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


# ── 21-N: the mint's outcome, tested BEHAVIOURALLY ──────────────────
#
# WHAT WAS HERE BEFORE, and why it is gone. This assertion:
#
#     src = inspect.getsource(...mint_sound); assert "wait_for_receipt" in src
#
# PROVED NOTHING. Driven by mutation: restoring the exact pre-21-C behaviour —
# claim status "minted", settled True, value_moved True on BROADCAST ALONE,
# never awaiting a receipt — left the whole suite green, because the string
# "wait_for_receipt" still appeared IN A COMMENT.
#
# A test that greps source text asserts the presence of a WORD. Only a test
# that drives the code asserts a BEHAVIOUR — and the defect 21-C fixed is
# entirely behavioural.


class _Receipt:
    def __init__(self, status, block=11, gas=21000):
        self.status = status
        self.blockNumber = block
        self.gasUsed = gas


def _armed_service(receipt=None, receipt_exc=None, send_exc=None):
    """A service whose chain transport is stubbed and whose DECISIONS are not."""
    cfg = _cfg(True)
    svc = CreatorPlatformsService(cfg)
    w = svc._web3
    w.available = True
    w.paymaster_key = "0xKEY"
    w.platform_wallet = "0xPLATFORM"

    class _Fn:
        def build_transaction(self, _):
            return {"to": "0xLEGIT", "data": "0x"}

    class _Fns:
        def mint(self, to, quantity):
            return _Fn()

    w.load_contract = lambda *a, **k: type("C", (), {"functions": _Fns()})()
    w.get_account = lambda: type("A", (), {"address": "0xPLATFORM"})()
    w.w3 = type("W3", (), {"to_checksum_address": staticmethod(lambda a: a)})()
    w.explorer_url = lambda h: f"https://x/tx/{h}"

    async def _send(tx):
        if send_exc:
            raise send_exc
        return "0xTXHASH"

    async def _wait(h, timeout=None):
        if receipt_exc:
            raise receipt_exc
        return receipt

    w.send_transaction = _send
    w.wait_for_receipt = _wait
    return svc


@pytest.mark.asyncio
async def test_a_confirmed_mint_is_reported_as_minted():
    """Reach-proof (SR-3): this must reach the receipt branch, which it proves
    by returning a tx_hash the stub supplied."""
    out = await _armed_service(receipt=_Receipt(1)).mint_sound(to="0xB", quantity=1)
    assert out["status"] == "minted"
    assert out["settled"] is True
    assert out["value_moved"] is True
    assert out["tx_hash"] == "0xTXHASH"
    assert out["block_number"] == 11
    assert _outcome_is_real(out) is True


@pytest.mark.asyncio
async def test_a_reverted_mint_is_not_reported_as_minted():
    """THE DEFECT 21-C FIXED. Pre-21-C this returned "minted" — a reverted
    transaction was indistinguishable from one that worked, and "minted" is a
    REAL-outcome status, so the dispatcher attested it and published it."""
    out = await _armed_service(receipt=_Receipt(0)).mint_sound(to="0xB", quantity=1)
    assert out["status"] == "failed"
    assert out["settled"] is True
    assert out["value_moved"] is False
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_a_mint_with_no_receipt_is_pending_not_minted_and_not_refused():
    """The third outcome, which pre-21-C could not express at all."""
    out = await _armed_service(
        receipt_exc=TimeoutError("no receipt")
    ).mint_sound(to="0xB", quantity=1)
    assert out["status"] == "pending"
    assert out["settled"] is False
    assert out["broadcast"] is True
    assert out["tx_hash"] == "0xTXHASH"
    assert "no idempotency key" in out["disclosure"]
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_a_broadcast_fault_of_unknown_outcome_is_not_a_credential_refusal():
    """21-E / AQ::3 driven behaviourally rather than grepped."""
    out = await _armed_service(
        send_exc=TimeoutError("read timeout")
    ).mint_sound(to="0xB", quantity=1)
    assert out["status"] == "pending"
    assert out["dispatched"] is True
    assert out["settled"] is False
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_a_provably_pre_broadcast_fault_is_not_reported_as_maybe_mined():
    """The other direction: a fault that proves nothing was sent must not claim
    a token may be minting."""
    out = await _armed_service(
        send_exc=ConnectionRefusedError("refused")
    ).mint_sound(to="0xB", quantity=1)
    assert out.get("status") != "pending" or out.get("dispatched") is not True


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


# ─────────────────────────────── 21-F ───────────────────────────────
# Documentation/behaviour mismatches in 21-B, found by round 2's completeness
# critic auditing the FIXES rather than the original code.

def test_the_config_keys_21B_reads_are_in_the_shipped_example():
    """critic::27. 21-B moved `edition_address`, `author` and `publication`
    from caller params to config — and INVENTED `mirror_author` and
    `mirror_publication`, which appeared in no document and no example config.

    A refusal that names a key the operator cannot find is not actionable, and
    an undiscoverable key is R-21.1's shape pointed the other way: there, the
    config named a control the code ignored; here, the code named a control the
    config never mentioned."""
    import json
    from pathlib import Path
    cfg = json.loads(Path("matrix.config.json.example").read_text())
    body = cfg["services"]["creator_platforms"]
    for key in ("sound_edition_address", "mirror_author",
                "mirror_publication", "paragraph_publication"):
        assert key in body, f"{key} is read by 21-B and absent from the example"


@pytest.mark.parametrize("method,advertised", [
    ("mint_sound", "edition_address"),
    ("publish_mirror_post", "author"),
    ("publish_paragraph_post", "publication"),
])
def test_no_docstring_advertises_a_param_the_code_now_refuses(method, advertised):
    """critic::28, and §AM.3 committed by this engagement: after 21-B began
    refusing these, all three docstrings still listed them as optional caller
    params — the artifact named exactly the thing that had changed."""
    import inspect
    from runtime.blockchain.services.creator_platforms import service as mod
    doc = inspect.getdoc(getattr(mod.CreatorPlatformsService, method)) or ""
    head = doc.split("Params:")[1] if "Params:" in doc else doc
    line = head.split("\n\n")[0]
    assert advertised not in line, (
        f"{method} still advertises {advertised!r} as a caller param"
    )
    assert "NO LONGER" in doc


@pytest.mark.parametrize("falsy", [None, "", 0, False, "   "])
def test_a_falsy_attributed_party_is_treated_as_not_supplied(falsy):
    """critic::30. Both guard docstrings promised 'refused rather than
    ignored' as an absolute, and have always SILENTLY IGNORED falsy and
    whitespace-only values. The behaviour is right — an absent key and an empty
    one mean the same thing — so the docstring was corrected to match the code
    rather than the code bent to match the slogan."""
    kwargs = {"author": falsy} if falsy is not None else {}
    assert resolve_attributed_party(kwargs, "author", "operator", "author") == "operator"


# ─────────────────────────────── 21-G ───────────────────────────────
# A DEFAULT ENDPOINT FOR A CREDENTIALED REQUEST IS A DECISION ABOUT WHO
# RECEIVES THE CREDENTIAL.

def _capture_client(recorder):
    import httpx

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._rec)
            super().__init__(*a, **k)

        def _rec(self, request):
            recorder.append(str(request.url))
            return httpx.Response(200, json={"id": "ar_fake"})

    return _C


@pytest.mark.asyncio
async def test_mirror_refuses_rather_than_send_the_credential_to_a_default_host():
    """THE REPRODUCTION, measured with the request intercepted locally:

        mirror    -> arweave.net        credential sent: True   NOT THE ISSUER
        paragraph -> api.paragraph.xyz  credential sent: True   issuer
        sound     -> api.sound.xyz      credential sent: True   issuer

    Only Mirror had the mismatch. `arweave.net` is a public gateway that never
    issued the credential and does not use Bearer auth — it would simply
    receive and log it. The failure mode is DISCLOSURE, not an error the
    operator sees, which is why this default could not be made safer and had
    to be removed."""
    import httpx
    from unittest.mock import patch
    sent = []
    cfg = _cfg(True)                       # api key present, NO mirror_endpoint
    svc = CreatorPlatformsService(cfg)
    with patch.object(httpx, "AsyncClient", _capture_client(sent)):
        out = await svc.publish_mirror_post(title="T", body="b")
    assert sent == [], "the credential left the process on the default path"
    assert out.get("missing") == "services.creator_platforms.mirror_endpoint"


@pytest.mark.asyncio
async def test_an_operator_who_names_their_gateway_can_still_publish():
    """§AQ class 3 — removing a default must not remove the capability."""
    import httpx
    from unittest.mock import patch
    sent = []
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["mirror_endpoint"] = "https://gw.example"
    svc = CreatorPlatformsService(cfg)
    with patch.object(httpx, "AsyncClient", _capture_client(sent)):
        out = await svc.publish_mirror_post(title="T", body="b")
    assert sent == ["https://gw.example/tx"]
    assert out["status"] == "published"


@pytest.mark.asyncio
async def test_a_hijack_is_not_masked_by_a_missing_endpoint():
    """Caught by an existing test when 21-G was added: the new config gate
    fired FIRST, so a byline hijack against an operator who had not configured
    `mirror_endpoint` came back as "your endpoint is unset" and the attempt was
    never recorded as one.

    A config problem is the operator's own state; an attempted hijack is
    someone acting against them. When both are true, the second is the one they
    need to see."""
    cfg = _cfg(True)                       # deliberately no mirror_endpoint
    svc = CreatorPlatformsService(cfg)
    out = await svc.publish_mirror_post(title="T", body="b", author="victim")
    assert out.get("refused") is True
    assert "not the operator-configured author" in str(out.get("reason", ""))


def test_the_two_defaults_that_remain_are_their_own_credentials_issuer():
    """The scope of 21-G, asserted so it is not over-applied: Sound and
    Paragraph default to the host that ISSUED their key, which is the correct
    shape. This is a specific defect, not a general ban on defaults."""
    from runtime.blockchain.services.creator_platforms import service as mod
    assert "api.sound.xyz" in mod._DEFAULT_SOUND_ENDPOINT
    assert "api.paragraph.xyz" in mod._DEFAULT_PARAGRAPH_ENDPOINT
    assert not hasattr(mod, "_DEFAULT_MIRROR_ENDPOINT")


# ─────────────────────────────── 21-H ───────────────────────────────
# NOT A WRONG RECORD — NO RECORD.

def test_cancelled_error_is_not_an_exception():
    """The premise, asserted so the reason survives: `asyncio.CancelledError`
    inherits from BaseException, so every `except Exception` in the service
    missed it."""
    import asyncio
    assert not issubclass(asyncio.CancelledError, Exception)
    assert issubclass(asyncio.CancelledError, BaseException)


@pytest.mark.asyncio
async def test_a_cancelled_publish_still_leaves_a_record(caplog):
    """MEASURED before 21-H: the POST was issued, cancellation propagated, and
    the service returned NOTHING — no record, no disclosure, no "may be live"
    warning. The batch route's per-item ceiling cancels exactly this way.

    Cancellation MUST still propagate: swallowing it to return a dict would
    break every caller's timeout. So the record goes to the log, which is the
    only channel a cancelled caller leaves open."""
    import asyncio
    import logging
    import httpx
    from unittest.mock import patch

    sent = []

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            sent.append(str(request.url))
            raise asyncio.CancelledError()

    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["mirror_endpoint"] = "https://gw.example"
    svc = CreatorPlatformsService(cfg)

    with caplog.at_level(logging.ERROR):
        with patch.object(httpx, "AsyncClient", _C):
            with pytest.raises(asyncio.CancelledError):
                await svc.publish_mirror_post(title="T", body="b")

    assert sent, "harness never issued the request"
    assert any("CANCELLED AFTER DISPATCH" in r.getMessage() for r in caplog.records)
    assert any("no idempotency key" in r.getMessage() for r in caplog.records)


def test_every_transport_site_has_a_cancellation_handler():
    """§AK.2 as a structural control rather than a promise. 21-C guarded two of
    three sites and 21-E found the third; this counts them so the next transport
    site cannot be added without one.

    Five sites, enumerated: the chain broadcast, the receipt wait, the Sound
    GraphQL call, and the two publisher POSTs.

    Every one of the five has a cancellation handler. Four have a broad handler
    here as well; the receipt wait's is inside `web3_manager.settle_transaction`,
    which the mint now waits through, and what it answers for a wait that runs
    out is driven by `test_a_mint_with_no_receipt_is_pending_not_minted_and_not_refused`.
    This counted the two equal while the receipt wait carried its own `except
    Exception`; both numbers are pinned instead, so neither can move unseen."""
    from pathlib import Path
    src = Path(
        "runtime/blockchain/services/creator_platforms/service.py"
    ).read_text()
    broad = src.count("except Exception as exc")
    cancelled = src.count("except asyncio.CancelledError")
    assert cancelled == 5, (
        f"{cancelled} cancellation handlers for five transport sites — a "
        f"transport site can be cancelled with no record written"
    )
    assert broad == 4, (
        f"{broad} broad handlers; four sites handle their own faults and the "
        f"receipt wait's are settle_transaction's — re-read before changing"
    )


# ─────────────────────────────── 21-K ───────────────────────────────

from runtime.blockchain.services.creator_platforms._guards import (  # noqa: E402
    require_mint_quantity, require_text,
)


@pytest.mark.parametrize("bad", [0, False, True, -5, 1.9, "7", "  7  ", 10 ** 30, None, [1], 11])
def test_a_mint_quantity_must_be_a_bounded_whole_number(bad):
    """MEASURED before 21-K, on `int(params.get("quantity", 1) or 1)`:

        0        -> mints 1      the `or 1` bypass: asked for none, got one
        False    -> mints 1
        -5       -> mints -5     straight into mint(to, uint256)
        1.9      -> mints 1      silent truncation
        10**30   -> mints 10**30 unbounded
        "  7  "  -> mints 7      string coercion

    It feeds a REAL on-chain mint paid for by the platform paymaster, so an
    unbounded caller-supplied count is an unbounded caller-directed spend."""
    with pytest.raises(PermissionError):
        require_mint_quantity(bad, 10)


@pytest.mark.parametrize("good", [1, 5, 10])
def test_honest_mint_quantities_are_still_permitted(good):
    """§AQ class 3."""
    assert require_mint_quantity(good, 10) == good


@pytest.mark.asyncio
async def test_the_quantity_guard_runs_before_the_mint():
    """Driven in situ with web3 marked available, so the mint path is actually
    reached — with a reach-proof: an honest quantity must fail DOWNSTREAM (at
    the contract call), not on quantity."""
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["max_mint_quantity"] = 10
    svc = CreatorPlatformsService(cfg)
    svc._web3.available = True
    svc._web3.paymaster_key = "0xKEY"
    svc._web3.platform_wallet = "0xPLAT"

    reach = await svc.mint_sound(quantity=5)
    assert reach.get("refused") is not True, "harness never reached the mint path"

    for bad in (0, -5, 11):
        out = await svc.mint_sound(quantity=bad)
        assert out.get("refused") is True
        assert "quantity" in str(out.get("reason", ""))


@pytest.mark.parametrize("bad", [0, [], {}, "", "   ", None, 5.0])
def test_publishable_text_must_be_a_non_empty_string(bad):
    """`is_placeholder_value` returns False for EVERY non-string — it detects
    unfilled config templates, a different question than "is this publishable
    text" (§I.13). Non-strings reached the third-party request body."""
    with pytest.raises(PermissionError):
        require_text(bad, "title")


def test_the_mint_quantity_cap_is_in_the_shipped_example_config():
    """21-F's lesson: a bound the operator cannot find is not a bound they
    chose."""
    import json
    from pathlib import Path
    cfg = json.loads(Path("matrix.config.json.example").read_text())
    body = cfg["services"]["creator_platforms"]
    assert "max_mint_quantity" in body
    assert "mirror_endpoint" in body


# ─────────────────────────────── 21-L ───────────────────────────────

@pytest.mark.parametrize("title", ["your_first_post", "Your_Guide_To_Arweave", "YOUR_TITLE"])
@pytest.mark.asyncio
async def test_a_legitimate_title_is_not_refused_as_a_config_placeholder(title):
    """AQ::8, and §AQ class 3 — a guard refusing valid input is its own defect.

    `is_placeholder_value` refuses any string starting "your_". Correct for a
    CONFIG value left as a template; wrong for user content, where
    "your_first_post" is an ordinary title. `require_text` (21-K) already asks
    the consumer's question, so the config-template detector no longer runs
    against caller content — §I.13 completed, since the guard had been
    answering the config question about a content field."""
    import httpx
    from unittest.mock import patch
    sent = []
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["mirror_endpoint"] = "https://gw.example"
    svc = CreatorPlatformsService(cfg)
    with patch.object(httpx, "AsyncClient", _capture_client(sent)):
        out = await svc.publish_mirror_post(title=title, body="b")
    assert out.get("refused") is not True
    assert out.get("status") != "not_deployed"
    assert sent, "the post was never dispatched"


@pytest.mark.parametrize("bad", [12345, ["x"], {"a": 1}, 3.5])
@pytest.mark.parametrize("method,key", [
    ("publish_mirror_post", "mirror_endpoint"),
    ("publish_paragraph_post", "paragraph_endpoint"),
])
@pytest.mark.asyncio
async def test_a_non_string_endpoint_refuses_instead_of_raising(method, key, bad):
    """regions::7. `.rstrip` sits OUTSIDE the try, so a non-string endpoint
    raised AttributeError straight past the service's own error handling.
    21-D's lesson at a second site: a config we cannot read is a config that
    did not configure this, and that is a refusal, not a crash."""
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"][key] = bad
    svc = CreatorPlatformsService(cfg)
    out = await getattr(svc, method)(title="T", body="b")   # must not raise
    assert key in str(out.get("missing", ""))


# ─────────────────────────────── 21-M ───────────────────────────────

from runtime.blockchain.services.creator_platforms._guards import (  # noqa: E402
    safe_endpoint,
)


@pytest.mark.parametrize("url,expected_secret_gone", [
    ("https://user:SUPERSECRET@gw.example/base", "SUPERSECRET"),
    ("https://TOKEN@gw.example", "TOKEN"),
    ("https://:SUPERSECRET@gw.example", "SUPERSECRET"),
])
def test_a_credential_in_the_gateway_url_is_redacted_from_the_record(url, expected_secret_gone):
    """MEASURED: with `mirror_endpoint` set to
    `https://user:SUPERSECRET@gw.example/base`, the returned record carried the
    full URL — and that record has `settled: True`, so it is attested AND
    published to the PUBLIC SOCIAL FEED. The census scored this LATENT; driven,
    it is LIVE and it publishes.

    A userinfo with NO colon is the credential itself (`https://TOKEN@host` is
    how bearer-style gateway URLs are written); an earlier version of this
    redactor preserved it as if it were a username."""
    assert expected_secret_gone not in safe_endpoint(url)
    assert "***" in safe_endpoint(url)


@pytest.mark.parametrize("url", [
    "https://gw.example/base", "https://gw.example/path@with-at", "not-a-url", "",
])
def test_a_url_without_a_credential_is_left_alone(url):
    assert safe_endpoint(url) == url


@pytest.mark.asyncio
async def test_the_credential_still_reaches_the_host_that_issued_it():
    """Only what is RECORDED is redacted. The credential must still reach the
    host it was issued for — redacting the request instead of the record would
    break publishing while looking like a fix."""
    import httpx
    from unittest.mock import patch
    sent = []
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["mirror_endpoint"] = (
        "https://user:SUPERSECRET@gw.example/base"
    )
    svc = CreatorPlatformsService(cfg)
    with patch.object(httpx, "AsyncClient", _capture_client(sent)):
        out = await svc.publish_mirror_post(title="T", body="b")

    assert "SUPERSECRET" in sent[0], "the credential never reached the gateway"
    assert "SUPERSECRET" not in str(out), "the credential is in the durable record"
    assert out["status"] == "published"


@pytest.mark.parametrize("url", [
    "https://user:SECRET@gw.example/p",
    "https://TOKEN@gw.example",
    "https://:SECRET@gw.example",
    "user:SECRET@gw.example",                       # no scheme
    "HTTPS://user:SECRET@gw.example",               # uppercase scheme
    "https://user:SECRET@[::1]:8443/p",             # IPv6 literal
    "https://user:SECRET@evil@gw.example/p",        # multiple @
    "https://gw.example/p?token=SECRET",            # credential in query
    "https://gw.example/p?api_key=SECRET&x=1",
])
def test_safe_endpoint_survives_evasion(url):
    """Driven against my OWN first version, three evasions worked. Two are
    fixed (schemeless userinfo, credential query params); the third is
    undecidable and documented rather than papered over."""
    assert "SECRET" not in safe_endpoint(url)
    assert "TOKEN" not in safe_endpoint(url) or "***" in safe_endpoint(url)


@pytest.mark.parametrize("url", [
    "https://gw.example/base",
    "https://gw.example/p?to=a@b.com",              # @ in a query VALUE
    "https://gw.example/path@with-at",              # @ in the path
    "not-a-url",
    "",
])
def test_safe_endpoint_leaves_clean_urls_alone(url):
    """§AQ class 3 — a redactor that mangles honest URLs breaks diagnostics."""
    assert safe_endpoint(url) == url


def test_the_undecidable_case_is_documented_not_claimed():
    """A secret in a PATH SEGMENT is indistinguishable from a route. This test
    exists so the limitation is asserted rather than discovered later: it
    records that we do NOT redact it, and the docstring says why."""
    assert safe_endpoint("https://gw.example/SECRET/tx") == "https://gw.example/SECRET/tx"
    from runtime.blockchain.services.creator_platforms import _guards
    assert "NOT DETECTABLE" in _guards.safe_endpoint.__doc__


# ─────────────────────────────── 21-O ───────────────────────────────

from runtime.blockchain.services.creator_platforms._guards import (  # noqa: E402
    safe_text,
)


@pytest.mark.asyncio
async def test_no_credential_survives_anywhere_in_the_record_or_the_log(caplog):
    """§AK.2 INSIDE 21-M. 21-M redacted the `endpoint` FIELD and left the field
    beside it. MEASURED before 21-O:

        endpoint : https://user:***@gw.example/base/tx         <- redacted
        error    : failed connecting to
                   https://user:SUPERSECRET@gw.example/base/tx <- NOT redacted

    httpx puts the request URL in its exception messages, so every
    `"error": str(exc)` and every logger line carried the credential the field
    next to it had just been scrubbed of.

    This asserts over the WHOLE record and the WHOLE log, not a field list — a
    per-field redactor is only as good as the enumeration of fields."""
    import logging
    import httpx
    from unittest.mock import patch

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            raise httpx.ConnectError(f"failed connecting to {request.url}",
                                     request=request)

    cfg = _cfg(True)
    cfg["services"]["creator_platforms"]["mirror_endpoint"] = (
        "https://user:SUPERSECRET@gw.example/base"
    )
    svc = CreatorPlatformsService(cfg)
    with caplog.at_level(logging.DEBUG):
        with patch.object(httpx, "AsyncClient", _C):
            out = await svc.publish_mirror_post(title="T", body="b")

    assert "SUPERSECRET" not in str(out)
    assert "SUPERSECRET" not in " ".join(r.getMessage() for r in caplog.records)
    assert "***" in str(out)


@pytest.mark.parametrize("text,secret", [
    ("failed connecting to https://user:SECRET@gw.example/p", "SECRET"),
    ("timeout for https://TOKEN@gw.example after 30s", "TOKEN"),
    ("two: https://a:S1@x/ and https://b:S2@y/", "S1"),
    ("query https://gw.example/p?token=SECRET failed", "SECRET"),
])
def test_safe_text_redacts_urls_embedded_in_free_text(text, secret):
    assert secret not in safe_text(text)


@pytest.mark.parametrize("text", [
    "nothing sensitive here", "", "connection reset by peer",
    "https://gw.example/clean/path failed",
])
def test_safe_text_leaves_clean_text_alone(text):
    """§AQ class 3 — a redactor that mangles diagnostics is its own defect."""
    assert safe_text(text) == text


# ─────────────────────────────── 21-P ───────────────────────────────
# 21-H covered FIVE transport sites and only ONE had a behavioural test.
#
# MEASURED by mutation: suppressing the body of `log_cancelled_dispatch` —
# handlers still present, so the structural count still passes — failed
# 1 of 141 tests. Four sites were guarded by a count of the word
# `except asyncio.CancelledError`, which is §AT's exact class: it asserts the
# handler EXISTS, never that it FIRES.
#
# The receipt-wait site is the one that matters most: cancellation there means
# a paymaster-funded transaction is already broadcast.


async def _cancel_at(monkeypatch, svc, where):
    """Drive a cancellation at one named transport site."""
    import httpx

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            raise asyncio.CancelledError()

    monkeypatch.setattr(httpx, "AsyncClient", _C)
    return svc


import asyncio  # noqa: E402


@pytest.mark.asyncio
async def test_a_cancelled_broadcast_is_recorded(caplog):
    """Site 1 — the chain broadcast."""
    import logging
    svc = _armed_service(send_exc=asyncio.CancelledError())
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await svc.mint_sound(to="0xB", quantity=1)
    assert any("CANCELLED AFTER DISPATCH" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_receipt_wait_is_recorded(caplog):
    """Site 2 — THE WORST ONE. Cancellation here means the mint was already
    broadcast and paid for by the platform paymaster, so without a record the
    platform holds no trace of a transaction it signed."""
    import logging
    svc = _armed_service(receipt_exc=asyncio.CancelledError())
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await svc.mint_sound(to="0xB", quantity=1)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "CANCELLED AFTER DISPATCH" in msg
    assert "0xTXHASH" in msg, "the record must name the broadcast transaction"


@pytest.mark.asyncio
async def test_a_cancelled_sound_metadata_call_is_recorded(caplog, monkeypatch):
    """Site 3 — the Sound GraphQL call."""
    import logging
    cfg = _cfg(True)
    cfg["services"]["creator_platforms"].pop("sound_edition_address", None)
    cfg["services"]["creator_platforms"]["sound_api_key"] = "k"
    svc = CreatorPlatformsService(cfg)
    await _cancel_at(monkeypatch, svc, "sound")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await svc.mint_sound(release_id="r1")
    assert any("CANCELLED AFTER DISPATCH" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_paragraph_publish_is_recorded(caplog, monkeypatch):
    """Site 5 — the Paragraph POST. (Site 4, Mirror, is covered above.)"""
    import logging
    svc = CreatorPlatformsService(_cfg(True))
    await _cancel_at(monkeypatch, svc, "paragraph")
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await svc.publish_paragraph_post(title="T", body="b")
    assert any("CANCELLED AFTER DISPATCH" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_cancellation_always_propagates():
    """Swallowing cancellation to return a dict would break every caller's
    timeout. All five sites re-raise; this asserts the property rather than
    the keyword."""
    svc = _armed_service(send_exc=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await svc.mint_sound(to="0xB", quantity=1)


# ─────────────────────────────── 21-Q ───────────────────────────────
# THE CONTRADICTION, RESOLVED BY MEASUREMENT.
#
# Two adversarial lenses reported the same 21-M gap with incompatible counts:
# guards::4 said "1 of 4 endpoint-recording sites never calls safe_endpoint";
# attest::1 said "2 of 3 sites record the RAW credentialed endpoint".
#
# My own enumeration: TWO raw sites, both on the Sound API path — the
# cancellation log and the failure record. BOTH LENSES UNDERCOUNTED,
# DIFFERENTLY, and a fix scoped to either lens's count would have shipped the
# other site. §AR's contradiction category is exactly this: two individually
# sound findings that cannot both be acted on as stated.


def test_no_endpoint_is_recorded_without_redaction():
    """A structural control, and legitimately so — the SUBJECT here is the
    source text (§AT's exception for structural invariants). It counts, so a
    new recording site cannot be added raw."""
    from pathlib import Path
    src = Path(
        "runtime/blockchain/services/creator_platforms/service.py"
    ).read_text()
    import re
    # No endpoint/url is recorded raw.
    assert not re.search(r'"endpoint": (endpoint|url),', src)
    # Every cancellation site passes either a redacted URL or a non-URL
    # locator (the chain sites pass "chain tx via ..." / "broadcast tx ...").
    calls = re.findall(r"log_cancelled_dispatch\(\s*(?:#[^\n]*\n\s*)*"
                       r'"[a-z_]+",\s*([^,]+),', src)
    assert len(calls) == 5, f"expected 5 cancellation sites, found {len(calls)}"
    for arg in calls:
        arg = arg.strip()
        assert arg.startswith("safe_endpoint(") or arg.startswith('f"'), (
            f"cancellation site logs a raw locator: {arg}"
        )


@pytest.mark.asyncio
async def test_the_sound_api_failure_record_carries_no_credential(caplog):
    """The behavioural half — §AT: the structural test above says a site
    exists, this one says it does not leak."""
    import logging
    import httpx
    from unittest.mock import patch

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            raise httpx.ConnectError("boom", request=request)

    cfg = _cfg(True)
    cfg["services"]["creator_platforms"].pop("sound_edition_address", None)
    cfg["services"]["creator_platforms"]["sound_api_key"] = "k"
    cfg["services"]["creator_platforms"]["sound_endpoint"] = (
        "https://user:SUPERSECRET@sound.example/graphql"
    )
    svc = CreatorPlatformsService(cfg)
    with caplog.at_level(logging.DEBUG):
        with patch.object(httpx, "AsyncClient", _C):
            out = await svc.mint_sound(release_id="r1")

    assert "SUPERSECRET" not in str(out)
    assert "SUPERSECRET" not in " ".join(r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_cancelled_sound_call_logs_no_credential(caplog):
    """The second raw site: the cancellation log on the same path."""
    import logging
    import httpx
    from unittest.mock import patch

    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(self._r)
            super().__init__(*a, **k)

        def _r(self, request):
            raise asyncio.CancelledError()

    cfg = _cfg(True)
    cfg["services"]["creator_platforms"].pop("sound_edition_address", None)
    cfg["services"]["creator_platforms"]["sound_api_key"] = "k"
    cfg["services"]["creator_platforms"]["sound_endpoint"] = (
        "https://user:SUPERSECRET@sound.example/graphql"
    )
    svc = CreatorPlatformsService(cfg)
    with caplog.at_level(logging.DEBUG):
        with patch.object(httpx, "AsyncClient", _C):
            with pytest.raises(asyncio.CancelledError):
                await svc.mint_sound(release_id="r1")

    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "CANCELLED AFTER DISPATCH" in msg
    assert "SUPERSECRET" not in msg


# ─────────────────────────────── 21-R ───────────────────────────────
# SR-2 across all three methods, and the bound SR-2 needed.

@pytest.mark.parametrize("method,kwargs", [
    ("publish_mirror_post", {"title": "T", "body": "b", "author": "victim"}),
    ("publish_paragraph_post", {"title": "T", "body": "b", "publication": "victim"}),
    ("mint_sound", {"edition_address": "0xATTACKER"}),
])
@pytest.mark.asyncio
async def test_a_hijack_is_recorded_even_with_no_credentials_configured(method, kwargs):
    """21-G fixed the ordering for the ENDPOINT gate and left it broken at the
    API_KEY gate — §AK.2 inside an ordering fix. A hijack attempt against an
    operator whose api_key is unset came back as "your api_key is missing", so
    the attempt was never recorded as one."""
    svc = CreatorPlatformsService({"services": {"creator_platforms": {"enabled": True}}})
    out = await getattr(svc, method)(**kwargs)
    assert out.get("refused") is True
    assert "not the operator-configured" in str(out.get("reason", ""))


@pytest.mark.parametrize("method,kwargs", [
    ("publish_mirror_post", {"title": "T", "body": "b", "author": "victim"}),
    ("publish_paragraph_post", {"title": "T", "body": "b", "publication": "victim"}),
    ("mint_sound", {"edition_address": "0xATTACKER"}),
])
@pytest.mark.asyncio
async def test_a_disabled_service_adjudicates_nothing(method, kwargs):
    """THE BOUND SR-2 NEEDED, and the reason ordering::4 is REFUSED rather than
    fixed. SR-2 orders gates WITHIN AN ENABLED SERVICE. "Is this service on at
    all" is not a configuration refusal in SR-2's sense — it is the operator's
    decision that this service adjudicates nothing. A disabled service
    answering "you may not name that author" would tell an unauthenticated
    caller that it exists and is configured."""
    svc = CreatorPlatformsService({"services": {"creator_platforms": {"enabled": False}}})
    out = await getattr(svc, method)(**kwargs)
    assert "enabled must be set to true" in str(out.get("missing", ""))
    assert out.get("refused") is not True


def test_the_authorization_refusal_does_not_disclose_the_configured_value():
    """Checked rather than assumed — it is what makes running authorization
    before the credential gates safe for an unauthenticated caller."""
    with pytest.raises(PermissionError) as caught:
        resolve_attributed_party(
            {"author": "victim"}, "author", "SECRET_OPERATOR_HANDLE", "author")
    assert "SECRET_OPERATOR_HANDLE" not in str(caught.value)
