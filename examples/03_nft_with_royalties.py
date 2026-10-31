#!/usr/bin/env python3
from __future__ import annotations
"""
03 — NFT with Royalties: Create, Mint, List and Sell

Calls the NFT service's actions through ServiceDispatcher:

  1. create_nft_collection: an ERC-721 collection with a 5% (500 bps) royalty
  2. configure_nft_royalty: the EIP-2981 royalty for token 1
  3. mint_nft: token 1 with metadata
  4. list_nft_for_sale: token 1 at 0.5 ETH
  5. buy_nft: a buyer's purchase, which the service settles with the royalty

Each step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened (its call_outcome is "success").
The royalty split of a sale is the service's to report; this example does
not compute one. Until the NFT factory is deployed and wired in, the
collection answers ``not_deployed`` and the steps that need its address are
skipped. Deploying the contracts is covered in contracts/DEPLOYMENT_GUIDE.md.

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
from examples._steps import BOLD, CYAN, RESET, Steps, fail, ok, shown, step


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
  The Matrix Example 03: NFT with Royalties
{'=' * 60}{RESET}

  An ERC-721 collection with an EIP-2981 royalty of 5%, one token,
  a listing and a sale.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    creator = config.get("blockchain", {}).get("demo_wallet_address", "0xCreator")
    buyer = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"  # example buyer
    steps = Steps(dispatcher)

    step(1, "Creating the NFT collection 'Genesis Art Collection' (GART)...")
    made = await steps.run("create the collection", "create_nft_collection", {
        "creator": creator,
        "name": "Genesis Art Collection",
        "symbol": "GART",
        "collection_type": "erc721",
        "royalty_bps": 500,
    })
    collection = None
    if made is not None:
        collection = made.get("collection_address") or made.get("contract_address") or made.get("collection")
        ok(f"Collection: {collection or 'not reported'}")
        if made.get("tx_hash"):
            ok(f"Tx: https://sepolia.basescan.org/tx/{made['tx_hash']}")

    step(2, "Configuring the EIP-2981 royalty for token 1 (500 bps to the creator)...")
    royalty = await steps.run("configure the royalty", "configure_nft_royalty", {
        "collection": collection, "token_id": 1, "recipient": creator, "bps": 500,
    }, needs=[("collection address", collection)])
    if royalty is not None:
        ok(f"Royalty: {shown(royalty, 'bps', 'royalty_bps')} bps to {shown(royalty, 'recipient')}")

    step(3, "Minting token 1: 'Quantum Dreams #001'...")
    minted = await steps.run("mint the token", "mint_nft", {
        "collection": collection,
        "creator": creator,
        "metadata": {
            "name": "Quantum Dreams #001",
            "description": "A generative art piece exploring quantum probability fields.",
            "image": "ipfs://QmExampleImageHash/001.png",
        },
        "royalty_bps": 500,
    }, needs=[("collection address", collection)])
    token_id = None
    if minted is not None:
        token_id = minted.get("token_id")
        ok(f"Token: {token_id if token_id is not None else 'not reported'}")
        if minted.get("tx_hash"):
            ok(f"Tx: https://sepolia.basescan.org/tx/{minted['tx_hash']}")

    step(4, "Listing the token for sale at 0.5 ETH...")
    listing = await steps.run("list the token", "list_nft_for_sale", {
        "collection": collection, "token_id": token_id, "price": 0.5,
    }, needs=[("collection address", collection), ("token id", token_id is not None)])
    if listing is not None:
        ok(f"Listing: {shown(listing, 'listing_id', 'id')}")

    step(5, "The buyer purchases the token...")
    sale = await steps.run("sell the token", "buy_nft", {
        "collection": collection, "token_id": token_id, "sale_price": 0.5,
        "seller": creator, "buyer": buyer,
    }, needs=[("listing", listing)])
    if sale is not None:
        ok(f"Royalty paid: {shown(sale, 'royalty_amount', 'royalty')}")
        ok(f"Seller received: {shown(sale, 'seller_proceeds', 'seller_amount')}")
        ok(f"Token transferred: {shown(sale, 'nft_transferred')}")

    steps.summary("NFT with royalties")


if __name__ == "__main__":
    asyncio.run(main())
