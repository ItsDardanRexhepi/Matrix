"""
Capability Registry — programmatic interface on top of the catalog.

Wraps ServiceDispatcher so callers can:
    * enumerate capabilities (by category, protocol, tier)
    * fetch metadata for a single capability
    * invoke a capability generically via its id

Trinity's ReAct tool (`platform_action`) still works unchanged — this
class is a higher-level facade used by the gateway's /api/v1/capabilities
endpoints and by tooling that needs descriptor metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.capabilities import catalog

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Facade over the capability catalog + service dispatcher."""

    def __init__(self, config: dict, dispatcher: Any | None = None) -> None:
        self._config = config
        self._dispatcher = dispatcher  # ServiceDispatcher instance (optional)

    # ── Read-only views ───────────────────────────────────────────────────

    def list_capabilities(
        self,
        *,
        category: str | None = None,
        available_only: bool = False,
        min_tier: str | None = None,
    ) -> list[dict]:
        results = catalog.CAPABILITIES
        if category:
            results = [c for c in results if c["category"] == category]
        if available_only:
            results = [c for c in results if c["available"]]
        if min_tier:
            tier_order = ["free", "pro", "enterprise"]
            if min_tier in tier_order:
                max_idx = tier_order.index(min_tier)
                results = [c for c in results if tier_order.index(c["min_tier"]) <= max_idx]
        return list(results)

    def list_by_category(self) -> list[dict]:
        """Return categories with their capabilities embedded."""
        out = []
        for cat in catalog.list_categories():
            out.append({
                **cat,
                "capabilities": catalog.get_by_category(cat["id"]),
            })
        return out

    def list_categories(self) -> list[dict]:
        return catalog.list_categories()

    def describe(self, capability_id: str) -> dict | None:
        return catalog.get_by_id(capability_id)

    # ── Invocation ────────────────────────────────────────────────────────

    async def invoke(
        self,
        capability_id: str,
        params: dict | None = None,
        *,
        caller_identity: str = "",
    ) -> dict:
        """Execute a capability via its descriptor.

        Translates the capability id to its ACTION_MAP action and delegates
        to the underlying ServiceDispatcher. If no dispatcher was injected,
        lazy-loads one from the standard registry.

        Parameters
        ----------
        caller_identity:
            The identity the gateway bound for this request, or "" when there is
            none: a session's identity when a session is presented, otherwise
            the caller-written X-Wallet-Address header, else a body ``wallet``,
            ``from``, ``sender`` or ``account`` field or ``params.from``, so it is
            authenticated only in the first case. See DOMAIN 17-D below. Keyword-only and
            defaulting to "" so the existing two-argument call sites keep
            working unchanged.
        """
        # ── DOMAIN 17-D, SECOND GATEWAY ENTRY POINT ───────────────────────
        # `gateway/bridge.py` was not the only live HTTP path that knew the
        # caller and threw the answer away. This method backs
        # ``POST /api/v1/capabilities/{id}/invoke``
        # (gateway/service_routes.py:_handle_capability_invoke), and
        # ``set_nft_rights`` is capability id 'set_nft_rights' in the catalog —
        # so the same IP-rights grant is reachable here, through the same
        # dispatcher, as on the bridge.
        #
        # The identity is NOT missing on this path either. `gateway/server.py`'s
        # `_security_context_middleware` binds it for EVERY ``POST /api/v1/*``
        # request, so `current_request_security()["wallet"]` is populated at the
        # moment this runs. Measured before this change: invoking
        # `set_nft_rights` through this route with a bound identity recorded
        # `set_by: ""` — the wallet was one frame up and never asked for.
        #
        # It is READ IN THE HANDLER, not here. `runtime/` does not import
        # `gateway.security_gate` — and the repo already has the idiom for it
        # (`_handle_governance_vote`, `_handle_insurance_claim`: "a bound
        # identity always wins, a body-supplied field is a dev fallback only").
        # Taking it as a parameter keeps that direction of dependency and keeps
        # the three non-HTTP callers, which bind no caller identity, working
        # with the honest "" default.

        cap = catalog.get_by_id(capability_id)
        if cap is None:
            return {
                "status": "error",
                "error": "unknown_capability",
                "capability_id": capability_id,
            }

        dispatcher = self._dispatcher
        if dispatcher is None:
            # Lazy import to avoid circular deps at module import time.
            from runtime.blockchain.services.service_dispatcher import (
                ServiceDispatcher,
            )

            # NEW-9: this passed a freshly-built ServiceRegistry as a second
            # positional argument. ServiceDispatcher.__init__ takes only
            # (self, config) and resolves its own registry lazily, so every
            # capability invocation raised
            #   TypeError: ServiceDispatcher.__init__() takes 2 positional
            #   arguments but 3 were given
            # and POST /api/v1/capabilities/{id}/invoke answered 500 — the whole
            # capability-invoke surface was dead. Signature drift, not a missing
            # feature: the dispatcher works, the call site was wrong.
            dispatcher = ServiceDispatcher(self._config)
            self._dispatcher = dispatcher

        action = cap["action"]

        # NEW-9 (second fault in the same call): execute() is
        # `execute(action: str, service=None, params=None)`, but this passed a
        # single {"action":..., "params":...} dict as the first positional arg.
        # `action` was therefore a dict, and the `action not in ACTION_MAP`
        # membership test raised `TypeError: unhashable type: 'dict'`. Fixing
        # the constructor arity above only moved the failure here; both had to
        # go for the capability-invoke surface to work at all.
        #
        # The old `except AttributeError` fallback to dispatch_tool is removed:
        # execute() exists, the fallback never fired for the real fault (a
        # TypeError), and a silent fallback around a broken call is exactly the
        # shape that let this survive unnoticed. If execute() ever disappears,
        # an AttributeError should be loud.
        # 17-D: `caller_identity` is threaded as its own argument; this method
        # does not read it out of `params`. That keeps `params["caller_identity"]`
        # from naming the caller: the dispatcher overwrites that one key with
        # the threaded value. It does NOT keep a body-written address out.
        # `params` is the request body on this route, and when the request
        # carries no session and no X-Wallet-Address header, the security
        # middleware has already bound a body `wallet`, `from`, `sender` or
        # `account` field, or `params.from`, and the handler passes that here
        # as `caller_identity`. It is then recorded as the caller.
        result = await dispatcher.execute(
            action=action, params=params or {}, caller_identity=caller_identity,
        )
        return {
            "status": "ok",
            "capability_id": capability_id,
            "action": action,
            "result": result,
        }


__all__ = ["CapabilityRegistry"]
