# The Matrix — Complete Capability Map

Every Web3 capability accessible through the gateway, organized by category.

State-modifying capabilities below are signed by the platform, which pays their gas within the operator's sponsorship policy (`runtime/blockchain/sponsorship.py`). An action allowlist, when the policy sets one, binds the platform's signature with or without a daily cap: an operation not on the list is refused, and so is an app-signed user operation sent to `/api/v1/paymaster/sign`. A per-identity daily cap, when the policy sets one, also refuses an operation past the cap or not attributable to a signed-in identity, rather than charging it to the user. With neither set, the platform signs a capability's transaction without a limit. The attestation capabilities (`create_attestation`, `batch_attest`, `revoke_attestation`) are refused at every door, whoever asks, and are metered, as `attestation.<method>`, only where the platform's own code calls them in process: the platform's key signs no attestation a request composes and revokes none a request names. 10 actions of Neo's blockchain tools `agent_identity`, `identity`, `crossborder_payment`, `gaming`, `insurance`, `ip_royalties`, `securities` and `supply_chain` are metered the same way, each under its own name; the `eas` tool's `attest`, `batch_attest` and `revoke` are refused. The writes listed in `UNMETERED_PLATFORM_OPERATIONS` are the platform's own records, signed with the platform key with no policy check: the service dispatcher's record of each state-modifying action it completes, `convert_contract`'s record of a contract it deployed with `conversion.auto_deploy` on, and the real-estate routes' records with `services.real_estate.enabled` set; the list also holds `GasSponsor.sponsor_transaction`, which nothing calls. [`docs/blockchain.md`](blockchain.md#signed-with-the-platform-key-with-no-policy-check) lists every path by file and function. Read-only capabilities don't touch a chain. Some operations carry a platform fee; see **Fees** in `docs/blockchain.md`. Every capability in the catalog is free tier (its `min_tier` is `free`), so the tables carry no tier column.

---

## Capability Catalog

The canonical inventory lives in [`runtime/capabilities/catalog.py`](../runtime/capabilities/catalog.py). It is the single source of truth that backs Trinity's `platform_action` tool, the gateway REST endpoints, the iOS extensions registry, and this document.

- **195 capabilities** across **20 categories**, backed by **43 services** in `runtime/blockchain/services/`. The catalog declares a twenty-first category, Security & Wallets, that holds none.
- Every capability has an `id`, `category`, `subcategory`, `service`, `method`, `action`, `params_schema`, `min_tier` (the field takes `free`, `pro` or `enterprise`, and is `free` for every capability), `uses_paymaster` flag, `protocol` tag, and `available` flag.
- Capabilities marked `available: false` are catalogued but still awaiting backend or contract deployment — they appear in the API with `"available": false` so clients can feature-flag them, and `POST /api/v1/capabilities/{id}/invoke` does not run one: it answers `503` with `"error": "unavailable"`, whoever asks. `/bridge/v1/action` and the chat agents' tools still dispatch one for a caller they otherwise allow. In the tables below, "via capability registry" names the catalog entry.
- A row marked **operator key only** is refused to a user session, and to chat acting for one, at every door a session reaches: the platform's wallet or a platform credential would sign, pay, publish or authorise what the request names, or the platform's server would send, with a platform credential, a request whose address, method, headers, query names or body the request writes, by the row's own method or by the method it hands the call to (the row says which). Transfer Stablecoin's dedicated route is one a session may not reach, and its operation is refused to a session at every dispatcher with it. A row marked **a session names only its own address** is kept for a session and must name the address it is bound to. The lists are in `runtime/access_policy.py` (`REFUSED_TO_A_SESSION`, `HANDS_THE_CALL_TO`, `BOUND_TO_THE_CALLER`) and `gateway/session_routes.py`, and `tests/test_no_session_has_the_platform_act_on_what_it_names.py` derives the three tables from the source, through the shapes it names, and reads what rides in each request the services layer sends. The generic oracle request (`oracle_request`, no row of its own) answers a session a price, a weather reading or randomness only, and any other value of its type, of any type, is refused (`HELD_FOR_A_SESSION`).

Discover and invoke them over HTTP:

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/v1/capabilities` | List every capability. Filters: `?category=defi`, `?min_tier=pro`, `?available=1` |
| `GET`  | `/api/v1/capabilities/categories` | List the 21 declared categories with counts (Security & Wallets has 0) |
| `GET`  | `/api/v1/capabilities/{id}` | Return the full descriptor for one capability |
| `POST` | `/api/v1/capabilities/{id}/invoke` | Execute a capability. Body: `{"params": {...}}` matching the capability's `params_schema` |

The sections below organise every capability by its high-level category. Older convenience endpoints remain in place for backwards compatibility — the capability registry is additive, not a replacement.

---

## Smart Contracts

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Convert Contract | Convert structured pseudocode, Solidity or Vyper into Solidity | POST /api/v1/contracts/convert | Solidity, Vyper |
| ~~Deploy Contract~~ **NOT AVAILABLE** | The route answers 501 on every request: nothing in the platform deploys a contract. Use `POST /api/v1/contracts/convert` to generate Solidity and deploy it with your own tooling and signer. | POST /api/v1/contracts/deploy → 501 | — |
| Quote Conversion Fee | Quote the conversion tier fee for a contract's size and complexity (capability id `estimate_contract_cost`); a quote only, not collected, and not a gas or deployment estimate | via capability registry | — |
| List Contract Templates | Browse built-in templates | via capability registry | — |

---

## DeFi

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Token Swap | Swap one token for another through the DEX service's in-memory pools, on the best of the direct and bridge-token routes | POST /api/v1/dex/swap | The service's own pools (no Uniswap, Curve or Balancer integration) |
| Swap Route | Get the optimal swap route across DEXs | POST /api/v1/defi/swap/route | Uniswap V3, Curve, 1inch |
| Swap Execute | Execute a pre-computed swap route | POST /api/v1/defi/swap/execute | Uniswap V3, Curve, 1inch |
| Liquidity Add | Add liquidity to one of the DEX service's in-memory pools | POST /api/v1/dex/liquidity/add | The service's own pools (no Uniswap or Curve integration) |
| Create Loan | Create a collateralised DeFi loan | POST /api/v1/defi/loan/create | Aave V3, Compound V3 |
| Repay Loan | Repay an outstanding DeFi loan | POST /api/v1/defi/loan/repay | Aave V3, Compound V3 |

---

## DeFi (Advanced)

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Place Limit Order | Submit a limit order to the orderbook DEX | via capability registry | custom orderbook |
| Cancel Limit Order | Cancel a resting limit order | via capability registry | custom orderbook |
| Pyth Pull Price | Pull a Pyth price update on demand | via capability registry | Pyth |

---

## Cross-chain / Bridging

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Bridge Quote | Get a cross-chain bridge quote | POST /api/v1/defi/bridge/quote | Stargate, Hop, Across |
| Bridge Execute | Execute a cross-chain bridge transfer | POST /api/v1/defi/bridge/execute | Stargate, Hop, Across |
| Bridge via CCIP | Transfer the platform's own tokens using Chainlink CCIP; it carries no message, and a request that brings one is refused | via capability registry · operator key only | Chainlink CCIP |
| ~~Cross-chain Message~~ **REFUSED** | The receiving chain reads the platform's wallet as the sender of a message the request wrote. Refused in the service and at every door. | via capability registry → refused | CCIP |
| ~~Bridge via Hyperlane~~ **REFUSED** | A Mailbox.dispatch of the request's message body from the platform's wallet; it moved no token. Refused in the service and at every door. | via capability registry → refused | Hyperlane |
| ~~Bridge via Wormhole~~ **REFUSED** | A publishMessage of the request's payload with the platform as emitter; it moved no token. Refused in the service and at every door. | via capability registry → refused | Wormhole |
| ~~Bridge via Axelar~~ **REFUSED** | A callContract with the request's payload to the request's contract, from the platform's wallet; it moved no token. Refused in the service and at every door. | via capability registry → refused | Axelar |
| Bridge via Stargate | Transfer stablecoins using Stargate | via capability registry · operator key only | Stargate |
| Query Remote Chain | Read state from a foreign chain | via capability registry | CCIP |

---

## Staking & Restaking

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Stake | Stake tokens for yield | POST /api/v1/staking/stake | native |
| Unstake | Unstake tokens and claim rewards | POST /api/v1/staking/unstake | native |
| Claim Staking Rewards | Claim accrued staking rewards | via capability registry | native |
| Get Staking Position | View current staking position | via capability registry | native |
| Liquid Stake (Lido) | Obtain stETH by liquid-staking ETH with Lido | via capability registry · operator key only | Lido |
| Liquid Stake (Rocket Pool) | Obtain rETH by liquid-staking with Rocket Pool | via capability registry | Rocket Pool |
| Restake on EigenLayer | Restake LSTs to EigenLayer AVSs | via capability registry · operator key only | EigenLayer |
| Restake on Symbiotic | Restake via Symbiotic | via capability registry · operator key only | Symbiotic |
| Restake on Karak | Restake via Karak | via capability registry · operator key only | Karak |
| Delegate to Operator | Delegate restaked capital to an AVS operator | via capability registry · operator key only | EigenLayer |
| Withdraw Restake | Initiate withdrawal from restaking | via capability registry · operator key only | EigenLayer, Symbiotic, Karak |

---

## NFTs

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Mint NFT | Mint a single NFT with metadata | POST /api/v1/nft/mint | ERC-721, ERC-1155 |
| Create Collection | Create an NFT collection with royalty settings | POST /api/v1/nft/collection/create | ERC-721 |
| Transfer NFT | Transfer an NFT to another owner | via capability registry | ERC-721, ERC-1155 |
| List NFT for Sale | List an NFT on the marketplace | via capability registry | ERC-721 |
| Buy NFT | Purchase a listed NFT | via capability registry | ERC-721 |
| Batch Mint | Mint multiple NFTs in a single transaction | POST /api/v1/nft/batch-mint | ERC-721, ERC-1155 |
| Fractionalize NFT | Split an NFT into fungible fractions for co-ownership | POST /api/v1/nft/fractionalize | Fractional, Tessera |
| Rent NFT | Rent an NFT for a specified duration | POST /api/v1/nft/rent | ERC-4907 |
| Royalty Claim | Claim accumulated royalties from secondary sales | POST /api/v1/nft/royalty/claim | ERC-2981 |
| Configure NFT Royalty | Set or update the royalty for a collection | via capability registry | ERC-2981 |
| Dynamic Update | Update dynamic NFT metadata | via capability registry | ERC-721 |
| Estimate NFT Value | Get an AI-derived value estimate | via capability registry | custom |
| Get NFT Rarity | Compute rarity rank for a token | via capability registry | custom |
| Set / Check NFT Rights | Encode and query programmable rights | via capability registry | custom |
| Bridge NFT | Bridge an NFT to another chain | POST /api/v1/nft/bridge | LayerZero, Wormhole |
| IP Registration | Register intellectual property on-chain | POST /api/v1/ip/register | EAS, custom |
| Soulbound Mint | Mint a non-transferable soulbound token | via capability registry | ERC-5192 |

---

## NFT Finance

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Borrow Against NFT | Take a loan collateralised by an NFT | via capability registry · operator key only | BendDAO, NFTfi |
| Liquidate NFT Loan | Liquidate a defaulted NFT loan | via capability registry · operator key only | BendDAO, NFTfi |
| Breed NFT | Breed two NFTs to produce a new one; the call goes from the platform's wallet to the breeding contract the request names | via capability registry · operator key only | custom |
| Create Token-bound Account | Deploy an ERC-6551 account for a token | via capability registry · operator key only | ERC-6551 |
| ~~Execute As TBA~~ **REFUSED** | Signed the request's call (a delegatecall if asked) from the platform's wallet, with the platform's ETH, to whatever contract the request named. Refused in the service and at every door. | via capability registry → refused | ERC-6551 |

---

## Identity

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Create DID | Create a decentralised identity | POST /api/v1/identity/create | DID:matrix |
| Create DID (expanded) | Create a DID with extended method support | POST /api/v1/identity/did/create | DID:matrix, DID:ethr |
| Update DID | Update a DID document | via capability registry | DID:matrix |
| Deactivate DID | Deactivate a DID | via capability registry | DID:matrix |
| Issue Credential | Issue a verifiable credential to a subject | POST /api/v1/identity/credential/issue | W3C VC, EAS |
| Verify Credential | Verify the validity of a credential | POST /api/v1/identity/credential/verify | W3C VC, EAS |
| Reputation Query | Query aggregated on-chain reputation for an agent | via capability registry | custom |
| Start KYC | Start a KYC session with the configured provider | via capability registry · operator key only | Sumsub, Persona |
| Check AML Risk | Screen an address for AML risk | via capability registry · operator key only | Sumsub, Persona |
| ~~Issue KYC Credential~~ **REFUSED** | The verification it attested was read from the request. Refused at every door until the service fetches the provider's own result. | via capability registry → refused | W3C VC |
| Register / Update / Deregister Agent | Manage an AI agent identity | via capability registry | custom |
| ~~Create / Revoke / Batch Attest~~ **REFUSED** | The platform's key signs no attestation a request composes and revokes none a request names; it attests an action when it executes it. Refused at every door. | via capability registry → refused | EAS |
| Attestation Verify | Verify an on-chain attestation by UID | GET /api/v1/attestation/verify/{uid} | EAS |
| ZK Proof | Generate a zero-knowledge proof for a claim | POST /api/v1/identity/zk-proof/generate | Semaphore, zkSNARK |

---

## Governance

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Create DAO | Create a new DAO with on-chain governance | POST /api/v1/dao/create | Governor, custom |
| Join DAO | Join an existing DAO | via capability registry | Governor |
| Leave DAO | Leave a DAO | via capability registry | Governor |
| Create Proposal | Submit a governance proposal | POST /api/v1/governance/proposal/create | Governor, Tally |
| Vote | Cast a vote on a governance proposal | POST /api/v1/governance/vote | Governor, Tally |
| Finalize Proposal | Execute a passed proposal | via capability registry | Governor |
| Snapshot Vote | Cast a gasless off-chain vote | POST /api/v1/governance/snapshot/vote | Snapshot |
| Timelock Queue | Queue an action through a timelock | via capability registry | OZ Timelock |
| Multisig Propose | Submit a proposal to a multisig wallet | via capability registry | Safe (Gnosis) |
| ~~Multisig Approve~~ **NOT AVAILABLE** | The route answers 501 on every request: the governance service approves a multisig, not a proposal within one, so per-proposal approval is unbuilt. | POST /api/v1/governance/multisig/approve → 501 | — |
| Parameter Change | Mutate a governed protocol parameter | via capability registry | Governor |
| Vote-Escrow Lock | Lock tokens in a veToken gauge | via capability registry | Curve, Balancer |
| Quadratic Vote | Cast a quadratic vote | via capability registry | Gitcoin, custom |
| ~~Submit RetroPGF~~ **REFUSED** | Attested, with the platform's key, an application and recipient the request wrote. Refused in the service and at every door. | via capability registry → refused | Optimism RetroPGF |
| Place Gauge Bribe | Bribe a gauge for vote weight | via capability registry · operator key only | Convex, Hidden Hand |
| Delegate Voting Power | Delegate voting to another address | via capability registry · operator key only | Governor |
| File / Submit Evidence / Resolve / Appeal Dispute | Dispute resolution lifecycle | POST /api/v1/dispute/file | custom |
| Arbitration Request | Request third-party arbitration | via capability registry | custom |

---

## Social

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Create Social Profile | Create an on-chain social profile | POST /api/v1/social/profile | Lens, custom |
| Update Social Profile | Update profile metadata | via capability registry | Lens, custom |
| Create Post | Publish a post to the decentralised social feed | POST /api/v1/social/post | Lens, Farcaster |
| ~~Social Gate~~ **NOT AVAILABLE** | The route answers 501 on every request: only token-balance gating exists (`social.create_token_gate`, via the capability registry); arbitrary gate types are unbuilt. | POST /api/v1/social/gate/create → 501 | — |
| Create Community | Launch a token-gated community | POST /api/v1/social/community/create | custom |
| ~~Send Message (XMTP)~~ **NOT AVAILABLE** | The route answers 501 on every request: no message-sending implementation exists, and the route is not pointed at the method that reports delivery without delivering. | POST /api/v1/social/message/send → 501 | — |
| Encrypted Message | Encrypt a payload for a recipient | via capability registry | XMTP |
| Create Lens Profile | Mint a profile on the Lens Protocol | via capability registry · a session names only its own address | Lens |
| Publish Farcaster Cast | Post a cast on Farcaster | via capability registry · operator key only | Farcaster |
| Subscribe to Push | Subscribe to Push Protocol notification channels | via capability registry · a session names only its own address | Push Protocol |
| Launch Social Token | Launch a personal social token | via capability registry · a session names only its own address | custom |
| Launch Creator Coin | Launch a creator coin with a bonding curve | via capability registry · a session names only its own address | custom |

---

## Creator Economy

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Monetize Content | Enable paywalls, tips, and subscriptions on content | via capability registry | custom |
| Mint Sound.xyz Drop | Release a music drop on Sound.xyz | via capability registry · operator key only | Sound.xyz |
| Publish Mirror Post | Publish a long-form post on Mirror | via capability registry · operator key only | Mirror |
| Publish Paragraph Post | Publish a Paragraph newsletter | via capability registry · operator key only | Paragraph |
| Register IP | Register intellectual property on-chain | via capability registry | EAS |
| Transfer IP | Transfer IP ownership | via capability registry | custom |
| License IP | Grant a license for intellectual property | via capability registry | custom |
| Execute Agreement | Execute a legally binding on-chain agreement | via capability registry | custom |

---

## Payments

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Create Payment | Create a one-time x402 payment record, pending until it is authorised, with the agent's spend limits checked: recorded, not settled — no value moves | POST /api/v1/payments/create | x402 |
| Complete Payment | Close an authorised x402 payment's record: recorded, not settled — no value moves (authorising and refunding are service methods, not registry capabilities) | via capability registry | x402 |
| Send Payment | Record a cross-border payment to a wallet, with a flat 0.5% fee: recorded, not settled — no value moves | via capability registry | none (a record) |
| Transfer Stablecoin | Record a stablecoin transfer on the service's in-memory ledger (tiered platform fee, 0.01%–0.1% by default): recorded, not settled — no value moves; the sender is the one the request names. The ledger starts empty and only a test helper funds it, so a transfer is refused for insufficient balance | via capability registry · operator key only. POST /api/v1/stablecoin/transfer records nothing, whatever the body, and admits the operator key only: a caller it admits who sends the four fields its handler requires, with an amount that is a number between -1e308 and 1e308, is answered 400, because its handler passes `sender` and `recipient` and the service's transfer takes `from_addr` and `to_addr` | USDC, USDT, DAI |
| Cross-Border Payment | Record a cross-border payment with FX conversion and a flat 0.5% fee: recorded, not settled — no value moves, and no payment provider is called | POST /api/v1/crossborder/send | none (a record) |
| Open / Route / Close Channel | State-channel lifecycle for off-chain micropayments | via capability registry · operator key only | state channels |

---

## Privacy & ZK

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| ~~Data Deletion~~ **NOT AVAILABLE** | No verified erasure path exists. The endpoint answers 501; nothing is queued and no deletion is ever reported (NEW-38). | POST /api/v1/privacy/delete → 501 | — |
| ~~Private Transfer~~ **REMOVED** | Moved no balance, hardcoded `"shielded": true`, echoed amounts in plaintext (NEW-36). Removed, not gated — Railgun/Aztec were never integrated. | — | — |
| ~~Stealth Address~~ **REMOVED** | Returned `0x` + random hex — an address with no key anyone holds; funds sent there were unrecoverable. Declared ERC-5564, implemented nothing. | — | — |
| ZK Proof Generate | Generate a zero-knowledge proof | via capability registry | Semaphore, zkSNARK |
| MPC Sign | Threshold-sign a transaction using an MPC quorum | via capability registry · operator key only | MPC threshold sig |
| ~~Social Recovery~~ **REFUSED** | Sent `initiateRecovery(account, newOwner)` from the platform's wallet with both addresses the request's, so the platform's standing with the recovery module, not the account holder's, authorized handing the account to a new owner. Refused in the service and at every door. | via capability registry → refused | custom |
| ~~Session Key~~ **REFUSED** | Sent `registerSessionKey(account, key, validUntil)` from the platform's wallet with all three the request's, so the platform's standing with the module authorized a key of the request's choosing on an account of its choosing. Refused in the service and at every door. | via capability registry → refused | ERC-4337 session keys |

---

## Oracles & Data

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Oracle Price Query | Get the current price for a trading pair | GET /api/v1/oracle/price/{pair} | Chainlink, Pyth, Band |
| Oracle VRF | Request verifiable randomness | via capability registry | Chainlink VRF |
| Weather Oracle | Query weather data for an address | via capability registry | custom |
| Pyth Pull | Pull a Pyth price update on demand | via capability registry | Pyth |
| RedStone Request | Fetch a signed RedStone data package; with the platform's API key, at the data-service path the request names | via capability registry · operator key only | RedStone |
| API3 Query | Query a first-party API3 dAPI | via capability registry | API3 |
| Register Keeper Job | Register a Chainlink Keeper / upkeep job | via capability registry · operator key only | Chainlink Keepers |

---

## Storage

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Decentralized Store | Store data on a decentralised storage network; hands the call to Filecoin Store | POST /api/v1/compute/store · operator key only | IPFS, Arweave, Filecoin |
| IPFS Pin | Pin content on IPFS for persistence; hands the call to Filecoin Store | POST /api/v1/compute/ipfs/pin · operator key only | IPFS |
| ~~Arweave Store~~ **NOT AVAILABLE** | The route answers 501 on every request: the platform has no Arweave upload client, and nothing is stored by a call. | POST /api/v1/compute/arweave/store → 501 | — |
| Filecoin Store | Make a Filecoin storage deal | via capability registry · operator key only | Filecoin |
| Ceramic Stream | Create a mutable Ceramic stream | via capability registry · operator key only | Ceramic |
| OrbitDB Write | Write to an OrbitDB peer-to-peer database | via capability registry · operator key only | OrbitDB |

---

## Compute & DePIN

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Submit Compute Job | Submit a decentralised compute job | via capability registry · operator key only | Akash, Gensyn, Render |
| Rent DePIN Device | Rent a device on a DePIN network | via capability registry · operator key only | custom |
| Claim Compute Reward | Claim rewards for running compute workers | via capability registry · operator key only | custom |
| Legacy Compute Submit | Submit a job through the legacy compute pipeline; hands the call to Submit Compute Job | via capability registry · operator key only | custom |

---

## Real-World Assets

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Tokenize Asset | Tokenize a real-world asset (property, vehicle, etc.) | POST /api/v1/rwa/tokenize | ERC-3643, custom |
| Transfer RWA Ownership | Transfer ownership of a tokenized asset | via capability registry | ERC-3643 |
| Fractional Buy | Purchase fractions of a tokenized RWA | via capability registry | ERC-3643, custom |
| RWA Income Claim | Claim income streams from a tokenized RWA | via capability registry | ERC-3643 |
| List Assets | Browse available tokenized real-world assets | GET /api/v1/rwa/listings | custom |
| Register Product | Register a product on-chain for tracking | POST /api/v1/supply-chain/register | custom |
| Log Provenance | Log a provenance event for a product | POST /api/v1/supply-chain/provenance/log | custom |
| Verify Authenticity | Verify the complete history and authenticity of a product | POST /api/v1/supply-chain/verify | custom |
| Transfer Custody | Transfer chain-of-custody to a new holder | POST /api/v1/supply-chain/custody/transfer | custom |
| Update Product Status | Update a tracked product's lifecycle status | via capability registry | custom |
| Batch Track | Track a batch of goods in a single call | via capability registry | custom |
| Buy Carbon Credits | Purchase carbon credits from verified projects | via capability registry | Toucan, KlimaDAO |
| Retire Carbon | Permanently retire carbon credits | via capability registry | Toucan, KlimaDAO |
| Buy Renewable Cert | Purchase a renewable energy certificate | via capability registry | custom |
| Invest in Green Bond | Invest in a tokenized green bond | via capability registry | custom |
| Create / File / Settle / Cancel Policy | Insurance policy lifecycle | POST /api/v1/insurance/policy/create | custom |
| Parametric Policy | Create a parametric policy with automatic oracle triggers | POST /api/v1/insurance/parametric/create | Chainlink, custom |
| Claim Auto-settle | Automatically settle an insurance claim on trigger | via capability registry | Chainlink |
| Cover Renew | Renew an insurance cover | via capability registry | custom |

---

## Markets

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Create Prediction Market | Create a new prediction market | via capability registry | Polymarket, custom |
| Place Prediction Bet | Place a bet on a prediction market outcome | via capability registry | Polymarket, custom |
| Resolve Market | Resolve a market to a final outcome | via capability registry | Polymarket, custom |
| Create Auction | Create an English, Dutch, or sealed-bid auction | via capability registry · operator key only | custom |
| Place Bid | Submit a bid to an auction | via capability registry | custom |
| Settle Auction | Settle an auction and distribute proceeds | via capability registry | custom |
| Create Fundraiser | Create a crowdfunding campaign with milestones | POST /api/v1/fundraising/campaign/create | custom |
| Contribute to Campaign | Contribute to an active fundraising campaign | POST /api/v1/fundraising/contribute | custom |
| Release Milestone Funds | Release funds upon milestone verification | via capability registry | custom |
| Trigger Refunds | Trigger refunds if milestones fail | via capability registry | custom |
| Create Security | Create a tokenized security | POST /api/v1/securities/create | ERC-3643 |
| List / Buy / Sell Security | Security token trading | via capability registry | ERC-3643 |
| List Marketplace Item | List an item for sale on the marketplace | POST /api/v1/marketplace/list | custom |
| Buy Marketplace Item | Purchase a marketplace listing | POST /api/v1/marketplace/buy | custom |
| Cancel Listing | Cancel an active listing | via capability registry | custom |
| Subscribe | Subscribe to a service plan | POST /api/v1/subscriptions/subscribe | custom |
| Create Subscription Plan / Cancel Subscription | Create a subscription plan, or cancel a subscriber's subscription | via capability registry | custom |
| Earn / Redeem Loyalty | Loyalty points lifecycle | POST /api/v1/loyalty/earn | custom |
| Track Cashback | Track spending for cashback rewards | POST /api/v1/cashback/track | custom |
| Claim Cashback | Claim accrued cashback | via capability registry | custom |
| Brand Campaign | Create a brand reward campaign | POST /api/v1/brand/campaign/create | custom |
| Distribute Brand Reward | Distribute a targeted brand reward | via capability registry | custom |

---

## Gaming

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Register Game | Register a game and its on-chain assets | POST /api/v1/gaming/register | ERC-721, ERC-1155 |
| Approve Game | Approve a registered game for listing | via capability registry | custom |
| Mint Game Asset | Mint an in-game asset NFT | via capability registry | ERC-721, ERC-1155 |
| Transfer Game Asset | Transfer an in-game asset | via capability registry | ERC-721, ERC-1155 |
| Tournament Enter | Enter an on-chain tournament | via capability registry | custom |
| Game Item Trade | Trade game items in a secondary marketplace | via capability registry | custom |
| Achievement Attest | Attest an in-game achievement on-chain | via capability registry | EAS |

---

## Infrastructure

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Register AI Agent | Register an AI agent with model and capabilities | via capability registry | custom |
| Trade AI Model | Buy or sell an AI model NFT | via capability registry | ERC-721, custom |
| Sell Training Data | List a tokenized training dataset for sale | via capability registry | custom |
| Grant IP License | Grant an IP license to another party | via capability registry | custom |

---

## Portfolio & Analytics

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Dashboard | Get a complete dashboard for a wallet address | GET /api/v1/dashboard/{address} | custom |
| Complete Portfolio | The wallet's native ETH balance, valued at a live ETH/USD quote (cached for 30 s). ERC-20 tokens, NFTs, DeFi, staking, streams and RWA positions are not read (listed in `not_covered`). Answers 503 when no RPC is configured, the balance read fails, or no live price exists for a non-zero balance, and 400 when `{wallet}` is not a 20-byte hex address. | GET /api/v1/portfolio/complete/{wallet} | Protocol Abstraction Layer |
| Open Positions | The same read as Complete Portfolio, projected into position groups; only the native balance is read, so DeFi, staking and other groups are always empty and listed in `not_covered`. Answers 503 and 400 on the same conditions. | GET /api/v1/portfolio/positions/{wallet} | Protocol Abstraction Layer |
| ~~Transaction History~~ **NOT AVAILABLE** | No time-series portfolio data is recorded; serving history needs an indexer that does not exist. The endpoint answers 501. | GET /api/v1/portfolio/history/{wallet} → 501 | — |
| Oracle Price | Get the current price for a trading pair | GET /api/v1/oracle/price/{pair} | Chainlink, Pyth, Band |
| Social Feed | View the activity feed for a wallet | GET /api/v1/social/feed/{wallet} | custom |

---

## Intent Resolution

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Resolve Intent | Match a keyword intent (swap, deposit, borrow, bridge, store) to a plan. Figures come from static per-protocol tables, not live quotes; the plan requires confirmation whenever its USD value is unknown. Answers 503 when the DEX, lending protocol or bridge the plan needs is not configured or failed, and 400 for input the caller got wrong. | POST /api/v1/intent/resolve | Intent Resolver |
| ~~Execute Intent~~ **NOT AVAILABLE** | Plans are not persisted, so nothing can execute one by id. The endpoint answers 501; keep the plan returned by Resolve Intent. | POST /api/v1/intent/execute → 501 | — |
| ~~Intent Summary~~ **NOT AVAILABLE** | Plans are not persisted, so there is no plan to summarise by id. The endpoint answers 501; the Resolve Intent response already carries the summary. | GET /api/v1/intent/summary/{plan_id} → 501 | — |

---

## Cross-Cutting

| Capability | Description | Gateway Endpoint | Protocols |
|---|---|---|---|
| Batch Dispatch | Execute multiple API calls in a single round trip | POST /api/v1/batch | custom |
| Event Stream | Server-Sent Events for live updates | GET /api/v1/events/stream | SSE |
| Capability Invoke | Data-driven dispatch to any catalogued capability | POST /api/v1/capabilities/{id}/invoke | registry |
