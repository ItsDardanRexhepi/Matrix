# Blockchain

## 221 Capabilities Across 21 Categories

0pnMatrx provides 221 discrete Web3 capabilities organised into 21 categories, all accessible through conversation:

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

State-changing capabilities are signed by the platform, which pays their gas within the sponsorship policy described under **Gas** below.

## How It Works

Users describe what they want to Trinity in plain language. Trinity translates the request into the appropriate blockchain operation. Neo executes it. If it's a first-time use or irreversible action, Morpheus explains what's happening first.

## Networks

The primary network is Base (Ethereum L2). Ethereum mainnet is used for high-value operations and attestations. Cross-chain bridges enable movement between networks.

## Gas

When an operator configures the platform paymaster, the platform pays gas for users' operations — within the operator's sponsorship policy (`runtime/blockchain/sponsorship.py`):

- **Per-identity daily cap.** A USD amount per identity over a rolling 24 hours (`paymaster.policy.daily_cap_usd`; the example config sets 50). Past it, the platform stops sponsoring: an operation the platform would sign is refused with the reason rather than charged to the user, and a user-operation sponsorship request to `/api/v1/paymaster/sign` is declined with `403`. A deployment that sets no cap sponsors without a daily limit.
- **Action allowlist.** `paymaster.policy.allowed_actions` limits which action types are sponsored. It is checked on every `/api/v1/paymaster/sign` request (against the request's action type), and on platform-signed operations only when a daily cap is also set. A platform-signed operation is matched by its `<capability>.<method>` name (for example `daos.vote`, `stablecoins.transfer`; registry services that sign through `Web3Manager.send_transaction` use `web3.send_transaction`). The example config's list (`transfer`, `swap`) names none of those, so under the example policy every platform-signed operation is refused.
- **Identity.** With a cap set, an operation that cannot be attributed to a signed-in identity is refused: a per-identity cap cannot meter spend it cannot attribute.
- **Not metered.** Writes the platform makes on its own behalf are listed in `UNMETERED_PLATFORM_OPERATIONS` (EAS attestations and their revocation, moving platform revenue to its treasury multisig); they are not counted against any user's cap.
- **No paymaster configured, no sponsorship.** The platform pays no gas there; an app-signed user operation pays its own.

What a particular deployment provides is returned by the dashboard, payments and cross-border tools as `gas_policy`, derived from the same configuration the signer reads.

## Fees

The platform does take fees on some operations. They are separate from gas sponsorship (above). `tests/test_fee_disclosure_matches_code.py` derives each rate below from the file cited next to it and fails if a row disagrees. It also sweeps `runtime/`, `gateway/` and `contracts/` for files that define a fee-named constant or default, a fee tier table, or a transfer to the platform fee recipient, and fails if one is neither in this table nor recorded in the test as not charged (for example, third-party bridge fees a route estimate only quotes). The sweep matches names: a fee computed under a name that says neither "fee" nor "commission" would not be found.

### On-chain, in the platform contracts

| Operation | What the platform receives | Source |
|---|---|---|
| Marketplace purchase | 5% of the sale price | `contracts/OpenMatrixMarketplace.sol` (`PLATFORM_FEE_BPS`) |
| Staking rewards | 5% of rewards, when claimed or paid out on unstake | `contracts/OpenMatrixStaking.sol` (`COMMISSION_BPS`) |
| DAO treasury withdrawal | 1% below 10,000 gwei; 0.5% up to 100,000 gwei; 0.25% above | `contracts/OpenMatrixDAO.sol` (`_tieredFeeBps`) |
| NFT mint | everything sent with the mint (`msg.value`, which must be at least `mintPrice`, set at deployment — an overpayment is kept too); the platform is also the default royalty receiver when a minter sets no royalty | `contracts/OpenMatrixNFT.sol` |
| Insurance | premiums stay in the pool; the owner can withdraw the balance above the reserve and outstanding coverage to the platform | `contracts/OpenMatrixInsurance.sol` (`withdrawExcess`) |

Token swaps on `contracts/OpenMatrixDEX.sol` are not charged a platform fee.

### In platform services

Computed by the service on the operation it performs. Defaults are shown; each is overridable in configuration where noted.

| Operation | Platform fee | Source |
|---|---|---|
| Stablecoin transfer | deducted from the amount: 0.1% below 1,000; 0.05% below 10,000; 0.025% below 100,000; 0.01% above | `runtime/blockchain/services/stablecoin/service.py` (`DEFAULT_FEE_TIERS`; `stablecoin.fee_tiers`) |
| Marketplace sale | 5% of the price | `runtime/blockchain/services/marketplace/service.py` (`platform_fee_pct`) |
| Creator subscription plan payment | 10% of each payment | `runtime/blockchain/services/subscriptions/service.py` (`platform_fee_pct`) |
| Game revenue distribution | 5% of the revenue distributed | `runtime/blockchain/services/gaming/revenue_share.py` (`platform_fee_pct`) |
| Pooled real-world-asset purchase | 1% of the amount raised, on finalise | `runtime/blockchain/services/rwa_tokenization/pooled_purchase.py` (`platform_fee_pct`) |
| NFT sale | 2.5% of the sale price | `runtime/blockchain/services/nft_services/royalty_enforcement.py`, `runtime/blockchain/services/nft_services/service.py` (`blockchain.platform_fee_bps`) |
| P2P loan | 0.5% of the principal, added to the repayment | `runtime/blockchain/services/defi/p2p_lending.py` (`defi.p2p.platform_fee_bps`) |
| Cross-border payment (`send_payment`, `get_payment_quote`, `cross_border_remit`) | 0.5% of the amount, deducted before conversion; the payment is recorded, not settled — no value moves | `runtime/blockchain/services/cross_border/service.py` (`cross_border.fee_pct`) |
| Staking rewards (service ledger) | 5% of rewards claimed, recorded on the claim; nothing is transferred | `runtime/blockchain/services/staking/service.py` (`staking.commission_pct`) |
| DAO treasury deposit or executed spend (a `create_dao` initial deposit, a `join_dao` stake) | on the service's treasury ledger, deducted from a deposit and added to a spend: 1% below 10,000; 0.5% below 100,000; 0.25% above | `runtime/blockchain/services/dao_management/treasury.py` (`_FEE_TIERS`) |
| Insurance policy cancellation | 10% of the pro-rata premium refund is withheld | `runtime/blockchain/services/insurance/service.py` (`cancel_policy`) |
| Contract conversion | when `blockchain.platform_wallet` is set, the generated contract gets a 2.5% fee on value sent to each `payable` function, paid to that wallet (its owner can change it, up to 10%); on by default (`conversion.inject_fees`) | `runtime/blockchain/services/contract_conversion/revenue_enforcer.py` (`blockchain.platform_fee_bps`) |

### Paid to others, through platform services

| Operation | Fee | Source |
|---|---|---|
| Token swap through the service's pools (`swap_tokens`, `get_swap_quote`) | 0.3% of the input at each pool hop by default, kept by the pool; the platform takes none, and quotes and trades report it as `user_fee` | `runtime/blockchain/services/dex/pools.py` (`dex.default_fee_tier`) |

Paid plugin sales are not live (the purchase route answers `501`); their commission is the operator's `plugin_marketplace.commission_rate`. Subscriptions (Pro, Enterprise) are sold in the MTRX app through Apple In-App Purchase.
