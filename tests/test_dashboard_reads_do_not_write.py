"""A dashboard read must not write — not to its own store, not to anyone else's.

Two findings, one shape, one file. Both are reads that mutated state, and both
were invisible to the suite because the mutation landed somewhere the tests did
not look.

FINDING D — MUTATION OF A FOREIGN SERVICE'S RECORDS.
`DashboardAggregator.aggregate_activity` did `item["component"] = svc_name` on
whatever each sub-service returned from `get_activity`/`get_transactions`.
Services in this platform return their stored records BY REFERENCE, so a
dashboard read permanently added a `component` key to another service's state —
every registered service, every page view. The stamped value is benign; the
PRIMITIVE is not. A proven ability to hold and mutate references to foreign
services' records is an arbitrary write one refactor away.

FINDING A — MUTATION OF ITS OWN STORE.
`DashboardService.get_overview` did `.get(addr, set())` — which returns the
STORED set when the key exists — then `.add()`ed inferred components into it.
Sixth mutation-on-read of this census. The `set()` default masked it: for a user
with no entry the mutation hit a throwaway, so the defect only appeared on the
SECOND call, after `record_interaction` created a real entry. A defect that only
manifests on the second call is one that unit tests with fresh fixtures
structurally cannot see.

WHY THE ASSERTIONS TARGET STORES AND NOT RETURN VALUES. Checking the returned
item passes identically on a copy and on a reference — it cannot distinguish the
fix from the defect. Every assertion below reads the state that was supposed to be
left alone: the sub-service's own list, and the service's own dict.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.dashboard.aggregator import DashboardAggregator
from runtime.blockchain.services.dashboard.service import DashboardService


class _ServiceReturningItsOwnRecords:
    """A sub-service that returns stored records BY REFERENCE.

    This is not a strawman: it is the shape the aggregator's own staking and
    securities branches rely on (`getattr(svc, "_positions", {})`,
    `getattr(svc, "_balances", {})`), so returning live state is this platform's
    normal idiom rather than an unusual one.
    """

    def __init__(self, records: list[dict]) -> None:
        self.records = records

    async def get_activity(self, address: str) -> list[dict]:
        return self.records


class _ServiceWithTransactionsOnly:
    """Exercises the `get_transactions` branch — the same defect, second site.

    MUST NOT DEFINE `get_activity` AT ALL. The first version of this fake
    defined it and raised AttributeError from the body, which made
    `hasattr(svc, "get_activity")` TRUE — so the aggregator called it, the bare
    `except Exception` swallowed the raise, the whole service was skipped, and
    the `get_transactions` branch never ran. The test passed against the
    UNFIXED code and proved nothing.

    Caught by the proof-of-failure count: 4 failures where 5 were expected. The
    content looked right; only the number disagreed.
    """

    def __init__(self, records: list[dict]) -> None:
        self.records = records

    async def get_transactions(self, address: str) -> list[dict]:
        return self.records


# ── D: the foreign-record write ──────────────────────────────────────────


async def test_reading_activity_does_not_write_into_the_service_that_owns_it():
    """THE LOAD-BEARING ASSERTION, against the SUB-SERVICE'S OWN RECORD."""
    svc = _ServiceReturningItsOwnRecords(
        [{"type": "stake", "amount": 5, "timestamp": 100}]
    )
    aggregator = DashboardAggregator({}, {"staking": svc})

    await aggregator.aggregate_activity("0xA")

    assert "component" not in svc.records[0], (
        "the dashboard stamped 'component' into the staking service's own stored "
        f"record: {svc.records[0]}"
    )
    assert svc.records[0] == {"type": "stake", "amount": 5, "timestamp": 100}


async def test_the_get_transactions_branch_does_not_write_either():
    """SECOND SITE, same defect. Fixing one branch and not its twin is how a
    correct fix reads as ineffective."""
    svc = _ServiceWithTransactionsOnly([{"type": "send", "amount": 2}])
    aggregator = DashboardAggregator({}, {"payments": svc})

    await aggregator.aggregate_activity("0xA")

    assert "component" not in svc.records[0]


async def test_the_caller_still_receives_the_component_label():
    """SCOPE PIN. Copying must not drop the labelling the aggregate needs — the
    component tag is the point of the loop."""
    svc = _ServiceReturningItsOwnRecords([{"type": "stake", "timestamp": 1}])
    aggregator = DashboardAggregator({}, {"staking": svc})

    result = await aggregator.aggregate_activity("0xA")

    assert result[0]["component"] == "staking"
    assert result[0]["type"] == "stake"


async def test_repeated_reads_do_not_accumulate_in_the_owning_service():
    """The write was permanent and unbounded — every view stamped again. A single
    read is the minimum reproduction; this is the one that shows it never stops."""
    svc = _ServiceReturningItsOwnRecords([{"type": "stake", "timestamp": 1}])
    aggregator = DashboardAggregator({}, {"staking": svc})

    for _ in range(3):
        aggregator._cache.clear()  # defeat the 30s cache; each call re-reads
        await aggregator.aggregate_activity("0xA")

    assert svc.records[0] == {"type": "stake", "timestamp": 1}


# ── A: the own-store write ───────────────────────────────────────────────


async def test_get_overview_does_not_widen_the_stored_component_set():
    """THE ASSERTION AGAINST THE STORE, and it must run the SECOND-CALL path —
    `record_interaction` first, because a fresh user's mutation lands on the
    throwaway default and proves nothing."""
    service = DashboardService({})
    service.record_interaction("0xA", "wallet")

    async def _portfolio_with_a_staking_position(address):
        return {"staking_positions": [{"amount": 1}], "defi_positions": [], "nfts": []}

    service._aggregator.aggregate_portfolio = _portfolio_with_a_staking_position
    await service.get_overview("0xA")

    assert service._user_components["0xA"] == {"wallet"}, (
        "get_overview widened the stored set — a read wrote: "
        f"{service._user_components['0xA']}"
    )


async def test_the_returned_view_still_reflects_the_inferred_components():
    """SCOPE PIN. The inference is a legitimate VIEW concern; only its
    persistence was the defect. The caller must still see 'staking'."""
    service = DashboardService({})
    service.record_interaction("0xA", "wallet")

    async def _portfolio(address):
        return {"staking_positions": [{"amount": 1}], "defi_positions": [], "nfts": []}

    service._aggregator.aggregate_portfolio = _portfolio
    result = await service.get_overview("0xA")

    assert "staking" in result["active_components"]
    assert "wallet" in result["active_components"]


async def test_a_closed_position_narrows_the_view_again():
    """THE MONOTONICITY HALF. Nothing in this service ever REMOVED a component,
    so before the fix a widened view could never narrow — the position could
    close and the dashboard would still advertise it forever."""
    service = DashboardService({})
    service.record_interaction("0xA", "wallet")

    async def _with_position(address):
        return {"staking_positions": [{"amount": 1}], "defi_positions": [], "nfts": []}

    async def _position_closed(address):
        return {"staking_positions": [], "defi_positions": [], "nfts": []}

    service._aggregator.aggregate_portfolio = _with_position
    await service.get_overview("0xA")

    service._aggregator.aggregate_portfolio = _position_closed
    result = await service.get_overview("0xA")

    assert "staking" not in result["active_components"], (
        "the position closed but the dashboard still lists it — the widening "
        "was persisted and nothing narrows it"
    )


async def test_record_interaction_still_persists():
    """CONTROL IN THE OTHER DIRECTION. The fix copies on READ; the WRITE path
    must still write, or the component set would never populate at all."""
    service = DashboardService({})
    service.record_interaction("0xA", "wallet")
    service.record_interaction("0xA", "defi")

    assert service._user_components["0xA"] == {"wallet", "defi"}


async def test_a_first_time_user_is_unaffected():
    """The masking condition, pinned. A user with no stored entry must not gain
    one from a read — before the fix this 'passed' only because the mutation hit
    a throwaway, so it is asserted explicitly rather than relied upon."""
    service = DashboardService({})

    async def _portfolio(address):
        return {"staking_positions": [{"amount": 1}], "defi_positions": [], "nfts": []}

    service._aggregator.aggregate_portfolio = _portfolio
    await service.get_overview("0xNEW")

    assert "0xNEW" not in service._user_components
