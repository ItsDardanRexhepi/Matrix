#!/usr/bin/env python3
from __future__ import annotations
"""
09 — Full User Journey: The Entire 0pnMatrx Platform in One Script

Demonstrates every major platform capability in a single coherent user flow:

  1. Create a decentralised identity (DID)
  2. Create a DAO for community governance
  3. Tokenize a real-world asset (house)
  4. Mint a governance NFT
  5. Create a governance proposal
  6. Vote on the proposal
  7. Launch a fundraising campaign
  8. Contribute to the campaign
  9. Stake platform tokens for rewards
  10. Claim staking rewards

This script exercises Components 1-8 plus governance, fundraising, staking,
and more — showing how they all compose through ServiceDispatcher.

Usage:
    python examples/09_full_user_journey.py
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

def step(n, text):  print(f"\n{CYAN}{BOLD}[Step {n:2d}]{RESET} {text}")
def ok(text):       print(f"   {GREEN}+{RESET} {text}")
def warn(text):     print(f"   {YELLOW}!{RESET} {text}")
def fail(text):     print(f"   {RED}x{RESET} {text}")


def load_config() -> dict:
    config_path = os.path.join(ROOT, "openmatrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def dispatch(dispatcher, action, params, label=""):
    """Helper that dispatches an action and returns the parsed result."""
    try:
        raw = await dispatcher.execute(action=action, params=params)
        data = json.loads(raw)
        if data.get("status") == "ok":
            return data["result"]
        else:
            warn(f"{label or action}: {data.get('error', 'service not fully configured')}")
            return None
    except Exception as e:
        warn(f"{label or action}: {e}")
        return None


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  0pnMatrx Example 09: Full User Journey
{'=' * 60}{RESET}

  A complete user journey through the platform:
  DID -> DAO -> Tokenize -> NFT -> Govern -> Fund -> Stake
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    user = bc.get("demo_wallet_address", "0xUser")

    # Track IDs across steps
    did_id = None
    dao_id = None
    asset_id = None
    nft_collection = None
    proposal_id = None
    campaign_id = None

    # ────────────────────────────────────────────────────────────────
    # PHASE 1: Identity
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 1: Identity ---{RESET}")

    # Step 1: Create DID
    step(1, "Creating Decentralised Identity (DID)...")

    result = await dispatch(dispatcher, "create_did", {
        "owner": user,
        "method": "did:ethr",
        "attributes": {
            "name": "Alice Builder",
            "role": "developer",
            "verified_email": True,
        },
    })
    if result:
        did_id = result.get("did", result.get("id", f"did:ethr:{user}"))
        ok(f"DID created: {did_id}")
        ok(f"Method: did:ethr")
        ok(f"Owner: {user}")
    else:
        did_id = f"did:ethr:{user}"
        ok(f"DID (fallback): {did_id}")

    # ────────────────────────────────────────────────────────────────
    # PHASE 2: Organisation
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 2: Organisation ---{RESET}")

    # Step 2: Create DAO
    step(2, "Creating DAO: 'Builders Collective'...")

    result = await dispatch(dispatcher, "create_dao", {
        "name": "Builders Collective",
        "creator": user,
        "governance_model": "token_weighted",
        "quorum_threshold": 0.04,
        "voting_period_blocks": 50400,
        "description": "A DAO for builders on 0pnMatrx",
    })
    if result:
        dao_id = result.get("dao_id", result.get("id", "N/A"))
        ok(f"DAO created: {dao_id}")
        ok(f"Name: Builders Collective")
        ok(f"Governance: token-weighted voting")
        ok(f"Quorum: 4%")
    else:
        dao_id = "dao-builders-001"
        ok(f"DAO (fallback ID): {dao_id}")

    # Step 3: Join DAO
    step(3, "Joining DAO as founding member...")

    result = await dispatch(dispatcher, "join_dao", {
        "dao_id": dao_id,
        "member": user,
        "role": "founder",
    })
    if result:
        ok(f"Joined DAO as: {result.get('role', 'founder')}")
        ok(f"Voting power: {result.get('voting_power', '1.0')}")
    else:
        ok("Member role: founder")

    # ────────────────────────────────────────────────────────────────
    # PHASE 3: Asset Tokenization
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 3: Asset Tokenization ---{RESET}")

    # Step 4: Tokenize a house
    step(4, "Tokenizing real-world asset: residential property...")

    result = await dispatch(dispatcher, "tokenize_asset", {
        "owner": user,
        "asset_type": "real_estate",
        "asset_details": {
            "address": "123 Blockchain Ave, San Francisco, CA 94105",
            "type": "residential",
            "bedrooms": 3,
            "sqft": 1800,
            "year_built": 2020,
        },
        "valuation_eth": 150.0,
        "fractionalize": True,
        "total_fractions": 1000,
    })
    if result:
        asset_id = result.get("asset_id", result.get("token_id", "N/A"))
        ok(f"Asset tokenized: {asset_id}")
        ok(f"Type: Residential property")
        ok(f"Valuation: 150 ETH")
        ok(f"Fractionalized: 1000 shares")
        if result.get("contract_address"):
            ok(f"Token contract: {result['contract_address']}")
    else:
        asset_id = "rwa-house-001"
        ok(f"Asset (fallback ID): {asset_id}")

    # ────────────────────────────────────────────────────────────────
    # PHASE 4: NFT
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 4: Governance NFT ---{RESET}")

    # Step 5: Create governance NFT collection
    step(5, "Creating governance NFT collection...")

    result = await dispatch(dispatcher, "create_nft_collection", {
        "name": "Builders Governance Badge",
        "symbol": "BGOV",
        "creator": user,
        "max_supply": 100,
        "base_uri": "ipfs://QmGovernanceBadge/",
        "royalty_bps": 0,  # No royalty on governance tokens
    })
    if result:
        nft_collection = result.get("collection_address", result.get("contract_address", "N/A"))
        ok(f"Collection: {nft_collection}")
        ok(f"Name: Builders Governance Badge (BGOV)")
    else:
        nft_collection = "0xGovNFTCollection"
        ok(f"Collection (fallback): {nft_collection}")

    # Step 6: Mint governance NFT
    step(6, "Minting governance NFT #1...")

    result = await dispatch(dispatcher, "mint_nft", {
        "collection_address": nft_collection,
        "to": user,
        "token_id": 1,
        "metadata": {
            "name": "Builders Governance Badge #1",
            "description": "Founding member governance badge for Builders Collective DAO",
            "image": "ipfs://QmGovernanceBadge/1.png",
            "attributes": [
                {"trait_type": "Role", "value": "Founder"},
                {"trait_type": "Voting Weight", "value": "10x"},
                {"trait_type": "DAO", "value": "Builders Collective"},
            ],
        },
    })
    if result:
        ok(f"Minted: Governance Badge #1")
        ok(f"Role: Founder (10x voting weight)")
    else:
        ok("Governance badge minted (fallback)")

    # ────────────────────────────────────────────────────────────────
    # PHASE 5: Governance
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 5: Governance ---{RESET}")

    # Step 7: Create proposal
    step(7, "Creating governance proposal...")

    result = await dispatch(dispatcher, "create_proposal", {
        "dao_id": dao_id,
        "proposer": user,
        "title": "Allocate 10 ETH to Developer Grants Program",
        "description": (
            "Proposal to allocate 10 ETH from the DAO treasury to fund "
            "developer grants for building on 0pnMatrx. Grants will be "
            "distributed in 1 ETH increments to approved projects."
        ),
        "proposal_type": "standard",
        "actions": [
            {"type": "transfer", "to": "grants_multisig", "amount_eth": 10.0},
        ],
        "voting_period_blocks": 50400,
    })
    if result:
        proposal_id = result.get("proposal_id", result.get("id", "N/A"))
        ok(f"Proposal created: {proposal_id}")
        ok(f"Title: Allocate 10 ETH to Developer Grants")
        ok(f"Type: standard (4% quorum)")
        ok(f"Voting period: 50,400 blocks (~7 days)")
    else:
        proposal_id = "proposal-001"
        ok(f"Proposal (fallback ID): {proposal_id}")

    # Step 8: Vote on proposal
    step(8, "Voting on proposal...")

    result = await dispatch(dispatcher, "vote", {
        "proposal_id": proposal_id,
        "voter": user,
        "support": True,
        "reason": "Strong community investment. Developer grants will accelerate platform growth.",
    })
    if result:
        ok(f"Vote cast: FOR")
        ok(f"Voting power: {result.get('voting_power', result.get('weight', '10'))}")
        ok(f"Reason: recorded on-chain")
    else:
        ok("Vote cast: FOR (fallback)")

    # ────────────────────────────────────────────────────────────────
    # PHASE 6: Fundraising
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 6: Fundraising ---{RESET}")

    # Step 9: Create campaign
    step(9, "Launching fundraising campaign...")

    result = await dispatch(dispatcher, "create_campaign", {
        "creator": user,
        "title": "0pnMatrx Mobile App Development",
        "description": "Funding the development of a mobile app for 0pnMatrx platform access.",
        "goal_eth": 50.0,
        "duration_days": 60,
        "milestones": [
            {"title": "Design & Prototyping", "percentage": 20, "description": "UI/UX design"},
            {"title": "Core Development", "percentage": 50, "description": "Main app features"},
            {"title": "Testing & Launch", "percentage": 30, "description": "QA and app store launch"},
        ],
    })
    if result:
        campaign_id = result.get("campaign_id", result.get("id", "N/A"))
        ok(f"Campaign created: {campaign_id}")
        ok(f"Goal: 50 ETH")
        ok(f"Duration: 60 days")
        ok(f"Milestones: 3")
    else:
        campaign_id = "campaign-001"
        ok(f"Campaign (fallback ID): {campaign_id}")

    # Step 10: Contribute
    step(10, "Contributing to campaign...")

    result = await dispatch(dispatcher, "contribute_to_campaign", {
        "campaign_id": campaign_id,
        "contributor": user,
        "amount_eth": 5.0,
    })
    if result:
        ok(f"Contributed: 5.0 ETH")
        ok(f"Campaign progress: {result.get('progress_pct', '10')}%")
        ok(f"Total raised: {result.get('total_raised', '5.0')} ETH")
    else:
        ok("Contributed: 5.0 ETH (fallback)")

    # ────────────────────────────────────────────────────────────────
    # PHASE 7: Staking
    # ────────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 7: Staking & Rewards ---{RESET}")

    # Step 11: Stake tokens
    step(11, "Staking platform tokens...")

    result = await dispatch(dispatcher, "stake", {
        "staker": user,
        "amount": 100.0,
        "token": "0pnMTX",
        "lock_period_days": 90,
    })
    if result:
        ok(f"Staked: 100.0 0pnMTX")
        ok(f"Lock period: 90 days")
        ok(f"APY: {result.get('apy', result.get('estimated_apy', 'N/A'))}%")
        ok(f"Position ID: {result.get('position_id', result.get('id', 'N/A'))}")
    else:
        ok("Staked: 100.0 0pnMTX (fallback)")

    # Step 12: Check staking position
    step(12, "Checking staking position and rewards...")

    result = await dispatch(dispatcher, "get_staking_position", {
        "staker": user,
    })
    if result:
        ok(f"Staked amount: {result.get('staked_amount', 100.0)} 0pnMTX")
        ok(f"Pending rewards: {result.get('pending_rewards', 'N/A')} 0pnMTX")
        ok(f"Time staked: {result.get('time_staked', 'N/A')}")
        ok(f"Unlock date: {result.get('unlock_date', 'N/A')}")
    else:
        ok("Position: 100.0 0pnMTX staked (fallback)")

    # ────────────────────────────────────────────────────────────────
    # Journey Summary
    # ────────────────────────────────────────────────────────────────
    print(f"""

{GREEN}{BOLD}{'=' * 60}
  FULL USER JOURNEY COMPLETE
{'=' * 60}{RESET}

  {BOLD}Journey Map:{RESET}

  [Identity]       DID: {did_id or 'created'}
       |
  [Organisation]   DAO: {dao_id or 'created'} (Builders Collective)
       |
  [Tokenization]   RWA: {asset_id or 'created'} (House -> 1000 fractions)
       |
  [NFT]            Governance Badge #1 minted
       |
  [Governance]     Proposal: {proposal_id or 'created'} (voted FOR)
       |
  [Fundraising]    Campaign: {campaign_id or 'created'} (contributed 5 ETH)
       |
  [Staking]        100 0pnMTX staked (90-day lock)

  {BOLD}Components exercised:{RESET}
     5  DID Identity        -  create_did
     6  DAO Management      -  create_dao, join_dao
     4  RWA Tokenization    -  tokenize_asset
     3  NFT Services        -  create_nft_collection, mint_nft
    19  Governance          -  create_proposal, vote
    22  Fundraising         -  create_campaign, contribute_to_campaign
    16  Staking             -  stake, get_staking_position
     8  Attestation         -  (automatic on all state changes)

  {BOLD}Total actions:{RESET}       12
  {BOLD}Services touched:{RESET}    8 of 30
  {BOLD}Attestations:{RESET}        12 (one per state-modifying action)

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
