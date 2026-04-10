# Course 01 Exercises

Complete these five exercises to solidify your understanding of 0pnMatrx. Each exercise builds on concepts from the course modules. Complete solutions are available in [SOLUTIONS.md](./SOLUTIONS.md).

---

## Exercise 1: Conversation with Trinity

**Objective**: Send a message to Trinity and capture her response.

**Instructions**:
1. Ensure the gateway is running (`python -m gateway.server`)
2. Use curl to send a POST request to `/chat`
3. Ask Trinity: "What can 0pnMatrx do? Give me a summary of your capabilities."
4. Save the full JSON response to a file called `exercise1_response.json`
5. Print the value of the `response` field only

**Expected Output Format**:
```
{
  "request_id": "req_...",
  "response": "...(Trinity's response describing capabilities)...",
  "agent": "trinity",
  "tools_used": [],
  "timestamp": "..."
}
```

**Success Criteria**:
- The request returns HTTP 200
- The `agent` field is `"trinity"`
- The `tools_used` array is empty (this is a conversational response, no tools needed)
- The response file is valid JSON

---

## Exercise 2: Weather Plugin

**Objective**: Create a plugin that adds a `/weather` command returning mock weather data.

**Instructions**:
1. Create the directory `plugins/installed/weather-plugin/`
2. Create `config.json` with appropriate metadata
3. Create `__init__.py` that:
   - Extends `OpenMatrixPlugin`
   - Implements `on_load` and `on_unload` with logging
   - Implements `get_commands` with a `/weather` command
   - Implements `get_tools` with a `get_weather` tool
   - The `/weather` command accepts a city name and returns mock data
   - Mock data should include: city name, temperature (72F), condition ("Sunny"), humidity (45%)
4. Restart the gateway and verify the plugin loads
5. Test the command with `/weather San Francisco`

**Expected Output Format**:
```
Weather for San Francisco:
  Temperature: 72°F
  Condition: Sunny
  Humidity: 45%
```

**Success Criteria**:
- Plugin loads without errors on gateway startup
- `/weather` command returns properly formatted output
- The `get_weather` tool is available to Neo
- Plugin handles missing city name gracefully (default to a reasonable city)

---

## Exercise 3: Smart Contract from English

**Objective**: Convert a simple rental agreement into a smart contract.

**Instructions**:
1. Write a plain-English description of a rental agreement with these terms:
   - Landlord sets a monthly rent amount in USDC
   - Tenant can pay rent by calling a pay function
   - If rent is more than 5 days late, a 5% late fee applies
   - Landlord can withdraw accumulated rent payments
   - Either party can terminate the agreement with 30 days notice
2. Send the description to Trinity via `/chat`
3. Review the Glasswing audit report in the response
4. If the audit passes, note the contract address from the deployment
5. Record the EAS attestation UID

**Expected Output Format**:
```
Contract Description: [your description]
Audit Status: passed
Vulnerabilities: 0 critical, 0 high
Contract Address: 0x...
Attestation UID: 0x...
```

**Success Criteria**:
- The description is specific enough to generate a valid contract
- The audit report returns with zero critical or high severity findings
- You can explain what each part of the audit report means
- The deployment (to testnet) succeeds

---

## Exercise 4: SDK Integration

**Objective**: Use the Python SDK to send three messages and print the responses.

**Instructions**:
1. Create a file called `exercise4_sdk.py`
2. Use `from sdk import OpenMatrixClient` to import the client
3. Send three sequential messages:
   - "What is Base and why does 0pnMatrx use it?"
   - "How many blockchain services are available?"
   - "What is the Glasswing security auditor?"
4. For each response, print:
   - The request ID
   - The first 100 characters of the response
   - The number of tools used
5. At the end, print the total number of requests sent

**Expected Output Format**:
```
Message 1:
  Request ID: req_...
  Response: Base is an Ethereum Layer 2 network that provides lower gas fees and faster transaction...
  Tools used: 0

Message 2:
  Request ID: req_...
  Response: There are 30 blockchain services currently available on 0pnMatrx, covering token dep...
  Tools used: 0

Message 3:
  Request ID: req_...
  Response: Glasswing is the security auditing engine built into 0pnMatrx. It performs a 12-poi...
  Tools used: 0

Total requests sent: 3
```

**Success Criteria**:
- The script runs without errors
- All three messages receive responses
- Request IDs are unique for each message
- Output is formatted as specified

---

## Exercise 5: Status Endpoint Parser

**Objective**: Query the `/status` endpoint and display the active agents in a formatted way.

**Instructions**:
1. Create a file called `exercise5_status.py`
2. Use the `requests` library (or `httpx`) to GET `http://localhost:18790/status`
3. Parse the JSON response
4. Display:
   - Overall system status
   - Each agent's name, status, and role in a formatted table
   - Number of active services out of total
   - System uptime in human-readable format (e.g., "2 hours, 15 minutes, 30 seconds")
5. Handle the case where the gateway is not running (connection error)

**Expected Output Format**:
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

**Success Criteria**:
- The script correctly parses the JSON response
- Agent information is displayed in a formatted table
- Uptime is converted from seconds to human-readable format
- Connection errors are handled gracefully with a helpful message
