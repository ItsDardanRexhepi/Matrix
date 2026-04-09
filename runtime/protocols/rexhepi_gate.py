from __future__ import annotations

"""
Rexhepi Framework Execution Gate — every decision passes through this gate.
The public interface to the closed-source framework.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Rate limit defaults
_DEFAULT_RATE_LIMIT_WINDOW = 60  # seconds
_DEFAULT_RATE_LIMIT_MAX = 30     # max actions per window


class RexhepiGate:
    """Unified execution gate. Every platform operation MUST pass
    through this gate before execution.

    Checks: safety, compliance, user authorization, rate limits,
    fee validation.  Logs every evaluation for audit.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._audit_log: list[dict[str, Any]] = []
        self._rate_window: list[float] = []  # timestamps of recent evaluations
        self._rate_limit_window = self.config.get(
            "rate_limit_window_seconds", _DEFAULT_RATE_LIMIT_WINDOW
        )
        self._rate_limit_max = self.config.get(
            "rate_limit_max_actions", _DEFAULT_RATE_LIMIT_MAX
        )
        self._blocked_addresses: set[str] = set(
            self.config.get("blocked_addresses", [])
        )
        self._blocked_action_types: set[str] = set(
            self.config.get("blocked_action_types", [])
        )
        self._max_audit_log = self.config.get("max_audit_log", 5000)
        logger.info("RexhepiGate initialised")

    # ── Public API ────────────────────────────────────────────────────

    async def evaluate(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate *action* against all gate checks.

        Returns:
            approved: bool
            reason: str (empty if approved)
            evaluation_id: str
            checks_passed: list[str]
            checks_failed: list[str]
            timestamp: float
        """
        evaluation_id = str(uuid.uuid4())
        timestamp = time.time()
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        denial_reasons: list[str] = []

        # Run all checks
        checkers = [
            ("safety", self._check_safety),
            ("compliance", self._check_compliance),
            ("authorization", self._check_authorization),
            ("rate_limit", self._check_rate_limit),
            ("fee_validation", self._check_fee_validation),
            ("address_screening", self._check_address_screening),
            ("action_type_allowed", self._check_action_type_allowed),
        ]

        for name, checker in checkers:
            try:
                passed, reason = checker(action, context)
                if passed:
                    checks_passed.append(name)
                else:
                    checks_failed.append(name)
                    denial_reasons.append(reason)
            except Exception as exc:
                logger.exception("Gate check '%s' raised an exception", name)
                checks_failed.append(name)
                denial_reasons.append(f"Internal error in {name} check: {exc}")

        approved = len(checks_failed) == 0
        combined_reason = "; ".join(denial_reasons) if denial_reasons else ""

        result = {
            "approved": approved,
            "reason": combined_reason,
            "evaluation_id": evaluation_id,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "timestamp": timestamp,
        }

        # Log every evaluation
        self._log_evaluation(evaluation_id, action, context, result)

        # Record for rate limiting
        self._rate_window.append(timestamp)

        if approved:
            logger.info("Gate APPROVED evaluation=%s", evaluation_id)
        else:
            logger.warning(
                "Gate DENIED evaluation=%s reason=%s", evaluation_id, combined_reason
            )

        return result

    # ── Audit access ──────────────────────────────────────────────────

    def get_audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent *limit* audit entries."""
        return list(self._audit_log[-limit:])

    # ── Gate checks ───────────────────────────────────────────────────

    def _check_safety(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Reject actions that are unsafe given the user's state."""
        action_type = str(action.get("action_type", action.get("type", "")))

        # Cannot transact without a connected wallet
        if not context.get("wallet_connected", True):
            return False, "No wallet connected. Connect a wallet before performing transactions."

        # Cannot operate on an unsupported network
        supported = set(self.config.get("supported_networks", []))
        network = context.get("network")
        if supported and network and network not in supported:
            return False, f"Network '{network}' is not supported. Supported: {', '.join(sorted(supported))}."

        # Prevent draining the wallet completely (keep dust for gas)
        balance = context.get("balance")
        value = action.get("parameters", {}).get("value", 0)
        if (
            isinstance(balance, (int, float))
            and isinstance(value, (int, float))
            and value > 0
            and balance > 0
        ):
            min_reserve = self.config.get("min_balance_reserve", 0.01)
            if value > balance - min_reserve:
                return False, (
                    f"Insufficient balance. Requested {value} but only "
                    f"{balance} available (reserve {min_reserve} for gas)."
                )

        return True, ""

    def _check_compliance(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Enforce compliance rules (sanctions, restricted jurisdictions)."""
        jurisdiction = context.get("jurisdiction", "").upper()
        restricted = set(self.config.get("restricted_jurisdictions", []))
        if restricted and jurisdiction in restricted:
            return False, f"Operations restricted in jurisdiction '{jurisdiction}'."

        # Age verification for certain categories
        action_type = str(action.get("action_type", action.get("type", "")))
        age_restricted = self.config.get("age_restricted_actions", [])
        if action_type in age_restricted:
            if not context.get("age_verified", False):
                return False, f"Age verification required for '{action_type}'."

        return True, ""

    def _check_authorization(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Verify the user is authorised to perform this action."""
        required_role = action.get("required_role")
        user_roles = set(context.get("user_roles", []))

        if required_role and required_role not in user_roles:
            return False, f"Requires role '{required_role}' but user has {user_roles or 'none'}."

        # Check if user has explicitly approved high-risk actions
        risk_level = action.get("risk_level", action.get("estimated_risk", "low"))
        if risk_level in ("high", "critical"):
            if not action.get("user_confirmed", False):
                return False, (
                    f"Action has '{risk_level}' risk level. "
                    f"User must explicitly confirm before execution."
                )

        return True, ""

    def _check_rate_limit(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Enforce rate limits to prevent abuse or runaway automation."""
        now = time.time()
        cutoff = now - self._rate_limit_window

        # Prune old entries
        self._rate_window = [t for t in self._rate_window if t >= cutoff]

        if len(self._rate_window) >= self._rate_limit_max:
            return False, (
                f"Rate limit exceeded: {self._rate_limit_max} actions "
                f"per {self._rate_limit_window}s window."
            )
        return True, ""

    def _check_fee_validation(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Validate that estimated fees are within acceptable bounds."""
        estimated_fee = action.get("parameters", {}).get("estimated_fee")
        if estimated_fee is None:
            return True, ""  # No fee to validate

        if not isinstance(estimated_fee, (int, float)):
            return True, ""

        max_fee = self.config.get("max_fee_usd", 500)
        if estimated_fee > max_fee:
            return False, (
                f"Estimated fee ${estimated_fee:.2f} exceeds maximum "
                f"allowed ${max_fee:.2f}. Adjust gas or wait for lower fees."
            )

        # Warn if fee is disproportionate to value
        value = action.get("parameters", {}).get("value", 0)
        if isinstance(value, (int, float)) and value > 0:
            fee_ratio = estimated_fee / value
            max_ratio = self.config.get("max_fee_ratio", 0.1)
            if fee_ratio > max_ratio:
                return False, (
                    f"Fee ${estimated_fee:.2f} is {fee_ratio:.0%} of transaction "
                    f"value ${value:.2f}, exceeding {max_ratio:.0%} threshold."
                )

        return True, ""

    def _check_address_screening(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Screen destination addresses against blocklist."""
        to_addr = (
            action.get("parameters", {}).get("to")
            or action.get("parameters", {}).get("recipient")
            or action.get("to")
        )
        if to_addr and to_addr.lower() in {a.lower() for a in self._blocked_addresses}:
            return False, f"Destination address {to_addr} is blocked."
        return True, ""

    def _check_action_type_allowed(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> tuple[bool, str]:
        """Ensure the action type is not globally disabled."""
        action_type = str(action.get("action_type", action.get("type", "")))
        if action_type in self._blocked_action_types:
            return False, f"Action type '{action_type}' is currently disabled."
        return True, ""

    # ── Logging ───────────────────────────────────────────────────────

    def _log_evaluation(
        self,
        evaluation_id: str,
        action: dict[str, Any],
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        entry = {
            "evaluation_id": evaluation_id,
            "action_type": action.get("action_type", action.get("type")),
            "approved": result["approved"],
            "reason": result["reason"],
            "checks_passed": result["checks_passed"],
            "checks_failed": result["checks_failed"],
            "timestamp": result["timestamp"],
            "network": context.get("network"),
            "wallet": context.get("wallet", "")[:10] + "..." if context.get("wallet") else None,
        }
        self._audit_log.append(entry)

        if len(self._audit_log) > self._max_audit_log:
            self._audit_log = self._audit_log[-self._max_audit_log:]
