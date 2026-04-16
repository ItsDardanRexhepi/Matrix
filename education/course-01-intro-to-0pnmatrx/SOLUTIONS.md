# Course 01 Solutions

Complete solutions for all five exercises. Try the exercises yourself before reading these.

---

## Exercise 1: Conversation with Trinity

### Solution

```bash
# Send the message and save the response
curl -s -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "What can 0pnMatrx do? Give me a summary of your capabilities."}' \
  > exercise1_response.json

# Print the full response (formatted)
python -c "import json; data=json.load(open('exercise1_response.json')); print(json.dumps(data, indent=2))"

# Print only the response text
python -c "import json; data=json.load(open('exercise1_response.json')); print(data['response'])"
```

### Expected Output

```json
{
  "request_id": "req_a1b2c3d4e5f6",
  "response": "I'm Trinity, and I can help you with a wide range of blockchain operations on Base. Here's what 0pnMatrx can do:\n\n1. **Token Operations**: Deploy ERC-20 tokens, manage supply, handle transfers\n2. **Smart Contracts**: Convert plain-English descriptions into audited Solidity contracts\n3. **DeFi**: Lending, borrowing, staking, and yield farming\n4. **NFTs**: Create, mint, and manage NFTs with on-chain royalties\n5. **DAOs**: Set up governance structures with voting and treasury management\n...",
  "agent": "trinity",
  "tools_used": [],
  "timestamp": "2026-04-10T12:00:00Z"
}
```

### Key Points

- The `-s` flag suppresses curl's progress output, giving you clean JSON
- `tools_used` is empty because Trinity answered conversationally without invoking any blockchain services
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
from plugins.base import OpenMatrixPlugin


class WeatherPlugin(OpenMatrixPlugin):
    """Mock weather plugin that returns hardcoded weather data."""

    def __init__(self):
        super().__init__()
        self.name = "weather-plugin"
        self.version = "1.0.0"

    async def on_load(self):
        self.logger.info(f"{self.name} v{self.version} loaded successfully")

    async def on_unload(self):
        self.logger.info(f"{self.name} unloaded")

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
        """Handle the /weather CLI command."""
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

```bash
# Restart gateway to load the plugin
python -m gateway.server

# Look for in startup logs:
# [INFO] Plugin loaded: weather-plugin v1.0.0

# Test via MTRX CLI:
# mtrx> /weather San Francisco

# Test via API (Neo should invoke the get_weather tool):
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "What is the weather in San Francisco?"}'
```

### Expected Output

```
Weather for San Francisco:
  Temperature: 72°F
  Condition: Sunny
  Humidity: 45%
```

### Key Points

- The plugin defaults to "New York" when no city is provided, handling the empty-argument case gracefully
- `get_tools()` and `get_commands()` serve different purposes: tools are for Neo, commands are for the CLI
- The `handler` for the tool returns a dict (structured data), while the command handler returns a string (formatted for display)

---

## Exercise 3: Smart Contract from English

### Contract Description

```
Create a rental agreement smart contract with the following terms:

- The landlord deploys the contract, setting the monthly rent amount in USDC and the tenant's wallet address.
- The tenant can call a payRent function to pay the current month's rent in USDC.
- If rent is paid more than 5 days after the first of the month, a 5% late fee is automatically added to the amount due.
- The landlord can call withdrawRent to withdraw all accumulated rent payments.
- Either the landlord or tenant can call terminateAgreement to begin a 30-day termination notice period. After 30 days, the contract is considered terminated and no further rent is due.
- Only the landlord can update the rent amount, and changes take effect the following month.
```

### Sending to Trinity

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "Create a rental agreement smart contract with the following terms: The landlord deploys the contract, setting the monthly rent amount in USDC and the tenant wallet address. The tenant can call a payRent function to pay the current month rent in USDC. If rent is paid more than 5 days after the first of the month, a 5% late fee is automatically added. The landlord can call withdrawRent to withdraw all accumulated rent payments. Either the landlord or tenant can call terminateAgreement to begin a 30-day termination notice period. After 30 days, the contract is terminated and no further rent is due. Only the landlord can update the rent amount, and changes take effect the following month."
  }'
```

### Expected Response Summary

```
Contract Description: Rental agreement with USDC payments, late fees, and termination
Audit Status: passed
Vulnerabilities: 0 critical, 0 high, 0 medium
Contract Address: 0x... (Base Sepolia testnet)
Attestation UID: 0x...
```

### Key Points

- Specifying "USDC" tells the contract generator to use an ERC-20 token interface for payments, not raw ETH
- The 5% late fee and 30-day notice period are specific enough for the generator to implement correctly
- Access control is clear: landlord-only for withdrawal and rent updates, either party for termination
- Morpheus will intervene before the actual deployment step to confirm

---

## Exercise 4: SDK Integration

### exercise4_sdk.py

```python
import asyncio
from sdk import OpenMatrixClient


async def main():
    client = OpenMatrixClient(
        gateway_url="http://localhost:18790",
        api_key="mtrx_k_your_api_key_here"
    )

    messages = [
        "What is Base and why does 0pnMatrx use it?",
        "How many blockchain services are available?",
        "What is the Glasswing security auditor?",
    ]

    for i, message in enumerate(messages, 1):
        response = await client.chat(message)

        print(f"Message {i}:")
        print(f"  Request ID: {response.request_id}")
        print(f"  Response: {response.text[:100]}...")
        print(f"  Tools used: {len(response.tools_used)}")
        print()

    print(f"Total requests sent: {len(messages)}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Expected Output

```
Message 1:
  Request ID: req_f1a2b3c4d5e6
  Response: Base is an Ethereum Layer 2 network built by Coinbase. 0pnMatrx uses Base because it offers signi...
  Tools used: 0

Message 2:
  Request ID: req_g7h8i9j0k1l2
  Response: There are 221 capabilities across 21 categories in the registry. Query `GET /api/v1/capabilities` for the list.
  Tools used: 0

Message 3:
  Request ID: req_m3n4o5p6q7r8
  Response: Glasswing is the built-in security auditing engine in 0pnMatrx. When a smart contract is generated...
  Tools used: 0

Total requests sent: 3
```

### Key Points

- Each request ID is unique, confirming these are separate server-side operations
- The `[:100]` slice ensures consistent output formatting regardless of response length
- All three responses have zero tools used because they are informational questions
- The `asyncio.run(main())` pattern is the standard way to run async code from a synchronous entry point

---

## Exercise 5: Status Endpoint Parser

### exercise5_status.py

```python
import requests
import sys


def format_uptime(seconds: int) -> str:
    """Convert seconds to human-readable duration."""
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
    """Fetch and display 0pnMatrx system status."""
    try:
        resp = requests.get("http://localhost:18790/status", timeout=5)
        resp.raise_for_status()
    except requests.ConnectionError:
        print("Error: Cannot connect to the gateway.")
        print("Make sure the gateway is running: python -m gateway.server")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Error fetching status: {e}")
        sys.exit(1)

    data = resp.json()

    print("=== 0pnMatrx System Status ===")
    print()
    print(f"System: {data['status']}")
    print()

    # Agent table
    print("Agents:")
    print("  +----------+--------+--------------+")
    print("  | Agent    | Status | Role         |")
    print("  +----------+--------+--------------+")

    agents = data.get("agents", {})
    for name, info in agents.items():
        agent_name = name.capitalize().ljust(8)
        status = info["status"].ljust(6)
        role = info["role"].ljust(12)
        print(f"  | {agent_name} | {status} | {role} |")

    print("  +----------+--------+--------------+")
    print()

    # Services
    services = data.get("services", {})
    active = services.get("active", 0)
    total = services.get("total", 0)
    print(f"Services: {active}/{total} active")

    # Uptime
    uptime = data.get("uptime_seconds", 0)
    print(f"Uptime: {format_uptime(uptime)}")


if __name__ == "__main__":
    print_status()
```

### Expected Output

```
=== 0pnMatrx System Status ===

System: operational

Agents:
  +----------+--------+--------------+
  | Agent    | Status | Role         |
  +----------+--------+--------------+
  | Neo      | active | execution    |
  | Trinity  | active | conversation |
  | Morpheus | active | confirmation |
  +----------+--------+--------------+

Services: 30/30 active
Uptime: 2 hours, 15 minutes, 30 seconds
```

### Key Points

- The `timeout=5` parameter prevents the script from hanging indefinitely if the gateway is unresponsive
- Connection errors are caught specifically with `requests.ConnectionError` for a targeted error message
- The `format_uptime` function handles edge cases: singular/plural and the case where uptime is 0 seconds
- String formatting with `ljust()` ensures the table columns align properly regardless of content length
- The script exits with code 1 on errors, making it suitable for use in scripts and automation
