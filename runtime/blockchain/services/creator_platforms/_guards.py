"""DOMAIN 21 — the creator_platforms guards: who may act, what is acted on,
and what the outside world actually did.

Every finding here is on a path that MINTS A TOKEN or PUBLISHES TO A THIRD-PARTY
PLATFORM using the platform's own credentials. Like domain 20's carbon
retirement, THE COUNTERPARTY FOR THESE RECORDS IS OUTSIDE THE PLATFORM — a
minted token and a published post are representations other people rely on, and
a fix that stops new false records does not retract the old ones.

21-A  WHO MAY ACT        `services.creator_platforms.enabled` had ZERO READERS
                         while the SHIPPED EXAMPLE CONFIG WRITES IT `false`.
                         An operator following our own documentation believes
                         this service is off, and all three actions execute:
                         minting with the platform paymaster and publishing
                         with the platform's Mirror/Paragraph credentials.

                         §AP's most misleading variant (19-x): a document
                         points at the dead control. This is 19-A's twin, and
                         the measurement is worse — 42 OF 44 SERVICES have an
                         `enabled` key with zero readers, and 13 of those are
                         set to `false` by the shipped example. That count is a
                         PLATFORM finding and goes to the register under Rule M
                         with its measurement intact; this gate is the
                         domain-scoped refusal that does not wait for it.

                         Reachability, measured at 3ff5a029: all three actions
                         are in ACTION_MAP (253 entries) and in
                         _STATE_MODIFYING_ACTIONS. `catalog.py` marks all three
                         `available=False` and `install_action_map` NEVER
                         CONSULTS IT — the same defect domain 19 measured. With
                         `morpheus_security` absent (the shipped default)
                         `gate_action` returns observe, blocked=False. So the
                         domain was LIVE and remotely dispatchable.

21-B  WHAT IS ACTED ON   The caller chose the contract the platform paymaster
                         signs against. `edition_address` was read from
                         `params` FIRST:

                             params.get("edition_address")
                                 or cfg.get("sound_edition_address")

                         so a caller-supplied address BEAT the operator's
                         configured one, and — because that same value is the
                         only branch selector — a caller could switch ON the
                         on-chain signing path against an operator who had
                         deliberately configured API-only access.

                         Seven census lenses reached this independently.

                         The same shape governs WHO IS NAMED: `author` on
                         Mirror and `publication` on both publishers were
                         caller-supplied, so caller A could publish under
                         author B's byline into B's publication, permanently
                         on Arweave, using the platform's credential.

                         §AH, and the reason it survived reading: the module
                         header's NON-CUSTODIAL note is prominent and truthful
                         — "gas/payment is settled by the platform paymaster,
                         never a user's wallet" answers *whose money leaves*.
                         It is silent on *what gets signed and who is named*,
                         and the defect is entirely on the second question.
                         Identical to 19-B, arrived at independently.

21-C  WHAT HAPPENED      `status: "minted"` was returned on BROADCAST alone —
                         `send_transaction` returns before any receipt, and
                         `wait_for_receipt` (which has existed on Web3Manager
                         the whole time) was never called. `status:
                         "published"` was returned on ANY HTTP 2xx, without
                         reading whether the gateway returned an id.

                         And the same field carried the opposite error: a
                         transport fault AFTER the request reached the third
                         party returned the CREDENTIAL-GATED refusal shape,
                         byte-identical to a fault that never left the process.
                         So a Mirror post that IS LIVE on Arweave was recorded
                         as "the platform declined, go configure your API key".

                         §AC's completed form again: a status field carrying
                         two opposite errors simultaneously proves the field
                         cannot be the evidence. BOTH HALVES ARE FIXED
                         TOGETHER (17-D's standard) — an over-claim is visible
                         to the claimant, AN UNDER-CLAIM IS VISIBLE TO NOBODY.

                         `settled` and `value_moved` appeared NOWHERE in this
                         module (`settled` occurs once, in a comment), so
                         `_outcome_is_real`'s highest-priority override never
                         fired and all four success shapes were attested.
                         Measured: "minted", "ok", "published", "published"
                         all returned True from `_outcome_is_real`.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import not_deployed_response

logger = logging.getLogger(__name__)

__all__ = [
    "require_creator_platforms_enabled",
    "resolve_edition_address",
    "resolve_attributed_party",
    "settle_publish",
    "publish_unknown",
    "publish_rejected",
    "publish_not_sent",
    "classify_transport_fault",
    "refusal_response",
]

#: How long to wait for a mint receipt before reporting the outcome as UNKNOWN.
#: A timeout is not a failure and must not be recorded as one.
RECEIPT_TIMEOUT_S = 120


def require_creator_platforms_enabled(
    service_name: str, config: dict, method: str
) -> dict | None:
    """Return a refusal unless `services.<name>.enabled` is explicitly true.

    21-A. FAILS CLOSED. The key defaults to absent, and absent means refuse —
    because the alternative is what shipped: a config key the example sets to
    `false`, nothing reads, and which therefore cannot turn anything off.

    NAMED `require_creator_platforms_enabled`, NOT `require_enabled`. The
    refusal registry matches by SUBSTRING, and a short name silently
    reclassifies every unrelated `_require_enabled` in the repo as a refusal
    wrapper — a measured false positive that manufactured two findings in
    domain 19. Register domain-qualified names.
    """
    # The traversal is defensive because MEASURED, an earlier version of this
    # guard RAISED rather than refused: `services` as a string, or a service
    # body that is a string or a list, produced
    # `AttributeError: 'str' object has no attribute 'get'`.
    #
    # That still failed closed in EFFECT — nothing minted — but it destroyed
    # the thing this gate exists to deliver. 21-A's whole product is the
    # DISCLOSURE: "set services.creator_platforms.enabled to true". An
    # operator with a malformed config got an opaque traceback instead, which
    # is §AC at the guard layer — an AttributeError is indistinguishable from
    # any other bug, so the one shape that tells the operator what to do is
    # exactly the shape they do not receive.
    #
    # Any config we cannot read is a config that did not say `enabled: true`,
    # and that is a refusal.
    svc_cfg: Any = config.get("services") if isinstance(config, dict) else None
    svc_cfg = svc_cfg.get(service_name) if isinstance(svc_cfg, dict) else None
    if isinstance(svc_cfg, dict) and svc_cfg.get("enabled") is True:
        return None
    return not_deployed_response(service_name, extra={
        "method": method,
        "missing": f"services.{service_name}.enabled must be set to true",
        "reason": (
            "This service mints tokens and publishes to third-party platforms "
            "using the platform's own credentials, and is disabled by default. "
            "Setting `enabled: true` is an explicit, auditable opt-in by an "
            "operator — it is not implied by populating credentials."
        ),
    })


def resolve_edition_address(params: dict, configured: str) -> str:
    """The contract the platform's key signs against is the OPERATOR'S choice.

    21-B. A caller-supplied `edition_address` is REFUSED rather than ignored.
    Silently dropping it would let a caller believe they had named an edition
    and leave them to discover otherwise; refusing says which contract the
    platform will sign against and why the caller does not get to pick.

    Config wins unconditionally. If the operator configured nothing, there is
    nothing to sign against and the caller cannot supply one — that is the
    whole point: `edition_address` was ALSO the branch selector, so accepting
    it let a caller turn on on-chain signing for an operator who had
    deliberately configured API-only access.
    """
    requested = params.get("edition_address")
    if requested and str(requested).strip():
        if not configured or str(requested).strip().lower() != str(configured).strip().lower():
            raise PermissionError(
                f"edition_address {requested!r} is not the operator-configured "
                f"edition. This mint is signed and gas-paid by the platform "
                f"paymaster, so the contract it is sent to is an operator "
                f"decision, not a caller's. A caller-named contract would make "
                f"the platform's key sign a mint anywhere that key holds a "
                f"minter role — and it would switch on on-chain signing for an "
                f"operator who configured API access only. Set "
                f"services.creator_platforms.sound_edition_address."
            )
    return configured


def resolve_attributed_party(
    params: dict, key: str, configured: str | None, what: str
) -> str | None:
    """A byline or target publication is the OPERATOR'S, not the caller's.

    21-B. `author` (Mirror) and `publication` (Mirror, Paragraph) were
    caller-supplied and reached the third-party request body. Mirror entries
    are stored PERMANENTLY ON ARWEAVE, so a caller could publish under another
    person's byline, into another person's publication, using the platform's
    credential, irreversibly, and to an audience outside this platform.

    Refused rather than overridden, for the same reason as 19-B: a caller who
    believes they named a byline and did not is worse off than one who is told
    they may not.

    ONE EXCEPTION, STATED BECAUSE THE PARAGRAPH ABOVE OTHERWISE OVERSTATES IT:
    a falsy or whitespace-only value (``None``, ``""``, ``0``, ``False``,
    ``"   "``) is treated as NOT SUPPLIED and is silently ignored, not refused.
    That is the right behaviour — an absent key and an empty one mean the same
    thing to a caller — but "refused rather than ignored" was written as an
    absolute and the code has always ignored this class. Saying so here is the
    difference between a contract and a slogan (§AM.3 applied to my own
    docstring: a comment that names the hazard reads as immune to it).
    """
    requested = params.get(key)
    if requested and str(requested).strip():
        if not configured or str(requested).strip().lower() != str(configured).strip().lower():
            raise PermissionError(
                f"{key}={requested!r} is not the operator-configured {what}. "
                f"This request is published with the PLATFORM'S credential, so "
                f"the {what} it is attributed to is an operator decision. A "
                f"caller-supplied {what} would let one caller publish under "
                f"another party's name — permanently, on a third-party "
                f"platform, and to readers who cannot see this platform's "
                f"internal records."
            )
    return configured


def settle_publish(
    *,
    base: dict[str, Any],
    id_value: Any,
    id_field: str,
    response_body: Any,
) -> dict[str, Any]:
    """Turn an HTTP 2xx into a settled, honest outcome. 21-C, publish half.

    The status vocabulary is the dispatcher's own, used for what it means:

        2xx WITH an id      -> "published"  REAL outcome, settled, it exists
        2xx WITHOUT an id   -> "pending"    NON-outcome. The gateway accepted
                                            the request and named nothing we
                                            can point at, so we cannot assert
                                            the post exists.

    The third case — a transport fault after the request reached the third
    party — is NOT handled here because it must not reach a success path at
    all; see `publish_unknown` usage at the call sites, which returns "pending"
    with `dispatched: True` rather than the credential-gated refusal shape.
    """
    if id_value:
        # `value_moved` IS DELIBERATELY ABSENT HERE, and the reason is a hole
        # found by driving this guard rather than reading it.
        #
        # `_outcome_is_real`'s FIRST clause is
        # `settled is False or value_moved is False -> not real`, and it
        # outranks everything, including `created is True`. The predicate's own
        # comment says those flags report THAT NO VALUE MOVED, "a different and
        # stronger claim than 'a record now exists'".
        #
        # A confirmed publish moves no value and IS a real, durable outcome. So
        # stamping `value_moved: False` here — factually true of money —
        # suppressed the attestation and the feed record for a post that really
        # exists on Arweave. That is an UNDER-CLAIM manufactured inside the fix
        # for under-claims: the genuine act loses its audit trail, and an
        # under-claim is visible to nobody.
        #
        # `settled: True` with no `value_moved` key is the honest shape: the
        # outcome is confirmed, and this action was never about value.
        return {
            **base,
            "status": "published",
            "settled": True,
            id_field: id_value,
            "gateway_response": response_body,
        }
    return {
        **base,
        "status": "pending",
        "settled": False,
        # Same reasoning as the confirmed branch, opposite direction:
        # `settled: False` is what suppresses this, and it is CORRECT here —
        # we cannot point a reader at anything.
        id_field: None,
        "gateway_response": response_body,
        "disclosure": (
            "The gateway returned a success code but named no identifier for "
            "the published entry. This is NOT a confirmation: without an id "
            "there is nothing to point a reader at and nothing to verify the "
            "post against. It is also NOT a refusal — the content may be live."
        ),
    }


def refusal_response(service_name: str, method: str, exc: PermissionError) -> dict:
    """Turn a 21-B PermissionError into a RETURNED refusal. 21-E.

    MEASURED through the real ServiceDispatcher: a RAISED refusal unwinds past
    the attestation block, so `execute` reported
    `{"status": "error", "error_category": "service_error", "degraded": true}`
    and wrote ZERO attestations — while a RETURNED refusal in the same run
    produced `ATTEST_REFUSAL`. The dispatcher says so itself at
    service_dispatcher.py:1288-1292.

    So the 21-B guards, which exist to stop a caller hijacking a byline, a
    publication or the contract the platform signs against, LEFT NO RECORD
    THAT THE ATTEMPT HAPPENED — and reported it as an internal fault of ours.
    An audit trail must show that the system DECLINED, and a hijack attempt is
    precisely the event it must show.
    """
    return not_deployed_response(service_name, extra={
        "method": method,
        "refused": True,
        "reason": str(exc),
        "disclosure": (
            "The request named a party or a contract that the operator did not "
            "configure. Nothing was signed, sent or published. This is a "
            "REFUSAL BY POLICY, not a fault."
        ),
    })


def classify_transport_fault(exc: Exception) -> str:
    """Did the request REACH the third party? 21-E.

    21-C collapsed every fault into "dispatched, may be live". Driven, that was
    wrong in both directions at one call site:

      * connection refused / DNS failure / a caller-supplied unserialisable
        param are PROOF THE REQUEST NEVER LEFT THIS PROCESS, and were reported
        as "the post may be live ... a retry may publish a second copy" —
        which discourages the one correct remedy. Caller-controllable, too: any
        unserialisable value in `subtitle` minted an unresolvable record.
      * an HTTP 401/422 is the STRONGEST EVIDENCE that the gateway received the
        request and stored nothing, and it was reported as unknown — throwing
        away the credential diagnosis that the whole `_gate` machinery exists
        to produce.

    So the over-claim and the under-claim were BOTH manufactured inside the fix
    for under-claims, at the same `except Exception`. The exception type was
    never inspected; it carries the answer.

    Returns one of: "not_sent" · "rejected" · "unknown".
    """
    import json as _json

    # Proof it never left: encoding failed before any socket write.
    if isinstance(exc, (TypeError, ValueError)) and not isinstance(exc, OSError):
        return "not_sent"
    if isinstance(exc, _json.JSONDecodeError):
        # A decode fault happens AFTER a response arrived — the post may exist.
        return "unknown"

    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        # The gateway answered. 4xx means it received and stored nothing.
        if 400 <= status < 500:
            return "rejected"
        return "unknown"  # 5xx may have been written before the error

    name = type(exc).__name__
    if name in {"ConnectError", "ConnectTimeout", "UnsupportedProtocol",
                "InvalidURL", "ProxyError"}:
        return "not_sent"
    if isinstance(exc, (ConnectionRefusedError, ConnectionError)):
        return "not_sent"
    return "unknown"


def publish_rejected(
    *, base: dict[str, Any], endpoint: str, exc: Exception, missing: str
) -> dict[str, Any]:
    """The gateway ANSWERED and refused. 21-E.

    A 4xx is knowable, and the actionable answer is the credential one. Naming
    the config key is what `_gate` does for a MISSING credential; a PRESENT but
    invalid one deserves the same answer, not "outcome unknown".
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return {
        **base,
        "status": "failed",
        "settled": True,
        "value_moved": False,
        "dispatched": True,
        "http_status": status,
        "endpoint": endpoint,
        "missing": missing,
        "error": str(exc),
        "disclosure": (
            f"The gateway received the request and REJECTED it"
            f"{f' with HTTP {status}' if status else ''}. Nothing was "
            f"published. This is not an unknown outcome — retrying without "
            f"changing the credential will fail the same way."
        ),
    }


def publish_not_sent(
    *, base: dict[str, Any], endpoint: str, exc: Exception
) -> dict[str, Any]:
    """The request never left this process. 21-E.

    Reported as a plain failure, NOT as "may be live". Retrying is safe here,
    and saying otherwise discourages the correct remedy.
    """
    return {
        **base,
        "status": "failed",
        "settled": True,
        "value_moved": False,
        "dispatched": False,
        "endpoint": endpoint,
        "error": str(exc),
        "disclosure": (
            "The request was NOT sent — it failed before reaching the "
            "gateway. Nothing was published and retrying is safe."
        ),
    }


def publish_unknown(
    *, base: dict[str, Any], endpoint: str, exc: Exception
) -> dict[str, Any]:
    """A fault AFTER the request left this process. 21-C, the under-claim half.

    This previously returned `not_deployed_response` — the CREDENTIAL-GATED
    shape — which told an operator to go configure an API key for a request
    that may already have published permanently to Arweave. That is the
    under-claim, and it is the worse half: an over-claim is visible to the
    claimant, an under-claim is visible to nobody.
    """
    return {
        **base,
        "status": "pending",
        "settled": False,
        "value_moved": False,
        "dispatched": True,
        "endpoint": endpoint,
        "error": str(exc),
        "disclosure": (
            "The request was DISPATCHED to the third-party gateway and the "
            "outcome is unknown — the fault occurred after it left this "
            "process. This is NOT a refusal and NOT a credential problem: the "
            "post may be live. Check the gateway before retrying, because "
            "there is no idempotency key on this path and a retry may publish "
            "a second copy."
        ),
    }
