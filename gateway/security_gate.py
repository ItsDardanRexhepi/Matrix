"""Gateway security gate — the thin call site that routes every privileged /
fund-moving HTTP action through the Morpheus contract.

This is a BOUNDARY caller, not an implementation. It contains NO security logic:
no thresholds, no spend caps, no destination allowlists, no detection signals, no
sanitizer patterns, no owner/OTP internals. It only:

  1. carries the per-request security CONTEXT (the caller's identity + the client's
     App Attest assertion) from the HTTP entry point to each gate call site, and
  2. calls ``get_morpheus_security().evaluate(action, context)`` via the public
     security seam (``runtime.security``).

The decision — allow / deny / classification — is made entirely inside the private
``morpheus_security`` package. When that package is not installed the seam is an inert
OBSERVE no-op and this gate allows everything (the platform still boots).

The one piece of routing metadata here, ``action_type_for``, maps a public service
method name to a generic action label so the gate can classify it; it is NOT a list
of which actions are privileged (that classification lives only in the private gate).
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Per-request security context, bound at the HTTP entry (middleware / handler) and
# read at each gate call site. A ContextVar propagates to everything awaited within
# the same request task — so batch sub-calls inherit the same context automatically.
_request_security: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "request_security", default={}
)

# HOW the bound identity was resolved, beside the context rather than inside it:
# the context is what the gate is handed, and this is read by the platform's own
# record of who acted (ServiceDispatcher's ``actor_source``), not by the gate.
# "session" — derived from the wallet session the request presented; "operator" —
# named by a request that carried the operator key and no session (an
# integration naming the user it acts for, docs/api-reference.md "Identity");
# "" — no identity was bound. Inherited by batch sub-calls like the context.
_identity_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "identity_source", default=""
)
IDENTITY_SOURCES = frozenset({"session", "operator"})

# Generic, non-leaking client message. The real (internal) reason from the gate is
# never surfaced to the client — only this is.
_GENERIC_DENY = "This action couldn't be authorized right now. Please try again."


def bind_request_security(
    *,
    identity: str = "",
    app_attest: Any = None,
    apple_id: str = "",
    session_id: str = "",
    extra: Optional[dict] = None,
    identity_source: str = "",
) -> None:
    """Bind the security context for the current request task.

    ``identity`` is the wallet address the action is attributed to, bound in the
    one spelling the platform names a caller by (runtime/auth/identity.py), so
    every spelling of one wallet is attributed to the same caller; ``app_attest``
    is the client's App Attest assertion block (or None). Read later via
    ``current_request_security`` at each gate call site.

    ``identity_source`` says how ``identity`` was resolved — ``"session"`` or
    ``"operator"`` — and is read back with ``bound_identity_source``. Every bind
    sets it, so a bind that does not say is recorded as not saying (""), never
    as the previous bind's answer; it is "" whenever no identity is bound, and
    a value outside the two is refused.
    """
    if identity_source and identity_source not in IDENTITY_SOURCES:
        raise ValueError(f"identity_source must be one of {sorted(IDENTITY_SOURCES)} "
                         f"or empty, not {identity_source!r}")
    from runtime.auth.identity import canonical_identity

    ctx: dict[str, Any] = {
        "wallet": canonical_identity(identity) or "",
        "apple_id": apple_id or "",
        "session_id": session_id or "",
    }
    if app_attest is not None:
        ctx["app_attest"] = app_attest
    if extra:
        ctx.update(extra)
    _request_security.set(ctx)
    _identity_source.set(identity_source if ctx["wallet"] else "")


def current_request_security() -> dict:
    """A copy of the security context bound for the current request (or empty)."""
    return dict(_request_security.get())


def bound_identity_source() -> str:
    """How the identity bound for the current request was resolved:
    ``"session"``, ``"operator"``, or "" (none bound, or the binder did not say)."""
    return _identity_source.get()


def action_type_for(service_name: str, method_name: str) -> str:
    """Generic action label for a service method, so the gate can classify it.

    Routing metadata only — NOT a privileged-action list. The gate (private) owns
    the classification of which labels are fund-moving / owner-gated / restricted.
    Most service methods already carry the canonical verb (swap, transfer, stake,
    …); a few public method names are normalised to their canonical action word.
    """
    method = (method_name or "").strip().lower()
    aliases = {
        "create_payment": "payment",
        "send_payment": "send",
        "add_liquidity": "provide_liquidity",
        "liquidity_provide": "provide_liquidity",
        "remove_liquidity": "remove_liquidity",
    }
    return aliases.get(method, method)


async def gate_action(
    action_type: str,
    parameters: Optional[dict] = None,
    context: Optional[dict] = None,
    *,
    operation: Optional[tuple[str, str]] = None,
) -> dict:
    """Run one action through the Morpheus gate and return its decision dict.

    Pure contract call: builds ``{action_type, type, parameters}`` and the context,
    then calls the process-wide gate via the public seam.

    While the gateway's gate is not up (still starting, or its start failed) the
    seam hands out no gate, and every action is refused here, reads included,
    without asking anything else in the gate's place: a decision about this
    request belongs with the gate, and there is none to make it. A gate that is
    up and faults on one call is a different case; see the except branch.
    """
    from runtime.security import SecurityGateUnavailable, get_morpheus_security  # public seam

    ctx = dict(context) if context is not None else current_request_security()
    action = {
        "action_type": action_type,
        "type": action_type,
        "parameters": parameters or {},
    }
    try:
        gate = get_morpheus_security()
        return await gate.evaluate(action, ctx)
    except SecurityGateUnavailable:
        logger.error("security gate not up; refused (action=%s)", action_type)
        return {"allow": False, "would_block": True, "route": "gate-not-up",
                "reason": _GENERIC_DENY}
    except Exception:
        # The gate is unreachable / faulted. Fail by ACTION TYPE, not blanket-allow:
        # a value-moving (or unknown) action must NOT proceed ungated — fail CLOSED
        # (deny) so nothing moves value when we can't reach the gate. A clearly-benign
        # read observe-allows so a transient gateway fault doesn't break it. The coarse
        # public label is the only input; the authoritative classification still lives
        # in the private gate.
        #
        # ``operation`` is the (service, method) the caller is about to RUN, when
        # it knows one. The label alone is not enough: ServiceRoutes._call passes
        # a METHOD name, and `list_item` (marketplace.list_item — a state change
        # the dispatcher's set calls `list_marketplace`) read as a benign
        # `list_` read, so POST /api/v1/marketplace/list ran under a faulted gate.
        from runtime.access_policy import operation_could_move_value
        if operation_could_move_value(action_type, *(operation or (None, None))):
            logger.exception("security gate unreachable; FAIL-CLOSED deny (action=%s)", action_type)
            return {"allow": False, "would_block": True, "route": "fail-closed",
                    "reason": _GENERIC_DENY}
        logger.warning("security gate unreachable; observe-allow (benign read=%s)", action_type)
        return {"allow": True, "would_block": False, "route": "observe-read-failopen", "reason": ""}


def is_blocked(decision: dict) -> bool:
    """True when the gate's binding decision is a deny."""
    return not decision.get("allow", True)


def generic_denial(decision: dict | None = None) -> str:
    """The client-facing message for a blocked action — never the internal reason."""
    return _GENERIC_DENY
