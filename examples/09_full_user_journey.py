#!/usr/bin/env python3
from __future__ import annotations
"""
09 — Full User Journey: One User Through Seven Services

Walks one user through a sequence of platform actions, each dispatched
through ServiceDispatcher:

  1. Create a decentralised identity (DID)
  2. Create a DAO and join it
  3. Tokenize a real-world asset (a house)
  4. Create a governance NFT collection and mint a badge
  5. Create a governance proposal and vote on it
  6. Launch a fundraising campaign and contribute to it
  7. Stake into the default staking pool and read the position back

Usage:
    python examples/09_full_user_journey.py            # live (uses config)
    python examples/09_full_user_journey.py --dry-run  # no dispatch calls

Every step prints what the service answered. A step the service refused or
could not run (until the platform contracts are deployed, most answer
``not_deployed``) is reported as not done, and a step that needs an id an
earlier step did not produce is skipped rather than run with an invented one.
The summary lists which steps happened. Deploying the contracts is covered
in contracts/DEPLOYMENT_GUIDE.md.
"""

import argparse
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
    config_path = os.path.join(ROOT, "matrix.config.json")
    if not os.path.exists(config_path):
        fail(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


DRY_RUN = False


async def dispatch(dispatcher, action, params, label=""):
    """Helper that dispatches an action and returns the parsed result."""
    if DRY_RUN:
        warn(f"[dry-run] would call {action}({len(params)} params)")
        return None
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
  The Matrix Example 09: Full User Journey
{'=' * 60}{RESET}

  One user through the platform:
  DID -> DAO -> Tokenize -> NFT -> Govern -> Fund -> Stake
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    bc = config.get("blockchain", {})
    user = bc.get("demo_wallet_address", "0xUser")
    done: dict[str, bool] = {}

    def shown(result, *keys):
        """The first of *keys* the service's answer carries, or 'not reported'."""
        for key in keys:
            if result.get(key) not in (None, ""):
                return result[key]
        return "not reported"

    async def run(label, action, params, needs=()):
        """Dispatch *action*, record whether it happened, return its result."""
        missing = [name for name, value in needs if not value]
        if missing:
            warn(f"Skipped: no {', '.join(missing)} from an earlier step")
            done[label] = False
            return None
        result = await dispatch(dispatcher, action, params)
        done[label] = result is not None
        if result is None and not DRY_RUN:
            warn(f"Not done: {label}")
        return result

    # ── Phase 1: Identity ──────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 1: Identity ---{RESET}")
    step(1, "Creating a decentralised identity (DID)...")
    result = await run("create a DID", "create_did", {"owner": user})
    did_id = None
    if result is not None:
        did_id = result.get("did") or result.get("id")
        ok(f"DID: {did_id or 'not reported'}")

    # ── Phase 2: Organisation ──────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 2: Organisation ---{RESET}")
    step(2, "Creating DAO: 'Builders Collective'...")
    result = await run("create a DAO", "create_dao", {
        "name": "Builders Collective",
        "creator": user,
        "governance_model": "token_weighted",
        "quorum_threshold": 0.04,
        "voting_period_blocks": 50400,
        "description": "A DAO for builders on The Matrix",
    })
    dao_id = None
    if result is not None:
        dao_id = result.get("dao_id") or result.get("id")
        ok(f"DAO: {dao_id or 'not reported'}")

    step(3, "Joining the DAO...")
    result = await run("join the DAO", "join_dao",
                       {"dao_id": dao_id, "member": user, "role": "founder"},
                       needs=[("DAO id", dao_id)])
    if result is not None:
        ok(f"Role: {shown(result, 'role')}")
        ok(f"Voting power: {shown(result, 'voting_power')}")

    # ── Phase 3: Asset tokenization ────────────────────────────────
    print(f"\n{BOLD}  --- Phase 3: Asset Tokenization ---{RESET}")
    step(4, "Tokenizing a residential property...")
    result = await run("tokenize an asset", "tokenize_asset", {
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
    if result is not None:
        ok(f"Asset: {shown(result, 'asset_id', 'token_id')}")
        ok(f"Token contract: {shown(result, 'contract_address')}")

    # ── Phase 4: Governance NFT ────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 4: Governance NFT ---{RESET}")
    step(5, "Creating a governance NFT collection...")
    result = await run("create an NFT collection", "create_nft_collection", {
        "name": "Builders Governance Badge",
        "symbol": "BGOV",
        "creator": user,
        "max_supply": 100,
        "base_uri": "ipfs://QmGovernanceBadge/",
        "royalty_bps": 0,
    })
    collection = None
    if result is not None:
        collection = result.get("collection_address") or result.get("contract_address")
        ok(f"Collection: {collection or 'not reported'}")

    step(6, "Minting governance badge #1...")
    result = await run("mint the badge", "mint_nft", {
        "collection_address": collection,
        "to": user,
        "token_id": 1,
        "metadata": {
            "name": "Builders Governance Badge #1",
            "description": "Founding member governance badge for Builders Collective DAO",
            "image": "ipfs://QmGovernanceBadge/1.png",
        },
    }, needs=[("collection address", collection)])
    if result is not None:
        ok(f"Token: {shown(result, 'token_id', 'id')}")

    # ── Phase 5: Governance ────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 5: Governance ---{RESET}")
    step(7, "Creating a governance proposal...")
    result = await run("create a proposal", "create_proposal", {
        "dao_id": dao_id,
        "proposer": user,
        "title": "Allocate 10 ETH to Developer Grants Program",
        "description": ("Proposal to allocate 10 ETH from the DAO treasury to fund "
                        "developer grants for building on The Matrix."),
        "proposal_type": "standard",
        "actions": [{"type": "transfer", "to": "grants_multisig", "amount_eth": 10.0}],
        "voting_period_blocks": 50400,
    }, needs=[("DAO id", dao_id)])
    proposal_id = None
    if result is not None:
        proposal_id = result.get("proposal_id") or result.get("id")
        ok(f"Proposal: {proposal_id or 'not reported'}")

    step(8, "Voting on the proposal...")
    result = await run("vote", "vote", {
        "proposal_id": proposal_id,
        "voter": user,
        "support": True,
        "reason": "Developer grants will accelerate platform growth.",
    }, needs=[("proposal id", proposal_id)])
    if result is not None:
        ok(f"Voting power: {shown(result, 'voting_power', 'weight')}")

    # ── Phase 6: Fundraising ───────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 6: Fundraising ---{RESET}")
    step(9, "Launching a fundraising campaign...")
    result = await run("create a campaign", "create_campaign", {
        "creator": user,
        "title": "The Matrix Mobile App Development",
        "description": "Funding the development of a mobile app for The Matrix platform access.",
        "goal_eth": 50.0,
        "duration_days": 60,
        "milestones": [
            {"title": "Design & Prototyping", "percentage": 20, "description": "UI/UX design"},
            {"title": "Core Development", "percentage": 50, "description": "Main app features"},
            {"title": "Testing & Launch", "percentage": 30, "description": "QA and app store launch"},
        ],
    })
    campaign_id = None
    if result is not None:
        campaign_id = result.get("campaign_id") or result.get("id")
        ok(f"Campaign: {campaign_id or 'not reported'}")

    step(10, "Contributing to the campaign...")
    result = await run("contribute", "contribute_to_campaign",
                       {"campaign_id": campaign_id, "contributor": user, "amount_eth": 5.0},
                       needs=[("campaign id", campaign_id)])
    if result is not None:
        ok(f"Total raised: {shown(result, 'total_raised')}")

    # ── Phase 7: Staking ───────────────────────────────────────────
    print(f"\n{BOLD}  --- Phase 7: Staking ---{RESET}")
    step(11, "Staking 100 tokens into the default pool...")
    result = await run("stake", "stake", {"staker": user, "amount": 100.0, "pool_id": "default"})
    if result is not None:
        ok(f"Staked amount: {shown(result, 'staked_amount', 'amount')}")

    step(12, "Reading the staking position...")
    result = await run("read the staking position", "get_staking_position", {"staker": user})
    if result is not None:
        ok(f"Staked amount: {shown(result, 'staked_amount', 'amount')}")
        ok(f"Pending rewards: {shown(result, 'pending_rewards')}")

    # ── Summary ────────────────────────────────────────────────────
    happened = [label for label, ok_ in done.items() if ok_]
    print(f"\n{BOLD}{'=' * 60}\n  Journey summary: {len(happened)} of {len(done)} steps happened\n{'=' * 60}{RESET}")
    for label, ok_ in done.items():
        (ok if ok_ else warn)(f"{label}: {'done' if ok_ else 'not done'}")
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
