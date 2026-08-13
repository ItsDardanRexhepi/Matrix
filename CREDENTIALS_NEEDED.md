# CREDENTIALS_NEEDED — the credentials a deployment needs

---

## 1. Chain core — unlocks ALL on-chain features (app + platform)

| Credential | Set in | Unlocks |
|---|---|---|
| **Base Sepolia RPC URL** | platform `blockchain.rpc_url` (env `OPENMATRIX_RPC_URL` / `BASE_RPC_URL`) | Every on-chain read/write, chain-id validation, balance reads. Get from Alchemy/Infura/QuickNode. |
| **Chain ID = 84532** | platform `blockchain.chain_id` (env `OPENMATRIX_CHAIN_ID`) | Chain validation; must match the RPC. (8453 = Base mainnet — leave on 84532 for testnet.) |
| **Deploy wallet private key** (funded with Sepolia ETH) | platform `blockchain.private_key` (env `OPENMATRIX_PRIVATE_KEY`) | `scripts/deploy_all.py` — deploying the platform contracts. |
| **Platform / NeoSafe wallet address** | platform `blockchain.platform_wallet` (env `OPENMATRIX_NEOSAFE_ADDRESS`) | Fee routing + EAS attestation recipient. |
| EAS contract | already defaulted to `0x4200000000000000000000000000000000000021` (Base predeploy) | On-chain attestations. No action unless you use a custom registry. |
| EAS schema UID | platform `blockchain.eas_schema` (env `OPENMATRIX_EAS_SCHEMA_UID`) | The attestation schema. Register once on Base Sepolia. |

> The app's Secure Enclave signs the **user's** wallet ops; the platform key only
> signs **platform-level** ops (deploys, sponsorship, attestations). The server never
> signs or moves user funds — non-custodial invariant.

## 3. Platform gateway + AI

| Credential | Set in | Unlocks |
|---|---|---|
| **Gateway API key** | platform `gateway.api_key` (env `OPENMATRIX_API_KEY` / `MTRX_API_KEY`) | Bearer auth for `/api/v1/*`. The app sends this. |
| **Anthropic API key** | env `ANTHROPIC_API_KEY` | The agents' model (Claude). Required for the ReAct loop to run. |
| OpenAI API key | env `OPENAI_API_KEY` | Optional fallback model. |

## 4. The 14 protocol services (Part 2A) — each CREDENTIAL-GATED until its key is set

Set under `services.<name>.*` in `openmatrix.config.json`. Each service returns a
`not_deployed` response naming its exact missing key until configured.

| Service | Required key(s) | Unlocks |
|---|---|---|
| payment_channels | `services.payment_channels.endpoint` (Raiden node) + `.token_address` (+ `.contract_address` for on-chain fallback) | L2 state-channel open/route/close |
| compute | `services.compute.endpoint` + `.api_key` (Akash/Render/Gensyn) | Compute job submit, device rental, reward claim |
| mpc | `services.mpc.module_address` or `.endpoint` | Threshold sign / recovery / session keys |
| social_protocols | `services.social_protocols.{lens,farcaster,push}_*` keys | Lens/Farcaster/Push + token launches |
| advanced_governance | `services.advanced_governance.*_address` + Snapshot hub | veToken, quadratic vote, RetroPGF, bribes, delegation |
| oracles_plus | `services.oracles_plus.pyth_contract` (Base `0x8250f4aF4B972684F7b336503E2D6dFeDeB1487a`) + hermes endpoint; RedStone/API3 keys | Pyth/RedStone/API3 feeds, Keeper jobs |
| tba | `services.tba.account_implementation` (registry is canonical `0x000000006551c19487814612e58FE06813775758`) | ERC-6551 token-bound accounts |
| storage | `services.storage.api_key` + `.endpoint` (Lighthouse/Ceramic) | Filecoin/Ceramic/OrbitDB |
| creator_platforms | `services.creator_platforms.{sound,mirror,paragraph}_api_key` | Sound/Mirror/Paragraph |
| kyc | `services.kyc.api_key` + `.secret_key` (Sumsub/Persona) | KYC/AML start, risk check, credential issue |
| restaking | `services.restaking.{eigenlayer,symbiotic,karak,lido,rocketpool}_*` addresses | Restaking + liquid staking |
| nft_lending | `services.nft_lending.pool_address` (BendDAO/NFTfi/Arcade) | NFT-backed loans |
| ccip | `services.ccip.router_address` (Base Sepolia CCIP router) + per-bridge addresses | CCIP/Hyperlane/Wormhole/Axelar/Stargate |
| auctions | `services.auctions.auction_address` + `.orderbook_address` | Dutch/English/sealed-bid + orderbook |

## 6b. Per-deployment secrets that have a WORKING DEFAULT — set these or they hold

**These are the dangerous ones**, because nothing fails when you skip them. A
credential you forget usually announces itself: a feature returns "needs config"
and you go and set it. A secret with a working default does not — the feature
functions, no test fails, no log complains, and the value protecting it is the
one printed in a public repository.

| Credential | Set in | Default if unset | Why it matters |
|---|---|---|---|
| **QR verification secret** | platform `supply_chain.qr_secret` | `"0pnmatrx-default-qr-secret"` — **published in this public repo** | The entire secret in the product-authenticity hash (`qr_codes.py:200`, `sha256(product_id\|timestamp\|qr_secret)`). Left unset, **anyone who can read this repository can forge a valid product verification hash for any product id.** Set it to a long random per-deployment value. |

**DEPLOYMENT PREREQUISITE — ordering matters, as it did for `blockchain.eas_schema`.**
Set `supply_chain.qr_secret` **before** issuing any product QR code you intend to
treat as authoritative.

**READ THIS BEFORE SETTING THE KEY — it has a cost, and the cost lands on
physical goods.** Verification hashes are computed from the secret, so changing
the secret changes every hash. **Rotating does not repair codes minted under the
default; it invalidates them.** Every QR code already generated stops verifying
the moment you set this key.

So the operational consequence, stated plainly:

- **Set it before your first production QR code** → costs nothing.
- **Set it after** → **every code already printed, applied to a product, shipped,
  or sitting in a warehouse becomes invalid**, and each one must be re-generated
  and physically re-applied. The bill is labour and relabelling, not engineering.
- **Never set it** → the codes verify, and anyone who can read this public
  repository can forge a valid one for any product id.

There is no option where you keep both the already-printed codes and a secret
worth having. **Whoever sets this key needs to know it obsoletes every code
already in circulation.**

## 8. Sign in with Apple — server credentials (P1-8)

| Credential | Where | Unlocks |
|---|---|---|
| `auth.apple.bundle_id` (`com.opnmatrx.mtrx`) | `openmatrix.config.json` | **Required** for `POST /api/v1/auth/apple` — the identity-token audience check. Unset → route fails closed (503). |
| `auth.apple.team_id` + `key_id` + `private_key_p8` (Sign in with Apple key) | `openmatrix.config.json` / secret | Token **revocation** on account deletion (`DELETE /api/v1/auth/account`). App Review requires working deletion once server accounts are live. Unconfigured → local data still deleted, Apple revocation skipped with a WARNING. |

## 9. IAP verification — monetization server (Phase 3)

| Credential | Where | Unlocks |
|---|---|---|
| `iap.bundle_id` (`com.opnmatrx.mtrx`) | `openmatrix.config.json` | **Required** for `POST /api/v1/iap/verify` + `POST /api/v1/iap/asn` — the signed-transaction bundle check. Unset → both routes fail closed (503). |
| `iap.environment` (`Production` or `Sandbox`) | `openmatrix.config.json` | Optional: restricts accepted payloads to one App Store environment. Unset → both accepted (each row records its environment). |
| ASN V2 webhook URL registered in App Store Connect → `https://<gateway>/api/v1/iap/asn` | App Store Connect → App Information | Renewal/expiry/refund/revoke flips reaching the server. No shared secret — the webhook authenticates by its Apple-signed JWS chain (pinned root at `gateway/certs/AppleRootCA-G3.pem`). |
