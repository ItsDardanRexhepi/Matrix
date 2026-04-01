# Blockchain Components

## Smart Contracts

0pnMatrx deploys and manages smart contracts on behalf of users. All contract interactions happen through Trinity — the user describes what they want in plain language, and the system handles the rest.

### Contract Types

| Contract | Purpose |
|----------|---------|
| Identity | On-chain identity with attestation support |
| Ownership | Verifiable ownership stakes with basis-point precision |
| Payment | Direct transfers, payment requests, recurring schedules |
| Governance | DAO proposals, voting, quorum-based execution |
| Insurance | Decentralized insurance pools with claim management |

## Ethereum Attestation Service (EAS)

0pnMatrx uses EAS for verifiable credentials and attestations. Every significant action can be attested on-chain, creating a permanent, verifiable record.

- **Schema Registry**: Custom schemas define the structure of attestations
- **Attestations**: Signed records that link data to on-chain identity
- **Verification**: Anyone can verify any attestation on-chain

## Wallet Management

Each user has a managed wallet. Private keys are generated locally and never leave the user's device. The platform never has access to user funds.

## Transaction Processing

All transactions use EIP-1559 (Type 2) for reliable inclusion:
- `maxPriorityFeePerGas` — tip for validators
- `maxFeePerGas` — maximum total price per unit of gas
- Dynamic estimation based on network conditions

All transaction fees are paid by the platform. Users never pay gas on 0pnMatrx.

## Event Monitoring

The system monitors on-chain events to:
- Confirm transaction inclusion
- Detect incoming transfers
- Track governance votes
- Trigger Morpheus when significant events occur
