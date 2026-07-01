"""P3-12: intent keyword routing determinism.

The liquidity pair (add_liquidity vs liquidity_provide) is a HARD gate — those
keywords must not overlap. A broader collision scan documents the ~30 PRE-EXISTING
overlaps (out of scope for the audit — R8) as a frozen baseline, so this test
still catches any NEW collision a future edit introduces without failing on the
known set.
"""

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
    """Hard gate: the P3-12 fix — liquidity_provide is canonical."""
    owners = _keyword_owners()
    for kw in ("add liquidity", "provide liquidity", "liquidity pool"):
        assert owners.get(kw, set()) == {"liquidity_provide"}, (
            f"'{kw}' must map only to liquidity_provide, got {owners.get(kw)}"
        )
    assert "add_liquidity" in owners.get("become lp", set())


def test_no_new_keyword_collisions():
    """No collision beyond the documented pre-existing baseline."""
    collisions = {kw for kw, acts in _keyword_owners().items() if len(acts) > 1}
    new = collisions - KNOWN_PREEXISTING_COLLISIONS
    assert not new, f"NEW keyword collision(s) introduced: {sorted(new)}"
    # The liquidity keys must have LEFT the collision set (proves P3-12 landed).
    assert "add liquidity" not in collisions
