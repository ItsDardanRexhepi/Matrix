from __future__ import annotations
#!/usr/bin/env python3
"""
03 — NFT with Royalties: Mint, List, Sell with Automatic Royalty Enforcement

Demonstrates NFT Services (Component 3) and IP/Royalties (Component 15):

  1. Creates an NFT collection on Base Sepolia
  2. Mints a token with metadata and 5% royalty configuration
  3. Lists the NFT for sale on the marketplace
  4. Simulates a purchase — royalties are distributed automatically
  5. Shows the royalty split breakdown

Usage:
    python examples/03_nft_with_royalties.py
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
  0pnMatrx Example 03: NFT with Automatic Royalties
{'=' * 60}{RESET}

  Creates an NFT with EIP-2981 royalty enforcement.
  Every resale automatically distributes 5% to the creator.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    creator = bc.get("demo_wallet_address", "0xCreator")
    buyer = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"  # example buyer

    # ── Step 1: Create NFT collection ───────────────────────────────
    step(1, "Creating NFT collection: 'Genesis Art Collection'")

    try:
        result = await dispatcher.execute(
            action="create_nft_collection",
            params={
                "name": "Genesis Art Collection",
                "symbol": "GART",
                "creator": creator,
                "max_supply": 10000,
                "base_uri": "ipfs://QmExampleMetadataHash/",
                "royalty_bps": 500,  # 5%
                "royalty_recipient": creator,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            collection = data["result"]
            collection_address = collection.get("collection_address", collection.get("contract_address", "N/A"))
            ok(f"Collection deployed: {collection_address}")
            ok(f"Name: Genesis Art Collection (GART)")
            ok(f"Max supply: 10,000")
            ok(f"Royalty: 5% (500 bps)")
            if collection.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{collection['tx_hash']}")
        else:
            collection_address = "0xCollectionAddress"
            warn(f"Collection: {data.get('error', 'check config')}")
    except Exception as e:
        collection_address = "0xCollectionAddress"
        warn(f"Collection creation: {e}")

    # ── Step 2: Configure royalty (EIP-2981) ────────────────────────
    step(2, "Configuring royalty distribution (EIP-2981)...")

    try:
        result = await dispatcher.execute(
            action="configure_nft_royalty",
            params={
                "collection_address": collection_address,
                "token_id": 1,
                "royalty_recipient": creator,
                "royalty_bps": 500,
                "distribution": [
                    {"recipient": creator, "share_bps": 8000},   # 80% to creator
                    {"recipient": "0xPlatform", "share_bps": 2000},  # 20% platform
                ],
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            ok("Royalty configured: 5% on every resale")
            ok("  Creator gets 80% of royalty (4% of sale)")
            ok("  Platform gets 20% of royalty (1% of sale)")
        else:
            warn(f"Royalty config: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Royalty configuration: {e}")

    # ── Step 3: Mint an NFT ─────────────────────────────────────────
    step(3, "Minting NFT #1: 'Quantum Dreams #001'")

    metadata = {
        "name": "Quantum Dreams #001",
        "description": "A generative art piece exploring quantum probability fields.",
        "image": "ipfs://QmExampleImageHash/001.png",
        "attributes": [
            {"trait_type": "Style", "value": "Generative"},
            {"trait_type": "Palette", "value": "Cosmic"},
            {"trait_type": "Complexity", "value": "High"},
            {"trait_type": "Edition", "value": "1/1"},
        ],
    }

    try:
        result = await dispatcher.execute(
            action="mint_nft",
            params={
                "collection_address": collection_address,
                "to": creator,
                "token_id": 1,
                "metadata": metadata,
                "royalty_bps": 500,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            mint = data["result"]
            ok(f"Minted: Quantum Dreams #001 (token ID 1)")
            ok(f"Owner: {creator}")
            ok(f"Metadata: {json.dumps(metadata['attributes'], indent=0)[:80]}...")
            if mint.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{mint['tx_hash']}")
        else:
            warn(f"Mint: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Minting: {e}")

    # ── Step 4: List for sale ───────────────────────────────────────
    step(4, "Listing NFT for sale at 0.5 ETH...")

    try:
        result = await dispatcher.execute(
            action="list_nft_for_sale",
            params={
                "collection_address": collection_address,
                "token_id": 1,
                "seller": creator,
                "price_eth": 0.5,
                "currency": "ETH",
                "duration_hours": 168,  # 7 days
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            listing = data["result"]
            ok(f"Listed for: 0.5 ETH")
            ok(f"Duration: 7 days")
            ok(f"Listing ID: {listing.get('listing_id', 'N/A')}")
        else:
            warn(f"Listing: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Listing: {e}")

    # ── Step 5: Simulate purchase with royalty distribution ─────────
    step(5, "Buyer purchases NFT — royalties distributed automatically")

    try:
        result = await dispatcher.execute(
            action="buy_nft",
            params={
                "collection_address": collection_address,
                "token_id": 1,
                "buyer": buyer,
                "price_eth": 0.5,
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            sale = data["result"]
            ok(f"Sale completed at 0.5 ETH")
            ok(f"New owner: {buyer[:10]}...{buyer[-6:]}")
            if sale.get("tx_hash"):
                ok(f"Tx: https://sepolia.basescan.org/tx/{sale['tx_hash']}")
        else:
            warn(f"Purchase: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Purchase: {e}")

    # Show the royalty breakdown
    print(f"\n  {BOLD}Royalty Distribution Breakdown:{RESET}")
    sale_price = 0.5
    royalty_total = sale_price * 0.05  # 5%
    creator_share = royalty_total * 0.80
    platform_share = royalty_total * 0.20
    seller_receives = sale_price - royalty_total

    print(f"  {DIM}{'─' * 45}{RESET}")
    print(f"  Sale price:        {sale_price:.4f} ETH")
    print(f"  Royalty (5%):      {royalty_total:.4f} ETH")
    print(f"    Creator (80%):   {creator_share:.4f} ETH")
    print(f"    Platform (20%):  {platform_share:.4f} ETH")
    print(f"  Seller receives:   {seller_receives:.4f} ETH")
    print(f"  {DIM}{'─' * 45}{RESET}")

    # ── Step 6: Show secondary sale royalties ───────────────────────
    step(6, "Simulating resale — royalties enforce on every transfer")

    resale_price = 2.0
    royalty_2 = resale_price * 0.05
    print(f"  {DIM}If resold at {resale_price} ETH:{RESET}")
    print(f"    Royalty: {royalty_2:.4f} ETH (creator gets {royalty_2 * 0.80:.4f} ETH)")
    print(f"    Seller receives: {resale_price - royalty_2:.4f} ETH")
    print(f"\n  {DIM}EIP-2981 royalties are enforced on-chain — the creator")
    print(f"  earns on every resale, automatically and permanently.{RESET}")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  NFT WITH ROYALTIES COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. create_nft_collection  - Deploy ERC-721 with royalties
    2. configure_nft_royalty   - Set EIP-2981 royalty splits
    3. mint_nft               - Mint with metadata + attributes
    4. list_nft_for_sale      - List on marketplace
    5. buy_nft                - Purchase with automatic royalty
    6. (resale scenario)      - Perpetual creator earnings

  {BOLD}Services used:{RESET}
    - NFT Services (Component 3)
    - IP & Royalties (Component 15)
    - Marketplace (Component 24)

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
