#!/usr/bin/env python3
from __future__ import annotations
"""
09 — Full User Journey: One User Through Seven Services

Walks one user through a sequence of platform actions, each dispatched
through ServiceDispatcher:

  1. Create a decentralised identity (DID)
  2. Create a DAO and join it
  3. Tokenize a real-world asset (a house)
  4. Create an NFT collection and mint a badge in it
  5. Create a governance proposal and vote on it
  6. Launch a fundraising campaign and contribute to it
  7. Stake into the default staking pool and read the position back

Usage:
    python examples/09_full_user_journey.py            # live (uses config)
    python examples/09_full_user_journey.py --dry-run  # no dispatch calls

Every step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened: its envelope's call_outcome is
"success". The envelope's own "ok" says only that the dispatch ran, and it
says that when the service answered ``not_deployed``. A step that needs an id
an earlier step did not produce is skipped rather than run with an invented
one, and the summary lists which steps happened.

Which steps can happen depends on the gateway. The DAO, the NFT collection
and the stake each need a platform contract deployed on the configured chain
(contracts/DEPLOYMENT_GUIDE.md); until then each answers ``not_deployed`` and
the steps that need its id are skipped. The DID, the asset record, the
proposal, the vote and the campaign are kept by their services themselves.
The governance service's proposals are its own and are not tied to the DAO:
create_proposal takes no DAO id.
"""

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
from examples._steps import BOLD, CYAN, DIM, RESET, Steps, fail, ok, shown, step


def load_config() -> dict:
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


DRY_RUN = False


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  The Matrix Example 09: Full User Journey
{'=' * 60}{RESET}

  One user through the platform:
  DID -> DAO -> Tokenize -> NFT -> Govern -> Fund -> Stake
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    user = config.get("blockchain", {}).get("demo_wallet_address", "0xUser")
    steps = Steps(dispatcher, dry_run=DRY_RUN)

    # ── Phase 1: Identity ──────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 1: Identity ---{RESET}")
    step(1, "Creating a decentralised identity (DID)...")
    did = await steps.run("create a DID", "create_did", {"owner": user})
    if did is not None:
        ok(f"DID: {shown(did, 'did', 'id')}")

    # ── Phase 2: Organisation ──────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 2: Organisation ---{RESET}")
    step(2, "Creating DAO: 'Builders Collective'...")
    dao = await steps.run("create a DAO", "create_dao", {
        "creator": user,
        "name": "Builders Collective",
        "config": {"governance_type": "one_person_one_vote",
                   "description": "A DAO for builders on The Matrix"},
    })
    dao_id = dao.get("dao_id") or dao.get("id") if dao is not None else None
    if dao is not None:
        ok(f"DAO: {dao_id or 'not reported'}")

    step(3, "Joining the DAO...")
    joined = await steps.run("join the DAO", "join_dao",
                             {"dao_id": dao_id, "member": user, "stake": 0.0},
                             needs=[("DAO id", dao_id)])
    if joined is not None:
        ok(f"Members: {shown(joined, 'member_count')}")

    # ── Phase 3: Asset tokenization ────────────────────────────────
    print(f"\n{BOLD}  --- Phase 3: Asset Tokenization ---{RESET}")
    step(4, "Tokenizing a residential property...")
    asset = await steps.run("tokenize an asset", "tokenize_asset", {
        "owner": user,
        "asset_type": "property",
        "metadata": {
            "address": "123 Blockchain Ave, San Francisco, CA 94105",
            "sq_footage": 1800,
            "zoning": "residential",
            "title_deed_hash": "0x" + "ab" * 32,
        },
        "valuation": 150.0,
    })
    if asset is not None:
        ok(f"Asset: {shown(asset, 'token_id', 'asset_id')}")

    # ── Phase 4: NFT ───────────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 4: NFT ---{RESET}")
    step(5, "Creating an NFT collection for member badges...")
    made = await steps.run("create an NFT collection", "create_nft_collection", {
        "creator": user, "name": "Builders Badge", "symbol": "BGOV",
        "collection_type": "erc721", "royalty_bps": 0,
    })
    collection = None
    if made is not None:
        collection = made.get("collection_address") or made.get("contract_address") or made.get("collection")
        ok(f"Collection: {collection or 'not reported'}")

    step(6, "Minting badge #1...")
    minted = await steps.run("mint the badge", "mint_nft", {
        "collection": collection,
        "creator": user,
        "metadata": {"name": "Builders Badge #1",
                     "description": "Founding member badge",
                     "image": "ipfs://QmGovernanceBadge/1.png"},
        "royalty_bps": 0,
    }, needs=[("collection address", collection)])
    if minted is not None:
        ok(f"Token: {shown(minted, 'token_id', 'id')}")

    # ── Phase 5: Governance ────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 5: Governance ---{RESET}")
    step(7, "Creating a governance proposal...")
    proposal = await steps.run("create a proposal", "create_proposal", {
        "proposer": user,
        "title": "Fund a developer grants program",
        "description": "Proposal to fund developer grants for building on The Matrix.",
        "voting_model": "one_person_one_vote",
        "options": ["yes", "no", "abstain"],
    })
    proposal_id = proposal.get("proposal_id") or proposal.get("id") if proposal is not None else None
    if proposal is not None:
        ok(f"Proposal: {proposal_id or 'not reported'}")

    step(8, "Voting on the proposal...")
    voted = await steps.run("vote", "vote", {"proposal_id": proposal_id, "voter": user, "choice": "yes"},
                            needs=[("proposal id", proposal_id)])
    if voted is not None:
        ok(f"Choice: {shown(voted, 'choice')}; weight: {shown(voted, 'weight')}")

    # ── Phase 6: Fundraising ───────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 6: Fundraising ---{RESET}")
    step(9, "Launching a fundraising campaign...")
    campaign = await steps.run("create a campaign", "create_campaign", {
        "creator": user,
        "title": "The Matrix mobile app development",
        "goal": 150.0,
        "deadline_days": 60,
        "milestones": [
            {"title": "Design & Prototyping", "description": "UI/UX design", "release_pct": 20},
            {"title": "Core Development", "description": "Main app features", "release_pct": 50},
            {"title": "Testing & Launch", "description": "QA and launch", "release_pct": 30},
        ],
    })
    campaign_id = campaign.get("campaign_id") or campaign.get("id") if campaign is not None else None
    if campaign is not None:
        ok(f"Campaign: {campaign_id or 'not reported'}")

    step(10, "Contributing to the campaign...")
    contributed = await steps.run("contribute", "contribute_to_campaign",
                                  {"campaign_id": campaign_id, "contributor": user, "amount": 5.0},
                                  needs=[("campaign id", campaign_id)])
    if contributed is not None:
        ok(f"Total raised: {shown(contributed, 'total_raised', 'raised')}")

    # ── Phase 7: Staking ───────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 7: Staking ---{RESET}")
    step(11, "Staking 100 tokens into the default pool...")
    staked = await steps.run("stake", "stake", {"staker": user, "amount": 100.0, "pool_id": "default"})
    if staked is not None:
        ok(f"Staked amount: {shown(staked, 'staked_amount', 'amount')}")

    step(12, "Reading the staking position...")
    position = await steps.run("read the staking position", "get_staking_position",
                               {"staker": user, "pool_id": "default"})
    if position is not None:
        ok(f"Staked amount: {shown(position, 'staked_amount', 'amount')}")
        ok(f"Pending rewards: {shown(position, 'pending_rewards')}")

    steps.summary("Journey summary")
    print(f"\n  {DIM}When a state-modifying action completes, the service dispatcher queues an EAS")
    print(f"  attestation of it; the queue is written to the chain once 50 have gathered in the")
    print(f"  same process, and what is queued is lost if the process exits first.{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The Matrix full user journey example")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip dispatcher calls and print what would happen.",
    )
    args = parser.parse_args()
    DRY_RUN = args.dry_run
    asyncio.run(main())
