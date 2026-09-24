"""No two shipping classes share a name.

65e09e6 found two unrelated classes both called DataAggregator, with different
methods, and three GET routes calling methods that existed on neither: an
importer that reaches for a name gets whichever class its import path happens
to name, and nothing at the call site says which. The dashboard one was renamed
DashboardAggregator.

The rename was applied to that pair only. The one other duplicated name in the
tree — RoyaltyEnforcement, defined in both ip_royalties/ and nft_services/ with
disjoint APIs (configure_royalty/process_usage/get_royalty_history against
configure_royalty/process_sale/get_royalty_info) — was left standing. Both
importers use fully-qualified paths today, so neither reaches the other; the
hazard is the next importer, and a shared `configure_royalty` means a wrong
import fails late, not at the import line.

Asserted over the AST of every top-level class in every shipping tree, so the
next collision fails here rather than in a route.
"""
from __future__ import annotations

import ast
import collections
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHIPPING = ("runtime", "gateway", "hivemind", "cli", "sdk", "bridge", "skills",
            "setup", "migration", "scripts")


def test_no_two_top_level_classes_share_a_name():
    where: dict[str, list[str]] = collections.defaultdict(list)
    for top in SHIPPING:
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef):
                    where[node.name].append(f"{path.relative_to(ROOT)}:{node.lineno}")
    collisions = {name: sites for name, sites in where.items() if len(sites) > 1}
    assert not collisions, (
        "class names defined more than once — an importer gets whichever its path "
        "names:\n  " + "\n  ".join(f"{n}: {s}" for n, s in sorted(collisions.items())))


def test_the_two_royalty_engines_are_distinguishable_by_name():
    from runtime.blockchain.services.ip_royalties.royalty_enforcement import IPRoyaltyEnforcement
    from runtime.blockchain.services.ip_royalties.service import IPRoyaltyService
    from runtime.blockchain.services.nft_services.royalty_enforcement import RoyaltyEnforcement

    assert IPRoyaltyEnforcement is not RoyaltyEnforcement
    assert isinstance(IPRoyaltyService({}).enforcement, IPRoyaltyEnforcement)
