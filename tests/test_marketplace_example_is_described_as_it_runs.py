"""THE MARKETPLACE EXAMPLE IS DESCRIBED AS IT RUNS.

MarketplaceService.buy_item builds a sale record with its fee split, marks the
listing sold and keeps the record in memory. It holds no payment and sends
nothing on chain. Example 05 and the two indexes that describe it once said
"atomic escrow" and "payment and transfer in one transaction"; this test
fails if any of them says escrow or atomic again without negating it.
"""
from __future__ import annotations

import inspect
import pathlib
import re

from runtime.blockchain.services.marketplace.service import MarketplaceService

REPO = pathlib.Path(__file__).resolve().parent.parent
_CLAIM = re.compile(r"(?<!no )\bescrow\b|\batomic", re.IGNORECASE)


def test_buy_item_moves_nothing_on_chain():
    source = inspect.getsource(MarketplaceService.buy_item)
    assert "self._sales.append(sale)" in source, "precondition: buy_item records the sale"
    for word in ("web3", "send_transaction", "send_raw_transaction", "transfer("):
        assert word not in source, f"buy_item now calls {word}; this test's premise is out of date"


def test_example_05_and_its_index_rows_claim_no_escrow():
    wrong = []
    for n, line in enumerate((REPO / "examples/05_marketplace_flow.py").read_text().splitlines(), 1):
        if _CLAIM.search(line):
            wrong.append(f"examples/05_marketplace_flow.py:{n}: {line.strip()}")
    for rel in ("README.md", "examples/README.md"):
        for n, line in enumerate((REPO / rel).read_text().splitlines(), 1):
            if "05_marketplace_flow" in line and _CLAIM.search(line):
                wrong.append(f"{rel}:{n}: {line.strip()}")
    assert not wrong, "the marketplace records a sale; these lines say escrow or atomic: " + "; ".join(wrong)
