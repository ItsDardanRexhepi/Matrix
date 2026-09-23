# Blockchain

## 195 Capabilities Across 21 Categories

The Matrix catalogues 195 discrete Web3 capabilities in 21 categories (`runtime/capabilities/catalog.py`), all accessible through conversation:

1. **Smart Contracts** — deploy, convert, templates
2. **DeFi** — swaps, lending, yield, LP, vaults, flash loans
3. **DeFi Advanced** — perpetuals, options, synthetics, orderbook, Pyth feeds
4. **NFTs** — mint, transfer, collections, royalties, fractionalization, rentals, dynamic, soulbound
5. **NFT Finance** — NFT-backed lending, ERC-6551 token-bound accounts, breeding
6. **Identity** — DIDs, verifiable credentials, reputation, KYC/AML, agent identity, attestations
7. **Governance** — DAOs, proposals, voting, Snapshot, timelock, multisig, veToken, quadratic, RetroPGF, bribes, delegation
8. **Social** — profiles, gating, communities, XMTP messaging, Lens, Farcaster, Push Protocol
9. **Creator Economy** — monetization, Sound.xyz, Mirror, Paragraph, IP registry, creator coins
10. **Payments** — streaming, escrow, recurring, splits, invoicing, payroll, state channels, cross-border
11. **Cross-chain** — CCIP, Hyperlane, Wormhole, Axelar, Stargate, remote chain queries
12. **Staking & Restaking** — staking, unstaking, liquid staking (Lido, Rocket Pool), restaking (EigenLayer, Symbiotic, Karak), delegation
13. **Privacy & ZK** — private transfers, stealth addresses, ZK proofs, MPC, threshold sigs, social recovery, session keys
14. **Oracles** — Chainlink price feeds, VRF randomness, Pyth, RedStone, API3, Keepers automation
15. **Storage** — IPFS, Arweave, Filecoin, Ceramic, OrbitDB
16. **Compute & DePIN** — Akash, Gensyn, Render, IoT device rentals, physical infrastructure
17. **Real-world Assets** — RWA tokenization, supply chain provenance, carbon credits, green bonds
18. **Markets** — prediction markets, auctions (Dutch/English/sealed-bid), fundraising, securities, marketplaces
19. **Security & Wallets** — catalogued with no capabilities in it yet. MPC signing, session keys and social recovery are under Privacy & ZK (all three not yet available), multisig under Governance, attestations under Identity (and one under Gaming)
20. **Gaming** — games, assets, tournaments, achievements, in-game economies
21. **Infrastructure** — AI agents, ML models, training data

Gas for state-changing capabilities is sponsored by the platform paymaster within the policy the operator configures (see Fees).

## How It Works

Users describe what they want to Trinity in plain language. Trinity translates the request into the appropriate blockchain operation. Neo executes it. If it's a first-time use or irreversible action, Morpheus explains what's happening first.

## Networks

The primary network is Base (Ethereum L2). The gateway writes to the one chain `blockchain.*` configures (Base Sepolia by default), attestations included; nothing sends high-value operations or attestations to Ethereum mainnet. The cross-chain capabilities are for movement between networks.

## Fees

Gas is sponsored by the platform paymaster **within the policy the operator configures**: an allowlist of actions and a per-identity daily cap (`runtime/blockchain/sponsorship.py`). Inside that policy a user pays no gas, and an operator who configures no policy sponsors everything. What is checked depends on who signs:

- A smart-account operation the paymaster signs (`POST /api/v1/paymaster/sign`) is checked against the allowlist, with its actions decoded from the call data being signed, and against the daily cap when one is set. Past either, sponsorship is refused rather than silently granted.
- A transaction the platform signs itself for a capability is checked against the allowlist and the cap only when a daily cap is set. With no cap it is signed whatever the allowlist says.
- A few signing paths are exempt from the policy altogether; they are listed by name in `UNMETERED_PLATFORM_OPERATIONS`: `eas.attest` (an EAS attestation, `EASClient.attest`), `eas.attest_time_critical`, `eas.revoke` and `gas_sponsor.sponsor`. The three EAS writes are signed with the platform key whatever the allowlist and the cap say, and these reach them: the `create_attestation`, `batch_attest` and `revoke_attestation` capabilities; the service dispatcher's own record of each state-modifying action it completes; `convert_contract` with `conversion.auto_deploy` on; the real-estate routes, with `services.real_estate.enabled` set; and 13 actions of Neo's blockchain tools `eas`, `agent_identity`, `identity`, `crossborder_payment`, `gaming`, `insurance`, `ip_royalties`, `securities` and `supply_chain`. The table below gives each path.

### Signed with the platform key, with no policy check

Every call into an exempt signer in `runtime/` and `gateway/` is listed here, found from the code; `tests/test_unmetered_signing_paths_are_documented.py` fails if one is missing, and it drives the paths below under a policy that allows nothing and caps at zero to see which of them sign.

| Path | When it signs | Exemption | Code |
|---|---|---|---|
| `create_attestation`, `batch_attest` | An attestation marked time-critical (`time_critical`, or a `category` of `dispute_filing`, `rights_reversion`, `ban_record` or `emergency_freeze`) is signed at once, with the recipient and payload the caller supplies. Any other goes on the dispatcher's attestation queue, next row. | `eas.attest_time_critical` | `runtime/blockchain/services/attestation/service.py` `attest`, `batch_attest`; `runtime/blockchain/services/attestation/time_critical.py` `attest_now` |
| The service dispatcher's record of a state-modifying action it completes, and the attestations above that are not time-critical | Queued on the attestation service of the dispatcher's service registry. When 50 have gathered, each is signed and sent as its own transaction. Nothing sends a shorter queue, and what is queued is lost if the process exits first. | `eas.attest` | `runtime/blockchain/services/service_dispatcher.py` `_attest_action`; `runtime/blockchain/services/attestation/batch_processor.py` `_submit_batch` |
| `revoke_attestation` | At once, revoking the uid under the schema the caller names. | `eas.revoke` | `runtime/blockchain/services/attestation/service.py` `revoke` |
| `convert_contract`, with `conversion.auto_deploy` on | Once the chain confirms a contract the pipeline deployed. The deployment itself is signed under the policy (`contract_conversion.deploy`), so a policy that refuses it leaves nothing to attest. | `eas.attest` | `runtime/blockchain/services/contract_conversion/service.py` `convert` |
| The real-estate routes (`/api/v1/realestate/…`), with `services.real_estate.enabled` set and a `document_verification` schema registered | A document upload, a buyer verification that passes, a purchase and a confirmed settlement each queue an attestation, with the seller's or the buyer's wallet as recipient, on the real-estate service's own queue. When 50 have gathered, each is signed and sent as its own transaction. | `eas.attest` | `runtime/blockchain/services/real_estate/service.py` `_attest` |
| Neo's tool `eas`: `attest`, `batch_attest` | At once: `attest` with the recipient and data the call supplies, and `batch_attest` one transaction for each attestation it is given. | `eas.attest` | `runtime/blockchain/eas_manager.py` `_attest`, `_batch_attest` |
| Neo's tool `agent_identity`: `register`, `attest_action` | At once. | `eas.attest` | `runtime/blockchain/agent_identity.py` `_register`, `_attest_action` |
| Neo's tool `identity`: `register` | At once, with the address the call names as recipient. | `eas.attest` | `runtime/blockchain/identity.py` `_register` |
| Neo's tool `crossborder_payment`: `send` | At once, with the payee as recipient; no transfer is made. | `eas.attest` | `runtime/blockchain/crossborder.py` `_send` |
| Neo's tool `gaming`: `record_achievement` | At once, with the player as recipient. | `eas.attest` | `runtime/blockchain/gaming.py` `_record_achievement` |
| Neo's tool `insurance`: `create_policy`, `file_claim` | At once. | `eas.attest` | `runtime/blockchain/insurance.py` `_create_policy`, `_file_claim` |
| Neo's tool `ip_royalties`: `register_ip` | At once. | `eas.attest` | `runtime/blockchain/ip_royalties.py` `_register_ip` |
| Neo's tool `securities`: `whitelist_investor` | At once, with the investor as recipient. | `eas.attest` | `runtime/blockchain/securities.py` `_whitelist` |
| Neo's tool `supply_chain`: `create_record`, `update_status` | At once. | `eas.attest` | `runtime/blockchain/supply_chain.py` `_create_record`, `_update_status` |

These call the same code and sign nothing today:

- `gas_sponsor.sponsor` is `GasSponsor.sponsor_transaction` (`runtime/blockchain/gas_sponsor.py`), which signs and sends whatever transaction it is handed. 14 services construct a `GasSponsor`; nothing calls the method.
- `NeoSafeRouter` queues an attestation for a fee it records, on an attestation service of its own, and attests revenue it sends once the transfer is mined (`runtime/blockchain/services/neosafe.py` `_attest_fee`, `route_revenue`); nothing in the gateway calls the router.
- A cross-border payment's attestation (`runtime/blockchain/services/cross_border/service.py` `_attest_payment`) is queued on a new attestation service made for that one call, whose queue never reaches 50, so it is dropped unsigned.
- An insurance claim's attestation (`runtime/blockchain/services/insurance/claims_processor.py` `_attest_claim`) is queued the same way and dropped the same way.
- An x402 limit change's attestation (`runtime/blockchain/services/x402_payments/limit_updater.py` `_attest_limit_change`) is queued the same way and dropped the same way.
- An IP rights reversion (`runtime/blockchain/services/ip_royalties/royalty_enforcement.py` `_attest_rights_reversion`) would be signed at once as time-critical, but it is reached only from `IPRoyaltyEnforcement.process_usage`, which nothing calls.
- An NFT royalty sale (`runtime/blockchain/services/nft_services/royalty_enforcement.py` `process_sale`) is attested only when the NFT service is given an attestation service, and the service registry builds it without one.

Outside the gateway, `contracts/deploy.py`, run by hand, deploys `MatrixAttestation` with `blockchain.paymaster_private_key`; the policy does not apply to it.

The README's section on the Web3 capability surface says the same.
