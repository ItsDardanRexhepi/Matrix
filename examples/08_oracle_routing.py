#!/usr/bin/env python3
from __future__ import annotations
"""
08 — Oracle Gateway: One Entry Point for Several Oracle Types

Calls the oracle gateway through ServiceDispatcher:

  1. get_price: the ETH/USD price feed
  2. get_price: the BTC/USD and LINK/USD feeds
  3. oracle_request: the weather oracle's reading for Fresno, CA
  4. oracle_request: a Chainlink VRF request for three random words

The gateway takes an oracle type (price_feed, weather, sports, random_vrf or
custom) and that type's parameters (runtime/blockchain/services/oracle_gateway).
get_price is its price_feed read, which answers with a structured error
rather than raising when the provider fails. Each step prints what the
gateway answered, and a step counts as done only when the dispatcher reports
that it happened (its call_outcome is "success"). A price feed needs an RPC
the gateway can read, the weather reading a weather provider's API key, and
VRF a coordinator and subscription; without them the step says what is
missing.

Usage:
    python examples/08_oracle_routing.py
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
  The Matrix Example 08: Oracle Gateway
{'=' * 60}{RESET}
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    steps = Steps(dispatcher)

    step(1, "Requesting the ETH/USD price feed...")
    price = await steps.run("read ETH/USD", "get_price", {"pair": "ETH/USD"})
    if price is not None:
        ok(f"Price: {shown(price, 'price', 'value')}")
        ok(f"Source: {shown(price, 'source')}")
        ok(f"Updated: {shown(price, 'updated_at', 'timestamp')}")

    step(2, "Requesting the BTC/USD and LINK/USD feeds...")
    for pair in ("BTC/USD", "LINK/USD"):
        other = await steps.run(f"read {pair}", "get_price", {"pair": pair})
        if other is not None:
            ok(f"{pair}: {shown(other, 'price', 'value')}")

    step(3, "Requesting the weather at Fresno, CA...")
    weather = await steps.run("read the weather", "oracle_request", {
        "oracle_type": "weather", "params": {"location": "36.7378,-119.7871"},
    })
    if weather is not None:
        ok(f"Reading: {shown(weather, 'data', 'value')}")
        ok(f"Source: {shown(weather, 'source', 'provider')}")

    step(4, "Requesting three random words from Chainlink VRF...")
    vrf = await steps.run("request VRF randomness", "oracle_request", {
        "oracle_type": "random_vrf", "params": {"action": "request", "num_words": 3},
    })
    if vrf is not None:
        ok(f"Request: {shown(vrf, 'request_id')}")
        for i, word in enumerate(vrf.get("random_words") or [], 1):
            ok(f"  Word {i}: {word}")

    steps.summary("Oracle gateway")


if __name__ == "__main__":
    asyncio.run(main())
