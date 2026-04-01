# Base L2 Integration

## Why Base

0pnMatrx uses Base as its primary L2 network. Base is an Ethereum L2 built on the OP Stack that provides:

- **Low network costs** — the platform covers all transaction fees, and Base keeps those costs minimal
- **Ethereum security** — settles to Ethereum L1 for full security guarantees
- **EVM compatibility** — all Solidity contracts work without modification
- **EAS support** — full Ethereum Attestation Service integration

## Configuration

Set your Base RPC URL in `openmatrix.config.json`:

```json
{
  "blockchain": {
    "network": "base",
    "rpc_url": "YOUR_BASE_RPC_URL",
    "eas_schema": "YOUR_EAS_SCHEMA_UID"
  }
}
```

## RPC Providers

You can use any Base RPC provider:
- **Alchemy** — reliable, free tier available
- **Infura** — widely supported
- **QuickNode** — high performance
- **Public RPC** — free but rate-limited

## Contract Deployment

Deploying to Base follows the same process as Ethereum mainnet. The contracts in `blockchain/contracts/` are fully compatible. All transaction fees are covered by the platform.

## Bridging

To move assets between Ethereum mainnet and Base:
1. Use the native Base Bridge
2. Or ask Trinity — she'll handle it through conversation

## Attestations on Base

EAS is deployed on Base at the same addresses as mainnet:
- **EAS Contract**: `0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587`
- **Schema Registry**: `0xA7b39296258348C78294F95B872b282326A97BDF`

Attestations on Base are free to the user and maintain the same verifiability as mainnet. All fees are covered by the platform.
