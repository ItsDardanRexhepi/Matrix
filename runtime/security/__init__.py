"""Security seam for 0pnMatrx — the interface to the closed-source layer.

This package is a BOUNDARY, not an implementation. It exposes the security
contract the open platform calls (the Morpheus gate, OTP, owner verification)
and binds it to the private ``morpheus_security`` package **if that package is
installed**. If it is not — an open-source clone, or local dev — the gate falls
back to an inert OBSERVE no-op that allows every action it evaluates; the
per-agent tool boundary falls back to the public coarse default
(``runtime.access_policy``), which still refuses; OTP and owner verification
fail closed. The other public checks keep running too, among them the
seam-level refusals, the Rexhepi (URF) gate and the Glasswing audit block in
``ProtocolStack.pre_action``. The platform boots either way.

A developer reading this repo can see that security IS invoked and where; the
rules for HOW it decides (detection, classification, bans, owner/OTP internals,
sanitizer patterns) live only in the private package and never appear here.

  - Real enforcement  → install ``morpheus_security`` (private), co-located at deploy.
  - No private package → OBSERVE no-op gate (blocks nothing); the public checks
    still run (per-agent boundary, seam-level refusals, Rexhepi gate, Glasswing
    audit block, fail-closed owner verification and OTP).

The Glasswing contract auditor (``audit.py``) is a separate, open feature and is
imported directly as ``runtime.security.audit`` — it does not pass through here.

See ``runtime/security/SECURITY_INTERFACE.md`` and the public ``SECURITY_STUB.md``.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

try:
    # Real enforcement core (the private package). Present only
    # when co-installed at deploy. The seam imports names, never logic.
    from morpheus_security import (  # type: ignore
        MorpheusMode,
        MorpheusSecurity,
        OTPService,
        OwnerVerification,
        get_morpheus_security,
        reset_morpheus_security,
        evaluate_agent_access as _private_agent_access,
        get_app_attest_verifier,
    )

    SECURITY_BACKEND = "morpheus_security"
    logger.info("Security backend: morpheus_security (real enforcement available)")

except (ImportError, ModuleNotFoundError):
    # H2/RUN-11: this was `except Exception`, which conflated two completely
    # different situations:
    #
    #   "the private package is not installed"  — legitimate. Local dev, CI,
    #       and the open-source checkout all run this way, and degrading to an
    #       inert OBSERVE no-op is the correct, documented behaviour.
    #
    #   "the package IS installed and blew up while loading" — a broken
    #       security core. Swallowing that silently turned a loud failure into
    #       a silent disarming: the gateway came up reporting itself fine, with
    #       nothing enforcing. That is the NEW-18 silent-fallback shape sitting
    #       on the security boundary.
    #
    # Only the first is caught now. Anything else propagates, because a
    # security core that cannot load should stop the process, not quietly
    # remove itself.
    SECURITY_BACKEND = "noop"
    _private_agent_access = None
    logger.warning(
        "Security backend: noop. The private morpheus_security package is not "
        "installed; the Morpheus gate is an OBSERVE no-op (it blocks nothing). "
        "The public checks in this repository still run, including the per-agent "
        "tool boundary, the seam-level refusals on platform-signed actions, the "
        "Rexhepi (URF) gate, the Glasswing audit block on contract deployments, "
        "and fail-closed owner verification and OTP. "
        "Install morpheus_security for real enforcement (see SECURITY_INTERFACE.md)."
    )

    class MorpheusMode(str, Enum):  # type: ignore[no-redef]
        OBSERVE = "observe"
        ENFORCE = "enforce"

    class _NoopMorpheus:
        """Inert gate: allows every action it evaluates and makes no security
        decision. It does not log; its decision (``backend: "noop"``) is
        returned to the caller, which records it in the pre-action result."""

        mode = MorpheusMode.OBSERVE

        async def evaluate(self, action: Any, context: Any) -> dict[str, Any]:
            return {
                "allow": True,
                "would_block": False,
                "route": "observe",
                "classification": "unknown",
                "reason": "security backend not installed (observe no-op)",
                "mode": "observe",
                "backend": "noop",
            }

        async def initialize(self) -> None:
            return None

        async def persist_security_state(self) -> dict[str, Any]:
            return {"bans_written": 0, "bans_onchain": 0,
                    "alerts_sent": 0, "breach_onchain": 0, "backend": "noop"}

    class MorpheusSecurity(_NoopMorpheus):  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class OTPService:  # type: ignore[no-redef]
        """Inert OTP service: never sends or verifies (no backend)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"sent": False, "reason": "security backend not installed"}

        async def verify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"verified": False, "reason": "security backend not installed"}

    class OwnerVerification:  # type: ignore[no-redef]
        """Inert owner verification: never authorizes (fail-closed for owner
        actions; the platform itself stays usable, only owner-gated ops are off)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def start_owner_otp(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"sent": False, "reason": "security backend not installed"}

        async def authorize_owner_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"authorized": False, "reason": "security backend not installed"}

    _noop_singleton: _NoopMorpheus | None = None

    def get_morpheus_security(config: dict[str, Any] | None = None) -> MorpheusSecurity:
        global _noop_singleton
        if _noop_singleton is None:
            _noop_singleton = MorpheusSecurity()
        return _noop_singleton  # type: ignore[return-value]

    def reset_morpheus_security() -> None:
        global _noop_singleton
        _noop_singleton = None

    class _NoopAppAttestVerifier:
        """Inert App Attest verifier: no challenges, no verification (no backend)."""

        enforce = False

        async def new_challenge(self, identity: str) -> str:
            raise RuntimeError("security backend not installed")

        async def verify_attestation(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"verified": False, "reason": "security backend not installed"}

        async def verify_assertion(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"verified": False, "reason": "security backend not installed"}

    _noop_attest_singleton: _NoopAppAttestVerifier | None = None

    def get_app_attest_verifier(config: dict[str, Any] | None = None):
        global _noop_attest_singleton
        if _noop_attest_singleton is None:
            _noop_attest_singleton = _NoopAppAttestVerifier()
        return _noop_attest_singleton


def agent_access_allowed(
    agent: str | None,
    tool: str,
    action: str | None = None,
    context: dict | None = None,
) -> tuple[bool, str]:
    """Per-agent tool-access decision, bound through the security seam.

    The ToolDispatcher calls this on EVERY tool call, keyed on the trusted
    ``agent`` from the request context. The authoritative policy lives in the
    private ``morpheus_security`` package when installed; otherwise the public
    coarse default (``runtime.access_policy``) applies. Either way the per-agent
    boundary is enforced — a subverted agent cannot reach another agent's tools.

    On any internal error, falls back to the public default (the boundary still
    holds — it never fails open).
    """
    if _private_agent_access is not None:
        try:
            verdict = _private_agent_access(agent, tool, action, context)
            return bool(verdict.get("allowed", False)), str(verdict.get("reason", ""))
        except Exception:
            logger.exception("Private agent-access policy failed; using public default")
    from runtime.access_policy import default_agent_access
    return default_agent_access(agent, tool, action)


__all__ = [
    "MorpheusSecurity",
    "MorpheusMode",
    "get_morpheus_security",
    "reset_morpheus_security",
    "OTPService",
    "OwnerVerification",
    "get_app_attest_verifier",
    "SECURITY_BACKEND",
    "agent_access_allowed",
]
