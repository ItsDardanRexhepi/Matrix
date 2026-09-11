"""Tests for the Unified Rexhepi Framework operational reasoning loop.

The canonical-outcome cases are the decision vectors documented in the URF
manuscript itself — the Section 16 deployment log and the Section 17
self-application audit. If the loop implements the protocol faithfully, it
must reproduce those exact outcomes from those exact gate scores.
"""

from __future__ import annotations

import pytest

from runtime.protocols.urf import (
    GateScores,
    HardRule,
    Outcome,
    TimeSensitivity,
    URFDecision,
    URFReasoningLoop,
)
from runtime.protocols.rexhepi_gate import RexhepiGate


def _loop() -> URFReasoningLoop:
    return URFReasoningLoop({})


# ── URF §16 documented deployment + §17 self-application vectors ─────
#
# Each row: (id, C, F, R, U, V, CE, T, flags, expected_outcome)
# flags carries the qualitative facts the scores alone don't encode
# (e.g. that a decision is external outreach requiring approval).

_VECTORS = [
    # Section 16 — documented deployment
    ("s16-001", 3, 3, 1, 0, 3, 3, "low", {}, Outcome.EXECUTE),
    ("s16-002", 3, 3, 0, 1, 2, 1, "low", {}, Outcome.EXECUTE),
    ("s16-003", 2, 3, 3, 1, 3, 2, "low", {"external": True}, Outcome.ASK),
    ("s16-004", 1, 0, 1, 3, 3, 3, "low", {}, Outcome.DEFER),
    ("s16-005", 3, 3, 1, 1, 3, 2, "low", {}, Outcome.EXECUTE),
    # Section 17 — self-application audit
    ("s17-adopt", 3, 3, 1, 1, 3, 2, "low", {}, Outcome.EXECUTE),
    ("s17-p1", 2, 2, 1, 3, 2, 1, "low", {}, Outcome.PROBE),
    ("s17-novelty", 2, 2, 1, 2, 2, 1, "low", {}, Outcome.PROBE),
    ("s17-universality", 1, 1, 1, 3, 2, 2, "low", {}, Outcome.DEFER),
    ("s17-metaphysical", 3, 3, 2, 1, 1, 0, "low", {}, Outcome.ABORT),
    ("s17-publish", 2, 3, 3, 1, 2, 1, "med", {"external": True}, Outcome.ASK),
]


class TestCanonicalOutcomes:
    @pytest.mark.parametrize(
        "vec", _VECTORS, ids=[v[0] for v in _VECTORS]
    )
    def test_documented_vector(self, vec):
        _id, c, f, r, u, v, ce, t, flags, expected = vec
        scores = GateScores(
            clarity=c, feasibility=f, risk=r, uncertainty=u,
            value=v, capability_expansion=ce, time_sensitivity=t,
        )
        action = dict(flags)
        decision = _loop().decide(action, {}, scores=scores, task=_id)
        assert decision.outcome is expected, (
            f"{_id}: expected {expected.value}, got {decision.outcome.value} "
            f"({decision.rationale})"
        )
        # Exactly one canonical outcome, always a member of the enum.
        assert decision.outcome in set(Outcome)

    def test_all_vectors_are_differentiated(self):
        outcomes = {v[9] for v in _VECTORS}
        # A vacuous scorer would collapse to a single outcome; the protocol
        # must produce differentiated verdicts (URF §17).
        assert outcomes == {
            Outcome.EXECUTE, Outcome.PROBE, Outcome.ASK,
            Outcome.DEFER, Outcome.ABORT,
        }


class TestScoringOrderAndClamping:
    def test_scores_are_clamped(self):
        s = GateScores(clarity=9, feasibility=-4, risk=7, uncertainty=2,
                       value=2, capability_expansion=1)
        assert s.clarity == 3
        assert s.feasibility == 0
        assert s.risk == 3

    def test_compact_line_format(self):
        s = GateScores(3, 3, 1, 0, 3, 3, TimeSensitivity.LOW)
        assert s.compact() == "C=3, F=3, R=1, U=0, V=3, CE=3, T=low"

    def test_decision_line(self):
        d = _loop().decide({}, {}, scores=GateScores(3, 3, 0, 0, 3, 2), task="x")
        assert d.compact_line() == "Decision: EXECUTE\nC=3, F=3, R=0, U=0, V=3, CE=2, T=low"


class TestHardRules:
    def test_destructive_without_rollback_aborts(self):
        d = _loop().decide(
            {"action_type": "delete_records", "destructive": True},
            {},
            scores=GateScores(3, 3, 1, 0, 3, 1),
        )
        assert d.outcome is Outcome.ABORT
        assert HardRule.NO_DESTRUCTIVE_WITHOUT_ROLLBACK.value in d.hard_rule_violations

    def test_destructive_with_rollback_not_aborted_by_that_rule(self):
        d = _loop().decide(
            {"action_type": "delete_records", "destructive": True, "rollback_plan": "restore from backup"},
            {},
            scores=GateScores(3, 3, 1, 0, 3, 1),
        )
        assert HardRule.NO_DESTRUCTIVE_WITHOUT_ROLLBACK.value not in d.hard_rule_violations
        assert d.outcome is Outcome.EXECUTE

    def test_no_loops_after_two_failures(self):
        d = _loop().decide(
            {"action_type": "retry_thing"},
            {"failed_attempts": 2},
            scores=GateScores(3, 3, 1, 0, 3, 1),
        )
        assert d.outcome is Outcome.ABORT
        assert HardRule.NO_LOOPS.value in d.hard_rule_violations

    def test_external_outreach_requires_approval(self):
        d = _loop().decide(
            {"action_type": "publish_announcement", "external": True},
            {},
            scores=GateScores(3, 3, 2, 1, 3, 1),
        )
        assert d.outcome is Outcome.ASK
        assert d.requires_approval is True
        assert HardRule.NO_UNAPPROVED_OUTREACH.value in d.hard_rule_violations

    def test_external_outreach_with_approval_can_execute(self):
        d = _loop().decide(
            {"action_type": "publish_announcement", "external": True, "owner_approved": True},
            {},
            scores=GateScores(3, 3, 2, 1, 3, 1),
        )
        assert d.outcome is Outcome.EXECUTE


class TestRiskApprovalGate:
    def test_r3_state_change_without_approval_asks(self):
        d = _loop().decide(
            {"action_type": "transfer", "state_change": True, "risk_level": "critical"},
            {},
            scores=GateScores(3, 3, 3, 0, 3, 1),
        )
        assert d.outcome is Outcome.ASK
        assert d.requires_approval is True

    def test_r3_state_change_with_approval_executes(self):
        d = _loop().decide(
            {"action_type": "transfer", "state_change": True, "user_confirmed": True},
            {},
            scores=GateScores(3, 3, 3, 0, 3, 1),
        )
        assert d.outcome is Outcome.EXECUTE
        # An approved R=3 execution still flags that approval was required.
        assert d.requires_approval is True


class TestTimeSensitivity:
    def test_high_time_sensitivity_relaxes_u2_probe(self):
        d = _loop().decide(
            {"action_type": "get_quote", "read_only": True},
            {},
            scores=GateScores(3, 3, 1, 2, 2, 1, TimeSensitivity.HIGH),
        )
        assert d.outcome is Outcome.EXECUTE
        assert "rollback" in d.verification_method.lower()

    def test_low_time_sensitivity_probes_u2(self):
        d = _loop().decide(
            {"action_type": "get_quote", "read_only": True},
            {},
            scores=GateScores(3, 3, 1, 2, 2, 1, TimeSensitivity.LOW),
        )
        assert d.outcome is Outcome.PROBE

    def test_u3_always_probes_even_under_time_pressure(self):
        d = _loop().decide(
            {"action_type": "get_quote", "read_only": True},
            {},
            scores=GateScores(3, 3, 1, 3, 2, 1, TimeSensitivity.HIGH),
        )
        assert d.outcome is Outcome.PROBE


class TestHeuristicScoring:
    """When no explicit scores are supplied, ordinary actions resolve to
    EXECUTE and only risky/unclear/uncertain ones diverge."""

    def test_plain_read_executes(self):
        d = _loop().decide({"action_type": "get_balance", "read_only": True}, {})
        assert d.outcome is Outcome.EXECUTE
        assert d.scores.risk == 0

    def test_large_unconfirmed_transfer_asks_for_approval(self):
        d = _loop().decide(
            {
                "action_type": "transfer",
                "parameters": {"value": 50000},
            },
            {},
        )
        assert d.scores.risk == 3
        assert d.outcome is Outcome.ASK

    def test_confirmed_moderate_transfer_executes(self):
        d = _loop().decide(
            {
                "action_type": "swap",
                "parameters": {"value": 100},
                "user_confirmed": True,
            },
            {},
        )
        assert d.outcome is Outcome.EXECUTE

    def test_missing_params_lowers_clarity_to_ask(self):
        d = _loop().decide(
            {"action_type": "swap", "missing_params": ["token_out"], "user_confirmed": True},
            {},
        )
        assert d.scores.clarity < 2
        assert d.outcome is Outcome.ASK

    def test_no_wallet_makes_state_change_infeasible(self):
        d = _loop().decide(
            {"action_type": "transfer", "parameters": {"value": 1}, "user_confirmed": True},
            {"wallet_connected": False},
        )
        assert d.scores.feasibility == 0
        assert d.outcome in (Outcome.ABORT, Outcome.DEFER)


class TestLoggingSchema:
    def test_log_entry_has_full_schema(self):
        loop = _loop()
        d = loop.decide(
            {"action_type": "get_status", "read_only": True},
            {"owner": "neo", "reviewer": "trinity", "evidence": ["ptr://x"]},
            task="check status",
        )
        entry = d.to_log_entry(owner="neo", reviewer="trinity", artifact="report.md")
        for field in (
            "id", "date", "task", "scores", "outcome", "rationale",
            "evidence", "hard_rule_check", "artifact", "verification_method",
            "stop_condition", "owner", "reviewer", "status", "revisit_date",
        ):
            assert field in entry, f"missing schema field: {field}"
        assert set(entry["scores"].keys()) == {"C", "F", "R", "U", "V", "CE", "T"}

    def test_decision_log_accumulates(self):
        loop = _loop()
        for _ in range(3):
            loop.decide({"action_type": "get_status", "read_only": True}, {})
        log = loop.get_decision_log()
        assert len(log) == 3
        assert all("hard_rule_check" in e for e in log)


class TestRexhepiGateIntegration:
    async def test_gate_read_executes(self):
        gate = RexhepiGate({})
        result = await gate.evaluate({"action_type": "get_balance", "read_only": True}, {})
        assert result["approved"] is True
        assert result["outcome"] == "EXECUTE"
        assert set(result["scores"].keys()) == {"C", "F", "R", "U", "V", "CE", "T"}
        assert result["decision_line"].startswith("Decision: EXECUTE")

    async def test_gate_safety_failure_forces_non_execute(self):
        gate = RexhepiGate({})
        # No wallet connected → the safety check fails → the trajectory
        # leaves the feasible set and cannot resolve to EXECUTE.
        result = await gate.evaluate(
            {"action_type": "transfer", "parameters": {"value": 1}, "user_confirmed": True},
            {"wallet_connected": False},
        )
        assert result["approved"] is False
        assert result["outcome"] != "EXECUTE"
        assert result["reason"]

    async def test_gate_high_risk_unconfirmed_asks(self):
        gate = RexhepiGate({})
        result = await gate.evaluate(
            {"action_type": "transfer", "parameters": {"value": 999999}},
            {},
        )
        assert result["approved"] is False
        assert result["outcome"] == "ASK"
