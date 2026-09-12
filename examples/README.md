# 0pnMatrx End-to-End Examples

Runnable scripts that prove the platform works on-chain (Base Sepolia).

## Prerequisites

1. **Install dependencies:**
   ```bash
   pip install web3 eth-account py-solc-x eth-abi
   ```

2. **Configure the platform:**
   ```bash
   cp openmatrix.config.json.example openmatrix.config.json
   ```
   Fill in at minimum:
   - `blockchain.rpc_url` — Base Sepolia RPC (get one free at [Alchemy](https://www.alchemy.com/))
   - `blockchain.demo_wallet_private_key` — private key for a test wallet
   - `blockchain.demo_wallet_address` — corresponding address
   - `blockchain.platform_wallet` — NeoSafe multisig address

3. **Fund your test wallet:**
   Get Base Sepolia ETH from https://www.alchemy.com/faucets/base-sepolia

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
| 01 | `01_contract_conversion.py` | Plain English -> Solidity -> audit -> deploy -> attest | 1, 8 |
| 02 | `02_defi_loan.py` | Collateralised lending: deposit, borrow, monitor health, repay | 2, 11 |
| 03 | `03_nft_with_royalties.py` | Mint NFT with EIP-2981 royalties, list, sell, royalty split | 3, 15, 24 |
| 04 | `04_parametric_insurance.py` | Weather-based crop insurance with oracle trigger and auto-payout | 13, 11 |
| 05 | `05_marketplace_flow.py` | List item, search, buy via atomic escrow, fee routing | 24 |
| 06 | `06_eas_attestation_chain.py` | Every action creates an EAS attestation; batch attest; query; verify | 8 |
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
- All examples run Glasswing security audit before deployment
- EAS attestations are created for every state-modifying action
- Fees are not routed to NeoSafe automatically: `NeoSafeRouter.route_fee` and `route_revenue` have no caller outside `examples/07_revenue_to_neosafe.py` (where each fee goes is listed under **Fees** in `docs/blockchain.md`)
- Oracle data feeds switch to mainnet Chainlink contracts automatically

## EAS Attestation on Every Action

Every state-modifying action in 0pnMatrx creates an on-chain EAS (Ethereum Attestation Service) attestation. This is built into `ServiceDispatcher.execute()` — you don't need to do anything extra.

What gets attested:
- Contract deployments (code hash, deployer, audit status)
- Token transfers (sender, recipient, amount, tx hash)
- Loan originations and repayments
- NFT mints and sales (with royalty info)
- Insurance policy creation and claim payouts
- Governance votes and proposal executions
- Identity registrations and verifications

See `examples/06_eas_attestation_chain.py` for the full attestation flow.

## Revenue Routing to NeoSafe

Nothing routes platform fees to the NeoSafe multisig today. `NeoSafeRouter` (`runtime/blockchain/services/neosafe.py`) can record a fee on an in-memory ledger (`route_fee`) and send ETH to the multisig (`route_revenue`), but no service calls either; only `examples/07_revenue_to_neosafe.py` does. `RevenueEnforcer` injects fee logic into generated contracts, paying that contract's fee to `blockchain.platform_wallet`; it routes nothing to NeoSafe.

Where fees actually go is listed under **Fees** in `docs/blockchain.md`: the platform contracts pay their fees to each contract's `platformFeeRecipient`, and service fees are computed on the service's own ledger, some recorded and not settled. That table has no insurance premium fee and no DeFi origination fee; the example list that used to stand here named both.

`examples/07_revenue_to_neosafe.py` shows what the router does when called directly.
