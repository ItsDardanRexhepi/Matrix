"""A snapshot that was taken decides the vote, even when it found no holders.

`AntiManipulation.take_snapshot` says: "This prevents flash loan attacks:
only balances at snapshot time count", and that a voter absent from a
snapshot held nothing and is refused. `check_vote` read the snapshot with
``if snapshot``, and an empty dict is falsy. So a snapshot that found no
holders at all skipped the check, and every voter kept the weight they
declared: balances that did not exist at snapshot time counted.

(`create_proposal` no longer plants an empty snapshot when nothing supplied
balances — tests/test_governance_cluster_a.py — so an empty snapshot is a
real reading from a balance source, and it means nobody held anything.)
"""

from __future__ import annotations

import math

import pytest

from runtime.blockchain.services.governance.service import GovernanceService


def _am():
    return GovernanceService({}).anti_manipulation


async def test_an_empty_snapshot_refuses_a_declared_weight():
    am = _am()
    am.take_snapshot("p1", {})
    out = await am.check_vote("p1", "0xwhale", 1_000_000.0)
    assert out["allowed"] is False and out["adjusted_weight"] == 0.0, (
        f"a balance that did not exist at snapshot time counted: {out}")
    assert "no_snapshot_balance" in out["flags"]


@pytest.mark.parametrize("balance", [-5.0, math.nan])
async def test_a_balance_that_is_not_a_positive_number_is_not_a_holding(balance):
    am = _am()
    am.take_snapshot("p1", {"0xodd": balance, "0xother": 10.0})
    out = await am.check_vote("p1", "0xodd", 50.0)
    assert out["allowed"] is False and out["adjusted_weight"] == 0.0, out


async def test_no_snapshot_at_all_is_still_not_a_refusal():
    """SCOPE PIN: a proposal with no snapshot taken is not refused here; the
    weight-dependent voting models refuse on their own while no balance source
    exists (governance/service.py)."""
    out = await _am().check_vote("p-none", "0xa", 1.0)
    assert out["allowed"] is True and out["adjusted_weight"] == 1.0, out


async def test_a_holder_is_still_clamped_to_the_snapshot():
    """SCOPE PIN: the clamp itself is unchanged."""
    am = _am()
    am.take_snapshot("p1", {"0xrich": 100.0})
    out = await am.check_vote("p1", "0xrich", 500.0)
    # The weight cap may lower it further; the clamp is that it is no higher.
    assert out["allowed"] is True and 0 < out["adjusted_weight"] <= 100.0, out
    assert "flash_loan_suspected" in out["flags"]
