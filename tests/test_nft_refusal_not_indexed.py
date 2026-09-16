"""22-B — the factory refused honestly and the caller indexed a success-only key.

MEASURED at pin 84a6c3e under THE SHIPPED CONFIG (which has no top-level `nft`
block at all):

    deploy_erc721(...) -> {status: 'not_deployed', action_required,
                           deployment_guide, message, operation, requested,
                           service}          <- no 'collection_address'
    service.py:187     -> result["collection_address"]   -> KeyError

The gate WORKS and the consumer DEFEATS IT. The crash is what made the whole
create -> mint -> list -> sell chain unreachable at step one, which in turn
recast the reachability of a large fraction of this domain's findings.

TWO SITES SHARE THE EXACT SHAPE (§AK.2) — `create_collection` indexing
`collection_address` and `mint` indexing `token_id` — so both are fixed
together. Fixing one would have left the chain dead one link further down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.blockchain.services.nft_services.service import NFTService
from runtime.blockchain.services.service_dispatcher import _outcome_is_real


def _shipped():
    return json.loads(Path("matrix.config.json.example").read_text())


@pytest.mark.asyncio
async def test_create_collection_refuses_instead_of_crashing():
    """THE REPRODUCTION for site 1."""
    out = await NFTService(_shipped()).create_collection(
        "0xC", "Name", "SYM", "erc721", 500)          # must NOT raise
    assert out["status"] == "not_deployed"
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_mint_refuses_instead_of_crashing():
    """THE REPRODUCTION for site 2 — the §AK.2 sibling."""
    out = await NFTService(_shipped()).mint(
        "0xCOLL", "0xC", {"n": 1}, 500)                # must NOT raise
    assert out["status"] == "not_deployed"
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_the_refusal_names_the_key_the_operator_must_set():
    """A refusal that does not say what to configure is not actionable."""
    out = await NFTService(_shipped()).create_collection(
        "0xC", "Name", "SYM", "erc721", 500)
    assert "factory" in str(out.get("missing", "")).lower()
    assert out.get("factory_response", {}).get("status") == "not_deployed"


@pytest.mark.asyncio
async def test_both_sites_are_covered_not_just_one():
    """§AK.2 as an assertion rather than a promise: the chain must refuse at
    BOTH links, since fixing one leaves it dead at the next."""
    svc = NFTService(_shipped())
    a = await svc.create_collection("0xC", "N", "S", "erc721", 500)
    b = await svc.mint("0xCOLL", "0xC", {"n": 1}, 500)
    assert a["status"] == b["status"] == "not_deployed"


def test_both_methods_can_originate_a_refusal():
    """Structural, and legitimately so (§AT's exception — the subject IS the
    source text): D6 classifies a method as able-to-refuse by looking for a
    CALL to a registered refusal primitive. A method that merely PROPAGATES a
    callee's refusal is invisible to it. This asserts the property D6 reads."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(
        "runtime/blockchain/services/nft_services/service.py").read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "NFTService")
    for name in ("create_collection", "mint"):
        fn = next(m for m in cls.body if getattr(m, "name", None) == name)
        calls = {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                 for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert "not_deployed_response" in calls, (
            f"{name} cannot originate a refusal, so D6 counts it as an "
            f"ungated state-modifying sibling"
        )


# ─────────────────────────────── 22-F ───────────────────────────────

@pytest.mark.asyncio
async def test_list_for_sale_names_the_real_cause_not_the_proximate_one():
    """22-F / §AC. Under the SHIPPED config no token can exist at all — `mint`
    refuses because the factory is undeployed, so the store is necessarily
    empty and EVERY call to this live ACTION_MAP action raised "Token 1 not
    found in 0xCOLL". An operator reads that as "wrong token id" and goes
    looking for a token, when the answer is "no NFT contract is deployed".

    The last of the three crashes the reachability recast found. The other two
    (22-B) indexed a success-only key on a refusal shape; this one raised an
    honest-but-misleading message. Same consequence: a live action whose
    failure does not name what to fix."""
    out = await NFTService(_shipped()).list_for_sale("0xCOLL", 1, 1.0)
    assert out["status"] == "not_deployed"
    assert "factory" in str(out.get("missing", "")).lower()
    assert "token id is not the problem" in out["reason"]
    assert _outcome_is_real(out) is False


@pytest.mark.asyncio
async def test_every_live_action_refuses_or_executes_and_none_crashes():
    """THE RECAST, AS A STANDING CONTROL. Reachability was re-derived per
    method under the shipped config and the answer set the disposition order:
    6 EXECUTE / 3 CRASH / 8 REFUSE before, 6 / 0 / 11 after.

    A crash is not a refusal — it reaches the dispatcher as
    `service_error, degraded: true`, which reports a platform fault for a
    correctly-configured platform doing the only honest thing available."""
    import inspect
    from runtime.blockchain.services import service_dispatcher as sd

    svc = NFTService(_shipped())
    args = {
        "create_nft_collection": dict(creator="0xC", name="N", symbol="S",
                                      collection_type="erc721", royalty_bps=500),
        "mint_nft": dict(collection="0xC", creator="0xC", metadata={}, royalty_bps=500),
        "transfer_nft": dict(collection="0xC", token_id=1, from_addr="0xA", to_addr="0xB"),
        "list_nft_for_sale": dict(collection="0xC", token_id=1, price=1.0),
        "buy_nft": dict(collection="0xC", token_id=1, sale_price=1.0,
                        seller="0xA", buyer="0xB"),
        "estimate_nft_value": dict(collection="0xC", token_id=1),
        "get_nft_rarity": dict(collection="0xC", token_id=1, total_supply=10, traits={}),
        "set_nft_rights": dict(collection="0xC", token_id=1,
                               rights={"commercial": {"granted": True, "holder": "0xA"}}),
        "check_nft_rights": dict(collection="0xC", token_id=1, right_type="commercial"),
        "configure_nft_royalty": dict(collection="0xC", token_id=-1,
                                      recipient="0xA", bps=500),
        "nft_fractionalize": dict(collection="0xC", token_id=1, fractions=10,
                                  price_per_fraction=1.0),
        "nft_rent": dict(collection="0xC", token_id=1, renter="0xR",
                         duration_days=1, price=1.0),
        "nft_dynamic_update": dict(collection="0xC", token_id=1, updates={}),
        "nft_batch_mint": dict(collection="0xC", creator="0xC", count=2,
                               metadata_template={}),
        "nft_royalty_claim": dict(collection="0xC", token_id=1, claimer="0xA"),
        "nft_bridge": dict(collection="0xC", token_id=1, destination_chain="base",
                           owner="0xO"),
        "soulbound_mint": dict(recipient="0xR", metadata={}, issuer="0xI"),
    }
    actions = {k: v[1] for k, v in sd.ACTION_MAP.items() if v[0] == "nft_services"}
    assert len(actions) == 17

    crashed = []
    for action, method in actions.items():
        try:
            r = getattr(svc, method)(**args[action])
            if inspect.isawaitable(r):
                await r
        except Exception as exc:
            crashed.append(f"{action}: {type(exc).__name__}")
    assert crashed == [], f"live actions crashing instead of refusing: {crashed}"
