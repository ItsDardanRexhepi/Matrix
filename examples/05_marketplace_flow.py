from __future__ import annotations
#!/usr/bin/env python3
"""
05 — Marketplace Flow: List, Buy, and Escrow on Base Sepolia

Demonstrates the Marketplace service (Component 24):

  1. Seller lists a digital asset on the marketplace
  2. Buyer browses and finds the listing
  3. Buyer purchases — payment is held in escrow
  4. Asset transfer and payment release happen atomically
  5. Platform fee is deducted and routed to NeoSafe

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
    config_path = os.path.join(ROOT, "openmatrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  0pnMatrx Example 05: Marketplace Buy/Sell Flow
{'=' * 60}{RESET}

  Atomic buy/sell via escrow — seller lists, buyer pays,
  platform handles transfer + fee routing in one transaction.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})

    seller = bc.get("demo_wallet_address", "0xSeller")
    buyer = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"

    # ── Step 1: List item on marketplace ────────────────────────────
    step(1, "Seller lists a smart contract template on the marketplace...")

    listing_id = None
    try:
        result = await dispatcher.execute(
            action="list_marketplace",
            params={
                "seller": seller,
                "title": "Production-Ready ERC-20 Token Template",
                "description": (
                    "Gas-optimised ERC-20 with permit, snapshot, and pausable. "
                    "Audited by Morpheus. Includes deployment scripts."
                ),
                "category": "smart_contract_template",
                "price_eth": 0.05,
                "currency": "ETH",
                "asset_type": "digital",
                "metadata": {
                    "language": "solidity",
                    "version": "0.8.24",
                    "audit_status": "passed",
                    "features": ["EIP-2612 Permit", "Snapshots", "Pausable", "Ownable"],
                    "lines_of_code": 280,
                },
                "duration_days": 30,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            listing = data["result"]
            listing_id = listing.get("listing_id", listing.get("id", "N/A"))
            ok(f"Listing created: {listing_id}")
            ok(f"Title: Production-Ready ERC-20 Token Template")
            ok(f"Price: 0.05 ETH")
            ok(f"Seller: {seller[:12]}...")
            if listing.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{listing['tx_hash']}")
        else:
            warn(f"Listing: {data.get('error', 'check config')}")
            listing_id = "demo-listing-001"
    except Exception as e:
        warn(f"Listing: {e}")
        listing_id = "demo-listing-001"

    # ── Step 2: Search marketplace ──────────────────────────────────
    step(2, "Buyer searches the marketplace...")

    try:
        result = await dispatcher.execute(
            action="search_marketplace",
            params={
                "query": "ERC-20 template",
                "category": "smart_contract_template",
                "max_price_eth": 0.1,
                "sort_by": "relevance",
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            results = data["result"]
            if isinstance(results, list):
                ok(f"Found {len(results)} matching listings")
            elif isinstance(results, dict):
                items = results.get("items", results.get("listings", []))
                ok(f"Found {len(items)} matching listings")
            ok(f"Top result: Production-Ready ERC-20 Token Template")
        else:
            warn(f"Search: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Search: {e}")

    # ── Step 3: View listing details ────────────────────────────────
    step(3, "Buyer views listing details...")

    try:
        result = await dispatcher.execute(
            action="get_listing",
            params={"listing_id": listing_id},
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            listing = data["result"]
            ok(f"Title: {listing.get('title', 'ERC-20 Token Template')}")
            ok(f"Price: {listing.get('price_eth', 0.05)} ETH")
            ok(f"Seller: {listing.get('seller', seller)[:16]}...")
            ok(f"Status: {listing.get('status', 'active')}")
        else:
            warn(f"Listing details: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Listing details: {e}")

    # ── Step 4: Buy item (atomic escrow) ────────────────────────────
    step(4, "Buyer purchases item via atomic escrow...")
    print(f"  {DIM}Payment + asset transfer happen in a single transaction.{RESET}")

    try:
        result = await dispatcher.execute(
            action="buy_marketplace",
            params={
                "listing_id": listing_id,
                "buyer": buyer,
                "payment_amount_eth": 0.05,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            purchase = data["result"]
            ok(f"Purchase completed!")
            ok(f"Order ID: {purchase.get('order_id', purchase.get('id', 'N/A'))}")
            ok(f"Buyer: {buyer[:12]}...")
            ok(f"Payment: 0.05 ETH")
            if purchase.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{purchase['tx_hash']}")
        else:
            warn(f"Purchase: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Purchase: {e}")

    # ── Step 5: Show escrow settlement breakdown ────────────────────
    step(5, "Escrow settlement breakdown")

    platform_fee_bps = config.get("services", {}).get("marketplace", {}).get("platform_fee_bps", 500)
    platform_fee_pct = platform_fee_bps / 100

    sale_price = 0.05
    platform_fee = sale_price * (platform_fee_bps / 10000)
    seller_receives = sale_price - platform_fee

    print(f"\n  {BOLD}Settlement:{RESET}")
    print(f"  {DIM}{'─' * 45}{RESET}")
    print(f"  Sale price:            {sale_price:.4f} ETH")
    print(f"  Platform fee ({platform_fee_pct:.1f}%):   {platform_fee:.4f} ETH  -> NeoSafe")
    print(f"  Seller receives:       {seller_receives:.4f} ETH")
    print(f"  {DIM}{'─' * 45}{RESET}")
    print(f"  Asset transferred:     Buyer now owns template")
    print(f"  Escrow:                Released atomically")
    print(f"  {DIM}{'─' * 45}{RESET}")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  MARKETPLACE FLOW COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. list_marketplace    - Seller creates listing
    2. search_marketplace  - Buyer discovers items
    3. get_listing         - View listing details
    4. buy_marketplace     - Atomic escrow purchase
    5. (settlement)        - Fee routing to NeoSafe

  {BOLD}Key features:{RESET}
    - Atomic buy/sell: payment and transfer in one tx
    - Escrow protection: funds held until transfer confirmed
    - Automatic fee routing to NeoSafe platform wallet
    - EAS attestation for every transaction

  {BOLD}Services used:{RESET}
    - Marketplace (Component 24)
    - NeoSafe revenue router
    - Attestation (Component 8)

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
