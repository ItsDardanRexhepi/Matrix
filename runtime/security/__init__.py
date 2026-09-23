"""Security seam for The Matrix — the interface to the closed-source layer.

This package is a BOUNDARY, not an implementation. It exposes the security
contract the open platform calls (the Morpheus gate, OTP, owner verification)
and binds it to the private ``morpheus_security`` package **if that package is
installed**. If it is not — an open-source clone, or local dev — the seam falls
back to an inert OBSERVE no-op: every action is allowed and logged, nothing is
enforced. The platform boots either way.

A developer reading this repo can see that security IS invoked and where; the
rules for HOW it decides (detection, classification, bans, owner/OTP internals,
sanitizer patterns) live only in the private package and never appear here.

  - Real enforcement  → install ``morpheus_security`` (private), co-located at deploy.
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
    # Real enforcement core (the separately installed private package). Present
    # only when co-installed at deploy. The seam imports names, never logic.
    from morpheus_security import (  # type: ignore
        MorpheusMode,
        MorpheusSecurity,
        OTPService,
        OwnerVerification,
        get_morpheus_security as _backend_get_gate,
        reset_morpheus_security as _backend_reset_gate,
        evaluate_agent_access as _private_agent_access,
        get_app_attest_verifier,
    )

    # The rule the core names a caller by (see "One spelling for a caller"
    # below). Imported on its own: a core that does not export it is still an
    # installed core and must not fall back to the no-op; the host declines to
    # start its gate instead.
    try:
        from morpheus_security import canonical_identity as _backend_canonical_identity  # type: ignore
    except ImportError:
        _backend_canonical_identity = None

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
    # The no-op records nothing about any caller; it names a caller the
    # platform's way.
    from runtime.auth.identity import canonical_identity as _backend_canonical_identity
    logger.warning(
        "Security backend: noop. The private morpheus_security package is not "
        "installed; the platform runs with security in OBSERVE (no enforcement). "
        "Install morpheus_security for real enforcement (see SECURITY_INTERFACE.md)."
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

    def _backend_get_gate(config: dict[str, Any] | None = None) -> MorpheusSecurity:
        global _noop_singleton
        if _noop_singleton is None:
            _noop_singleton = MorpheusSecurity()
        return _noop_singleton  # type: ignore[return-value]

    def _backend_reset_gate() -> None:
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


# ── The caller's identity in a seam context ───────────────────────────────

#: The one key under which the platform hands the seam the caller's identity
#: when it builds a context for a security decision: the value the entry point
#: bound (a session's wallet), never one a model wrote into tool arguments, and
#: a wallet address in its one spelling (runtime/auth/identity.py). What the
#: core does with it is the core's business; that it arrives is ours.
CALLER_IDENTITY_KEY = "wallet_address"


# ── The process-wide gate: the host builds it, every other caller receives it ──
#
# The gate is process-wide so the state it keeps is shared by every request.
# The backend builds it for whichever caller asks first, with that caller's
# config, and most callers ask with less than the whole: every gated HTTP route
# asks with no config, the chat path and the hand-off with no database. So when
# the gateway's own start of the gate failed, the next request rebuilt it,
# silently, without the database or the gate's settings, and every later caller
# was handed that one.
#
# The split: a HOST (the gateway, at startup) builds the gate from its full
# config and loads its durable state, and only then is the gate handed out.
# While the host is starting it, and after the host's start failed, the accessor
# raises SecurityGateUnavailable instead of building a lesser gate. While the
# host's gate is not up (security_gate_withheld), every caller that would ask
# it refuses instead and asks no other policy in its place: the per-agent tool
# boundary (agent_access_allowed) refuses every tool call, the HTTP gate
# (gateway/security_gate.py) refuses every gated action, reads included, and
# the chat path's pre-action check (runtime/protocols/integration.py) refuses
# every tool call it is asked about. No decision about a request is made while
# the host's gate is down. With no host (a script, the CLI, a test that boots
# no gateway) the accessor and the boundary behave as they always have.

class SecurityGateUnavailable(RuntimeError):
    """The process-wide gate is not up: its host is still starting it, or its
    start failed. Callers treat this exactly as a gate fault."""


class SecurityGateStartFailed(SecurityGateUnavailable):
    """The host's start of the gate failed.

    ``stage`` names the step: ``"identity"`` (the backend does not name a
    caller the way the platform does, so nothing was built), ``"construct"``
    or ``"initialize"``. ``gate`` is the gate object when it was built and did
    not finish loading (the host keeps writing back whatever it comes to
    hold), and None otherwise.
    """

    _STEP = {"identity": "name a caller the way the platform does"}

    def __init__(self, stage: str, cause: BaseException, gate: Any = None) -> None:
        super().__init__(f"the security gate failed to {self._STEP.get(stage, stage)}: {cause}")
        self.stage = stage
        self.gate = gate


_HOST_NONE, _HOST_STARTING, _HOST_UP, _HOST_FAILED = "none", "starting", "up", "failed"
_GATE_NOT_UP_REFUSAL = "The security gate is not available, so no tool can run."
_host_phase: str = _HOST_NONE
_host_gate: Any = None


def get_morpheus_security(config: dict[str, Any] | None = None) -> MorpheusSecurity:
    """The process-wide gate.

    Under a host this is the gate the host built, whatever ``config`` the
    caller passes; it never builds another. While the host is starting it, or
    after the host's start failed, it raises SecurityGateUnavailable. With no
    host the backend builds it on first use, as it always has.
    """
    if _host_phase == _HOST_UP:
        return _host_gate
    if _host_phase == _HOST_STARTING:
        raise SecurityGateUnavailable("the process-wide security gate is still starting")
    if _host_phase == _HOST_FAILED:
        raise SecurityGateUnavailable("the process-wide security gate failed to start")
    return _backend_get_gate(config)


# ── One spelling for a caller, on both sides of the seam ─────────────────
#
# The platform names a caller in one spelling (runtime/auth/identity.py) and
# hands the seam that spelling. The core keeps records about callers and
# compares the caller it is handed against them. If it named a caller any
# other way, a record it holds under another spelling of the same wallet would
# match no caller the platform hands it, so the platform settling on one
# spelling would make that record bind for nobody. The core therefore names a
# caller by the same rule, exported as ``canonical_identity``, and before the
# host starts the gate it checks that the rule the backend exports gives the
# platform's answer for every spelling below. A backend that exports no rule,
# or another one, is not started: the start fails at stage "identity" and is
# handled like any other failed start (production refuses to start; elsewhere
# the gate is withheld and every request it would decide is refused). How the
# core applies the rule to what it holds is the core's.

_SPELLINGS = (
    "0x" + "aB" * 20,
    "0X" + "Ab" * 20,
    "0x" + "AB" * 20,
    "0x" + "ab" * 20,
    "  0x" + "Ab" * 20 + "\n",
    "apple:AbC",
    "Label",
    "0x" + "ab" * 19,
    "",
)


def backend_names_callers_as_the_platform_does() -> bool:
    """True when the installed backend exports a rule for naming a caller and
    it gives the platform's answer (runtime/auth/identity.py) for every
    spelling the host tries."""
    from runtime.auth.identity import canonical_identity

    rule = _backend_canonical_identity
    if not callable(rule):
        return False
    try:
        return all(rule(v) == canonical_identity(v) for v in _SPELLINGS)
    except Exception:
        logger.exception("the security backend's rule for naming a caller raised")
        return False


async def start_security_gate(config: dict[str, Any]) -> MorpheusSecurity:
    """HOST ONLY. Build the process-wide gate from the host's full config and
    load its durable state, before anything is served.

    The gate is handed out only once both steps succeed, and neither is taken
    unless the backend names a caller the way the platform does (above). A
    gate that an earlier caller built from its own, lesser config is dropped
    first, so the host's gate is built from the host's config rather than
    adopted. On failure this raises SecurityGateStartFailed, and the accessor
    raises from then on until the host releases its declaration.
    """
    global _host_phase, _host_gate
    _host_phase, _host_gate = _HOST_STARTING, None
    try:
        _backend_reset_gate()
    except Exception as exc:
        _host_phase = _HOST_FAILED
        raise SecurityGateStartFailed("construct", exc) from exc
    if not backend_names_callers_as_the_platform_does():
        _host_phase = _HOST_FAILED
        raise SecurityGateStartFailed("identity", RuntimeError(
            "the installed security core does not export canonical_identity, or "
            "its rule gives another spelling than runtime/auth/identity.py, so a "
            "record it holds about a caller could match no caller the platform "
            "names"))
    try:
        gate = _backend_get_gate(config)
    except Exception as exc:
        _host_phase = _HOST_FAILED
        raise SecurityGateStartFailed("construct", exc) from exc
    try:
        await gate.initialize()
    except Exception as exc:
        _host_phase = _HOST_FAILED
        raise SecurityGateStartFailed("initialize", exc, gate=gate) from exc
    _host_phase, _host_gate = _HOST_UP, gate
    return gate


def security_gate_state() -> str:
    """``"none"`` (no host), ``"starting"``, ``"up"`` or ``"failed"``. Read by
    the host's readiness check. The cause of a failure is the host's to log."""
    return _host_phase


def security_gate_withheld() -> bool:
    """True while a host has declared the gate and it is not up: still
    starting, or its start failed. Every caller that would otherwise decide a
    request with the gate refuses it instead, and asks no other policy in the
    gate's place (the tool boundary below, the HTTP gate, the chat path's
    pre-action check)."""
    return _host_phase in (_HOST_STARTING, _HOST_FAILED)


def release_security_gate() -> None:
    """HOST ONLY, at shutdown: withdraw the declaration, so a later host in the
    same process starts from nothing. The gate object itself is untouched."""
    global _host_phase, _host_gate
    _host_phase, _host_gate = _HOST_NONE, None


def reset_morpheus_security() -> None:
    """Test/lifecycle helper: drop the gate and any host declaration, so the
    next get_morpheus_security() builds it again."""
    release_security_gate()
    _backend_reset_gate()


def agent_access_allowed(
    agent: str | None,
    tool: str,
    action: str | None = None,
    context: dict | None = None,
) -> tuple[bool, str]:
    """Per-agent tool-access decision, bound through the security seam.

    The ToolDispatcher calls this on EVERY tool call, keyed on the trusted
    ``agent`` from the request context, with a ``context`` that carries the
    caller the entry point bound (under ``CALLER_IDENTITY_KEY``, when there is
    one), so the decision can be about this caller and not only this agent.
    The authoritative policy lives in the
    private ``morpheus_security`` package when installed; otherwise the public
    coarse default (``runtime.access_policy``) applies. Either way the per-agent
    boundary is enforced — a subverted agent cannot reach another agent's tools.

    On any internal error, falls back to the public default (the boundary still
    holds — it never fails open).

    While a host has declared the gate and it is not up (still starting, or
    its start failed), every call is refused and neither policy is asked. A
    decision about this caller belongs with the gate; with no gate to hand
    out, nothing is asked in its place, as the accessor above hands out no
    other gate. With no host (a script, the CLI) the policy decides as it
    always has.
    """
    if security_gate_withheld():
        return False, _GATE_NOT_UP_REFUSAL
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
    "CALLER_IDENTITY_KEY",
    "SecurityGateUnavailable",
    "SecurityGateStartFailed",
    "start_security_gate",
    "security_gate_state",
    "security_gate_withheld",
    "backend_names_callers_as_the_platform_does",
    "release_security_gate",
]
