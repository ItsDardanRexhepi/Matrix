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

CYAN = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED = "\033[91m"; BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

def step(n, text):  print(f"\n{CYAN}{BOLD}[Step {n}]{RESET} {text}")
def ok(text):       print(f"  {GREEN}+{RESET} {text}")
def warn(text):     print(f"  {YELLOW}!{RESET} {text}")
def fail(text):     print(f"  {RED}x{RESET} {text}")


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
    bc = config.get("blockchain", {})

    seller = bc.get("demo_wallet_address", "0xSeller")
    buyer = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"

    # ── Step 1: List item on marketplace ────────────────────────────
    step(1, "Seller lists a smart contract template on the marketplace...")

    title = "Production-Ready ERC-20 Token Template"
    price = 0.05
    listing_id = None
    try:
        result = await dispatcher.execute(
            action="list_marketplace",
            params={
                "seller": seller,
                "item_type": "digital",
                "price": price,
                "metadata": {
                    "title": title,
                    "description": (
                    "Gas-optimised ERC-20 with permit, snapshot, and pausable. "
                    "Audited by Morpheus. Includes deployment scripts."
                    ),
                    "language": "solidity",
                    "version": "0.8.24",
                    "features": ["EIP-2612 Permit", "Snapshots", "Pausable", "Ownable"],
                },
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok" and data["result"].get("status") == "active":
            listing_id = data["result"]["listing_id"]
            ok(f"Listing created: {listing_id}")
            ok(f"Title: {title}")
            ok(f"Price: {price}")
            ok(f"Seller: {seller[:12]}...")
        elif data.get("status") == "ok":
            warn(f"Listing not active: {data['result'].get('status')} "
                 f"({data['result'].get('compliance', {}).get('reason', 'N/A')})")
        else:
            warn(f"Listing: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Listing: {e}")

    # ── Step 2: Search marketplace ──────────────────────────────────
    step(2, "Buyer searches the marketplace...")

    try:
        result = await dispatcher.execute(
            action="search_marketplace",
            params={"query": {"item_type": "digital", "keyword": "ERC-20", "max_price": 0.1}},
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            found = data["result"]
            ok(f"Found {len(found)} listing(s)")
            for item in found[:3]:
                ok(f"  {item['listing_id']}: {item['metadata'].get('title', 'N/A')} at {item['price']}")
        else:
            warn(f"Search: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Search: {e}")

    # ── Step 3: Get listing details ─────────────────────────────────
    step(3, "Buyer views the listing...")

    if listing_id is None:
        warn("No listing was created, so there is nothing to view or buy.")
    else:
        try:
            result = await dispatcher.execute(action="get_listing", params={"listing_id": listing_id})
            data = json.loads(result)
            if data.get("status") == "ok":
                ok(f"Status: {data['result'].get('status', 'N/A')}")
            else:
                warn(f"Listing details: {data.get('error', 'N/A')}")
        except Exception as e:
            warn(f"Listing details: {e}")

    # ── Step 4: Buy item ────────────────────────────────────────────
    step(4, "Buyer buys the item...")
    print(f"  {DIM}The service records the sale; no payment or asset moves on chain.{RESET}")

    sale = None
    if listing_id is not None:
        try:
            result = await dispatcher.execute(
                action="buy_marketplace",
                params={"listing_id": listing_id, "buyer": buyer},
            )
            data = json.loads(result)
            if data.get("status") == "ok":
                sale = data["result"]
                ok(f"Sale recorded: {sale['sale_id']}")
                ok(f"Buyer: {buyer[:12]}...")
            else:
                warn(f"Purchase: {data.get('error', 'N/A')}")
        except Exception as e:
            warn(f"Purchase: {e}")

    # ── Step 5: Show the fee split the sale record carries ──────────
    step(5, "The sale's fee split")

    if sale is None:
        warn("No sale was recorded, so there is no fee split to show.")
    else:
        print(f"\n  {BOLD}Fee split, as the sale record states it:{RESET}")
        print(f"  {DIM}{'─' * 45}{RESET}")
        print(f"  Sale price:            {sale['price']}")
        print(f"  Platform fee:          {sale['platform_fee']}  (owed to {sale['platform_wallet']}; not sent)")
        print(f"  Seller is owed:        {sale['seller_proceeds']}")
        print(f"  {DIM}{'─' * 45}{RESET}")
        print(f"  Asset:                 recorded as sold; not transferred on chain")
        print(f"  {DIM}{'─' * 45}{RESET}")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  MARKETPLACE FLOW COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. list_marketplace    - Seller creates listing
    2. search_marketplace  - Buyer discovers items
    3. get_listing         - View listing details
    4. buy_marketplace     - Records the sale
    5. (fee split)         - The fee split the sale record carries

  {BOLD}Key features:{RESET}
    - A sale is a record: no escrow, and no payment or asset
      moves on chain
    - The platform fee is recorded on the sale, owed to the
      marketplace's platform wallet; nothing sends it there
    - When blockchain.eas_schema is a well-formed bytes32 UID (the code
      checks the form, not that it is registered), the service dispatcher
      queues an attestation for a sale it completes, written to the chain
      once 50 have gathered; otherwise the attempt is logged and dropped

  {BOLD}Services used:{RESET}
    - Marketplace (Component 24)
    - Attestation (Component 8), through the service dispatcher

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
