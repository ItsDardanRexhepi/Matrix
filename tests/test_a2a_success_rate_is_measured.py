"""An A2A listing's success rate is measured from its jobs, or it is absent.

attest-money F21. `A2AMarketplace.complete_job` carried a comment saying a
job's DISPUTED-vs-FAILED status "feeds `total_jobs` and the success rate buyers
pick a service on". Neither was true: `total_jobs` was incremented for every
finished job whatever its status, and `ServiceListing.success_rate` defaulted
to 1.0 with no writer anywhere under runtime/ or gateway/ — every listing
advertised a perfect record that nothing had measured.

The comment is made true rather than deleted: the rate is now written from the
jobs whose outcome was established (completed / (completed + failed)), a
disputed job moves neither side, and a listing with no established job has no
rate at all.

SIBLING AXES, named and not changed: `rating` (5.0) and `avg_response_time_ms`
(5000) are the same kind of figure — defaults on the listing with no writer —
and are still published by `to_dict` as they stand.
"""

from __future__ import annotations

import pytest

from runtime.protocols.outcome_truth import FAILURE, SUCCESS


class _Loop:
    def __init__(self, tool_calls):
        self._tool_calls = tool_calls

    async def run(self, _context):
        from runtime.react_loop import ReActResult

        return ReActResult(response="done", tool_calls=self._tool_calls,
                           iterations=1, provider="test")


async def _market_and_listing():
    from runtime.a2a.marketplace import A2AMarketplace
    from runtime.a2a.protocol import ServiceListing

    market = A2AMarketplace({})
    listing = await market.register_service(ServiceListing(
        agent_id="trinity", name="analysis", description="d",
        category="analysis", price_usd=12.0))
    return market, listing


async def _run_job(market, listing, tool_calls):
    from runtime.a2a.coordinator import A2ACoordinator
    from runtime.a2a.protocol import JobRequest

    coordinator = A2ACoordinator(marketplace=market, react_loop=_Loop(tool_calls))
    await coordinator.execute_job(JobRequest(
        service_id=listing.service_id, requester_agent_id="0xA",
        input_data={"q": "x"}))


async def test_a_listing_nobody_has_measured_advertises_no_success_rate():
    """DEFECT-PROVER. It advertised 1.0."""
    _market, listing = await _market_and_listing()
    assert listing.to_dict()["success_rate"] is None


async def test_the_rate_counts_established_outcomes():
    market, listing = await _market_and_listing()

    await _run_job(market, listing, [{"tool": "t", "reported": SUCCESS}])
    assert listing.success_rate == pytest.approx(1.0)

    await _run_job(market, listing, [{"tool": "t", "reported": FAILURE}])
    assert listing.success_rate == pytest.approx(0.5)
    assert listing.total_jobs == 2


async def test_a_disputed_job_counts_as_a_job_and_not_against_the_rate():
    """The distinction the comment was written for: an agent whose tools
    disagreed may well have done the work, so the job is not a failure on the
    provider's record — and not a success either."""
    market, listing = await _market_and_listing()
    await _run_job(market, listing, [{"tool": "t", "reported": SUCCESS}])

    await _run_job(market, listing, [
        {"tool": "t", "reported": SUCCESS},
        {"tool": "t", "reported": FAILURE},
    ])

    assert listing.total_jobs == 2
    assert listing.success_rate == pytest.approx(1.0)


async def test_only_disputed_jobs_leave_the_rate_unmeasured():
    market, listing = await _market_and_listing()
    await _run_job(market, listing, [
        {"tool": "t", "reported": SUCCESS},
        {"tool": "t", "reported": FAILURE},
    ])

    assert listing.total_jobs == 1
    assert listing.success_rate is None
