# ABI_VERIFICATION_NEEDED — per-service checklist before go-live

The 14 wired blockchain services (`runtime/blockchain/services/<name>/service.py`)
call **real protocol interfaces**, but the exact ABIs / function signatures / API
request shapes were written **best-effort against public documentation** and
**cannot be confirmed without the real deployed contract address + a network
connection**. This file is the honest catalog of what a human must verify against
the actual deployed contract / live API **before** flipping each service on. It is
an audit, not a fix — no ABIs were changed to "look more right."

How to read it: each service lists the **config key(s)** you populate, the
**ABI / interface assumption** to check against the real contract, and the
**API endpoint** to confirm. Items marked `UNVERIFIED` are flagged inline in the
service source too. Until a service's row is verified, leave it unconfigured — it
stays a CREDENTIAL-GATED no-op.

Default network: **Base Sepolia (84532)**. Non-custodial invariant preserved
(server signs only the platform paymaster account, never user funds).

---

### 1. payment_channels (Raiden)
- **Config:** `services.payment_channels.endpoint` (Raiden REST node), `.token_address`, `.contract_address`/`.token_network_address`, `.api_key` (optional).
- **Verify ABI:** `TokenNetwork.openChannel(address,address,uint256)`, `getChannelIdentifier(address,address)`, `closeChannel(...)`. **UNVERIFIED:** `closeChannel` is the minimal 2-arg cooperative form; a **unilateral close carries a balance-proof** (balance_hash, nonce, additional_hash, signatures) only the node can produce — confirm against your deployed `raiden-contracts` TokenNetwork and use the REST path for balance-proof closes.
- **Verify API:** Raiden REST `PUT /api/v1/channels`, `POST /api/v1/payments/{token}/{target}`, `PATCH /api/v1/channels/{token}/{partner}` (field names + settle-timeout bounds) against your node version.

### 2. compute (Akash / Render / Gensyn / DePIN)
- **Config:** `services.compute.endpoint`, `.api_key`, `.provider` (akash|render|gensyn), `.rental_contract`.
- **Verify ABI:** generic `claimRewards(address)` on the DePIN reward contract — **UNVERIFIED**, the real selector is provider-specific.
- **Verify API:** Akash `POST {endpoint}/v1/deployments`, `/v1/leases`, `/v1/rewards/claim`. **UNVERIFIED:** exact SDL/manifest body + paths are provider-specific (`https://api.akash.network`).

### 3. mpc (recovery / session keys / threshold sign)
- **Config:** `services.mpc.recovery_module`/`module_address`, `.session_key_module`, `.endpoint`, `.api_key`.
- **Verify ABI:** `initiateRecovery(account,newOwner,...)`, `registerSessionKey(account,...)`. **UNVERIFIED:** signatures follow a *generic* social-recovery / session-key module — confirm against your deployed recovery module (e.g. the specific 4337/6900 module).
- **Verify API:** MPC-node signing request shape (generic) — confirm against the real MPC node.
- **Non-custodial note:** must operate via the user-authorized module; the server never holds user keys.

### 4. social_protocols (Lens / Farcaster / Push)
- **Config:** `services.social_protocols.lens_hub_address`, `.farcaster_api_base`/`.farcaster_api_key`/`.farcaster_signer_uuid`, `.push_api_base`/`.push_channel`, `.token_factory_address`.
- **Verify ABI:** `LensHub.createProfile(createProfileParams)` — **UNVERIFIED** against the exact deployed LensHub (v1 vs v2 param struct differs); token-launch factory selector **UNVERIFIED**.
- **Verify API:** Farcaster via Neynar `https://api.neynar.com`, Push `https://backend.epns.io` — confirm endpoints/keys.

### 5. advanced_governance (veToken / Snapshot / RetroPGF / bribes)
- **Config:** `services.advanced_governance.ve_token_address`, `.snapshot_hub`/`.snapshot_space`, `.bribe_market_address`, `.delegate_registry_address`, `.eas_address`/`.eas_schema`.
- **Verify ABI:** Curve `VotingEscrow.create_lock(uint256,uint256)`, `balanceOf(address)`, `locked(address)`. **UNVERIFIED:** bribe-market selector (Votium-style varies); **assumes an 18-decimal lock/reward token** (line ~180/442) — confirm decimals.
- **Verify API:** Snapshot hub `https://hub.snapshot.org` (message/typed-data shape).

### 6. oracles_plus (Pyth / RedStone / API3 / Chainlink Keepers)
- **Config:** `services.oracles_plus.pyth_contract_address`, `.hermes_endpoint`, `.redstone_endpoint`/`.redstone_api_key`/`.redstone_data_service_id`, `.keeper_registrar_address`/`.registrar_address`.
- **Verify ABI:** Pyth `getPriceUnsafe(bytes32)` returning `(price,conf,expo,publishTime)` — Pyth on Base is canonical `0x8250f4aF4B972684F7b336503E2D6dFeDeB1487a` (confirm). **UNVERIFIED:** Chainlink `AutomationRegistrar` `RegistrationParams` struct/selector differs across Automation versions (2.1 shape assumed, line ~110/473).
- **Verify API:** `https://hermes.pyth.network`, RedStone `https://oracle-gateway-1.a.redstone.finance`.

### 7. tba (ERC-6551 token-bound accounts)
- **Config:** `services.tba.account_implementation` (registry is canonical `0x000000006551c19487814612e58FE06813775758`).
- **Verify ABI:** `ERC6551Registry.createAccount(implementation,salt,chainId,tokenContract,tokenId)` + `IERC6551Account.execute(...)`. Lowest-risk (the registry is standardized) — **verify the account-implementation address + that your registry is the canonical one**.

### 8. storage (Filecoin / Ceramic / OrbitDB)
- **Config:** `services.storage.filecoin_api_key`/`.filecoin_endpoint`/`.filecoin_provider`, `.ceramic_endpoint`/`.ceramic_controller`, `.orbitdb_endpoint`/`.orbitdb_api_key`.
- **Verify API:** Lighthouse `https://node.lighthouse.storage/api/v0/add` / web3.storage upload — **UNVERIFIED:** multipart field name (`file`) + response shape (line ~150). Ceramic genesis commit normally must be **DAG-CBOR encoded & signed** (line ~233) — confirm. OrbitDB has **no standard HTTP API** (line ~331) — confirm your gateway.

### 9. creator_platforms (Sound.xyz / Mirror / Paragraph)
- **Config:** `services.creator_platforms.sound_api_key`/`.sound_edition_address`/`.sound_endpoint`, `.mirror_api_key`/`.mirror_endpoint`, `.paragraph_api_key`/`.paragraph_endpoint`/`.paragraph_publication`.
- **Verify ABI:** Sound `mint(address,quantity)` — **UNVERIFIED** against the exact deployed SoundEdition version (line ~164).
- **Verify API:** Sound GraphQL `https://api.sound.xyz/graphql` (query shape, line ~228), Mirror via Arweave bundler (UNVERIFIED for direct posting), Paragraph `https://api.paragraph.xyz`.

### 10. kyc (Sumsub / Persona)
- **Config:** `services.kyc.api_key`/`.secret_key`/`.base_url`/`.level_name` (Sumsub) or `.template_id` (Persona).
- **Verify API:** Sumsub `https://api.sumsub.com` with **HMAC-SHA256 signed** requests — **UNVERIFIED** end-to-end without a real app token (line ~137); Persona `https://withpersona.com/api/v1` inquiry create/fetch (Bearer) — **UNVERIFIED** (line ~207/310).
- **Privacy note:** confirm no raw PII is stored — it passes through to the provider.

### 11. restaking (EigenLayer / Symbiotic / Karak / Lido / Rocket Pool)
- **Config:** `services.restaking.strategy_manager_address`/`.strategy_address`/`.delegation_manager_address` (EigenLayer), `.symbiotic_vault_address`, `.karak_vault_address`, `.lido_steth_address`, `.rocketpool_deposit_address`.
- **Verify ABI:** EigenLayer `StrategyManager.depositIntoStrategy(strategy,token,amount)`, `DelegationManager.delegateTo(...)`; Lido `submit(address)`; Rocket Pool deposit. **Verify each manager/strategy address + signature** against the live deployments (these differ per network and have changed across EigenLayer upgrades).
- **DISPATCH WIRING BUG (separate, flagged):** `ACTION_MAP` routes `liquid_stake_lido` / `liquid_stake_rocketpool` to **`StakingService`**, which has no such methods — the real methods are on **`RestakingService`**. Fix `ACTION_MAP` (in the untouched `service_dispatcher.py`) to repoint these two actions. (See also FIX 2's note.)

### 12. nft_lending (BendDAO / NFTfi / Arcade)
- **Config:** `services.nft_lending.pool_address` (per protocol).
- **Verify ABI:** lending-pool borrow/liquidate signatures differ substantially across BendDAO vs NFTfi vs Arcade `LoanCore` — **verify against the specific protocol + pool address** you target.

### 13. ccip (Chainlink CCIP / Hyperlane / Wormhole / Axelar / Stargate)
- **Config:** `services.ccip.router_address` (+ per-bridge addresses).
- **Verify ABI:** Chainlink `Router.ccipSend(destChainSelector, EVM2AnyMessage)` — the **`EVM2AnyMessage` tuple encoding** is intricate; verify against the live router. Base Sepolia CCIP router address must be confirmed (defaulted + marked UNVERIFIED). Hyperlane `Mailbox.dispatch`, Wormhole core, Axelar gateway, Stargate router each need their real addresses + signatures.

### 14. auctions (Dutch / English / sealed-bid + orderbook DEX)
- **Config:** `services.auctions.auction_address`, `.orderbook_address`.
- **Verify ABI:** `createAuction / placeBid / settleAuction` and `placeLimitOrder / cancelLimitOrder` are **bespoke to your auction + orderbook contracts** — there is no single standard. Verify every signature against your deployed contracts.

---

## Cross-cutting items to verify
- **EAS:** Base + Base Sepolia EAS = `0x4200000000000000000000000000000000000021`, Ethereum mainnet = `0xA1207F3BBa224E2c9c3c6D5aF63D0eb1582Ce587` (both verified against the official eas-contracts deployment artifacts in FIX 3).
- **Selectors:** the platform computes selectors via `web3` (real keccak256) — correct. The iOS app's selectors were fixed to real keccak256 in FIX 1 (proven against `0xa9059cbb` etc.).
- **Token decimals:** several services assume 18-decimal tokens — confirm per token.
- **Every `not_deployed`/CREDENTIAL-GATED response** names its exact missing key; grep the logs for `called but credential '…' is not configured` to see what each service still needs.
