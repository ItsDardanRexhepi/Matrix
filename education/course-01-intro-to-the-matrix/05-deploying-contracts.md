# Module 05: Converting Contracts, and Deploying Them Yourself

## The Contract Conversion Pipeline

The Matrix turns a contract description into Solidity and scans the result with Glasswing. It does not deploy the contract for you: the gateway's `POST /api/v1/contracts/deploy` answers `501`, and the conversion pipeline deploys only on a gateway whose operator has turned on `conversion.auto_deploy` (Step 5). This module walks through a conversion, reads its audit report, and then deploys the result from your own wallet.

```
Structured description (pseudocode), or Solidity / Vyper source
    |
    v
Parse, then generate Solidity (with per-chain gas rewrites)
    |
    v
Glasswing scan (12 automated checks)
    |
    v
Generated source + audit report + tier quote
    |
    v
You read it, fix it, compile it and deploy it with your own wallet
```

## Step 1: Write a Structured Description

The converter reads **pseudocode**, not free prose: a `contract` line with the name, `state name: type` lines for storage, and `function name(params)` lines with an indented body. A paragraph of plain English gives it almost nothing to read. Sent as pseudocode, "Create a token called MatrixCoin with the symbol MTRX..." comes back as an empty contract named `called`, with the answer's `status` set to `partial` and an audit verdict of `not_applicable`.

Here is a description it can read:

```
contract MatrixCoin
state owner: address
state paused: bool
state totalSupply: uint

function pause()
    require(msg.sender == owner, "only owner");
    paused = true;

function unpause()
    require(msg.sender == owner, "only owner");
    paused = false;

function burn(amount: uint)
    require(!paused, "paused");
    totalSupply -= amount;
```

It names the contract, its storage, each function and who may call it. What the parser does not find in the description is not in the contract.

## Step 2: Send It to the Converter

The conversion route takes the source and its language, with the gateway's API key:

```bash
curl -X POST http://localhost:18790/api/v1/contracts/convert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"source_code": "contract MatrixCoin\nstate owner: address\n...", "source_lang": "pseudocode"}'
```

`source_lang` is one of `pseudocode`, `solidity` or `vyper`. You can also ask Trinity in chat to convert a contract, with the operator key or a wallet session on the request: she calls the same capability, and on a gateway with a key set an anonymous chat is refused it.

The answer carries `generated_source`, the name of the contract in it, the complexity `tier` with its fee quote (`fee_eth`; nothing collects it), `audit` and `audit_passed`. For the description above, the generated source declares `MatrixCoin` with the three state variables and the three functions.

## Step 3: Reading the Audit Report

The generated source is scanned by **Glasswing**, the platform's security auditing engine: the 12 pattern checks listed in course 02, module 04. For the description above, the report reads (findings shortened):

```json
{
  "audit": {
    "contract_name": "MatrixCoin",
    "passed": true,
    "auditable": true,
    "verdict": "passed",
    "finding_count": 4,
    "critical_count": 0,
    "high_count": 3,
    "medium_count": 0,
    "findings": [
      {"rule_id": "SWC-103", "severity": "low", "title": "Floating pragma version", "line": 2},
      {"rule_id": "AC-001", "severity": "high", "title": "Missing access control on burn()", "line": 26},
      {"rule_id": "AC-001", "severity": "high", "title": "Missing access control on pause()", "line": 12},
      {"rule_id": "AC-001", "severity": "high", "title": "Missing access control on unpause()", "line": 19}
    ],
    "summary": "Found 4 issue(s): 0 critical, 3 high, 0 medium, 1 low."
  },
  "audit_passed": true
}
```

Each finding also carries a one-line description of the problem and the code it points at; most checks also suggest a fix (the locked-ether, selfdestruct and timestamp checks do not). How to read the verdict:

- **Critical**: the audit fails.
- **High**: the audit fails only when the operator turns on `security.block_on_high`; it is off by default, which is why the report above passes with three High findings.
- **Medium, Low, Info**: advisory.

Read the findings against the code, not just the verdict. AC-001 reads a function's signature for an access-control modifier, so it flags `pause()` and `unpause()` even though their bodies check `msg.sender == owner`, and it flags `burn()`, which any holder may call by design. A finding is a place to look, and a pass is not a proof that the contract is safe.

## Step 4: Deploy It Yourself on Base Sepolia

The generated source is a starting point. Compile it with Solidity 0.8.20 (the version it declares) and fix what the compiler reports; the generator does not compile it for you. Then deploy it with the tool you already use (Foundry, Hardhat or Remix) from your own wallet on **Base Sepolia** (chain id 84532), which you fund from a faucet. You sign the deployment and you pay its gas; the platform is not involved.

Always deploy to Base Sepolia first, and test the contract there before anything reaches mainnet.

## Step 5: When an Operator Turns On `conversion.auto_deploy`

On a gateway whose operator sets `conversion.auto_deploy`, the pipeline compiles the generated source and deploys it with the platform's paymaster account, only when the audit passed. That deployment is signed under the operator's sponsorship policy as `contract_conversion.deploy`, so a policy that refuses it leaves nothing deployed.

When the chain confirms such a deployment and EAS is configured (`blockchain.eas_contract`, `blockchain.eas_schema` and the paymaster key), the pipeline writes an **EAS (Ethereum Attestation Service) attestation** for it, best effort, and puts the answer in the response under `attestation`:

```json
{
  "attestation": {
    "attestation_tx": "0xabc123...",
    "status": "attested",
    "action": "contract_deployed",
    "agent": "contract_conversion",
    "block_number": 12345678,
    "gas_paid_by": "platform (The Matrix)"
  }
}
```

What the attestation records on-chain is the platform name, the action (`contract_deployed`), the agent and a timestamp, under the configured schema. It does not record the contract's address or the audit result, so it shows that a deployment happened, not which contract was audited or what the audit found. If EAS is not configured, `status` is `skipped`; if the attestation fails, it is `failed`. Either way the deployment itself stands.

## Best Practices

- Write the description as pseudocode the converter can read, and state who may call each function
- Read every finding in the audit report, and read the generated source itself
- Compile and test the contract before you deploy it
- Deploy to testnet first, always, from your own wallet
- After deployment, verify the contract source code on the block explorer

## Key Takeaways

- The converter reads structured pseudocode, Solidity or Vyper; free prose yields an empty contract
- The pipeline: parse, generate, Glasswing scan; you compile, test and deploy
- A Critical finding fails the audit; a High one only with `security.block_on_high` on
- The platform deploys nothing unless an operator turns on `conversion.auto_deploy`
- The EAS attestation of such a deployment records that it happened, not what the audit found

---

**Next:** [The SDK](./06-the-sdk.md) -- interact with The Matrix programmatically from Python and JavaScript.
