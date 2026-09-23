# Blockchain

## 221 Capabilities Across 21 Categories

The Matrix provides 221 discrete Web3 capabilities organised into 21 categories, all accessible through conversation:

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
19. **Security & Wallets** — MPC, session keys, social recovery, multisig, attestations
20. **Gaming** — games, assets, tournaments, achievements, in-game economies
21. **Infrastructure** — AI agents, ML models, training data

Transactions the platform signs are paid for by the platform account. Some capabilities instead prepare an unsigned transaction for your own wallet to sign (advanced governance, auctions), and your wallet pays that gas; user operations the gateway sponsors are sponsored within the operator's policy and daily cap.

## How It Works

Users describe what they want to Trinity in plain language. Trinity translates the request into the appropriate blockchain operation. Neo executes it. If it's a first-time use or irreversible action, Morpheus explains what's happening first.

## Networks

The primary network is Base (Ethereum L2). Ethereum mainnet is used for high-value operations and attestations. Cross-chain bridges enable movement between networks.

## Fees

Gas: the platform pays for the transactions it signs, and sponsors user operations within the policy and per-identity daily cap its operator configures. A transaction prepared for your wallet to sign is paid by your wallet.

Fees that are not gas exist and are shown where they apply: the marketplace takes a platform fee from a sale, a DEX pool deducts its liquidity-provider fee from a swap's input, and the conversion pipeline writes a platform fee into the contracts it generates. This page used to say there were none, with no exceptions and no conditions — each of the above is an exception.
