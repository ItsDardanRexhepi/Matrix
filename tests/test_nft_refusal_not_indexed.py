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
    return json.loads(Path("openmatrix.config.json.example").read_text())


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
