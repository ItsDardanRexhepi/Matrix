"""P3-12: intent keyword routing determinism.

The liquidity pair (add_liquidity vs liquidity_provide) is a HARD gate — those
keywords must not overlap. A broader collision scan documents the ~30 PRE-EXISTING
overlaps (out of scope for the audit — R8) as a frozen baseline, so this test
still catches any NEW collision a future edit introduces without failing on the
known set.
"""

import inspect
from collections import defaultdict

from runtime.chat.intent_actions import INTENT_ACTION_MAP


def _keyword_owners():
    owners = defaultdict(set)
    for action, spec in INTENT_ACTION_MAP.items():
        for kw in spec.get("keywords", []):
            owners[kw.lower()].add(action)
    return owners


# Pre-existing collisions as of the 2026-07 audit — DOCUMENTED, not fixed (R8
# scope control). This baseline exists so new collisions are caught; it must
# only ever SHRINK, never grow.
KNOWN_PREEXISTING_COLLISIONS = {
    "collateral", "move nft", "tokenize asset", "tokenize property",
    "real world asset", "transfer ownership", "create identity", "create did",
    "who is", "register agent", "payment status", "product status",
    "track shipment", "transfer custody", "game nft", "trade game item",
    "grant license", "ip license", "exchange rate", "campaign details",
    "file dispute", "complaint", "resolve dispute", "creator earnings",
    "is it real", "prove without revealing", "privacy proof", "permanent storage",
}


def test_liquidity_keywords_do_not_overlap():
    """Hard gate: single owner for the liquidity keywords.

    NEW-61 CHANGED THE EXPECTED OWNER, and the reason matters — this is a
    correction, not an accommodation. The invariant under test is unchanged
    (exactly one owner, so routing stays deterministic); what changed is WHICH
    action is canonical.

    P3-12 made liquidity_provide canonical and demoted add_liquidity to a
    legacy alias, on the stated grounds that liquidity_provide had "richer
    params: price ranges, protocol". liquidity_provide was a fabrication —
    uuid + status string, no pool, no reserves, no shares — and those richer
    params were the invented ones: the real dex method cannot accept them and
    the fabrication never read them. So the collision was resolved toward the
    fake precisely because the fake advertised more.

    add_liquidity is backed by a real constant-product AMM
    (dex/service.py:217 -> dex/pools.py:151), and is canonical again.
    """
    owners = _keyword_owners()
    for kw in ("add liquidity", "provide liquidity", "liquidity pool"):
        assert owners.get(kw, set()) == {"add_liquidity"}, (
            f"'{kw}' must map only to add_liquidity (the real AMM), "
            f"got {owners.get(kw)}"
        )
    assert "add_liquidity" in owners.get("become lp", set())


def test_the_liquidity_keywords_route_to_a_real_implementation():
    """The point of the correction, asserted directly rather than implied.

    Owning the keywords is worthless if the owner is another fabrication, so
    resolve the action through the dispatch table and assert the target is the
    real AMM.
    """
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    owners = _keyword_owners()
    action = next(iter(owners["add liquidity"]))
    assert ACTION_MAP[action] == ("dex", "add_liquidity")

    from runtime.blockchain.services.dex.pools import LiquidityPoolManager

    src = inspect.getsource(LiquidityPoolManager.add_liquidity)
    assert "total_lp_shares" in src and "reserve_a" in src, (
        "the canonical liquidity action no longer resolves to code that "
        "maintains real pool reserves and LP shares"
    )


def test_no_new_keyword_collisions():
    """No collision beyond the documented pre-existing baseline."""
    collisions = {kw for kw, acts in _keyword_owners().items() if len(acts) > 1}
    new = collisions - KNOWN_PREEXISTING_COLLISIONS
    assert not new, f"NEW keyword collision(s) introduced: {sorted(new)}"
    # The liquidity keys must have LEFT the collision set (proves P3-12 landed).
    assert "add liquidity" not in collisions
