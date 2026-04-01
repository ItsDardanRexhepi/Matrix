# Migration

Import your existing data from other platforms into 0pnMatrx.

## Supported Platforms

| Platform | Importer | What It Imports |
|----------|----------|-----------------|
| MetaMask | `metamask_importer.py` | Wallet addresses, transaction history, token balances |
| Coinbase | `coinbase_importer.py` | Portfolio data, transaction history |
| OpenSea | `opensea_importer.py` | NFT collections, ownership records |
| ENS | `ens_importer.py` | Domain names, resolution records |
| Snapshot | `snapshot_importer.py` | Governance history, voting records |

## How It Works

Each importer reads exported data from the source platform and creates corresponding records in 0pnMatrx. No private keys are ever imported — only public data.

## Usage

```bash
python3 -m migration.metamask_importer --input export.json
python3 -m migration.coinbase_importer --input transactions.csv
python3 -m migration.opensea_importer --address 0x...
python3 -m migration.ens_importer --address 0x...
python3 -m migration.snapshot_importer --address 0x...
```

Or just ask Trinity: "Import my MetaMask wallet" — she'll guide you through it.
