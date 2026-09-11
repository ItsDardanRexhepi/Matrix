from __future__ import annotations

"""
Unified Rexhepi Framework — Operational Reasoning Loop.

This module implements Part II of the Unified Rexhepi Framework (URF):
the operational decision protocol, expressed as a reasoning loop that
every governed decision passes through before it is allowed to execute.

The loop is deliberately model-agnostic and deterministic. Given a
candidate action (a "trajectory") and its context, it:

1. Scores six gates in the fixed order C, F, R, U, V, CE (0-3 each),
   against anchored rubrics. Scoring order is fixed so the outcome
   cannot be chosen first and rationalised backward (URF §14.1).
2. Applies the inviolable hard rules that remove a trajectory from the
   feasible set regardless of gate scores (URF §13).
3. Resolves exactly one canonical outcome — EXECUTE, PROBE, ASK, DEFER,
   or ABORT (URF §12) — via the default-move logic of URF §10.
4. Emits a compact, auditable record following the URF §14.3 logging
   schema.

Scores may be supplied explicitly by a caller (e.g. an agent's own
reasoning, a second scorer, or a test vector). When they are not, the
loop derives them heuristically from the action and context so ordinary,
well-specified, low-risk actions resolve to EXECUTE and only genuinely
risky, unclear, or uncertain trajectories diverge.

The mapping from theory to execution (URF §9):
    Clarity            → specification of the feasible set T_feasible
    Feasibility        → whether the candidate trajectory lies within it
    Risk + Uncertainty → concrete meaning for the uncertainty measure P
    Value              → the evaluation functional U
    Capability Exp.    → a directional preference within U toward
                         trajectories that enlarge T_feasible over time
    Canonical outcomes → the selection operator solved under real
                         conditions with imperfect information.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ── Gates (URF §10) ──────────────────────────────────────────────────

class Gate(str, Enum):
    """The six scored evaluation gates, in canonical scoring order."""

    CLARITY = "C"
    FEASIBILITY = "F"
    RISK = "R"
    UNCERTAINTY = "U"
    VALUE = "V"
    CAPABILITY_EXPANSION = "CE"


# Fixed scoring order — never reorder (URF §14.1: score C, F, R, U, V, CE
# so the outcome cannot be chosen first and rationalised backward).
GATE_ORDER: tuple[Gate, ...] = (
    Gate.CLARITY,
    Gate.FEASIBILITY,
    Gate.RISK,
    Gate.UNCERTAINTY,
    Gate.VALUE,
    Gate.CAPABILITY_EXPANSION,
)

# Gates where higher is worse (asymmetric-caution rule, URF §14.1: when
# torn between two scores, record the lower for C, F, V and the higher
# for R, U).
_HIGHER_IS_WORSE: frozenset[Gate] = frozenset({Gate.RISK, Gate.UNCERTAINTY})

_MIN_SCORE = 0
_MAX_SCORE = 3


class TimeSensitivity(str, Enum):
    """Per-decision time modifier (URF §11)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Outcome(str, Enum):
    """The five canonical outcomes (URF §12). Every governed decision
    produces exactly one — there is no partially committed conclusion."""

    EXECUTE = "EXECUTE"
    PROBE = "PROBE"
    ASK = "ASK"
    DEFER = "DEFER"
    ABORT = "ABORT"


# ── Hard rules (URF §13) ─────────────────────────────────────────────

class HardRule(str, Enum):
    """Inviolable constraints. Trajectories that violate them are removed
    from the feasible set regardless of gate scores."""

    NO_UNAPPROVED_OUTREACH = "no_external_publish_without_approval"   # (1)
    NO_DESTRUCTIVE_WITHOUT_ROLLBACK = "no_destructive_without_rollback"  # (2)
    NO_LOOPS = "no_loops_after_two_failures"                          # (3)
    DEFINITION_OF_DONE = "artifact_and_verification_required"         # (4)
    INDEPENDENCE = "governance_is_not_evidence"                       # (5)


@dataclass
class GateScores:
    """The seven-tuple that shapes a governed decision (URF §12 output
    line: C=?, F=?, R=?, U=?, V=?, CE=?, T=?)."""

    clarity: int = 3
    feasibility: int = 3
    risk: int = 0
    uncertainty: int = 0
    value: int = 2
    capability_expansion: int = 1
    time_sensitivity: TimeSensitivity = TimeSensitivity.LOW

    def __post_init__(self) -> None:
        self.clarity = _clamp(self.clarity)
        self.feasibility = _clamp(self.feasibility)
        self.risk = _clamp(self.risk)
        self.uncertainty = _clamp(self.uncertainty)
        self.value = _clamp(self.value)
        self.capability_expansion = _clamp(self.capability_expansion)
        if not isinstance(self.time_sensitivity, TimeSensitivity):
            self.time_sensitivity = _coerce_time(self.time_sensitivity)

    def get(self, gate: Gate) -> int:
        return {
            Gate.CLARITY: self.clarity,
            Gate.FEASIBILITY: self.feasibility,
            Gate.RISK: self.risk,
            Gate.UNCERTAINTY: self.uncertainty,
            Gate.VALUE: self.value,
            Gate.CAPABILITY_EXPANSION: self.capability_expansion,
        }[gate]

    def compact(self) -> str:
        """The one-line gate score summary (URF §12)."""
        return (
            f"C={self.clarity}, F={self.feasibility}, R={self.risk}, "
            f"U={self.uncertainty}, V={self.value}, CE={self.capability_expansion}, "
            f"T={self.time_sensitivity.value}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "C": self.clarity,
            "F": self.feasibility,
            "R": self.risk,
            "U": self.uncertainty,
            "V": self.value,
            "CE": self.capability_expansion,
            "T": self.time_sensitivity.value,
        }


@dataclass
class URFDecision:
    """The result of one pass through the reasoning loop."""

    decision_id: str
    outcome: Outcome
    scores: GateScores
    rationale: str
    task: str = ""
    hard_rule_violations: list[str] = field(default_factory=list)
    stop_condition: str = ""
    verification_method: str = ""
    requires_approval: bool = False
    timestamp: float = field(default_factory=time.time)

    @property
    def approved(self) -> bool:
        """Back-compat convenience: only EXECUTE is a green light to act."""
        return self.outcome is Outcome.EXECUTE

    def compact_line(self) -> str:
        """The compact, complete, auditable output block (URF §12)."""
        return f"Decision: {self.outcome.value}\n{self.scores.compact()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "outcome": self.outcome.value,
            "approved": self.approved,
            "scores": self.scores.to_dict(),
            "rationale": self.rationale,
            "hard_rule_violations": list(self.hard_rule_violations),
            "requires_approval": self.requires_approval,
            "stop_condition": self.stop_condition,
            "verification_method": self.verification_method,
            "timestamp": self.timestamp,
        }

    def to_log_entry(
        self,
        *,
        owner: str = "",
        reviewer: str = "",
        evidence: list[str] | None = None,
        artifact: str = "",
        status: str = "open",
        revisit_date: str = "",
    ) -> dict[str, Any]:
        """Machine-readable record following the URF §14.3 logging schema:
        identifier, date, task, the seven scores, outcome, rationale line,
        evidence pointers, hard-rule check, artifact, verification method,
        stop condition, owner, reviewer, status, and revisit date."""
        return {
            "id": self.decision_id,
            "date": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "task": self.task,
            "scores": self.scores.to_dict(),
            "outcome": self.outcome.value,
            "rationale": self.rationale,
            "evidence": list(evidence or []),
            "hard_rule_check": (
                "clear" if not self.hard_rule_violations
                else "; ".join(self.hard_rule_violations)
            ),
            "artifact": artifact,
            "verification_method": self.verification_method,
            "stop_condition": self.stop_condition,
            "owner": owner,
            "reviewer": reviewer,
            "status": status,
            "revisit_date": revisit_date,
        }


def _clamp(value: Any) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(_MIN_SCORE, min(_MAX_SCORE, n))


def _coerce_time(value: Any) -> TimeSensitivity:
    if isinstance(value, TimeSensitivity):
        return value
    text = str(value or "").strip().lower()
    for t in TimeSensitivity:
        if t.value == text:
            return t
    if text in ("med", "m"):
        return TimeSensitivity.MEDIUM
    if text in ("hi", "h", "urgent"):
        return TimeSensitivity.HIGH
    return TimeSensitivity.LOW


# ── Value-moving / destructive / external heuristics ─────────────────

_STATE_CHANGE_HINTS = (
    "deploy", "send", "transfer", "swap", "stake", "unstake", "mint",
    "burn", "withdraw", "borrow", "repay", "bridge", "execute", "buy",
    "sell", "vote", "claim", "approve", "sign", "pay", "purchase",
    "delete", "revoke", "settle", "liquidate",
)

_DESTRUCTIVE_HINTS = (
    "delete", "drop", "wipe", "destroy", "revoke", "burn", "self_destruct",
    "selfdestruct", "purge", "reset",
)

_EXTERNAL_HINTS = (
    "publish", "outreach", "post", "tweet", "announce", "email", "broadcast",
    "send_notification", "notify_external", "dm", "message",
)


class URFReasoningLoop:
    """The Unified Rexhepi Framework operational layer, as a reasoning loop.

    Call :meth:`decide` with a candidate action and its context to obtain
    a single canonical outcome, its gate scores, and an auditable rationale.
    Every decision is logged for the URF §14.3 dataset.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._log: list[dict[str, Any]] = []
        self._max_log = int(self.config.get("max_decision_log", 5000))
        # An action is "reversible enough" to relax verification under time
        # pressure only when its risk gate is at or below this level.
        self._reversible_risk_ceiling = int(
            self.config.get("reversible_risk_ceiling", 1)
        )

    # ── Public API ────────────────────────────────────────────────────

    def decide(
        self,
        action: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        *,
        scores: GateScores | dict[str, Any] | None = None,
        task: str = "",
    ) -> URFDecision:
        """Run one pass of the reasoning loop and return a URFDecision.

        ``scores`` may be provided to bypass heuristic scoring (e.g. from a
        second scorer, an LLM, or a test vector); otherwise scores are
        derived from ``action`` and ``context``.
        """
        action = action or {}
        context = context or {}
        task = task or self._describe(action)

        gate_scores = self._resolve_scores(action, context, scores)

        violations = self._check_hard_rules(action, context, gate_scores)

        outcome, rationale, requires_approval = self._resolve_outcome(
            gate_scores, action, context, violations
        )

        stop_condition = self._stop_condition(outcome, gate_scores)
        verification = self._verification_method(outcome, gate_scores)

        decision = URFDecision(
            decision_id=str(uuid.uuid4()),
            outcome=outcome,
            scores=gate_scores,
            rationale=rationale,
            task=task,
            hard_rule_violations=violations,
            stop_condition=stop_condition,
            verification_method=verification,
            requires_approval=requires_approval,
        )

        self._record(decision, action, context)
        logger.info(
            "URF decision=%s outcome=%s (%s) task=%r",
            decision.decision_id, outcome.value, gate_scores.compact(), task[:80],
        )
        return decision

    def get_decision_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent *limit* logged decisions (URF §14.3)."""
        return list(self._log[-limit:])

    # ── Outcome resolution (URF §10 default moves + §12 outcomes) ─────

    def _resolve_outcome(
        self,
        s: GateScores,
        action: dict[str, Any],
        context: dict[str, Any],
        violations: list[str],
    ) -> tuple[Outcome, str, bool]:
        """Resolve exactly one canonical outcome from the gate scores and
        hard-rule check. The ordering encodes the URF precedence: hard
        rules first, then the approval gate, then readiness, value, and the
        clarity/feasibility/uncertainty default moves."""

        # ── Hard rules (URF §13): inviolable, override gate scores ──
        if HardRule.NO_DESTRUCTIVE_WITHOUT_ROLLBACK.value in violations:
            return (
                Outcome.ABORT,
                "Hard rule 2: destructive operation without a rollback plan; "
                "removed from the feasible set.",
                False,
            )
        if HardRule.NO_LOOPS.value in violations:
            return (
                Outcome.ABORT,
                "Hard rule 3: two failed attempts at the same approach — stop "
                "and re-plan rather than trying a third time.",
                False,
            )
        if HardRule.NO_UNAPPROVED_OUTREACH.value in violations:
            return (
                Outcome.ASK,
                "Hard rule 1: no external publishing or outreach without explicit "
                "approval. R=3 exposure requires owner approval before any send.",
                True,
            )

        # ── Risk approval gate (URF §10 Gate 3): when R=3, explicit
        # approval is required before any state change ──
        if s.risk >= _MAX_SCORE and self._is_state_change(action) and not self._approved(action, context):
            return (
                Outcome.ASK,
                "Gate R=3: worst-credible downside is external/irreversible; explicit "
                "approval is required before any state change.",
                True,
            )

        # ── Readiness: very low clarity AND feasibility means the
        # constraint manifold is undefined and the path is unproven —
        # this is not ready to probe yet; park it (DEFER) ──
        if s.clarity < 2 and s.feasibility < 2:
            return (
                Outcome.DEFER,
                "Low Clarity and low Feasibility: the feasible set is undefined and no "
                "path is proven. Build foundations, then revisit.",
                False,
            )

        # ── Value / leverage (URF §10 Gate 5): when V<=1 and anything
        # else is hard, defer; if there is real downside and no durable
        # capability is created, abandon it entirely ──
        something_hard = (
            s.feasibility <= 1 or s.uncertainty >= 2 or s.risk >= 2
        )
        if s.value <= 1 and something_hard:
            if s.risk >= 2 and s.capability_expansion == 0:
                return (
                    Outcome.ABORT,
                    "Gate V<=1 with real downside (R>=2) and no durable capability "
                    "(CE=0): not worth doing; abandon.",
                    False,
                )
            return (
                Outcome.DEFER,
                "Gate V<=1 and the work is hard (low F, high U, or non-trivial R): "
                "park it and revisit when conditions change.",
                False,
            )

        # ── Feasibility (URF §10 Gate 2): F=0 means the candidate
        # trajectory is not in the feasible set ──
        if s.feasibility == 0:
            if s.value >= 2 and s.uncertainty >= 2:
                return (
                    Outcome.DEFER,
                    "Gate F=0 but the trajectory is valuable (V>=2) and blocked by "
                    "high uncertainty (U>=2): defer and revisit on defined conditions.",
                    False,
                )
            return (
                Outcome.ABORT,
                "Gate F=0: the candidate trajectory is not feasible with current "
                "tools, access, time, or skill.",
                False,
            )

        # ── Uncertainty (URF §10 Gate 4): U>=2 → probe to reduce
        # uncertainty before committing. Under high time sensitivity a
        # merely-elevated (U=2), reversible action may proceed with
        # tightened verification instead (URF §11) ──
        if s.uncertainty >= 2:
            if (
                s.uncertainty == 2
                and s.time_sensitivity is TimeSensitivity.HIGH
                and s.risk <= self._reversible_risk_ceiling
                and s.clarity >= 2
                and s.feasibility >= 2
            ):
                return (
                    Outcome.EXECUTE,
                    "Gate U=2 but high time sensitivity and a low-risk, reversible path: "
                    "accept a good-enough solution now with tightened verification and a "
                    "rollback path.",
                    False,
                )
            return (
                Outcome.PROBE,
                "Gate U>=2: outcome is sensitive to factors not yet understood — run "
                "the smallest experiment that reduces uncertainty before committing.",
                False,
            )

        # ── Feasibility probe (URF §10 Gate 2 default when F<2) ──
        if s.feasibility < 2:
            return (
                Outcome.PROBE,
                "Gate F<2: the path is plausible but unproven — run the smallest probe "
                "that proves or disproves it before committing resources.",
                False,
            )

        # ── Clarity (URF §10 Gate 1 default when C<2) ──
        if s.clarity < 2:
            return (
                Outcome.ASK,
                "Gate C<2: acceptance criteria are missing — ask one sharp question or "
                "propose a concrete specification and request confirmation.",
                False,
            )

        # ── Gates satisfied → execute (URF §12) ──
        approval = s.risk >= _MAX_SCORE and self._is_state_change(action)
        return (
            Outcome.EXECUTE,
            "Gates satisfied: clarity, feasibility, and value are adequate and "
            "uncertainty and risk are within bounds — do the work now.",
            approval,
        )

    # ── Hard-rule checks (URF §13) ────────────────────────────────────

    def _check_hard_rules(
        self,
        action: dict[str, Any],
        context: dict[str, Any],
        scores: GateScores,
    ) -> list[str]:
        violations: list[str] = []

        # (2) No destructive operations without a rollback plan.
        if self._is_destructive(action):
            has_rollback = bool(
                action.get("rollback_plan")
                or action.get("reversible")
                or context.get("rollback_plan")
            )
            if not has_rollback:
                violations.append(HardRule.NO_DESTRUCTIVE_WITHOUT_ROLLBACK.value)

        # (3) No loops: after two failed attempts at the same approach, stop.
        attempts = context.get("failed_attempts", action.get("failed_attempts", 0))
        try:
            if int(attempts) >= 2:
                violations.append(HardRule.NO_LOOPS.value)
        except (TypeError, ValueError):
            pass

        # (1) No external publishing/outreach without explicit approval.
        if self._is_external(action) and not self._approved(action, context):
            violations.append(HardRule.NO_UNAPPROVED_OUTREACH.value)

        return violations

    # ── Heuristic gate scoring (anchored rubrics, URF §10) ────────────

    def _resolve_scores(
        self,
        action: dict[str, Any],
        context: dict[str, Any],
        scores: GateScores | dict[str, Any] | None,
    ) -> GateScores:
        if isinstance(scores, GateScores):
            return scores
        if isinstance(scores, dict):
            return _scores_from_dict(scores)

        # Explicit scores may also ride along on the action/context.
        for src in (action.get("urf_scores"), context.get("urf_scores")):
            if isinstance(src, GateScores):
                return src
            if isinstance(src, dict):
                return _scores_from_dict(src)

        return self._heuristic_scores(action, context)

    def _heuristic_scores(
        self, action: dict[str, Any], context: dict[str, Any]
    ) -> GateScores:
        params = action.get("parameters", action.get("params", {})) or {}

        clarity = self._score_clarity(action, context, params)
        feasibility = self._score_feasibility(action, context, params)
        risk = self._score_risk(action, context, params)
        uncertainty = self._score_uncertainty(action, context, params)
        value = self._score_value(action, context, params)
        capability = self._score_capability(action, context, params)
        t = _coerce_time(
            action.get("time_sensitivity", context.get("time_sensitivity", "low"))
        )

        return GateScores(
            clarity=clarity,
            feasibility=feasibility,
            risk=risk,
            uncertainty=uncertainty,
            value=value,
            capability_expansion=capability,
            time_sensitivity=t,
        )

    def _score_clarity(self, action, context, params) -> int:
        missing = action.get("missing_params") or context.get("missing_params")
        if missing:
            return 1
        # An explicitly matched intent with a high confidence is a clear ask.
        confidence = context.get("intent_confidence")
        if isinstance(confidence, (int, float)):
            if confidence >= 0.75:
                return 3
            if confidence >= 0.5:
                return 2
            return 1
        return 3 if params or not self._expects_params(action) else 2

    def _score_feasibility(self, action, context, params) -> int:
        # Preconditions that place the trajectory outside the feasible set.
        if self._is_state_change(action):
            if context.get("wallet_connected") is False:
                return 0
            supported = set(context.get("supported_networks", []) or [])
            network = context.get("network")
            if supported and network and network not in supported:
                return 0
        if context.get("blocked") or action.get("blocked"):
            return 0
        proven = context.get("proven_path")
        if proven is True:
            return 3
        if proven is False:
            return 1
        return 3 if self._is_read(action) else 2

    def _score_risk(self, action, context, params) -> int:
        explicit = action.get("risk_level", action.get("estimated_risk"))
        mapping = {"none": 0, "low": 1, "medium": 2, "moderate": 2, "high": 3, "critical": 3}
        base = mapping.get(str(explicit).lower()) if explicit is not None else None

        heuristic = 0
        if self._is_read(action):
            heuristic = 0
        elif self._is_external(action) or self._is_destructive(action):
            heuristic = 3
        elif self._is_state_change(action):
            heuristic = 2
            # Large or irreversible value transfers escalate to R=3.
            value = params.get("value", params.get("amount"))
            threshold = self.config.get("high_value_threshold", 10000)
            try:
                if value is not None and float(value) >= float(threshold):
                    heuristic = 3
            except (TypeError, ValueError):
                pass
            if action.get("reversible") is False:
                heuristic = 3

        if base is None:
            return heuristic
        # Asymmetric caution (URF §14.1): for R, keep the HIGHER score.
        return max(base, heuristic)

    def _score_uncertainty(self, action, context, params) -> int:
        explicit = action.get("uncertainty")
        if explicit is not None:
            return _clamp(explicit)
        u = 0
        if context.get("previous_error"):
            u = max(u, 2)
        if action.get("depends_on_oracle") or context.get("volatile"):
            u = max(u, 2)
        confidence = context.get("confidence")
        if isinstance(confidence, (int, float)):
            if confidence < 0.3:
                u = max(u, 3)
            elif confidence < 0.6:
                u = max(u, 2)
        return u

    def _score_value(self, action, context, params) -> int:
        explicit = action.get("value_score")
        if explicit is not None:
            return _clamp(explicit)
        if self._is_read(action):
            return 1
        if self._is_state_change(action):
            return 2
        return 2

    def _score_capability(self, action, context, params) -> int:
        explicit = action.get("capability_expansion")
        if explicit is not None:
            return _clamp(explicit)
        label = self._label(action)
        if any(h in label for h in ("deploy", "create", "register", "build", "publish_plugin")):
            return 2
        return 1

    # ── Small classifiers ─────────────────────────────────────────────

    def _label(self, action: dict[str, Any]) -> str:
        params = action.get("parameters", action.get("params", {})) or {}
        return " ".join(
            str(x).lower()
            for x in (
                action.get("action_type"),
                action.get("type"),
                action.get("name"),
                params.get("action"),
            )
            if x
        )

    def _is_state_change(self, action: dict[str, Any]) -> bool:
        if action.get("state_change") is not None:
            return bool(action.get("state_change"))
        if self._is_read(action):
            return False
        label = self._label(action)
        if any(h in label for h in _STATE_CHANGE_HINTS):
            return True
        # Fall back to the platform's coarse value-moving heuristic.
        try:
            from runtime.access_policy import could_move_value
            params = action.get("parameters", action.get("params", {})) or {}
            gated = params.get("action") or action.get("action_type") or action.get("type")
            return could_move_value(gated)
        except Exception:
            return False

    def _is_read(self, action: dict[str, Any]) -> bool:
        if action.get("read_only") is True:
            return True
        try:
            from runtime.access_policy import could_move_value
            params = action.get("parameters", action.get("params", {})) or {}
            gated = params.get("action") or action.get("action_type") or action.get("type")
            if gated:
                return not could_move_value(gated)
        except Exception:
            pass
        return False

    def _is_destructive(self, action: dict[str, Any]) -> bool:
        if action.get("destructive") is not None:
            return bool(action.get("destructive"))
        return any(h in self._label(action) for h in _DESTRUCTIVE_HINTS)

    def _is_external(self, action: dict[str, Any]) -> bool:
        if action.get("external") is not None:
            return bool(action.get("external"))
        return any(h in self._label(action) for h in _EXTERNAL_HINTS)

    def _approved(self, action: dict[str, Any], context: dict[str, Any]) -> bool:
        return bool(
            action.get("user_confirmed")
            or action.get("approved")
            or action.get("owner_approved")
            or context.get("user_confirmed")
            or context.get("owner_approved")
        )

    def _expects_params(self, action: dict[str, Any]) -> bool:
        return self._is_state_change(action)

    # ── Stop condition & verification (URF §11, §13 rule 4, §14.1) ────

    def _stop_condition(self, outcome: Outcome, s: GateScores) -> str:
        if outcome is Outcome.PROBE:
            return "Probe resolves Feasibility>=2 and Uncertainty<2, or the path is disproven."
        if outcome is Outcome.ASK:
            return "A single clarifying answer (or explicit approval) is received."
        if outcome is Outcome.DEFER:
            return "Revisit when the blocking condition changes."
        if outcome is Outcome.ABORT:
            return "Do not retry this trajectory without a materially different approach."
        # EXECUTE — pre-commit the falsification/stop condition (URF §14.4).
        return "Stop if verification fails or the worst-credible downside materialises."

    def _verification_method(self, outcome: Outcome, s: GateScores) -> str:
        if outcome is not Outcome.EXECUTE:
            return ""
        # Definition of done (URF §13 rule 4): every task ends with an
        # artifact and a verification method. Time sensitivity tunes rigour
        # (URF §11).
        if s.time_sensitivity is TimeSensitivity.HIGH:
            return "Tightened post-hoc verification with a confirmed rollback path."
        if s.time_sensitivity is TimeSensitivity.LOW:
            return "Full verification against acceptance criteria before completion."
        return "Verify the produced artifact against acceptance criteria."

    # ── Logging (URF §14.3) ───────────────────────────────────────────

    def _describe(self, action: dict[str, Any]) -> str:
        label = self._label(action).strip()
        return label or "unspecified action"

    def _record(
        self, decision: URFDecision, action: dict[str, Any], context: dict[str, Any]
    ) -> None:
        entry = decision.to_log_entry(
            owner=str(context.get("owner", "")),
            reviewer=str(context.get("reviewer", "")),
            evidence=context.get("evidence"),
        )
        self._log.append(entry)
        if len(self._log) > self._max_log:
            self._log = self._log[-self._max_log:]


def _scores_from_dict(d: dict[str, Any]) -> GateScores:
    """Build GateScores from a dict keyed by either short (C/F/R/U/V/CE/T)
    or long (clarity/feasibility/...) names."""
    def pick(*keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in d:
                return d[k]
        return default

    return GateScores(
        clarity=_clamp(pick("C", "clarity", default=3)),
        feasibility=_clamp(pick("F", "feasibility", default=3)),
        risk=_clamp(pick("R", "risk", default=0)),
        uncertainty=_clamp(pick("U", "uncertainty", default=0)),
        value=_clamp(pick("V", "value", default=2)),
        capability_expansion=_clamp(pick("CE", "capability_expansion", default=1)),
        time_sensitivity=_coerce_time(pick("T", "time_sensitivity", default="low")),
    )
