# Course 01 Solutions

Complete solutions for all five exercises. Try the exercises yourself before reading these.

---

## Exercise 1: Conversation with Trinity

### Solution

```bash
# Send the message and save the response
curl -s -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What can The Matrix do? Give me a summary of your capabilities.", "session_id": "exercise-1"}' \
  > exercise1_response.json

# Print the full response (formatted)
python -c "import json; data=json.load(open('exercise1_response.json')); print(json.dumps(data, indent=2))"

# Print only the response text
python -c "import json; data=json.load(open('exercise1_response.json')); print(data['response'])"
```

### Expected Output

```json
{
  "response": "I'm Trinity, and I can help you with a wide range of blockchain operations on Base. Here's what The Matrix can do:\n\n1. **Payments**: Recording a cross-border payment or a stablecoin transfer. Nothing is sent, and no value moves. The stablecoin ledger starts empty, so a transfer there is refused for insufficient balance\n2. **Smart Contracts**: Convert structured descriptions (pseudocode), Solidity or Vyper into Solidity with a Glasswing audit report\n3. **DeFi**: Token swaps, loans against collateral, and staking\n4. **NFTs**: Create, mint, and manage NFTs with on-chain royalties\n5. **DAOs**: Set up governance structures with voting and treasury management\n...",
  "tool_calls": [],
  "session_id": "exercise-1",
  "agent": "trinity",
  "provider": "ollama"
}
```

The answer is the model's, so its wording will differ from this one.

### Key Points

- The `-s` flag suppresses curl's progress output, giving you clean JSON
- `/chat` is public: no key is needed to talk to Trinity
- `tool_calls` is empty because Trinity answered conversationally without invoking any blockchain services
- The `agent` field confirms Trinity handled the response

---

## Exercise 2: Weather Plugin

### config.json

```json
{
  "name": "weather-plugin",
  "version": "1.0.0",
  "description": "A mock weather plugin for learning purposes",
  "author": "Student",
  "license": "MIT",
  "min_platform_version": "1.0.0",
  "permissions": ["commands"],
  "tags": ["weather", "example", "tutorial"]
}
```

### __init__.py

```python
import logging

from runtime.plugins.base import MatrixPlugin

logger = logging.getLogger(__name__)


class WeatherPlugin(MatrixPlugin):
    """Mock weather plugin that returns hardcoded weather data."""

    @property
    def name(self) -> str:
        return "weather-plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def on_load(self, config: dict) -> None:
        logger.info("%s v%s loaded successfully", self.name, self.version)

    async def on_unload(self) -> None:
        logger.info("%s unloaded", self.name)

    def get_tools(self):
        return [
            {
                "name": "get_weather",
                "description": "Get the current weather for a given city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "The city to get weather for",
                        }
                    },
                    "required": ["city"],
                },
                "handler": self.handle_get_weather,
            }
        ]

    async def handle_get_weather(self, city: str) -> dict:
        """Return mock weather data for any city."""
        return {
            "city": city,
            "temperature_f": 72,
            "condition": "Sunny",
            "humidity_percent": 45,
        }

    def get_commands(self):
        return [
            {
                "name": "/weather",
                "description": "Get mock weather data for a city",
                "usage": "/weather <city name>",
                "handler": self.handle_weather_command,
            }
        ]

    async def handle_weather_command(self, args: str) -> str:
        """Handle the /weather command."""
        city = args.strip() if args.strip() else "New York"
        data = await self.handle_get_weather(city)
        return (
            f"Weather for {data['city']}:\n"
            f"  Temperature: {data['temperature_f']}\u00b0F\n"
            f"  Condition: {data['condition']}\n"
            f"  Humidity: {data['humidity_percent']}%"
        )
```

### Testing

Nothing in the gateway loads plugins, so load it yourself from the repository
root (the loader looks in `plugins/installed/` relative to where it runs):

```python
import asyncio

from runtime.plugins.loader import PluginLoader


async def main():
    loader = PluginLoader()
    await loader.load_all({})
    plugin = loader.loaded["weather-plugin"]
    print(await plugin.handle_weather_command("San Francisco"))
    await loader.unload_all()


asyncio.run(main())
```

Neo cannot invoke `get_weather` through `/chat`: nothing registers plugin tools
with the dispatcher.

### Expected Output

```
Weather for San Francisco:
  Temperature: 72°F
  Condition: Sunny
  Humidity: 45%
```

### Key Points

- The plugin defaults to "New York" when no city is provided, handling the empty-argument case gracefully
- `get_tools()` and `get_commands()` describe different things: tools are meant for an agent, commands for a person. Nothing registers either with the platform today
- The `handler` for the tool returns a dict (structured data), while the command handler returns a string (formatted for display)

---

## Exercise 3: Smart Contract from Pseudocode

### Contract Description

The converter reads pseudocode (Module 05, Step 1), so the terms are written as a contract with its state and functions. This version takes rent in ETH (`msg.value`); taking it in USDC would need an ERC-20 `transferFrom` in `payRent`.

```
contract RentalAgreement
state landlord: address
state tenant: address
state rentAmount: uint
state paidThrough: uint
state terminationStart: uint
state balance: uint

function constructor(tenantAddress: address, rent: uint)
    landlord = msg.sender;
    tenant = tenantAddress;
    rentAmount = rent;
    paidThrough = block.timestamp;

function payRent() payable
    require(msg.sender == tenant, "only tenant");
    require(terminationStart == 0 || block.timestamp < terminationStart + 30 days, "terminated");
    uint due = rentAmount;
    if (block.timestamp > paidThrough + 5 days) { due = due + due * 5 / 100; }
    require(msg.value >= due, "rent due");
    paidThrough = paidThrough + 30 days;
    balance += msg.value;

function withdrawRent()
    require(msg.sender == landlord, "only landlord");
    uint amount = balance;
    balance = 0;
    payable(landlord).transfer(amount);

function terminateAgreement()
    require(msg.sender == landlord || msg.sender == tenant, "only parties");
    terminationStart = block.timestamp;

function updateRent(newRent: uint)
    require(msg.sender == landlord, "only landlord");
    rentAmount = newRent;
```

### Sending It to the Converter

Put the description above in a file, `rental.txt`, and send it as `source_code` (the `jq` call builds the JSON body with the file's text escaped):

```bash
jq -n --rawfile src rental.txt '{source_code: $src, source_lang: "pseudocode"}' |
curl -X POST http://localhost:18790/api/v1/contracts/convert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d @-
```

### Expected Response Summary

Measured by running this description through the conversion pipeline:

```
Contract: RentalAgreement (a constructor, payRent, withdrawRent, terminateAgreement, updateRent)
Audit verdict: passed
Findings: 0 critical, 0 high, 0 medium, 3 low (a floating pragma, and block.timestamp
          used in the late-fee and termination comparisons)
Contract Address: from your own deployment to Base Sepolia
```

### Key Points

- Each term became code only because the description wrote it as a function or a state variable; the converter does not read free prose
- The two block.timestamp findings are expected here: the late fee and the notice period are measured in time, and a validator can move a timestamp by seconds, not days
- Access control is in the function bodies (`require(msg.sender == landlord)`), which the audit's access-control check does not read; check it yourself
- The platform does not deploy it: compile it, test it, and deploy it to Base Sepolia from your own wallet

---

## Exercise 4: SDK Integration

### exercise4_sdk.py

```python
import asyncio
from sdk import MatrixClient


async def main():
    client = MatrixClient("http://localhost:18790")

    messages = [
        "What is Base and why does The Matrix use it?",
        "How many blockchain services are available?",
        "What is the Glasswing security auditor?",
    ]

    for i, message in enumerate(messages, 1):
        response = await client.achat(message)

        print(f"Message {i}:")
        print(f"  Session: {response.session_id}")
        print(f"  Response: {response.text[:100]}...")
        print(f"  Tool calls: {len(response.tool_calls)}")
        print()

    print(f"Total requests sent: {len(messages)}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Expected Output

```
Message 1:
  Session: 3f9c2a1b7d4e
  Response: Base is an Ethereum Layer 2 network built by Coinbase. The Matrix uses Base because it offers signi...
  Tool calls: 0

Message 2:
  Session: 3f9c2a1b7d4e
  Response: There are 195 capabilities across 20 categories in the catalog. Query `GET /api/v1/capabilities` for the list.
  Tool calls: 0

Message 3:
  Session: 3f9c2a1b7d4e
  Response: Glasswing is the built-in security auditing engine in The Matrix. When a smart contract is generated...
  Tool calls: 0

Total requests sent: 3
```

### Key Points

- The session ID is the same for all three: the client sends the one it made when it was created, so the three messages are one conversation
- The `[:100]` slice ensures consistent output formatting regardless of response length
- All three responses have zero tool calls because they are informational questions
- The `asyncio.run(main())` pattern is the standard way to run async code from a synchronous entry point

---

## Exercise 5: Status Endpoint Parser

### exercise5_status.py

```python
import os
import sys

import requests


def format_uptime(seconds: float) -> str:
    """Convert seconds to human-readable duration."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs > 0 or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")

    return ", ".join(parts)


def print_status():
    """Fetch and display what the gateway's /status reports."""
    key = os.environ.get("MATRIX_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = requests.get("http://localhost:18790/status", headers=headers, timeout=5)
    except requests.ConnectionError:
        print("Error: Cannot connect to the gateway.")
        print("Make sure the gateway is running: python -m gateway.server")
        sys.exit(1)
    if resp.status_code == 401:
        print("Error: this gateway has a key set. Export it as MATRIX_API_KEY and run again.")
        sys.exit(1)
    try:
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching status: {e}")
        sys.exit(1)

    data = resp.json()

    print("=== The Matrix System Status ===")
    print()
    print(f"Platform: {data.get('platform', '?')} {data.get('version', '')}")
    print()
    print("Agents:")
    for name in data.get("agents", []):
        print(f"  - {name}")
    print()
    model = data.get("model", {})
    print(f"Model: {model.get('provider', '?')} ({model.get('primary', '?')})")
    print(f"Sessions: {data.get('sessions', 0)}   Requests: {data.get('total_requests', 0)}")
    print(f"Uptime: {format_uptime(data.get('uptime_seconds', 0))}")


if __name__ == "__main__":
    print_status()
```

### Expected Output

```
=== The Matrix System Status ===

Platform: The Matrix 1.0.0

Agents:
  - neo
  - trinity
  - morpheus

Model: ollama (llama3.1)
Sessions: 2   Requests: 57
Uptime: 2 hours, 15 minutes, 30 seconds
```

The agents are the ones enabled in the gateway's config, and the model is the one it is configured to use.

### Key Points

- `/status` is behind the operator key when the gateway has one, so the script sends `MATRIX_API_KEY` when it is set and says what to do on a `401`
- The `timeout=5` parameter prevents the script from hanging indefinitely if the gateway is unresponsive
- Connection errors are caught specifically with `requests.ConnectionError` for a targeted error message
- The `format_uptime` function handles edge cases: singular/plural and the case where uptime is 0 seconds
- The script exits with code 1 on errors, making it suitable for use in scripts and automation
