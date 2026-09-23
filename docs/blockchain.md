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

The primary network is Base (Ethereum L2). Ethereum mainnet is used for high-value operations and attestations. Cross-chain bridges enable movement between networks.

## Fees

Gas is sponsored by the platform paymaster **within the policy the operator configures**: an allowlist of actions and a per-identity daily cap, decided from the call data being signed (`runtime/blockchain/sponsorship.py`). Inside that policy a user pays no gas. Past the cap, or for an action the allowlist does not cover, sponsorship is refused rather than silently granted. An operator who configures no policy sponsors everything. The README's section on the Web3 capability surface says the same.
