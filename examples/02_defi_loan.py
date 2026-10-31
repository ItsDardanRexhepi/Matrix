#!/usr/bin/env python3
from __future__ import annotations
"""
02 — DeFi Loan: Collateralised Lending

Calls the DeFi service's loan actions through ServiceDispatcher:

  1. create_loan: deposit ETH as collateral and borrow USDC against it
  2. get_loan: read the loan back
  3. repay_loan: repay it in full

Each step prints what the service answered, and a step counts as done only
when the dispatcher reports that it happened (its call_outcome is "success").
Until ``defi.lending_pool_address`` points at a deployed contract on the
configured chain, create_loan answers ``not_deployed`` with a deployment
guide, and the two steps after it are skipped because there is no loan id to
read or repay. Deploying the contracts is covered in
contracts/DEPLOYMENT_GUIDE.md.

Usage:
    python examples/02_defi_loan.py
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
        fail("Copy matrix.config.json.example and configure it.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    print(f"""
{CYAN}{BOLD}{'=' * 60}
  The Matrix Example 02: DeFi Collateralised Loan
{'=' * 60}{RESET}

  Deposit 0.1 ETH as collateral, borrow 100 USDC, read the loan, repay it.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    wallet = config.get("blockchain", {}).get("demo_wallet_address", "0xDemoWallet")
    steps = Steps(dispatcher)

    step(1, "Creating a collateralised loan: 0.1 ETH collateral, 100 USDC borrowed...")
    loan = await steps.run("create the loan", "create_loan", {
        "borrower": wallet,
        "collateral_token": "ETH",
        "collateral_amount": 0.1,
        "borrow_token": "USDC",
        "borrow_amount": 100.0,
    })
    loan_id = None
    if loan is not None:
        loan_id = loan.get("loan_id") or loan.get("id")
        ok(f"Loan: {loan_id or 'not reported'}")
        ok(f"Health factor: {shown(loan, 'health_factor')}")
        ok(f"Interest rate: {shown(loan, 'interest_rate')}")
        if loan.get("tx_hash"):
            ok(f"Tx: https://sepolia.basescan.org/tx/{loan['tx_hash']}")

    step(2, "Reading the loan back...")
    info = await steps.run("read the loan", "get_loan", {"loan_id": loan_id},
                           needs=[("loan id", loan_id)])
    if info is not None:
        ok(f"Status: {shown(info, 'status')}")
        ok(f"Health factor: {shown(info, 'health_factor')}")
        ok(f"Outstanding debt: {shown(info, 'outstanding_debt', 'borrow_amount')}")

    step(3, "Repaying the loan in full...")
    repay = await steps.run("repay the loan", "repay_loan", {"loan_id": loan_id, "amount": 100.0},
                            needs=[("loan id", loan_id)])
    if repay is not None:
        ok(f"Status: {shown(repay, 'status')}")
        ok(f"Repaid: {shown(repay, 'repaid_amount', 'amount')}")
        if repay.get("tx_hash"):
            ok(f"Tx: https://sepolia.basescan.org/tx/{repay['tx_hash']}")

    steps.summary("DeFi loan")


if __name__ == "__main__":
    asyncio.run(main())
