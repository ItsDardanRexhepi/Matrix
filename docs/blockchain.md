# Blockchain

## 195 Capabilities Across 20 Categories

The Matrix provides 195 discrete Web3 capabilities organised into 20 categories, all accessible through conversation:

1. **Smart Contracts** (3) — Convert to Solidity, Quote Conversion Fee, List Contract Templates
2. **DeFi** (4) — Borrow Against Collateral, Repay Loan, Get Loan Details, Swap Tokens
3. **DeFi (Advanced)** (3) — all catalogued with `available: false`: Place Limit Order, Cancel Limit Order, Pull Pyth Price
4. **NFTs** (17) — Mint NFT, Create NFT Collection, Transfer NFT, List NFT for Sale, Buy NFT, Estimate NFT Value, Get NFT Rarity, Set NFT Rights, Check NFT Rights, Configure NFT Royalty, Fractionalize NFT, Rent NFT, Update Dynamic NFT, Batch Mint NFTs, Claim NFT Royalties, Bridge NFT, Mint Soulbound NFT
5. **NFT Finance** (5) — all catalogued with `available: false`: Borrow Against NFT, Liquidate NFT Loan, Breed NFT, Create Token-bound Account, Execute As TBA
6. **Identity** (14) — Create DID, Update DID, Deactivate DID, Issue Credential, Query Reputation, Register AI Agent, Update Agent, Deregister Agent, Create Attestation, Revoke Attestation, Batch Attest; catalogued with `available: false`: Start KYC, Check AML Risk, Issue KYC Credential
7. **Governance** (22) — Create DAO, Join DAO, Leave DAO, Create Proposal, Vote on Proposal, Finalize Proposal, Queue Timelock Action, Propose Multisig Action, Parameter Change, File Dispute, Submit Evidence, Resolve Dispute, Appeal Dispute, Dispute File (Legacy), Request Arbitration; catalogued with `available: false`: Snapshot Vote, Approve Multisig Action, Vote-Escrow Lock, Quadratic Vote, Submit RetroPGF, Place Gauge Bribe, Delegate Voting Power
8. **Social** (12) — Create Social Profile, Update Social Profile, Social Post, Gated Social Content, Create Community, Send Message (XMTP), Encrypted Message; catalogued with `available: false`: Create Lens Profile, Publish Farcaster Cast, Subscribe to Push, Launch Social Token, Launch Creator Coin
9. **Creator Economy** (8) — Monetize Content, Register IP, Transfer IP, License IP, Execute Agreement; catalogued with `available: false`: Mint Sound.xyz Drop, Publish Mirror Post, Publish Paragraph Post
10. **Payments** (8) — Create Payment, Complete Payment, Send Payment, Transfer Stablecoin, Cross-border Remit; catalogued with `available: false`: Open Payment Channel, Route via Channel, Close Payment Channel
11. **Cross-chain** (8) — all catalogued with `available: false`: Bridge Tokens, Bridge via CCIP, Cross-chain Message, Bridge via Hyperlane, Bridge via Wormhole, Bridge via Axelar, Bridge via Stargate, Query Remote Chain
12. **Staking & Restake** (11) — Stake Tokens, Unstake Tokens, Claim Staking Rewards, Get Staking Position; catalogued with `available: false`: Restake on EigenLayer, Restake on Symbiotic, Restake on Karak, Delegate to Operator, Withdraw Restake, Liquid Stake with Lido, Liquid Stake (Rocket)
13. **Privacy & ZK** (5) — Generate ZK Proof; catalogued with `available: false`: MPC Sign, Social Recovery, Create Session Key, Request Deletion
14. **Oracles & Data** (7) — Query Oracle Price, Request VRF Randomness, Query Weather Oracle; catalogued with `available: false`: Pull Pyth Update, Request RedStone Data, Query API3, Register Keeper Job
15. **Storage** (5) — Pin to IPFS, Decentralized Store; catalogued with `available: false`: Store on Filecoin, Create Ceramic Stream, Write to OrbitDB
16. **Compute & DePIN** (4) — Submit Legacy Compute; catalogued with `available: false`: Submit Compute Job, Rent DePIN Device, Claim Compute Reward
17. **Real-world Assets** (21) — Tokenize Asset, Transfer RWA Ownership, RWA Tokenize, Buy RWA Fraction, Claim RWA Income, Register Product, Update Product Status, Transfer Custody, Log Provenance, Batch Track, Custody Transfer, Buy Carbon Credit, Retire Carbon Credit, Buy Renewable Cert, Invest in Green Bond, Create Policy, File Claim, Cancel Policy, Parametric Policy, Auto-settle Claim, Renew Cover
18. **Markets** (26) — Create Prediction Market, Place Prediction Bet, Resolve Market, Create Fundraiser, Contribute to Campaign, Release Milestone Funds, Trigger Refunds, Create Security Token, List Security, Sell Security, List Marketplace Item, Buy Marketplace Item, Cancel Listing, Earn Loyalty Points, Redeem Loyalty Points, Track Spending, Claim Cashback, Create Brand Campaign, Distribute Brand Reward, Create Subscription Plan, Subscribe, Cancel Subscription; catalogued with `available: false`: Create Auction, Place Auction Bid, Settle Auction, Buy Security
19. **Gaming** (8) — Register Game, Mint Game Asset, Transfer Game Asset, Approve Game, Mint Game Asset (Legacy), Enter Tournament, Trade Game Item, Attest Achievement
20. **Infrastructure** (4) — Register AI Agent, Trade AI Model, Sell Training Data, Grant IP License

The catalog also declares **Security & Wallets**, which holds no capability.

State-changing capabilities are signed by the platform, which pays their gas within the sponsorship policy described under **Gas** below.

## How It Works

Users describe what they want to Trinity in plain language. Trinity translates the request into the appropriate blockchain operation. Neo executes it. If it's a first-time use or irreversible action, Morpheus explains what's happening first.

## Networks

Everything runs on the one chain the operator configures (`blockchain.rpc_url`, `blockchain.chain_id`): the example config and the examples use Base Sepolia, and Base (Ethereum L2) is the intended mainnet. Nothing sends an operation to another network because of its value. The cross-chain capabilities are all catalogued with `available: false`.

## Gas

When an operator configures the platform paymaster, the platform pays gas for users' operations — within the operator's sponsorship policy (`runtime/blockchain/sponsorship.py`):

- **Per-identity daily cap.** A USD amount per identity over a rolling 24 hours (`paymaster.policy.daily_cap_usd`; the example config sets 50). Past it, the platform stops sponsoring: an operation the platform would sign is refused with the reason rather than charged to the user, and a user-operation sponsorship request to `/api/v1/paymaster/sign` is declined with `403`. A deployment that sets no cap sponsors without a daily limit.
- **Action allowlist.** `paymaster.policy.allowed_actions` limits which action types are sponsored. It is checked on every `/api/v1/paymaster/sign` request (against the actions decoded from the user operation's call data), and on platform-signed operations only when a daily cap is also set. A platform-signed operation is matched by its `<capability>.<method>` name (for example `daos.vote`, `stablecoins.transfer`; registry services that sign through `Web3Manager.send_transaction` use `web3.send_transaction` unless the call site names its own action). The example config's list (`transfer`, `swap`) names none of those, so under the example policy every platform-signed operation is refused.
- **Identity.** With a cap set, an operation that cannot be attributed to a signed-in identity is refused: a per-identity cap cannot meter spend it cannot attribute.
- **Attestations.** An attestation written because a user asked for it is metered like any platform-signed operation, under its `<capability>.<method>` name: the `eas` tool's `attest` and `batch_attest` and the tool-layer records (agent identity, identity, insurance, gaming, cross-border, IP, securities, supply chain) under names such as `eas_manager.attest`, and the `create_attestation`, `batch_attest` and `revoke_attestation` capabilities under `attestation.attest`, `attestation.batch_attest` and `attestation.revoke`. For a capability attestation that is queued rather than time-critical, the allowlist, the identity requirement and whether the caller has any cap left are checked when it is queued, and a write that fails one of them is refused then; the whole policy, including the cap at the write's real price, is applied for the identity it was queued under when its batch signs, and a refusal at that later point is logged and the attestation is dropped. A single batch request may hold at most 20 attestations.
- **Not metered.** Writes listed in `UNMETERED_PLATFORM_OPERATIONS` are signed and paid by the platform without counting against any cap: the platform's own records (the dispatcher's record of each capability call, and records a service writes after another operation — a conversion deploy, a claim outcome, a royalty) and the sponsorship accounting path itself. No attestation a caller composes is on that list.
- **No paymaster configured, no sponsorship.** The platform pays no gas there; an app-signed user operation pays its own.

What a particular deployment provides is returned by the dashboard, payments and cross-border tools as `gas_policy`, derived from the same configuration the signer reads.

## Fees

The platform does take fees on some operations. They are separate from gas sponsorship (above). `tests/test_fee_disclosure_matches_code.py` derives each rate below from the file cited next to it and fails if a row disagrees. It also sweeps `runtime/`, `gateway/` and `contracts/` for files that define a fee-named constant or default, a tier table, or a transfer to the platform fee recipient, and fails if one is neither in these tables nor recorded in the test as not charged (for example, third-party bridge fees a route estimate only quotes, or the insurance premium schedule, which prices cover rather than taking a fee). The sweep matches names: a fee computed under a name that says neither "fee" nor "commission" would not be found.

### On-chain, in the platform contracts

| Operation | What the platform receives | Source |
|---|---|---|
| Marketplace purchase | 5% of the sale price | `contracts/MatrixMarketplace.sol` (`PLATFORM_FEE_BPS`) |
| Staking rewards | 5% of rewards, when claimed or paid out on unstake | `contracts/MatrixStaking.sol` (`COMMISSION_BPS`) |
| DAO treasury withdrawal | 1% below 10,000 gwei; 0.5% up to 100,000 gwei; 0.25% above | `contracts/MatrixDAO.sol` (`_tieredFeeBps`) |
| NFT mint | everything sent with the mint (`msg.value`, which must be at least `mintPrice`, set at deployment — an overpayment is kept too); the platform is also the default royalty receiver when a minter sets no royalty | `contracts/MatrixNFT.sol` |
| Insurance | premiums stay in the pool; the owner can withdraw the balance above the reserve and outstanding coverage to the platform | `contracts/MatrixInsurance.sol` (`withdrawExcess`) |

Token swaps on `contracts/MatrixDEX.sol` are not charged a platform fee.

Each contract pays its fee to its `platformFeeRecipient`, set at deployment and changeable by the owner: `scripts/deploy_all.py` (the deployment `CREDENTIALS_NEEDED.md` describes) passes the configured NeoSafe address (`MATRIX_NEOSAFE_ADDRESS`) as `platformFeeRecipient` for every platform contract, so on a deployment built that way the contracts above pay these fees to NeoSafe. `NeoSafeRouter` (`runtime/blockchain/services/neosafe.py`) is not involved: no service calls it. Injected conversion fees (below) are paid to `blockchain.platform_wallet`, which the same setup calls the NeoSafe wallet; service-ledger fees are recorded, not settled.

### In platform services

Computed by the service on the operation it performs. Defaults are shown; each is overridable in configuration where noted.

| Operation | Platform fee | Source |
|---|---|---|
| Stablecoin transfer (the `transfer_stablecoin` capability) | deducted from the amount: 0.1% below 1,000; 0.05% below 10,000; 0.025% below 100,000; 0.01% above | `runtime/blockchain/services/stablecoin/service.py` (`DEFAULT_FEE_TIERS`; `stablecoin.fee_tiers`) |
| Marketplace sale | 5% of the price | `runtime/blockchain/services/marketplace/service.py` (`platform_fee_pct`) |
| Creator subscription plan payment | 10% of each payment | `runtime/blockchain/services/subscriptions/service.py` (`platform_fee_pct`) |
| Game revenue distribution | 5% of the revenue distributed | `runtime/blockchain/services/gaming/revenue_share.py` (`platform_fee_pct`) |
| Pooled real-world-asset purchase | 1% of the amount raised, on finalise | `runtime/blockchain/services/rwa_tokenization/pooled_purchase.py` (`platform_fee_pct`) |
| NFT sale | 2.5% of the sale price | `runtime/blockchain/services/nft_services/royalty_enforcement.py`, `runtime/blockchain/services/nft_services/service.py` (`blockchain.platform_fee_bps`) |
| P2P loan | 0.5% of the principal, added to the repayment | `runtime/blockchain/services/defi/p2p_lending.py` (`defi.p2p.platform_fee_bps`) |
| Cross-border payment (`send_payment`, `get_payment_quote`) | 0.5% of the amount, deducted before conversion; the payment is recorded, not settled — no value moves | `runtime/blockchain/services/cross_border/service.py` (`cross_border.fee_pct`) |
| Staking rewards (service ledger) | 5% of rewards claimed, recorded on the claim; nothing is transferred | `runtime/blockchain/services/staking/service.py` (`staking.commission_pct`) |
| DAO treasury deposit or executed spend | on the service's treasury ledger, deducted from a deposit and added to an executed spend: 1% below 10,000; 0.5% below 100,000; 0.25% above | `runtime/blockchain/services/dao_management/treasury.py` (`_FEE_TIERS`) |
| Insurance policy cancellation | 10% of the pro-rata premium refund is withheld | `runtime/blockchain/services/insurance/service.py` (`cancel_policy`) |
| Contract conversion | when `blockchain.platform_wallet` is set, the generated contract gets a 2.5% fee on value sent to each `payable` function, paid to that wallet (its owner can change it, up to 10%); on by default (`conversion.inject_fees`) | `runtime/blockchain/services/contract_conversion/revenue_enforcer.py` (`blockchain.platform_fee_bps`) |

The `stablecoin` agent tool's transfer (`runtime/blockchain/stablecoins.py`) sends the full amount on-chain; the platform deducts nothing from it. The cross-border tool's estimate quotes the fee on each of these paths.

### Paid to others, through platform services

| Operation | Fee | Source |
|---|---|---|
| Token swap through the service's pools (`swap_tokens`, `get_swap_quote`) | 0.3% of each hop's input by default, kept by the pool; the platform takes none. Quotes and trades report it per hop as `pool_fees`, each entry in that hop's input token, so a routed swap has one fee per token it passes through and no single total | `runtime/blockchain/services/dex/pools.py` (`dex.default_fee_tier`) |

### Quoted, not collected

| Operation | Quote | Source |
|---|---|---|
| Contract conversion tier (`estimate_contract_cost`, and the `tier` in a conversion result) | 0.01 ETH below 100 non-blank lines; 0.05 ETH below 500; 0.1 ETH above; "negotiated" past a complexity score of 200. Nothing collects it: no route or service takes a payment for a conversion | `runtime/blockchain/services/contract_conversion/tier_manager.py` (`_TIERS`; `conversion.tier_overrides`) |

Paid plugin sales are not live (the purchase route answers `501`); their commission is the operator's `plugin_marketplace.commission_rate`. Subscriptions (Pro, Enterprise) are sold in the MTRX app through Apple In-App Purchase.
