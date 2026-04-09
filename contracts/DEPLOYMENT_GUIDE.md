# 0pnMatrx Contract Deployment Guide

This guide walks you through deploying the 0pnMatrx smart-contract suite to
Base Sepolia (testnet) or Base Mainnet, then plugging the resulting addresses
into `openmatrix.config.json`.

## Prerequisites

- Python 3.10+
- An RPC URL for Base (default Sepolia: `https://sepolia.base.org`)
- A funded deployer wallet
  - Sepolia ETH faucet: <https://www.alchemy.com/faucets/base-sepolia>
- `solc` 0.8.20 (auto-installed by `py-solc-x` on first run)

## 1. Configure environment

Copy `.env.example` to `.env` and fill in:

```
BASE_RPC_URL=https://sepolia.base.org
```

Set the deployer key in `openmatrix.config.json`:

```json
"blockchain": {
  "network": "base-sepolia",
  "rpc_url": "https://sepolia.base.org",
  "chain_id": 84532,
  "demo_wallet_private_key": "0x...",
  "demo_wallet_address": "0x..."
}
```

## 2. Compile and deploy

```bash
python -m contracts.deploy
```

The deployer compiles each `.sol` file under `contracts/`, deploys it, and
writes the resulting addresses to `contracts/deployed_addresses.json`.

## 3. Wire addresses into config

After deployment, copy each address from `deployed_addresses.json` into the
matching `services.*` block in `openmatrix.config.json`. For example:

```json
"services": {
  "marketplace": {
    "enabled": true,
    "contract_address": "0xYourMarketplaceAddress",
    "platform_fee_bps": 500,
    "platform_wallet": "0xYourPlatformWallet"
  }
}
```

## 4. Verify

```bash
curl http://localhost:18790/status | jq .subsystems.blockchain
```

You should see `{"configured": true}`.

## Reference: Pre-deployed addresses

The 0pnMatrx team maintains a public deployment on Base Sepolia for testing.
These addresses are stable and can be used directly in your config:

| Service              | Base Sepolia                                       |
|----------------------|----------------------------------------------------|
| EAS (Attestation)    | `0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587`       |
| Marketplace          | _populate after deploy_                            |
| Staking              | _populate after deploy_                            |
| DAO factory          | _populate after deploy_                            |
| DID registry         | _populate after deploy_                            |
| Insurance            | _populate after deploy_                            |
| NFT factory          | _populate after deploy_                            |
| DEX router           | _populate after deploy_                            |
| Paymaster            | _populate after deploy_                            |

> If you deploy your own copies, please open a PR adding your addresses to
> this table so others can reuse them.

## Troubleshooting

- **`insufficient funds`** — top up the deployer wallet at the faucet above.
- **`replacement transaction underpriced`** — increase gas in the deployer
  config or wait for the previous tx to confirm.
- **`solc not found`** — `py-solc-x` should auto-install on first run; if it
  fails, run `python -c "import solcx; solcx.install_solc('0.8.20')"`.
