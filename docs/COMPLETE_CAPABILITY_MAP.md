# 0pnMatrx — Complete Capability Map

Every Web3 capability accessible through the gateway, organized by category.

The platform pays gas for everything. Paymaster sponsorship is the default for every state-modifying capability below, so end users never hold or spend native tokens to transact. Read-only capabilities don't touch a chain and are free to call.

---

## Capability Catalog

The canonical inventory lives in [`runtime/capabilities/catalog.py`](../runtime/capabilities/catalog.py). It is the single source of truth that backs Trinity's `platform_action` tool, the gateway REST endpoints, the iOS extensions registry, and this document.

- **221 capabilities** across **21 categories**, backed by **44 services** in `runtime/blockchain/services/`.
- Every capability has an `id`, `category`, `subcategory`, `service`, `method`, `action`, `params_schema`, `min_tier` (`free` / `pro` / `enterprise`), `uses_paymaster` flag, `protocol` tag, and `available` flag.
- Capabilities marked `available: false` are catalogued but still awaiting backend or contract deployment — they appear in the API with `"available": false` so clients can feature-flag them.

Discover and invoke them over HTTP:

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/capabilities` | List every capability. Filters: `?category=defi`, `?min_tier=pro`, `?available=1` |
| `GET`  | `/api/v1/capabilities/categories` | List the 21 categories with counts |
| `GET`  | `/api/v1/capabilities/{id}` | Return the full descriptor for one capability |
| `POST` | `/api/v1/capabilities/{id}/invoke` | Execute a capability. Body: `{"params": {...}}` matching the capability's `params_schema` |

The sections below organise every capability by its high-level category. Older convenience endpoints remain in place for backwards compatibility — the capability registry is additive, not a replacement.

---

## Smart Contracts

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Convert Contract | Convert plain-English or pseudocode into Solidity | Free | POST /api/v1/contracts/convert | Solidity, Vyper |
| Deploy Contract | Compile and deploy a smart contract | Free | POST /api/v1/contracts/deploy | Base, EVM |
| Estimate Deployment Cost | Estimate gas and paymaster coverage for a deployment | Free | via capability registry | Base, EVM |
| List Contract Templates | Browse built-in templates | Free | via capability registry | — |

---

## DeFi

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Token Swap | Swap any token for another at the best rate | Free | POST /api/v1/dex/swap | Uniswap V3, Curve, Balancer |
| Swap Route | Get the optimal swap route across DEXs | Free | POST /api/v1/defi/swap/route | Uniswap V3, Curve, 1inch |
| Swap Execute | Execute a pre-computed swap route | Free | POST /api/v1/defi/swap/execute | Uniswap V3, Curve, 1inch |
| Liquidity Add | Add liquidity to a DEX pool | Free | POST /api/v1/dex/liquidity/add | Uniswap V3, Curve |
| Liquidity Provide | Provide liquidity with concentrated positions | Free | POST /api/v1/defi/liquidity/provide | Uniswap V3, Curve |
| Liquidity Remove | Withdraw liquidity from a DEX pool | Free | POST /api/v1/defi/liquidity/remove | Uniswap V3, Curve |
| Create Loan | Create a collateralised DeFi loan | Free | POST /api/v1/defi/loan/create | Aave V3, Compound V3 |
| Repay Loan | Repay an outstanding DeFi loan | Free | POST /api/v1/defi/loan/repay | Aave V3, Compound V3 |
| Yield Optimize | Find and enter the best yield strategy for an asset | Pro | POST /api/v1/defi/yield/optimize | Yearn, Beefy, Convex |
| Flash Loan | Execute an atomic flash loan with bundled operations | Pro | POST /api/v1/defi/flash-loan/execute | Aave V3, dYdX |
| Vault Deposit | Deposit assets into a yield vault | Free | POST /api/v1/defi/vault/deposit | Yearn, Beefy |
| Collateral Manage | Add, withdraw, or rebalance collateral positions | Free | POST /api/v1/defi/collateral/manage | Aave V3, Compound V3 |

---

## DeFi (Advanced)

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Perpetual Trade | Trade perpetual futures on-chain | Pro | POST /api/v1/defi/perp/trade | GMX, dYdX, Synthetix |
| Options Trade | Buy or sell on-chain options | Pro | via capability registry | Lyra |
| Synthetic Asset | Mint a synthetic exposure | Pro | via capability registry | Synthetix |
| Leverage Position | Open a leveraged position | Pro | via capability registry | GMX, Gearbox |
| Place Limit Order | Submit a limit order to the orderbook DEX | Pro | via capability registry | custom orderbook |
| Cancel Limit Order | Cancel a resting limit order | Free | via capability registry | custom orderbook |
| Pyth Pull Price | Pull a Pyth price update on demand | Free | via capability registry | Pyth |

---

## Cross-chain / Bridging

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Bridge Quote | Get a cross-chain bridge quote | Free | POST /api/v1/defi/bridge/quote | Stargate, Hop, Across |
| Bridge Execute | Execute a cross-chain bridge transfer | Free | POST /api/v1/defi/bridge/execute | Stargate, Hop, Across |
| Bridge via CCIP | Transfer tokens using Chainlink CCIP | Free | via capability registry | Chainlink CCIP |
| Cross-chain Message | Send an arbitrary message across chains | Free | via capability registry | CCIP, Hyperlane |
| Bridge via Hyperlane | Transfer using Hyperlane | Free | via capability registry | Hyperlane |
| Bridge via Wormhole | Transfer using Wormhole | Free | via capability registry | Wormhole |
| Bridge via Axelar | Transfer using Axelar GMP | Free | via capability registry | Axelar |
| Bridge via Stargate | Transfer stablecoins using Stargate | Free | via capability registry | Stargate |
| Query Remote Chain | Read state from a foreign chain | Free | via capability registry | CCIP |

---

## Staking & Restaking

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Stake | Stake tokens for yield | Free | POST /api/v1/staking/stake | native |
| Unstake | Unstake tokens and claim rewards | Free | POST /api/v1/staking/unstake | native |
| Claim Staking Rewards | Claim accrued staking rewards | Free | via capability registry | native |
| Get Staking Position | View current staking position | Free | via capability registry | native |
| Liquid Stake (Lido) | Obtain stETH by liquid-staking ETH with Lido | Free | via capability registry | Lido |
| Liquid Stake (Rocket Pool) | Obtain rETH by liquid-staking with Rocket Pool | Free | via capability registry | Rocket Pool |
| Restake on EigenLayer | Restake LSTs to EigenLayer AVSs | Pro | via capability registry | EigenLayer |
| Restake on Symbiotic | Restake via Symbiotic | Pro | via capability registry | Symbiotic |
| Restake on Karak | Restake via Karak | Pro | via capability registry | Karak |
| Delegate to Operator | Delegate restaked capital to an AVS operator | Pro | via capability registry | EigenLayer |
| Withdraw Restake | Initiate withdrawal from restaking | Pro | via capability registry | EigenLayer, Symbiotic, Karak |

---

## NFTs

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Mint NFT | Mint a single NFT with metadata | Free | POST /api/v1/nft/mint | ERC-721, ERC-1155 |
| Create Collection | Create an NFT collection with royalty settings | Free | POST /api/v1/nft/collection/create | ERC-721 |
| Transfer NFT | Transfer an NFT to another owner | Free | via capability registry | ERC-721, ERC-1155 |
| List NFT for Sale | List an NFT on the marketplace | Free | via capability registry | ERC-721 |
| Buy NFT | Purchase a listed NFT | Free | via capability registry | ERC-721 |
| Batch Mint | Mint multiple NFTs in a single transaction | Pro | POST /api/v1/nft/batch-mint | ERC-721, ERC-1155 |
| Fractionalize NFT | Split an NFT into fungible fractions for co-ownership | Pro | POST /api/v1/nft/fractionalize | Fractional, Tessera |
| Rent NFT | Rent an NFT for a specified duration | Free | POST /api/v1/nft/rent | ERC-4907 |
| Royalty Claim | Claim accumulated royalties from secondary sales | Free | POST /api/v1/nft/royalty/claim | ERC-2981 |
| Configure NFT Royalty | Set or update the royalty for a collection | Free | via capability registry | ERC-2981 |
| Dynamic Update | Update dynamic NFT metadata | Free | via capability registry | ERC-721 |
| Estimate NFT Value | Get an AI-derived value estimate | Free | via capability registry | custom |
| Get NFT Rarity | Compute rarity rank for a token | Free | via capability registry | custom |
| Set / Check NFT Rights | Encode and query programmable rights | Free | via capability registry | custom |
| Bridge NFT | Bridge an NFT to another chain | Free | POST /api/v1/nft/bridge | LayerZero, Wormhole |
| IP Registration | Register intellectual property on-chain | Free | POST /api/v1/ip/register | EAS, custom |
| Soulbound Mint | Mint a non-transferable soulbound token | Free | POST /api/v1/identity/soulbound/mint | ERC-5192 |

---

## NFT Finance

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Borrow Against NFT | Take a loan collateralised by an NFT | Pro | via capability registry | BendDAO, NFTfi |
| Liquidate NFT Loan | Liquidate a defaulted NFT loan | Pro | via capability registry | BendDAO, NFTfi |
| Breed NFT | Breed two NFTs to produce a new one | Free | via capability registry | custom |
| Create Token-bound Account | Deploy an ERC-6551 account for a token | Free | via capability registry | ERC-6551 |
| Execute As TBA | Execute a transaction from a token-bound account | Free | via capability registry | ERC-6551 |

---

## Identity

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create DID | Create a decentralised identity | Free | POST /api/v1/identity/create | DID:openmatrix |
| Create DID (expanded) | Create a DID with extended method support | Free | POST /api/v1/identity/did/create | DID:openmatrix, DID:ethr |
| Update DID | Update a DID document | Free | via capability registry | DID:openmatrix |
| Deactivate DID | Deactivate a DID | Free | via capability registry | DID:openmatrix |
| Issue Credential | Issue a verifiable credential to a subject | Free | POST /api/v1/identity/credential/issue | W3C VC, EAS |
| Verify Credential | Verify the validity of a credential | Free | POST /api/v1/identity/credential/verify | W3C VC, EAS |
| Reputation Query | Query aggregated on-chain reputation for an agent | Free | via capability registry | custom |
| Start KYC | Start a KYC session with the configured provider | Free | via capability registry | Sumsub, Persona |
| Check AML Risk | Screen an address for AML risk | Free | via capability registry | Sumsub, Persona |
| Issue KYC Credential | Issue a KYC-verified credential after approval | Free | via capability registry | W3C VC |
| Register / Update / Deregister Agent | Manage an AI agent identity | Free | via capability registry | custom |
| Create / Revoke / Batch Attest | On-chain attestations | Free | via capability registry | EAS |
| Attestation Verify | Verify an on-chain attestation by UID | Free | GET /api/v1/attestation/verify/{uid} | EAS |
| ZK Proof | Generate a zero-knowledge proof for a claim | Pro | POST /api/v1/identity/zk-proof/generate | Semaphore, zkSNARK |

---

## Governance

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create DAO | Create a new DAO with on-chain governance | Free | POST /api/v1/dao/create | Governor, custom |
| Join DAO | Join an existing DAO | Free | via capability registry | Governor |
| Leave DAO | Leave a DAO | Free | via capability registry | Governor |
| Create Proposal | Submit a governance proposal | Free | POST /api/v1/governance/proposal/create | Governor, Tally |
| Vote | Cast a vote on a governance proposal | Free | POST /api/v1/governance/vote | Governor, Tally |
| Finalize Proposal | Execute a passed proposal | Free | via capability registry | Governor |
| Snapshot Vote | Cast a gasless off-chain vote | Free | POST /api/v1/governance/snapshot/vote | Snapshot |
| Timelock Queue | Queue an action through a timelock | Free | via capability registry | OZ Timelock |
| Multisig Propose | Submit a proposal to a multisig wallet | Free | POST /api/v1/governance/multisig/propose | Safe (Gnosis) |
| Multisig Approve | Approve a pending multisig transaction | Free | POST /api/v1/governance/multisig/approve | Safe (Gnosis) |
| Treasury Transfer | Execute a DAO treasury transfer | Pro | POST /api/v1/governance/treasury/transfer | Governor, Safe |
| Parameter Change | Mutate a governed protocol parameter | Pro | via capability registry | Governor |
| Vote-Escrow Lock | Lock tokens in a veToken gauge | Pro | via capability registry | Curve, Balancer |
| Quadratic Vote | Cast a quadratic vote | Free | via capability registry | Gitcoin, custom |
| Submit RetroPGF | Submit a retroactive public-goods funding claim | Pro | via capability registry | Optimism RetroPGF |
| Place Gauge Bribe | Bribe a gauge for vote weight | Pro | via capability registry | Convex, Hidden Hand |
| Delegate Voting Power | Delegate voting to another address | Free | via capability registry | Governor |
| File / Submit Evidence / Resolve / Appeal Dispute | Dispute resolution lifecycle | Free | POST /api/v1/dispute/file | custom |
| Arbitration Request | Request third-party arbitration | Free | via capability registry | custom |

---

## Social

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Social Profile | Create an on-chain social profile | Free | POST /api/v1/social/profile | Lens, custom |
| Update Social Profile | Update profile metadata | Free | via capability registry | Lens, custom |
| Create Post | Publish a post to the decentralised social feed | Free | POST /api/v1/social/post | Lens, Farcaster |
| Social Gate | Create a token-gated access rule | Free | POST /api/v1/social/gate/create | custom |
| Create Community | Launch a token-gated community | Free | POST /api/v1/social/community/create | custom |
| Send Message (XMTP) | Send an encrypted peer-to-peer message | Free | POST /api/v1/social/message/send | XMTP, custom |
| Encrypted Message | Encrypt a payload for a recipient | Free | via capability registry | XMTP |
| Create Lens Profile | Mint a profile on the Lens Protocol | Free | via capability registry | Lens |
| Publish Farcaster Cast | Post a cast on Farcaster | Free | via capability registry | Farcaster |
| Subscribe to Push | Subscribe to Push Protocol notification channels | Free | via capability registry | Push Protocol |
| Launch Social Token | Launch a personal social token | Pro | via capability registry | custom |
| Launch Creator Coin | Launch a creator coin with a bonding curve | Pro | via capability registry | custom |

---

## Creator Economy

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Monetize Content | Enable paywalls, tips, and subscriptions on content | Free | via capability registry | custom |
| Mint Sound.xyz Drop | Release a music drop on Sound.xyz | Pro | via capability registry | Sound.xyz |
| Publish Mirror Post | Publish a long-form post on Mirror | Free | via capability registry | Mirror |
| Publish Paragraph Post | Publish a Paragraph newsletter | Free | via capability registry | Paragraph |
| Register IP | Register intellectual property on-chain | Free | via capability registry | EAS |
| Transfer IP | Transfer IP ownership | Free | via capability registry | custom |
| License IP | Grant a license for intellectual property | Pro | POST /api/v1/legal/license/grant | custom |
| Execute Agreement | Execute a legally binding on-chain agreement | Pro | POST /api/v1/legal/agreement/execute | custom |

---

## Payments

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Payment | Create a one-time payment | Free | POST /api/v1/payments/create | x402, native |
| Authorize / Complete / Refund | Two-phase payment lifecycle | Free | via capability registry | x402 |
| Send Payment | Send a payment to a wallet | Free | via capability registry | stablecoin |
| Transfer Stablecoin | Send stablecoins globally with zero fees | Free | POST /api/v1/stablecoin/transfer | USDC, USDT, DAI |
| Payment Stream | Create a continuous payment stream over time | Pro | POST /api/v1/payments/stream/create | Sablier, Superfluid |
| Recurring Payment | Set up a recurring payment schedule | Pro | POST /api/v1/payments/recurring/create | Superfluid, custom |
| Escrow Milestone | Manage milestone-based escrow releases | Free | POST /api/v1/payments/escrow/milestone | custom |
| Split Payment | Split a payment across multiple recipients | Free | POST /api/v1/payments/split | 0xSplits, custom |
| Invoice Factor | Tokenize and sell an invoice for working capital | Pro | via capability registry | custom |
| Payroll | Execute a batch payroll run | Enterprise | POST /api/v1/payments/payroll | 0xSplits, Sablier |
| Cross-Border Payment | Send money across borders with FX conversion | Free | POST /api/v1/crossborder/send | Circle, Wise, native |
| Open / Route / Close Channel | State-channel lifecycle for off-chain micropayments | Pro | via capability registry | state channels |

---

## Privacy & ZK

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Data Deletion (request / execute) | Request deletion of personal data | Free | POST /api/v1/privacy/delete | custom |
| Private Transfer | Send tokens with privacy shielding | Pro | POST /api/v1/privacy/transfer | Railgun, Aztec |
| Stealth Address | Generate a one-time stealth address for receiving | Pro | POST /api/v1/privacy/stealth-address | ERC-5564 |
| ZK Proof Generate | Generate a zero-knowledge proof | Pro | via capability registry | Semaphore, zkSNARK |
| Private Vote | Vote privately on a proposal | Pro | via capability registry | Semaphore |
| Confidential Compute | Run a confidential compute job | Pro | via capability registry | TEE, MPC |
| MPC Sign | Threshold-sign a transaction using an MPC quorum | Pro | via capability registry | MPC threshold sig |
| Social Recovery | Recover a wallet through a social guardian set | Free | via capability registry | custom |
| Session Key | Issue a scoped session key for dApp interactions | Free | via capability registry | ERC-4337 session keys |

---

## Oracles & Data

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Oracle Price Query | Get the current price for a trading pair | Free | GET /api/v1/oracle/price/{pair} | Chainlink, Pyth, Band |
| Oracle VRF | Request verifiable randomness | Free | via capability registry | Chainlink VRF |
| Weather Oracle | Query weather data for an address | Free | via capability registry | custom |
| Pyth Pull | Pull a Pyth price update on demand | Free | via capability registry | Pyth |
| RedStone Request | Fetch a signed RedStone data package | Free | via capability registry | RedStone |
| API3 Query | Query a first-party API3 dAPI | Free | via capability registry | API3 |
| Register Keeper Job | Register a Chainlink Keeper / upkeep job | Pro | via capability registry | Chainlink Keepers |

---

## Storage

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Decentralized Store | Store data on a decentralised storage network | Free | POST /api/v1/compute/store | IPFS, Arweave, Filecoin |
| IPFS Pin | Pin content on IPFS for persistence | Free | POST /api/v1/compute/ipfs/pin | IPFS |
| Arweave Store | Store data permanently on Arweave | Free | POST /api/v1/compute/arweave/store | Arweave |
| Filecoin Store | Make a Filecoin storage deal | Free | via capability registry | Filecoin |
| Ceramic Stream | Create a mutable Ceramic stream | Free | via capability registry | Ceramic |
| OrbitDB Write | Write to an OrbitDB peer-to-peer database | Free | via capability registry | OrbitDB |

---

## Compute & DePIN

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Submit Compute Job | Submit a decentralised compute job | Pro | via capability registry | Akash, Gensyn, Render |
| Rent DePIN Device | Rent a device on a DePIN network | Pro | via capability registry | custom |
| Claim Compute Reward | Claim rewards for running compute workers | Free | via capability registry | custom |
| Legacy Compute Submit | Submit a job through the legacy compute pipeline | Pro | via capability registry | custom |

---

## Real-World Assets

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Tokenize Asset | Tokenize a real-world asset (property, vehicle, etc.) | Free | POST /api/v1/rwa/tokenize | ERC-3643, custom |
| Transfer RWA Ownership | Transfer ownership of a tokenized asset | Free | via capability registry | ERC-3643 |
| Fractional Buy | Purchase fractions of a tokenized RWA | Free | POST /api/v1/rwa/fractional/buy | ERC-3643, custom |
| RWA Income Claim | Claim income streams from a tokenized RWA | Free | via capability registry | ERC-3643 |
| List Assets | Browse available tokenized real-world assets | Free | GET /api/v1/rwa/listings | custom |
| Register Product | Register a product on-chain for tracking | Free | POST /api/v1/supply-chain/register | custom |
| Log Provenance | Log a provenance event for a product | Free | POST /api/v1/supply-chain/provenance/log | custom |
| Verify Authenticity | Verify the complete history and authenticity of a product | Free | POST /api/v1/supply-chain/verify | custom |
| Transfer Custody | Transfer chain-of-custody to a new holder | Free | POST /api/v1/supply-chain/custody/transfer | custom |
| Update Product Status | Update a tracked product's lifecycle status | Free | via capability registry | custom |
| Batch Track | Track a batch of goods in a single call | Free | via capability registry | custom |
| Buy Carbon Credits | Purchase carbon credits from verified projects | Free | POST /api/v1/energy/carbon/buy | Toucan, KlimaDAO |
| Retire Carbon | Permanently retire carbon credits | Free | POST /api/v1/energy/carbon/retire | Toucan, KlimaDAO |
| Carbon Prices | Get current carbon credit pricing | Free | GET /api/v1/energy/carbon/prices | Toucan, KlimaDAO |
| Buy Renewable Cert | Purchase a renewable energy certificate | Free | via capability registry | custom |
| Invest in Green Bond | Invest in a tokenized green bond | Pro | via capability registry | custom |
| Create / File / Settle / Cancel Policy | Insurance policy lifecycle | Free | POST /api/v1/insurance/policy/create | custom |
| Parametric Policy | Create a parametric policy with automatic oracle triggers | Pro | POST /api/v1/insurance/parametric/create | Chainlink, custom |
| Claim Auto-settle | Automatically settle an insurance claim on trigger | Pro | via capability registry | Chainlink |
| Cover Renew | Renew an insurance cover | Free | via capability registry | custom |

---

## Markets

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Create Prediction Market | Create a new prediction market | Pro | POST /api/v1/prediction/market/create | Polymarket, custom |
| Place Prediction Bet | Place a bet on a prediction market outcome | Free | POST /api/v1/prediction/market/bet | Polymarket, custom |
| Resolve Market | Resolve a market to a final outcome | Pro | via capability registry | Polymarket, custom |
| List Markets | Browse active prediction markets | Free | GET /api/v1/prediction/market/list | Polymarket, custom |
| Create Auction | Create an English, Dutch, or sealed-bid auction | Free | via capability registry | custom |
| Place Bid | Submit a bid to an auction | Free | via capability registry | custom |
| Settle Auction | Settle an auction and distribute proceeds | Free | via capability registry | custom |
| Create Fundraiser | Create a crowdfunding campaign with milestones | Free | POST /api/v1/fundraising/campaign/create | custom |
| Contribute to Campaign | Contribute to an active fundraising campaign | Free | POST /api/v1/fundraising/contribute | custom |
| Release Milestone Funds | Release funds upon milestone verification | Pro | via capability registry | custom |
| Trigger Refunds | Trigger refunds if milestones fail | Pro | via capability registry | custom |
| Create Security | Create a tokenized security | Enterprise | POST /api/v1/securities/create | ERC-3643 |
| List / Buy / Sell Security | Security token trading | Enterprise | via capability registry | ERC-3643 |
| List Marketplace Item | List an item for sale on the marketplace | Free | POST /api/v1/marketplace/list | custom |
| Buy Marketplace Item | Purchase a marketplace listing | Free | POST /api/v1/marketplace/buy | custom |
| Cancel Listing | Cancel an active listing | Free | via capability registry | custom |
| Subscribe | Subscribe to a service plan | Free | POST /api/v1/subscriptions/subscribe | custom |
| Create / Cancel Subscription Plan | Manage subscription plans | Pro | via capability registry | custom |
| Earn / Redeem Loyalty | Loyalty points lifecycle | Free | POST /api/v1/loyalty/earn | custom |
| Track Cashback | Track spending for cashback rewards | Free | POST /api/v1/cashback/track | custom |
| Claim Cashback | Claim accrued cashback | Free | via capability registry | custom |
| Brand Campaign | Create a brand reward campaign | Enterprise | POST /api/v1/brand/campaign/create | custom |
| Distribute Brand Reward | Distribute a targeted brand reward | Enterprise | via capability registry | custom |

---

## Gaming

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Register Game | Register a game and its on-chain assets | Free | POST /api/v1/gaming/register | ERC-721, ERC-1155 |
| Approve Game | Approve a registered game for listing | Pro | via capability registry | custom |
| Mint Game Asset | Mint an in-game asset NFT | Free | via capability registry | ERC-721, ERC-1155 |
| Transfer Game Asset | Transfer an in-game asset | Free | via capability registry | ERC-721, ERC-1155 |
| Tournament Enter | Enter an on-chain tournament | Free | via capability registry | custom |
| Game Item Trade | Trade game items in a secondary marketplace | Free | via capability registry | custom |
| Achievement Attest | Attest an in-game achievement on-chain | Free | via capability registry | EAS |

---

## Infrastructure

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Register AI Agent | Register an AI agent with model and capabilities | Pro | POST /api/v1/ai/agent/register | custom |
| Trade AI Model | Buy or sell an AI model NFT | Pro | POST /api/v1/ai/model/trade | ERC-721, custom |
| Sell Training Data | List a tokenized training dataset for sale | Pro | via capability registry | custom |
| Grant IP License | Grant an IP license to another party | Pro | via capability registry | custom |

---

## Portfolio & Analytics

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Dashboard | Get a complete dashboard for a wallet address | Free | GET /api/v1/dashboard/{address} | custom |
| Complete Portfolio | Aggregated portfolio view across all protocols | Free | GET /api/v1/portfolio/complete/{wallet} | Protocol Abstraction Layer |
| Open Positions | View all open DeFi positions for a wallet | Free | GET /api/v1/portfolio/positions/{wallet} | Protocol Abstraction Layer |
| Transaction History | Full transaction history for a wallet | Free | GET /api/v1/portfolio/history/{wallet} | Protocol Abstraction Layer |
| Oracle Price | Get the current price for a trading pair | Free | GET /api/v1/oracle/price/{pair} | Chainlink, Pyth, Band |
| Social Feed | View the activity feed for a wallet | Free | GET /api/v1/social/feed/{wallet} | custom |

---

## Intent Resolution

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Resolve Intent | Parse a natural-language intent into an execution plan | Free | POST /api/v1/intent/resolve | Intent Resolver |
| Execute Intent | Execute a previously resolved intent plan | Free | POST /api/v1/intent/execute | Intent Resolver |
| Intent Summary | Get the summary and status of an intent plan | Free | GET /api/v1/intent/summary/{plan_id} | Intent Resolver |

---

## Cross-Cutting

| Capability | Description | Tier | Gateway Endpoint | Protocols |
|---|---|---|---|---|
| Batch Dispatch | Execute multiple API calls in a single round trip | Free | POST /api/v1/batch | custom |
| Event Stream | Server-Sent Events for live updates | Free | GET /api/v1/events/stream | SSE |
| Capability Invoke | Data-driven dispatch to any catalogued capability | Free | POST /api/v1/capabilities/{id}/invoke | registry |
