# 0pnMatrx — Complete Capability Map

Every Web3 capability accessible through the gateway, organized by category.

---

## DeFi

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Token Swap | Swap any token for another at the best rate | Free | POST /api/v1/dex/swap | Uniswap V3, Curve, Balancer |
| Swap Route | Get the optimal swap route across DEXs | Free | POST /api/v1/defi/swap/route | Uniswap V3, Curve, 1inch |
| Swap Execute | Execute a pre-computed swap route | Free | POST /api/v1/defi/swap/execute | Uniswap V3, Curve, 1inch |
| Liquidity Add | Add liquidity to a DEX pool | Free | POST /api/v1/dex/liquidity/add | Uniswap V3, Curve |
| Liquidity Provide | Provide liquidity with concentrated positions | Free | POST /api/v1/defi/liquidity/provide | Uniswap V3, Curve |
| Create Loan | Create a collateralised DeFi loan | Free | POST /api/v1/defi/loan/create | Aave V3, Compound V3 |
| Repay Loan | Repay an outstanding DeFi loan | Free | POST /api/v1/defi/loan/repay | Aave V3, Compound V3 |
| Yield Optimize | Find and enter the best yield strategy for an asset | Pro | POST /api/v1/defi/yield/optimize | Yearn, Beefy, Convex |
| Bridge Quote | Get a cross-chain bridge quote | Free | POST /api/v1/defi/bridge/quote | Stargate, Hop, Across |
| Bridge Execute | Execute a cross-chain bridge transfer | Free | POST /api/v1/defi/bridge/execute | Stargate, Hop, Across |
| Flash Loan | Execute an atomic flash loan with bundled operations | Pro | POST /api/v1/defi/flash-loan/execute | Aave V3, dYdX |
| Vault Deposit | Deposit assets into a yield vault | Free | POST /api/v1/defi/vault/deposit | Yearn, Beefy |
| Perpetual Trade | Trade perpetual futures on-chain | Pro | POST /api/v1/defi/perp/trade | GMX, dYdX, Synthetix |
| Collateral Manage | Add, withdraw, or rebalance collateral positions | Free | POST /api/v1/defi/collateral/manage | Aave V3, Compound V3 |
| Staking | Stake tokens for yield | Free | POST /api/v1/staking/stake | Lido, Rocket Pool, native |
| Unstaking | Unstake tokens and claim rewards | Free | POST /api/v1/staking/unstake | Lido, Rocket Pool, native |
| Stablecoin Transfer | Send stablecoins globally with zero fees | Free | POST /api/v1/stablecoin/transfer | USDC, USDT, DAI |
| Cross-Border Payment | Send money across borders with FX conversion | Free | POST /api/v1/crossborder/send | Circle, Wise, native |

---

## NFT

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Mint NFT | Mint a single NFT with metadata | Free | POST /api/v1/nft/mint | ERC-721, ERC-1155 |
| Create Collection | Create an NFT collection with royalty settings | Free | POST /api/v1/nft/collection/create | ERC-721 |
| Batch Mint | Mint multiple NFTs in a single transaction | Pro | POST /api/v1/nft/batch-mint | ERC-721, ERC-1155 |
| Fractionalize NFT | Split an NFT into fungible fractions for co-ownership | Pro | POST /api/v1/nft/fractionalize | Fractional, Tessera |
| Rent NFT | Rent an NFT for a specified duration | Free | POST /api/v1/nft/rent | ERC-4907 |
| Royalty Claim | Claim accumulated royalties from secondary sales | Free | POST /api/v1/nft/royalty/claim | ERC-2981 |
| Bridge NFT | Bridge an NFT to another chain | Free | POST /api/v1/nft/bridge | LayerZero, Wormhole |
| IP Registration | Register intellectual property on-chain | Free | POST /api/v1/ip/register | EAS, custom |

---

## Identity

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create DID | Create a decentralised identity | Free | POST /api/v1/identity/create | DID:openmatrix |
| Create DID (expanded) | Create a DID with extended method support | Free | POST /api/v1/identity/did/create | DID:openmatrix, DID:ethr |
| Issue Credential | Issue a verifiable credential to a subject | Free | POST /api/v1/identity/credential/issue | W3C VC, EAS |
| Verify Credential | Verify the validity of a credential | Free | POST /api/v1/identity/credential/verify | W3C VC, EAS |
| ZK Proof | Generate a zero-knowledge proof for a claim | Pro | POST /api/v1/identity/zk-proof/generate | Semaphore, zkSNARK |
| Soulbound Mint | Mint a non-transferable soulbound token | Free | POST /api/v1/identity/soulbound/mint | ERC-5192 |
| Attestation Verify | Verify an on-chain attestation by UID | Free | GET /api/v1/attestation/verify/{uid} | EAS |

---

## Governance

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create DAO | Create a new DAO with on-chain governance | Free | POST /api/v1/dao/create | Governor, custom |
| Create Proposal | Submit a governance proposal | Free | POST /api/v1/governance/proposal/create | Governor, Tally |
| Vote | Cast a vote on a governance proposal | Free | POST /api/v1/governance/vote | Governor, Tally |
| Multisig Propose | Submit a proposal to a multisig wallet | Free | POST /api/v1/governance/multisig/propose | Safe (Gnosis) |
| Multisig Approve | Approve a pending multisig transaction | Free | POST /api/v1/governance/multisig/approve | Safe (Gnosis) |
| Snapshot Vote | Cast a gasless off-chain vote | Free | POST /api/v1/governance/snapshot/vote | Snapshot |
| Treasury Transfer | Execute a DAO treasury transfer | Pro | POST /api/v1/governance/treasury/transfer | Governor, Safe |

---

## RWA (Real-World Assets)

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Tokenize Asset | Tokenize a real-world asset (property, vehicle, etc.) | Free | POST /api/v1/rwa/tokenize | ERC-3643, custom |
| Fractional Buy | Purchase fractions of a tokenized RWA | Free | POST /api/v1/rwa/fractional/buy | ERC-3643, custom |
| List Assets | Browse available tokenized real-world assets | Free | GET /api/v1/rwa/listings | custom |
| Create Security | Create a tokenized security | Enterprise | POST /api/v1/securities/create | ERC-3643 |

---

## Payments

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Payment | Create a one-time payment | Free | POST /api/v1/payments/create | x402, native |
| Payment Stream | Create a continuous payment stream over time | Pro | POST /api/v1/payments/stream/create | Sablier, Superfluid |
| Recurring Payment | Set up a recurring payment schedule | Pro | POST /api/v1/payments/recurring/create | Superfluid, custom |
| Escrow Milestone | Manage milestone-based escrow releases | Free | POST /api/v1/payments/escrow/milestone | custom |
| Split Payment | Split a payment across multiple recipients | Free | POST /api/v1/payments/split | 0xSplits, custom |
| Payroll | Execute a batch payroll run | Enterprise | POST /api/v1/payments/payroll | 0xSplits, Sablier |

---

## Privacy

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Data Deletion | Request deletion of personal data | Free | POST /api/v1/privacy/delete | custom |
| Private Transfer | Send tokens with privacy shielding | Pro | POST /api/v1/privacy/transfer | Railgun, Aztec |
| Stealth Address | Generate a one-time stealth address for receiving | Pro | POST /api/v1/privacy/stealth-address | ERC-5564 |

---

## Social

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Share Proof | Share a social proof on-chain | Free | POST /api/v1/social/message | custom |
| Create Profile | Create an on-chain social profile | Free | POST /api/v1/social/profile | Lens, custom |
| Create Post | Publish a post to the decentralised social feed | Free | POST /api/v1/social/post | Lens, Farcaster |
| Send Message | Send an encrypted peer-to-peer message | Free | POST /api/v1/social/message/send | XMTP, custom |
| Token Gate | Create a token-gated access rule | Free | POST /api/v1/social/gate/create | custom |
| Create Community | Launch a token-gated community | Free | POST /api/v1/social/community/create | custom |
| Social Feed | View the activity feed for a wallet | Free | GET /api/v1/social/feed/{wallet} | custom |

---

## Gaming

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Register Game | Register a game and its on-chain assets | Free | POST /api/v1/gaming/register | ERC-721, ERC-1155 |

---

## Prediction Markets

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Market | Create a new prediction market | Pro | POST /api/v1/prediction/market/create | Polymarket, custom |
| Place Bet | Place a bet on a prediction market outcome | Free | POST /api/v1/prediction/market/bet | Polymarket, custom |
| List Markets | Browse active prediction markets | Free | GET /api/v1/prediction/market/list | Polymarket, custom |

---

## Supply Chain

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Register Product | Register a product on-chain for tracking | Free | POST /api/v1/supply-chain/register | custom |
| Log Provenance | Log a provenance event for a product | Free | POST /api/v1/supply-chain/provenance/log | custom |
| Verify Authenticity | Verify the complete history and authenticity of a product | Free | POST /api/v1/supply-chain/verify | custom |
| Transfer Custody | Transfer chain-of-custody to a new holder | Free | POST /api/v1/supply-chain/custody/transfer | custom |

---

## Insurance

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Policy | Create an insurance policy | Free | POST /api/v1/insurance/policy/create | custom |
| File Claim | File an insurance claim with trigger data | Free | POST /api/v1/insurance/claim | custom |
| Parametric Policy | Create a parametric policy with automatic oracle triggers | Pro | POST /api/v1/insurance/parametric/create | Chainlink, custom |
| Settle Claim | Settle a claim with a specified amount | Free | POST /api/v1/insurance/claim/settle | custom |

---

## Compute & Storage

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Decentralized Store | Store data on a decentralised storage network | Free | POST /api/v1/compute/store | IPFS, Arweave, Filecoin |
| IPFS Pin | Pin content on IPFS for persistence | Free | POST /api/v1/compute/ipfs/pin | IPFS |
| Arweave Store | Store data permanently on Arweave | Free | POST /api/v1/compute/arweave/store | Arweave |

---

## AI

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Register Agent | Register an on-chain agent identity | Free | POST /api/v1/agent/register | custom |
| Register AI Agent | Register an AI agent with model and capabilities | Pro | POST /api/v1/ai/agent/register | custom |
| Trade Model | Buy or sell an AI model NFT | Pro | POST /api/v1/ai/model/trade | ERC-721, custom |

---

## Energy & Sustainability

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Buy Carbon Credits | Purchase carbon credits from verified projects | Free | POST /api/v1/energy/carbon/buy | Toucan, KlimaDAO |
| Retire Carbon | Permanently retire carbon credits | Free | POST /api/v1/energy/carbon/retire | Toucan, KlimaDAO |
| Carbon Prices | Get current carbon credit pricing | Free | GET /api/v1/energy/carbon/prices | Toucan, KlimaDAO |

---

## Legal

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Grant License | Grant a license for intellectual property | Pro | POST /api/v1/legal/license/grant | custom |
| Execute Agreement | Execute a legally binding on-chain agreement | Pro | POST /api/v1/legal/agreement/execute | custom |
| File Dispute | File a legal dispute for on-chain arbitration | Free | POST /api/v1/legal/dispute/file | custom |
| Dispute Resolution | File a dispute through the resolution service | Free | POST /api/v1/dispute/file | custom |

---

## Contracts

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Convert Contract | Convert plain-English or pseudocode into Solidity | Free | POST /api/v1/contracts/convert | Solidity, Vyper |
| Deploy Contract | Compile and deploy a smart contract | Free | POST /api/v1/contracts/deploy | Base, EVM |

---

## Portfolio & Analytics

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Dashboard | Get a complete dashboard for a wallet address | Free | GET /api/v1/dashboard/{address} | custom |
| Complete Portfolio | Aggregated portfolio view across all protocols | Free | GET /api/v1/portfolio/complete/{wallet} | Protocol Abstraction Layer |
| Open Positions | View all open DeFi positions for a wallet | Free | GET /api/v1/portfolio/positions/{wallet} | Protocol Abstraction Layer |
| Transaction History | Full transaction history for a wallet | Free | GET /api/v1/portfolio/history/{wallet} | Protocol Abstraction Layer |
| Oracle Price | Get the current price for a trading pair | Free | GET /api/v1/oracle/price/{pair} | Chainlink, Pyth, Band |

---

## Intent Resolution

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Resolve Intent | Parse a natural-language intent into an execution plan | Free | POST /api/v1/intent/resolve | Intent Resolver |
| Execute Intent | Execute a previously resolved intent plan | Free | POST /api/v1/intent/execute | Intent Resolver |
| Intent Summary | Get the summary and status of an intent plan | Free | GET /api/v1/intent/summary/{plan_id} | Intent Resolver |

---

## Marketplace & Commerce

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| List Item | List an item for sale on the marketplace | Free | POST /api/v1/marketplace/list | custom |
| Buy Item | Purchase a marketplace listing | Free | POST /api/v1/marketplace/buy | custom |
| Subscribe | Subscribe to a service plan | Free | POST /api/v1/subscriptions/subscribe | custom |
| Earn Loyalty | Earn loyalty points from platform actions | Free | POST /api/v1/loyalty/earn | custom |
| Redeem Loyalty | Redeem loyalty points for rewards | Free | POST /api/v1/loyalty/redeem | custom |
| Track Cashback | Track spending for cashback rewards | Free | POST /api/v1/cashback/track | custom |
| Brand Campaign | Create a brand reward campaign | Enterprise | POST /api/v1/brand/campaign/create | custom |

---

## Fundraising

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Campaign | Create a crowdfunding campaign with milestones | Free | POST /api/v1/fundraising/campaign/create | custom |
| Contribute | Contribute to an active fundraising campaign | Free | POST /api/v1/fundraising/contribute | custom |

---

## Cross-Cutting

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Batch Dispatch | Execute multiple API calls in a single round trip | Free | POST /api/v1/batch | custom |
| Event Stream | Server-Sent Events for live updates | Free | GET /api/v1/events/stream | SSE |
