# Blockchain

## 195 Capabilities Across 20 Categories

The Matrix catalogues 195 discrete Web3 capabilities in 20 categories (`runtime/capabilities/catalog.py`), all accessible through conversation:

1. **Smart Contracts** (3) — Convert to Solidity, Quote Conversion Fee, List Contract Templates
2. **DeFi** (4) — Borrow Against Collateral, Repay Loan, Get Loan Details, Swap Tokens
3. **DeFi (Advanced)** (3) — all catalogued with `available: false`: Place Limit Order, Cancel Limit Order, Pull Pyth Price
4. **NFTs** (17) — Mint NFT, Create NFT Collection, Transfer NFT, List NFT for Sale, Buy NFT, Estimate NFT Value, Get NFT Rarity, Set NFT Rights, Check NFT Rights, Configure NFT Royalty, Fractionalize NFT, Rent NFT, Update Dynamic NFT, Batch Mint NFTs, Claim NFT Royalties, Bridge NFT, Mint Soulbound NFT
5. **NFT Finance** (5) — all catalogued with `available: false`: Borrow Against NFT, Liquidate NFT Loan, Breed NFT, Create Token-bound Account, Execute As TBA
6. **Identity** (14) — Create DID, Update DID, Deactivate DID, Issue Credential, Query Reputation, Register AI Agent, Update Agent, Deregister Agent; catalogued with `available: false`: Start KYC, Check AML Risk, Issue KYC Credential, Create Attestation, Revoke Attestation, Batch Attest
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

Refused to every caller, whoever asks, at every door that dispatches them (`REFUSED_ON_REQUEST` in `runtime/access_policy.py`): executing as a token-bound account, which signed the request's call with the platform's key and ETH; the KYC credential, whose verification came from the request; RetroPGF, which attested an application the request wrote; the cross-chain message sends over CCIP, Hyperlane, Wormhole and Axelar, whose receiving chain reads the platform's wallet as the sender of words the request wrote; social recovery and session keys, whose module call went out from the platform's wallet, so the platform's standing with the module, not the account holder's, handed the account the request named to a new owner or key; and the attestation capabilities, because the platform's key signs no attestation a request composes and revokes none a request names.

A user session — the app's own credential — and chat acting for one are refused each capability a test finds, in the shapes it reads, in which the platform's wallet or a platform credential would sign, pay, publish or authorise while the request names the payee, the account, the asset, the contract the call is sent to, the key, the digest or the content: the platform's funds sent where the request says (the restaking, NFT-lending, payment-channel, keeper, compute-reward, Stargate and CCIP token-bridge actions, a delegation, a bribe, an auction, a token-bound account), a call from the platform's wallet to a breeding contract the request names (`breed_nft`), the operator's MPC cluster signing a digest the request wrote (`mpc_sign`), a post, a cast or a stored record under the platform's own account, the platform's compute or KYC provider account, and an oracle request that would have the platform's server fetch a URL the request writes. The refusal follows the method a capability reaches, so a second name for one of those, or a method that hands the call on to one, is refused with it (`compute_job_submit`, `decentralized_store` and `ipfs_pin`). A Lens profile, a social or creator token and a Push subscription are kept for a session and must name its own address. The operator's key keeps them over `/bridge/v1/action` and Neo's `platform_action`; capability invoke runs, for any caller, only what the catalog marks available. The lists are `REFUSED_TO_A_SESSION`, `HANDS_THE_CALL_TO`, `BOUND_TO_THE_CALLER` and `HELD_FOR_A_SESSION` in `runtime/access_policy.py`, derived by `tests/test_no_session_has_the_platform_act_on_what_it_names.py` through the shapes its docstring names.

## How It Works

Users describe what they want to Trinity in plain language. Trinity translates the request into the appropriate blockchain operation. Neo executes it. If it's a first-time use or an irreversible action, Morpheus adds a note saying what it does; the note reaches the user with the result, and nothing waits for an answer to it.

## Networks

Everything runs on the one chain the operator configures (`blockchain.rpc_url`, `blockchain.chain_id`): the example config and the examples use Base Sepolia, and Base (Ethereum L2) is the intended mainnet. Nothing sends an operation, or an attestation, to another network because of its value. The cross-chain capabilities are all catalogued with `available: false`.

## Gas

When an operator configures the platform paymaster, the platform pays gas for users' operations — within the operator's sponsorship policy (`runtime/blockchain/sponsorship.py`):

- **Per-identity daily cap.** A USD amount per identity over a rolling 24 hours (`paymaster.policy.daily_cap_usd`; the example config sets 50). Past it, the platform stops sponsoring: an operation the platform would sign is refused with the reason rather than charged to the user, and a user-operation sponsorship request to `/api/v1/paymaster/sign` is declined with `403`. A deployment that sets no cap sponsors without a daily limit.
- **Action allowlist.** `paymaster.policy.allowed_actions` limits which action types are sponsored. It is checked on every `/api/v1/paymaster/sign` request (against the actions decoded from the user operation's call data), and on every platform-signed operation whenever it is configured, with or without a daily cap: an action off the list is refused, cap or no cap. A platform-signed operation is matched by its `<capability>.<method>` name (for example `daos.vote`, `stablecoins.transfer`; registry services that sign through `Web3Manager.send_transaction` use `web3.send_transaction` unless the call site names its own action). The example config's list (`transfer`, `swap`) names none of those, so under the example policy every platform-signed operation is refused.
- **Identity.** With a cap set, an operation that cannot be attributed to a signed-in identity is refused: a per-identity cap cannot meter spend it cannot attribute.
- **Attestations.** An attestation written because a user asked for it is metered like any platform-signed operation, under its `<capability>.<method>` name: 10 actions of Neo's blockchain tools `agent_identity`, `identity`, `crossborder_payment`, `gaming`, `insurance`, `ip_royalties`, `securities` and `supply_chain`, each under the name the table below gives it. The `create_attestation`, `batch_attest` and `revoke_attestation` capabilities, and the `eas` tool's `attest`, `batch_attest` and `revoke`, are refused at every door, whoever asks (`REFUSED_ON_REQUEST` in `runtime/access_policy.py`, and `runtime/blockchain/eas_manager.py`), and the capabilities are metered, as `attestation.attest`, `attestation.batch_attest` and `attestation.revoke`, only where the platform's own code calls them in process: the platform's key signs no attestation a request composes and revokes none a request names. An attestation whose schema (`blockchain.eas_schema`, or the component's `blockchain.schemas.<component>`) is not a well-formed bytes32 UID is refused before any of this.
- **Not metered.** The writes listed in `UNMETERED_PLATFORM_OPERATIONS` are signed with the platform key with no policy check (no allowlist and no daily cap) and are not counted against any cap. They are the platform's own records: the service dispatcher's record of each state-modifying action it completes; `convert_contract`'s record of a contract it deployed, with `conversion.auto_deploy` on; and the real-estate routes' records, with `services.real_estate.enabled` set. The list also holds `gas_sponsor.sponsor`, `GasSponsor.sponsor_transaction`, which signs whatever transaction it is handed; nothing calls it. No attestation a caller asks for is on the list. The tables below give every path.
- **No paymaster configured, no sponsorship.** The platform pays no gas there; an app-signed user operation pays its own.

What a particular deployment provides is returned by the dashboard, payments and cross-border tools as `gas_policy`, derived from the same configuration the signer reads.

### Signed with the platform key, with no policy check

Every call into an EAS signer or `GasSponsor.sponsor_transaction` in `runtime/` and `gateway/` is listed in this section or the next, found from the code; `tests/test_unmetered_signing_paths_are_documented.py` fails if one is missing. Under a policy that allows nothing and caps at zero, it drives the service dispatcher's record and the real-estate queue and sees them signed, drives Neo's tool actions and sees none of them signed, and checks the other rows by reading the code; `tests/test_gas_sponsorship_is_described_as_it_signs.py` drives `revoke_attestation` and a time-critical `create_attestation` and sees both refused.

| Path | When it signs | Exemption | Code |
|---|---|---|---|
| The service dispatcher's record of a state-modifying action it completes | Queued on the attestation service of the dispatcher's service registry, as a platform record (`AttestationService.attest`), when `blockchain.eas_schema` is a well-formed bytes32 UID; otherwise the service refuses it and the dispatcher logs the refusal. When 50 have gathered, each is signed and sent as its own transaction. Nothing sends a shorter queue, and what is queued is lost if the process exits first. | `eas.attest` | `runtime/blockchain/services/service_dispatcher.py` `_attest_action`; `runtime/blockchain/services/attestation/service.py` `_attest`; `runtime/blockchain/services/attestation/batch_processor.py` `_submit_batch` |
| `convert_contract`, with `conversion.auto_deploy` on | Once the chain confirms a contract the pipeline deployed. The deployment itself is signed under the policy (`contract_conversion.deploy`), so a policy that refuses it leaves nothing to attest. | `eas.attest` | `runtime/blockchain/services/contract_conversion/service.py` `convert` |
| The real-estate routes (`/api/v1/realestate/…`), with `services.real_estate.enabled` set and a `document_verification` schema registered | A document upload, a buyer verification that passes, a purchase and a confirmed settlement each queue an attestation, with the seller's or the buyer's wallet as recipient, on the real-estate service's own queue. When 50 have gathered, each is signed and sent as its own transaction. | `eas.attest` | `runtime/blockchain/services/real_estate/service.py` `_attest` |

These call the same code and sign nothing today, each for the reason its line gives. The ones that attest through `AttestationService.attest` resolve their schema first, `primary` from `blockchain.eas_schema` and a component's name from `blockchain.schemas.<component>`, and when that is not a well-formed bytes32 UID the attestation is refused and nothing is queued. Under the shipped example config, `primary` is refused and the `payments` component's schema resolves:

- Neo's tool `eas` refuses `attest`, `batch_attest` and `revoke` (`runtime/blockchain/eas_manager.py` `_attest`, `_batch_attest`, `_revoke`), and `agent_identity` refuses `attest_action` (`runtime/blockchain/agent_identity.py` `_attest_action`), before anything is signed: each answers with a refusal, not an attestation, because the platform attests what it executes, never a statement a request composes.
- `gas_sponsor.sponsor` is `GasSponsor.sponsor_transaction` (`runtime/blockchain/gas_sponsor.py`), which is not an attestation: it signs and sends whatever transaction it is handed. 14 services construct a `GasSponsor`; nothing calls the method.
- `NeoSafeRouter` queues an attestation for a fee it records, under `primary`, on an attestation service of its own, and attests revenue it sends once the transfer is mined through `EASClient.attest`, which signs at once under `blockchain.eas_schema` rather than queuing and skips the write while EAS is not configured (`runtime/blockchain/services/neosafe.py` `_attest_fee`, `route_revenue`); nothing in the gateway calls the router.
- A cross-border payment's attestation, under `primary` (`runtime/blockchain/services/cross_border/service.py` `_attest_payment`), is queued on a new attestation service made for that one call, whose queue never reaches 50, so it is dropped unsigned.
- An insurance claim's attestation, under `primary` (`runtime/blockchain/services/insurance/claims_processor.py` `_attest_claim`), is queued the same way and dropped the same way.
- An x402 limit change's attestation, under the `payments` component's schema, `blockchain.schemas.payments` (`runtime/blockchain/services/x402_payments/limit_updater.py` `_attest_limit_change`), is queued the same way and dropped the same way; the example config's `eas_schema` placeholder does not stop it.
- An IP rights reversion, under `primary` (`runtime/blockchain/services/ip_royalties/royalty_enforcement.py` `_attest_rights_reversion`), would be signed at once as time-critical, but it is reached only from `IPRoyaltyEnforcement.process_usage`, which nothing calls.
- An NFT royalty sale, under `primary` (`runtime/blockchain/services/nft_services/royalty_enforcement.py` `process_sale`), is attested only when the NFT service is given an attestation service, and the service registry builds it without one.

Outside the gateway, `contracts/deploy.py`, run by hand, deploys `MatrixAttestation` with `blockchain.paymaster_private_key`; the policy does not apply to it.

### Attestations a caller asks for, metered by the policy

Each of these is signed with the platform key through the sponsorship policy under the name in the second column, so the allowlist, the per-identity cap and the identity requirement apply, and a refusal comes back before anything is signed. The attestation capabilities (`create_attestation`, `batch_attest`, `revoke_attestation`, through `attestation.attest_for_caller`, `batch_attest` and `revoke`) and the `eas` tool's `attest`, `batch_attest` and `revoke` are not among them: every door refuses them, whoever asks, before anything is built.

| Path | Metered as | When it signs | Code |
|---|---|---|---|
| Neo's tool `agent_identity`: `register` | `agent_identity.register` | At once, for one of the platform's own three agents. | `runtime/blockchain/agent_identity.py` `_register` |
| Neo's tool `identity`: `register` | `identity.register` | At once, with the address the call names as recipient: the caller's own or none, as the seam refuses any other. | `runtime/blockchain/identity.py` `_register` |
| Neo's tool `crossborder_payment`: `send` | `crossborder.send` | At once, naming no recipient (the zero address); no transfer is made. | `runtime/blockchain/crossborder.py` `_send` |
| Neo's tool `gaming`: `record_achievement` | `gaming.record_achievement` | At once, with the player as recipient: the caller's own address or none, as the seam refuses any other. | `runtime/blockchain/gaming.py` `_record_achievement` |
| Neo's tool `insurance`: `create_policy`, `file_claim` | `insurance.create_policy`, `insurance.file_claim` | At once. | `runtime/blockchain/insurance.py` `_create_policy`, `_file_claim` |
| Neo's tool `ip_royalties`: `register_ip` | `ip_royalties.register_ip` | At once, with the owner as recipient: the caller's own address or none, as the seam refuses any other. | `runtime/blockchain/ip_royalties.py` `_register_ip` |
| Neo's tool `securities`: `whitelist_investor` | `securities.whitelist` | At once, with the investor as recipient: the caller's own address or none, as the seam refuses any other. | `runtime/blockchain/securities.py` `_whitelist` |
| Neo's tool `supply_chain`: `create_record`, `update_status` | `supply_chain.create_record`, `supply_chain.update_status` | At once. | `runtime/blockchain/supply_chain.py` `_create_record`, `_update_status` |

The README's section on the Web3 capability surface says the same.

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
| Contract conversion tier (`estimate_contract_cost`, and the `tier` in a conversion result) | 0.01 ETH below 100 non-blank lines and 0.05 ETH from 100, while the complexity score (the non-blank line count plus weights for patterns such as `assembly` or `delegatecall`) stays under 200; at 200 or more the quote is "negotiated". The 0.1 ETH tier for 500 lines and more is reached only where an operator raises `conversion.custom_threshold` above 500, because the score is never below the line count. Nothing collects it: no route or service takes a payment for a conversion | `runtime/blockchain/services/contract_conversion/tier_manager.py` (`_TIERS`; `conversion.tier_overrides`) |

Paid plugin sales are not live (the purchase route answers `501`); their commission is the operator's `plugin_marketplace.commission_rate`. Subscriptions (Pro, Enterprise) are sold in the MTRX app through Apple In-App Purchase.
