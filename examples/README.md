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
| 05 | `05_marketplace_flow.py` | List item, search, buy via atomic escrow, fee routing | 24 |
| 06 | `06_eas_attestation_chain.py` | Every action creates an EAS attestation; batch attest; verify | 8 |
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
- EAS attestations are created for every state-modifying action
- Contract fees reach NeoSafe through deployment, not through a router: each platform contract pays its fee to `platformFeeRecipient`, which `scripts/deploy_all.py` sets to the configured NeoSafe address, while `NeoSafeRouter.route_fee` and `route_revenue` have no caller outside `examples/07_revenue_to_neosafe.py` (where each fee goes is listed under **Fees** in `docs/blockchain.md`)
- Oracle data feeds switch to mainnet Chainlink contracts automatically

## EAS Attestation on Every Action

Every state-modifying action in The Matrix creates an on-chain EAS (Ethereum Attestation Service) attestation. This is built into `ServiceDispatcher.execute()` — you don't need to do anything extra.

What gets attested:
- Contract deployments (code hash, deployer, audit status)
- Token transfers (sender, recipient, amount, tx hash)
- Loan originations and repayments
- NFT mints and sales (with royalty info)
- Insurance policy creation and claim payouts
- Governance votes and proposal executions
- Identity registrations and verifications

See `examples/06_eas_attestation_chain.py` for the full attestation flow.

## Where Fees Go, and What NeoSafe Receives

The platform contracts pay their on-chain fees (marketplace 5%, staking 5% of rewards, DAO withdrawal tiers, NFT mint proceeds, insurance excess) to each contract's `platformFeeRecipient`, and `scripts/deploy_all.py` — the deployment `CREDENTIALS_NEEDED.md` describes — sets that to the configured NeoSafe address (`MATRIX_NEOSAFE_ADDRESS`) for every platform contract, so on a deployment built that way those fees are paid to NeoSafe by the contracts themselves. `RevenueEnforcer` injects fee logic into generated contracts, paying that contract's fee to `blockchain.platform_wallet`, which the same setup calls the NeoSafe wallet.

`NeoSafeRouter` (`runtime/blockchain/services/neosafe.py`) is not on that path: it can record a fee on an in-memory ledger (`route_fee`) and send ETH to the multisig (`route_revenue`), but no service calls either; only `examples/07_revenue_to_neosafe.py` does. Service fees (stablecoin transfers, cross-border payments, the service-ledger staking commission and others) are computed on the service's own ledger, some recorded and not settled; nothing moves them anywhere.

The full list is under **Fees** in `docs/blockchain.md`. That table has no insurance premium fee and no DeFi origination fee; the example list that used to stand here named both.

`examples/07_revenue_to_neosafe.py` shows what the router does when called directly.
