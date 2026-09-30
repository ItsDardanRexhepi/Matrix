#!/usr/bin/env python3
from __future__ import annotations
"""
05 — Marketplace Flow: List and Buy

Demonstrates the Marketplace service (Component 24):

  1. Seller lists a digital asset on the marketplace
  2. Buyer browses and finds the listing
  3. Buyer purchases — the service records the sale; no payment is held
     and nothing is transferred on chain
  4. The sale record carries the price, the platform fee and what the
     seller is owed
  5. The platform fee is owed to the platform wallet the record names;
     the fee is not sent anywhere

Each step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened (its call_outcome is "success").
When blockchain.eas_schema is a well-formed bytes32 UID (the code checks the
form, not that it is registered), the service dispatcher queues an
attestation for a sale it completes, written to the chain once 50 have
gathered; otherwise the attempt is logged and dropped.

Usage:
    python examples/05_marketplace_flow.py
"""

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from examples._steps import BOLD, CYAN, DIM, RESET, Steps, fail, ok, shown, step, warn


def load_config() -> dict:
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  The Matrix Example 05: Marketplace Buy/Sell Flow
{'=' * 60}{RESET}

  Seller lists, buyer buys: the marketplace records the sale and
  its fee split. No escrow, and nothing is transferred on chain.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    seller = config.get("blockchain", {}).get("demo_wallet_address", "0xSeller")
    buyer = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
    steps = Steps(dispatcher)

    step(1, "Seller lists a smart contract template on the marketplace...")
    title = "ERC-20 Token Template"
    listing = await steps.run("list the item", "list_marketplace", {
        "seller": seller,
        "item_type": "digital",
        "price": 0.05,
        "metadata": {
            "title": title,
            "description": "ERC-20 with permit, snapshot and pausable. Scanned with Glasswing.",
            "language": "solidity",
            "version": "0.8.24",
            "features": ["EIP-2612 Permit", "Snapshots", "Pausable", "Ownable"],
        },
    })
    listing_id = None
    if listing is not None:
        listing_id = listing.get("listing_id")
        ok(f"Listing: {listing_id or 'not reported'} ({shown(listing, 'status')})")
        ok(f"Title: {title}")
        ok(f"Price: {shown(listing, 'price')}")

    step(2, "Buyer searches the marketplace...")
    found = await steps.run("search the marketplace", "search_marketplace", {
        "query": {"item_type": "digital", "keyword": "ERC-20", "max_price": 0.1},
    })
    if isinstance(found, list):
        ok(f"Found {len(found)} listing(s)")
        for item in found[:3]:
            ok(f"  {item.get('listing_id')}: {item.get('metadata', {}).get('title', 'untitled')} "
               f"at {item.get('price')}")

    step(3, "Buyer views the listing...")
    viewed = await steps.run("view the listing", "get_listing", {"listing_id": listing_id},
                             needs=[("listing id", listing_id)])
    if viewed is not None:
        ok(f"Status: {shown(viewed, 'status')}")

    step(4, "Buyer buys the item...")
    print(f"  {DIM}The service records the sale; no payment or asset moves on chain.{RESET}")
    sale = await steps.run("buy the item", "buy_marketplace", {"listing_id": listing_id, "buyer": buyer},
                           needs=[("listing id", listing_id)])
    if sale is not None:
        ok(f"Sale recorded: {shown(sale, 'sale_id')}")
        print(f"\n  {BOLD}Fee split, as the sale record states it:{RESET}")
        print(f"  {DIM}{'─' * 45}{RESET}")
        print(f"  Sale price:            {shown(sale, 'price')}")
        print(f"  Platform fee:          {shown(sale, 'platform_fee')}  "
              f"(owed to {shown(sale, 'platform_wallet')}; not sent)")
        print(f"  Seller is owed:        {shown(sale, 'seller_proceeds')}")
        print(f"  Asset:                 recorded as sold; not transferred on chain")
        print(f"  {DIM}{'─' * 45}{RESET}")
    elif listing_id is not None:
        warn("No sale was recorded, so there is no fee split to show.")

    steps.summary("Marketplace flow")


if __name__ == "__main__":
    asyncio.run(main())
