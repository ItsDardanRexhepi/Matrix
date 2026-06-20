"""Security seam for 0pnMatrx — the interface to the closed-source layer.

This package is a BOUNDARY, not an implementation. It exposes the security
contract the open platform calls (the Morpheus gate, OTP, owner verification)
and binds it to the private ``matrix_security`` package **if that package is
installed**. If it is not — an open-source clone, or local dev — the seam falls
back to an inert OBSERVE no-op: every action is allowed and logged, nothing is
enforced. The platform boots either way.

A developer reading this repo can see that security IS invoked and where; the
rules for HOW it decides (detection, classification, bans, owner/OTP internals,
sanitizer patterns) live only in the private package and never appear here.

  - Real enforcement  → install ``matrix_security`` (private), co-located at deploy.
  - No private package → OBSERVE no-op (safe, non-blocking, no enforcement).

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
    # Real enforcement core (private repo: Matrix-Security-System). Present only
    # when co-installed at deploy. The seam imports names, never logic.
    from matrix_security import (  # type: ignore
        MorpheusMode,
        MorpheusSecurity,
        OTPService,
        OwnerVerification,
        get_morpheus_security,
        reset_morpheus_security,
    )

    SECURITY_BACKEND = "matrix_security"
    logger.info("Security backend: matrix_security (real enforcement available)")

except Exception:  # ImportError, or any load error → inert OBSERVE no-op.
    SECURITY_BACKEND = "noop"
    logger.warning(
        "Security backend: noop. The private matrix_security package is not "
        "installed; the platform runs with security in OBSERVE (no enforcement). "
        "Install matrix_security for real enforcement (see SECURITY_INTERFACE.md)."
    )

    class MorpheusMode(str, Enum):  # type: ignore[no-redef]
        OBSERVE = "observe"
        ENFORCE = "enforce"

    class _NoopMorpheus:
        """Inert gate: allows everything, enforces nothing. Logs that it ran so
        the invocation is observable, but it makes no security decision."""

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


__all__ = [
    "MorpheusSecurity",
    "MorpheusMode",
    "get_morpheus_security",
    "reset_morpheus_security",
    "OTPService",
    "OwnerVerification",
    "SECURITY_BACKEND",
]
