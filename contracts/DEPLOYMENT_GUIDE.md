# The Matrix Contract Deployment Guide

This repository has two deployment tools, and they deploy different things.
Both default to Base Sepolia (testnet, chain id 84532). Neither is run for
you: you run them with your own key, and the contracts are yours.

| Tool | Deploys | Reads its key from | Writes |
|------|---------|--------------------|--------|
| `python -m contracts.deploy` | `MatrixAttestation` only | `matrix.config.json` → `blockchain.paymaster_private_key` | `contracts/deployment.json` and `contracts/MatrixAttestation.abi.json` |
| `python scripts/deploy_all.py [config.json]` | `MatrixMarketplace`, `MatrixStaking`, `MatrixDAO`, `MatrixInsurance`, `MatrixDEX`, `MatrixNFT`, `MatrixDID`, `PropertyDeed`, `PropertyEscrow`, attesting each deployment | a JSON config's `private_key`, or `MATRIX_PRIVATE_KEY` | `deployment_manifest.json` at the repository root |

All of those output files are git-ignored. `contracts.deploy` no longer
deploys `MatrixPaymaster`, and prints on every run what it will not deploy and
why (`scripts/refuse_legacy_contracts.py` holds the list).

## Prerequisites

- Python 3.10+
- An RPC URL for Base (Sepolia: `https://sepolia.base.org`)
- A funded deployer wallet
  - Sepolia ETH faucet: <https://www.alchemy.com/faucets/base-sepolia>
- `solc` 0.8.20 (installed by `py-solc-x` on first run)
- For Foundry builds and tests, the three Solidity dependencies under
  `contracts/lib/`, pinned as git submodules: forge-std,
  openzeppelin-contracts and account-abstraction. On a fresh checkout:

  ```bash
  git submodule update --init --recursive
  ```

  `scripts/build-contracts.sh` installs forge-std and OpenZeppelin when they
  are missing, but not account-abstraction, which `MatrixAccount.sol`
  imports; initialise the submodules first.

## 1a. MatrixAttestation, with `contracts.deploy`

Set these in `matrix.config.json`, in the directory you run from:

```json
"blockchain": {
  "network": "base-sepolia",
  "rpc_url": "https://sepolia.base.org",
  "chain_id": 84532,
  "paymaster_private_key": "0x...",
  "platform_wallet": "0x..."
}
```

`paymaster_private_key` is the deployer: it signs and pays for the deployment,
so fund its address. The tool refuses to start if any of `rpc_url`,
`paymaster_private_key` or `platform_wallet` is missing or still a `YOUR_…`
placeholder, and stops if the deployer's balance is zero.

```bash
python -m contracts.deploy
```

## 1b. The rest of the suite, with `scripts/deploy_all.py`

Give it `rpc_url`, `chain_id`, `private_key` and `neosafe_address` (the address
the contracts send platform fees to), and optionally `oracle_address` and
`eas_schema_uid`, in a JSON file passed as its argument or as `MATRIX_RPC_URL`,
`MATRIX_CHAIN_ID`, `MATRIX_PRIVATE_KEY`, `MATRIX_NEOSAFE_ADDRESS`,
`MATRIX_ORACLE_ADDRESS` and `MATRIX_EAS_SCHEMA_UID`. `rpc_url` and `chain_id`
default to Base Sepolia.

```bash
MATRIX_PRIVATE_KEY=0x... MATRIX_NEOSAFE_ADDRESS=0x... python scripts/deploy_all.py
```

## 2. Wire addresses into config

Copy each address from the tool's output file into the matching `services.*`
block in `matrix.config.json`. For example:

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

## 3. Verify

```bash
curl http://localhost:18790/status -H "Authorization: Bearer YOUR_API_KEY" | jq .subsystems.blockchain
```

`{"configured": true}` means `blockchain.rpc_url` is set to something other
than a placeholder. It does not check your contract addresses.

## Reference: EAS on Base

The Ethereum Attestation Service is a predeploy on Base, the same address on
Base Sepolia and Base mainnet:

| Contract       | Base Sepolia and Base mainnet                  |
|----------------|------------------------------------------------|
| EAS            | `0x4200000000000000000000000000000000000021`   |
| SchemaRegistry | `0x4200000000000000000000000000000000000020`   |

`0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587`, which this guide used to list
for Base Sepolia, is Ethereum's EAS contract. Check any address against
<https://docs.attest.org> before trusting it. This guide lists no shared
deployment of the other contracts; deploy your own.

## Troubleshooting

- **`insufficient funds`** — top up the deployer wallet at the faucet above.
- **`replacement transaction underpriced`** — increase gas in the deployer
  config or wait for the previous tx to confirm.
- **`solc not found`** — `py-solc-x` should auto-install on first run; if it
  fails, run `python -c "import solcx; solcx.install_solc('0.8.20')"`.
