#!/usr/bin/env python3
from __future__ import annotations
"""
04 — Parametric Insurance: Weather-Based Crop Insurance

Calls the insurance service and the oracle gateway through ServiceDispatcher:

  1. create_insurance: a crop policy for Fresno, CA (5 ETH cover, 0.25 ETH premium)
  2. oracle_request: the weather oracle's reading for the same place
  3. file_insurance_claim: a claim against the policy, by its holder
  4. get_insurance_policy: the policy's record afterwards

Each step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened (its call_outcome is "success").
A claim is judged against oracle data the insurance service fetches itself,
never against data the claimant sends, and it fails closed when no trigger or
no oracle answer is available; any payout, and its amount, is the service's
answer to report. Until the insurance contract is deployed, create_insurance
answers ``not_deployed`` and the claim and the policy read are skipped. The
weather reading needs a weather provider configured for the oracle gateway.

Usage:
    python examples/04_parametric_insurance.py
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


FRESNO = "36.7378,-119.7871"


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  The Matrix Example 04: Parametric Crop Insurance
{'=' * 60}{RESET}

  A policy that pays when the oracle's rainfall reading for the insured
  place falls below the threshold the policy sets.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    farmer = config.get("blockchain", {}).get("demo_wallet_address", "0xFarmer")
    steps = Steps(dispatcher)

    step(1, "Creating a crop policy: 5 ETH cover for 180 days, 0.25 ETH premium...")
    policy = await steps.run("create the policy", "create_insurance", {
        "holder": farmer,
        "policy_type": "crop",
        "coverage": {
            "amount": 5.0,
            "duration_days": 180,
            "location": FRESNO,
            "trigger": {"metric": "rainfall_mm", "below": 50.0, "period": "monthly"},
        },
        "premium": 0.25,
    })
    policy_id = None
    if policy is not None:
        policy_id = policy.get("policy_id") or policy.get("id")
        ok(f"Policy: {policy_id or 'not reported'}")
        ok(f"Status: {shown(policy, 'status')}")
        if policy.get("tx_hash"):
            ok(f"Tx: https://sepolia.basescan.org/tx/{policy['tx_hash']}")

    step(2, "Asking the oracle gateway for the weather at the insured place...")
    reading = await steps.run("read the weather", "oracle_request", {
        "oracle_type": "weather", "params": {"location": FRESNO},
    })
    if reading is not None:
        ok(f"Source: {shown(reading, 'source', 'provider')}")
        ok(f"Reading: {shown(reading, 'data', 'value')}")

    step(3, "Filing a claim against the policy, as its holder...")
    claim = await steps.run("file a claim", "file_insurance_claim", {
        "policy_id": policy_id, "caller": farmer,
    }, needs=[("policy id", policy_id)])
    if claim is not None:
        ok(f"Claim: {shown(claim, 'claim_id', 'id')}")
        ok(f"Status: {shown(claim, 'status')}")
        ok(f"Payout: {shown(claim, 'payout_amount', 'payout')}")

    step(4, "Reading the policy's record...")
    record = await steps.run("read the policy", "get_insurance_policy", {"policy_id": policy_id},
                             needs=[("policy id", policy_id)])
    if record is not None:
        ok(f"Status: {shown(record, 'status')}")

    steps.summary("Parametric insurance")


if __name__ == "__main__":
    asyncio.run(main())
