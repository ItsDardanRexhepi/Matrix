from __future__ import annotations
#!/usr/bin/env python3
"""
08 — Oracle Gateway: Multi-Source Oracle Routing on Base Sepolia

Demonstrates the Oracle Gateway (Component 11):

  1. Requests a price feed from Chainlink (ETH/USD)
  2. Requests weather data for insurance trigger evaluation
  3. Requests a VRF random number for gaming
  4. Shows how oracle data flows into other services

The Oracle Gateway unifies access to Chainlink price feeds, weather APIs,
VRF randomness, and custom oracle sources behind a single dispatch API.

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
  0pnMatrx Example 08: Oracle Gateway Routing
{'=' * 60}{RESET}

  Unified oracle access: price feeds, weather data, VRF randomness.
  One API for all external data needs across the platform.
""")

    config = load_config()
    dispatcher = ServiceDispatcher(config)
    oracle_config = config.get("services", {}).get("oracle_gateway", {})

    print(f"  {BOLD}Configured feeds:{RESET}")
    feeds = oracle_config.get("chainlink_feeds", {})
    for name, addr in feeds.items():
        configured = "configured" if addr and not addr.startswith("YOUR_") else "not configured"
        print(f"    {name}: {configured}")

    # ── Step 1: Chainlink Price Feed — ETH/USD ──────────────────────
    step(1, "Requesting ETH/USD price from Chainlink...")

    try:
        result = await dispatcher.execute(
            action="get_price",
            params={
                "oracle_type": "chainlink",
                "request": {
                    "feed": "eth_usd",
                    "pair": "ETH/USD",
                },
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            price_data = data["result"]
            ok(f"Feed: ETH/USD")
            ok(f"Price: ${price_data.get('price', price_data.get('value', 'N/A'))}")
            ok(f"Decimals: {price_data.get('decimals', 8)}")
            ok(f"Round ID: {price_data.get('round_id', 'N/A')}")
            ok(f"Updated: {price_data.get('updated_at', price_data.get('timestamp', 'N/A'))}")
            ok(f"Source: Chainlink on Base Sepolia")
        else:
            warn(f"Price feed: {data.get('error', 'N/A')}")
            print(f"  {DIM}Ensure services.oracle_gateway.chainlink_feeds.eth_usd is configured{RESET}")
    except Exception as e:
        warn(f"Price feed: {e}")

    # ── Step 2: Multiple price feeds ────────────────────────────────
    step(2, "Requesting multiple price feeds...")

    pairs = [
        ("btc_usd", "BTC/USD"),
        ("link_usd", "LINK/USD"),
    ]

    for feed_key, pair_name in pairs:
        try:
            result = await dispatcher.execute(
                action="get_price",
                params={
                    "oracle_type": "chainlink",
                    "request": {"feed": feed_key, "pair": pair_name},
                },
            )
            data = json.loads(result)
            if data.get("status") == "ok":
                p = data["result"]
                price = p.get("price", p.get("value", "N/A"))
                ok(f"{pair_name}: ${price}")
            else:
                warn(f"{pair_name}: {data.get('error', 'not configured')}")
        except Exception as e:
            warn(f"{pair_name}: {e}")

    # ── Step 3: Weather oracle for insurance ────────────────────────
    step(3, "Requesting weather data for insurance trigger...")
    print(f"  {DIM}Location: Fresno, CA (36.74, -119.79){RESET}")

    try:
        result = await dispatcher.execute(
            action="oracle_request",
            params={
                "oracle_type": "weather",
                "request": {
                    "metric": "rainfall_mm",
                    "location": {
                        "lat": 36.7378,
                        "lon": -119.7871,
                        "name": "Fresno, CA",
                    },
                    "period": "last_30_days",
                },
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            weather = data["result"]
            ok(f"Metric: rainfall (mm)")
            ok(f"Value: {weather.get('value', 'N/A')}mm")
            ok(f"Period: last 30 days")
            ok(f"Source: {weather.get('source', 'weather_oracle')}")
            ok(f"Timestamp: {weather.get('timestamp', 'N/A')}")

            rainfall = weather.get("value", 65)
            if isinstance(rainfall, (int, float)) and rainfall < 50:
                warn(f"DROUGHT ALERT: {rainfall}mm is below 50mm threshold")
            else:
                ok(f"Normal conditions: above 50mm threshold")
        else:
            warn(f"Weather: {data.get('error', 'N/A')}")
            print(f"  {DIM}Ensure services.oracle_gateway.weather_api_key is configured{RESET}")
    except Exception as e:
        warn(f"Weather oracle: {e}")

    # ── Step 4: Temperature data ────────────────────────────────────
    step(4, "Requesting temperature data...")

    try:
        result = await dispatcher.execute(
            action="oracle_request",
            params={
                "oracle_type": "weather",
                "request": {
                    "metric": "temperature_celsius",
                    "location": {"lat": 36.7378, "lon": -119.7871},
                    "period": "current",
                },
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            temp = data["result"]
            ok(f"Temperature: {temp.get('value', 'N/A')} C")
            ok(f"Source: {temp.get('source', 'weather_oracle')}")
        else:
            warn(f"Temperature: {data.get('error', 'N/A')}")
    except Exception as e:
        warn(f"Temperature oracle: {e}")

    # ── Step 5: VRF random number for gaming ────────────────────────
    step(5, "Requesting VRF random number for gaming...")
    print(f"  {DIM}Chainlink VRF provides verifiable on-chain randomness{RESET}")

    try:
        result = await dispatcher.execute(
            action="oracle_request",
            params={
                "oracle_type": "vrf",
                "request": {
                    "num_words": 3,
                    "callback_gas_limit": 200000,
                    "purpose": "gaming_loot_drop",
                },
            },
        )
        data = json.loads(result)
        if data.get("status") == "ok":
            vrf = data["result"]
            ok(f"Request ID: {vrf.get('request_id', 'N/A')}")
            ok(f"Random words requested: 3")
            ok(f"Callback gas: 200,000")
            if vrf.get("random_words"):
                for i, word in enumerate(vrf["random_words"]):
                    ok(f"  Word {i+1}: {word}")
            ok(f"Source: Chainlink VRF v2")
        else:
            warn(f"VRF: {data.get('error', 'N/A')}")
            print(f"  {DIM}Ensure VRF coordinator and subscription are configured{RESET}")
    except Exception as e:
        warn(f"VRF oracle: {e}")

    # ── Step 6: Show oracle data flow ───────────────────────────────
    step(6, "Oracle data flow into other services")

    print(f"""
  {BOLD}How oracle data flows through the platform:{RESET}

  {DIM}
  External Sources               Oracle Gateway            Platform Services
  +-----------------+            +---------------+         +-----------------+
  | Chainlink       |---price--->|               |--ETH/-->| DeFi (Comp 2)   |
  | Price Feeds     |   feeds    |               |  USD    | - Loan LTV      |
  +-----------------+            |               |         | - Liquidation    |
                                 |   Oracle      |         +-----------------+
  +-----------------+            |   Gateway     |
  | Weather API     |--weather-->|  (Comp 11)    |--rain-->| Insurance (13)  |
  | (OpenWeather)   |   data     |               |  data   | - Trigger check |
  +-----------------+            |               |         | - Auto payout   |
                                 |               |         +-----------------+
  +-----------------+            |               |
  | Chainlink VRF   |---random-->|               |--rand-->| Gaming (14)     |
  | v2              |   numbers  |               |  nums   | - Loot drops    |
  +-----------------+            +---------------+         | - Fair outcomes |
                                                           +-----------------+
  {RESET}

  {BOLD}Oracle types supported:{RESET}
    - {GREEN}chainlink{RESET}  - Price feeds (ETH/USD, BTC/USD, LINK/USD, etc.)
    - {GREEN}weather{RESET}    - Rainfall, temperature, humidity, wind
    - {GREEN}vrf{RESET}        - Verifiable random functions (Chainlink VRF v2)
    - {GREEN}custom{RESET}     - User-defined oracle sources
""")

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  ORACLE GATEWAY COMPLETE
{'=' * 60}{RESET}

  {BOLD}Actions demonstrated:{RESET}
    1. get_price       - Chainlink ETH/USD price feed
    2. get_price       - Multiple price feeds (BTC, LINK)
    3. oracle_request  - Weather data (rainfall)
    4. oracle_request  - Temperature data
    5. oracle_request  - VRF random number
    6. (architecture)  - Data flow to services

  {BOLD}Key feature:{RESET}
    One unified API for all oracle types. Services request
    data via oracle_request and the Gateway handles routing,
    caching, and source validation automatically.

  {BOLD}Service:{RESET} Oracle Gateway (Component 11)

{GREEN}{'=' * 60}{RESET}
""")


if __name__ == "__main__":
    asyncio.run(main())
