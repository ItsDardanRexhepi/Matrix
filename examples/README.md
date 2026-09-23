# The Matrix End-to-End Examples

Runnable scripts that prove the platform works on-chain (Base Sepolia).

## Prerequisites

1. **Install dependencies:**
   ```bash
   pip install web3 eth-account py-solc-x eth-abi
   ```

2. **Configure the platform:**
   ```bash
   cp matrix.config.json.example matrix.config.json
   ```
   Fill in at minimum:
   - `blockchain.rpc_url` — Base Sepolia RPC (get one free at [Alchemy](https://www.alchemy.com/))
   - `blockchain.demo_wallet_address` — the address the examples act for
   - `blockchain.platform_wallet` — NeoSafe multisig address

   None of these examples reads `blockchain.demo_wallet_private_key` or signs
   anything with it — leave it unset for them. `demo.py` (repo root) is the
   script that deploys with that key; use a dedicated **testnet** wallet there,
   never one holding real funds. tests/test_examples_are_honest.py runs every
   example and fails if one reads a signing key.

   The examples call the real platform, and the platform does sign with ITS
   OWN configured account (`blockchain.paymaster_private_key`) in two places:
   - `conversion.auto_deploy` — when on, contract conversion deploys what it
     generates. `01_contract_conversion.py` turns it off for its own run and
     says so if your config had it on; the same test fails if an example that
     converts could deploy.
   - EAS attestation — `ServiceDispatcher` attests state-modifying actions
     through the attestation service which, where EAS is configured, submits
     them (immediately, or once its batch fills) signed with the platform
     account. The examples do not turn this off.

## Running

Every example is self-contained. Run from the repo root:

```bash
python examples/01_contract_conversion.py
python examples/02_defi_loan.py
# ... etc.
```

All scripts degrade gracefully: if a service is not fully configured they
will print a warning and continue with the remaining steps.

## Examples

| # | Script | What it demonstrates | Components |
|---|--------|---------------------|------------|
| 01 | `01_contract_conversion.py` | Plain English -> Solidity -> audit (runs with `conversion.auto_deploy` off; deploying it is yours to do) | 1 |
| 02 | `02_defi_loan.py` | Collateralised lending: deposit, borrow, monitor health, repay | 2, 11 |
| 03 | `03_nft_with_royalties.py` | Mint NFT with EIP-2981 royalties, list, sell, royalty split | 3, 15, 24 |
| 04 | `04_parametric_insurance.py` | Weather-based crop insurance with oracle trigger and auto-payout | 13, 11 |
| 05 | `05_marketplace_flow.py` | List item, search, buy via atomic escrow, fee split | 24 |
| 06 | `06_eas_attestation_chain.py` | Writing EAS attestations, batching them, verifying one | 8 |
| 07 | `07_revenue_to_neosafe.py` | RevenueEnforcer fee injection, NeoSafeRouter fee routing | 1, NeoSafe |
| 08 | `08_oracle_routing.py` | Chainlink price feeds, weather data, VRF randomness | 11 |
| 09 | `09_full_user_journey.py` | Complete journey: DID -> DAO -> tokenize -> NFT -> govern -> fund -> stake | 3-6, 16, 19, 22 |

## Architecture

All examples use the same entry point that the gateway and Trinity agent use:

```python
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

dispatcher = ServiceDispatcher(config)
result = await dispatcher.execute(
    action="create_loan",
    params={"borrower": "0x...", "collateral_amount": 0.1, ...},
)
```

The `ServiceDispatcher.execute()` method:
1. Resolves the action to a service and method via `ACTION_MAP`
2. Calls the service method with the provided params
3. Automatically creates an EAS attestation for state-modifying actions
4. Returns a JSON string with `status`, `result`, and timing info

## Network

All examples target **Base Sepolia** (chain ID 84532) by default.
Block explorer: https://sepolia.basescan.org

### Deploying to Base Mainnet

Every example works on mainnet with zero code changes — just update your config:

```json
{
  "blockchain": {
    "network": "base",
    "chain_id": 8453,
    "rpc_url": "https://mainnet.base.org",
    "explorer_url": "https://basescan.org"
  }
}
```

**Before going to mainnet:**
- Contract conversion runs the Glasswing security audit on generated Solidity; it does not deploy it unless `conversion.auto_deploy` is on, in which case it deploys with the platform's paymaster account (example 01 always runs with it off)
- A state-modifying action the service dispatcher completes is queued for an EAS attestation, written to the chain in batches of 50 (see below)
- Contracts the conversion pipeline generates carry a platform fee paid to `platform_wallet`; there is no single flow that routes every platform fee to NeoSafe (see below)
- Oracle data feeds switch to mainnet Chainlink contracts automatically

## EAS Attestations

`ServiceDispatcher.execute()` queues an EAS (Ethereum Attestation Service) attestation for a state-modifying action it completes; a refusal or an unconfirmed broadcast is not queued as done. The queue is written to the chain once 50 have gathered in the same process. Nothing drains it on a timer, and what is queued is lost if the process exits first.

The dispatcher's record carries the action, the service, the caller it resolved and a hash of the parameters. What reaches the chain is narrower: each attestation encodes the platform name, the action, the agent (`system` for the dispatcher's records) and a timestamp (`runtime/blockchain/eas_client.py`).

See `examples/06_eas_attestation_chain.py` for the attestation calls.

## Revenue Routing to NeoSafe

The conversion pipeline's `RevenueEnforcer` writes a platform fee into the contracts it generates, paid to the configured `platform_wallet` when the contract collects it. Protocol referral fees name the NeoSafe address as their recipient (`runtime/blockchain/protocol_referrals.py`). `NeoSafeRouter` can record fees and send revenue to the NeoSafe wallet, but nothing in the gateway calls it yet. There is no single flow that routes every platform fee to NeoSafe.

See `examples/07_revenue_to_neosafe.py`, which calls the router directly.
