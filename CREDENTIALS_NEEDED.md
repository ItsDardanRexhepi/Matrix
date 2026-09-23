# CREDENTIALS_NEEDED — what a deployment of The Matrix needs

The credentials, keys and addresses a deployment of The Matrix needs, grouped by
the capability each one unlocks, with what happens while it is unset. Nothing in
this repository ships with a real secret: every value below is a placeholder in
`matrix.config.json.example` or an environment variable, and
`runtime/config/validation.py` lists the secrets the gateway takes from the
environment, each with its variable. Default network is
**Base Sepolia (testnet, chain 84532)**; nothing touches mainnet unless you
configure it to.

The enforcing security core is a separately installed private package and is not
part of this repository. Without it the platform runs the no-op security
backend: its gate allows every action it is asked about and applies none of the
core's checks, the platform's own per-agent tool boundary still holds, and it says
so at boot. A gateway declared production (`MATRIX_ENV=production`) refuses to start on it
(section 5).

Terms used below: **CREDENTIAL-GATED** (code complete, needs the value to
function) · **UNVERIFIED** (built, provable only after a deployment).

---

## 0. Where configuration lives

| Source | What goes there |
|---|---|
| `matrix.config.json` (copy from `matrix.config.json.example`; gitignored) | Every setting below that names a config path. |
| Environment variables | Secrets. With `MATRIX_ENV=production` the gateway refuses to start when a required secret is missing, and when a secret-shaped setting sits in the file with no variable covering it. |

---

## 1. Chain core — unlocks ALL on-chain features

The gateway and the deploy scripts read these from different places. The
gateway reads `matrix.config.json`, and of the values below takes only the RPC
URL from the environment. `scripts/deploy_all.py` and
`scripts/verify_platform.py` read the `MATRIX_*` variables named here (or a
flat JSON file passed as their first argument), not `matrix.config.json`.

| Credential | Set in | Unlocks |
|---|---|---|
| **Base Sepolia RPC URL** | gateway: `blockchain.rpc_url` (env `BASE_RPC_URL`) · deploy scripts: env `MATRIX_RPC_URL` | Every on-chain read/write, chain-id validation, balance reads. Get from Alchemy/Infura/QuickNode. |
| **Chain ID = 84532** | gateway: `blockchain.chain_id` · deploy scripts: env `MATRIX_CHAIN_ID`; both default to 84532 | Chain validation; must match the RPC. (8453 = Base mainnet — leave on 84532 for testnet.) |
| **Deploy wallet private key** (funded with Sepolia ETH) | deploy scripts: env `MATRIX_PRIVATE_KEY`; the gateway never reads it | `scripts/deploy_all.py` — deploying the platform contracts. |
| **Platform / NeoSafe wallet address** | gateway: `blockchain.platform_wallet` · deploy scripts: env `MATRIX_NEOSAFE_ADDRESS` (required to deploy) | Fee routing, and the address the platform's own transactions, attestations included, are sent from. |
| EAS contract | already defaulted to `0x4200000000000000000000000000000000000021` (Base predeploy) | On-chain attestations. No action unless you use a custom registry. |
| EAS schema UID | gateway: `blockchain.eas_schema` · `scripts/deploy_all.py`: env `MATRIX_EAS_SCHEMA_UID` | The attestation schema. Register once on Base Sepolia. |

> The app's Secure Enclave signs the **user's** wallet ops; the platform key only
> signs **platform-level** ops (deploys, sponsorship, attestations). The server never
> signs or moves user funds — non-custodial invariant.

## 2. Gas sponsorship — the platform's paymaster signer (ERC-4337)

| Credential | Set in | Unlocks |
|---|---|---|
| **Paymaster signer key** | platform `blockchain.paymaster.signer_key` (env `MATRIX_PAYMASTER_SIGNER_KEY`); when that is absent, the flat `blockchain.paymaster_private_key` (env `MATRIX_PAYMASTER_KEY`) | `POST /api/v1/paymaster/sign`, the server half of the verifying paymaster. The sponsorship signature covers gas only, never anything the user's account does. |
| **Platform signer key** | platform `blockchain.paymaster_private_key` (env `MATRIX_PAYMASTER_KEY`) | Required under `MATRIX_ENV=production`: the gateway refuses to start without it. The platform's own on-chain calls — EAS attestations and the transactions the blockchain services send — are signed with it, and it is the paymaster signer's fallback. |
| **Paymaster address** | platform `blockchain.paymaster.address` | The deployed verifying paymaster the signature is for. Without it, or without the signer key, the sign route answers 503. |
| Sponsorship policy | platform `blockchain.paymaster.policy.allowed_actions` + `.daily_cap_usd` | Which actions, decoded from the call data being signed, are sponsored, and the per-identity daily cap enforced before signing. Unset → no allowlist and no cap. Some EAS attestation and revocation paths are signed with the platform signer key outside the policy, whatever it says; `docs/blockchain.md` lists each of them. |

## 3. Platform gateway + AI

| Credential | Set in | Unlocks |
|---|---|---|
| **Gateway API key** | platform `gateway.api_key` (env `MATRIX_API_KEY`) | Bearer auth for `/api/v1/*`. The app sends this. |
| **Model provider key** | the env var of the provider you choose — e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`; none for `ollama` (README → Model Support) | The agents' model. The ReAct loop needs one reachable provider, and `GET /ready` fails while none is. |

## 4. The 14 protocol services — each CREDENTIAL-GATED until its key is set

Set under `services.<name>.*` in `matrix.config.json`. Each service returns a
`not_deployed` response naming its exact missing key until configured.

| Service | Required key(s) | Unlocks |
|---|---|---|
| payment_channels | `services.payment_channels.endpoint` (Raiden node) + `.token_address` (+ `.contract_address` for on-chain fallback) | L2 state-channel open/route/close |
| compute | `services.compute.endpoint` + `.api_key` (Akash/Render/Gensyn) | Compute job submit, device rental, reward claim |
| mpc | `services.mpc.module_address` or `.endpoint` | Threshold sign / recovery / session keys |
| social_protocols | `services.social_protocols.{lens,farcaster,push}_*` keys | Lens/Farcaster/Push + token launches |
| advanced_governance | `services.advanced_governance.*_address` + Snapshot hub | veToken, quadratic vote, RetroPGF, bribes, delegation |
| oracles_plus | `services.oracles_plus.pyth_contract_address` (Base `0x8250f4aF4B972684F7b336503E2D6dFeDeB1487a`) + hermes endpoint; RedStone/API3 keys | Pyth/RedStone/API3 feeds, Keeper jobs |
| tba | `services.tba.account_implementation` (registry is canonical `0x000000006551c19487814612e58FE06813775758`) | ERC-6551 token-bound accounts |
| storage | `services.storage.api_key` + `.endpoint` (Lighthouse/Ceramic) | Filecoin/Ceramic/OrbitDB |
| creator_platforms | `services.creator_platforms.{sound,mirror,paragraph}_api_key` | Sound/Mirror/Paragraph |
| kyc | `services.kyc.api_key` + `.secret_key` (Sumsub/Persona) | KYC/AML start, risk check, credential issue |
| restaking | `services.restaking.{eigenlayer,symbiotic,karak,lido,rocketpool}_*` addresses | Restaking + liquid staking |
| nft_lending | `services.nft_lending.pool_address` (BendDAO/NFTfi/Arcade) | NFT-backed loans |
| ccip | `services.ccip.router_address` (Base Sepolia CCIP router) + per-bridge addresses | CCIP/Hyperlane/Wormhole/Axelar/Stargate |
| auctions | `services.auctions.auction_address` + `.orderbook_address` | Dutch/English/sealed-bid + orderbook |

## 5. Security layer — a separately installed private package

The enforcing security core is closed source, is not part of this repository,
and is installed separately; its own configuration is not documented here. The
platform reaches it only through the seam in `runtime/security/` (see
`runtime/security/SECURITY_INTERFACE.md`). Nothing in this section is a value
you set in this repository.

- With no core installed the platform runs the inert no-op backend: its gate
  allows every action it is asked about and applies none of the core's checks,
  the platform's own per-agent tool boundary still holds, and the platform says so
  at boot.
  That is a normal state for local and testnet use.
- Under `MATRIX_ENV=production` the gateway refuses to start on the no-op
  backend, and names the cause. The readiness probe (`GET /ready`) fails on it
  too, as a second line of defence. `docker-compose.prod.yml` and
  `k8s/deployment.yaml` set `MATRIX_ENV=production`, `docker-compose.yml`
  defaults to it, and the image this repository's `Dockerfile` builds installs
  only the public requirements, so on those routes a gateway without the core
  does not start. For a run without the core, set a non-production value such as
  `MATRIX_ENV=testnet`. Leaving it unset is enough only when you start
  `python -m gateway.server` yourself: `docker-compose.yml` turns an unset value
  into `production`.
- `python -c "import runtime.security as s; print(s.SECURITY_BACKEND)"` prints
  the backend that is live: `noop`, or `morpheus_security` when the core is
  installed and loaded. `./scripts/ops.sh doctor` reports the same value, and
  says so when the core is installed but failed to load.
- The core itself defaults to OBSERVE, and ENFORCE is not to be enabled before a
  human security review and testnet validation.

## 6. The supply-chain authenticity secret — no default, and changing it has a cost

| Credential | Set in | If unset | Why it matters |
|---|---|---|---|
| **QR verification secret** | platform `supply_chain.qr_secret` (env `MATRIX_QR_SECRET`) | **No default.** Product QR codes are refused (`not_configured`) rather than issued, and no scan is called valid. A placeholder such as `CHANGE-ME-…` counts as unset, and so does the value that used to be the published default. | The entire secret in the product-authenticity hash (`HMAC-SHA256(qr_secret, product_id\|timestamp)`, in `runtime/blockchain/services/supply_chain/qr_codes.py`). Anyone who knows it can mint a valid code for any product id. Set it to a long random per-deployment value. |

**DEPLOYMENT PREREQUISITE — ordering matters, as it did for `blockchain.eas_schema`.**
Set the value you mean to keep **before** issuing any product QR code you intend
to treat as authoritative. A code issued under a test value stops verifying when
the value changes.

**READ THIS BEFORE CHANGING THE KEY — it has a cost, and the cost lands on
physical goods.** Verification hashes are computed from the secret, so changing
the secret changes every hash. Every QR code already generated stops verifying
the moment you change this key.

So the operational consequence, stated plainly:

- **Set it before your first production QR code** → costs nothing.
- **Change it after** → **every code already printed, applied to a product,
  shipped, or sitting in a warehouse becomes invalid**, and each one must be
  re-generated and physically re-applied. The bill is labour and relabelling,
  not engineering.
- **Never set it** → no code is issued, and none verifies.

There is no option where you keep both the already-printed codes and a new
secret. **Whoever changes this key needs to know it obsoletes every code
already in circulation.**

## 7. Contract addresses — fill AFTER `deploy_all.py`

`scripts/deploy_all.py` deploys the platform contracts and writes
`deployment_manifest.json`. Copy each deployed address into the matching
`services.<name>.*` key in `matrix.config.json` (section 4); a service whose
address is blank keeps answering `not_deployed`.

## 8. Sign in with Apple — server credentials

| Credential | Where | Unlocks |
|---|---|---|
| `auth.apple.bundle_id` (`com.opnmatrx.mtrx`) | `matrix.config.json` | **Required** for `POST /api/v1/auth/apple` — the identity-token audience check. Unset → route fails closed (503). |
| `auth.apple.team_id` + `key_id` + `private_key_p8` (Sign in with Apple key) | `matrix.config.json` / secret | Token **revocation** on account deletion (`DELETE /api/v1/auth/account`). App Review requires working deletion once server accounts are live. Unconfigured → local data still deleted, Apple revocation skipped with a WARNING. |

## 9. IAP verification — monetization server

| Credential | Where | Unlocks |
|---|---|---|
| `iap.bundle_id` (`com.opnmatrx.mtrx`) | `matrix.config.json` | **Required** for `POST /api/v1/iap/verify` + `POST /api/v1/iap/asn` — the signed-transaction bundle check. Unset → both routes fail closed (503). |
| `iap.environment` (`Production` or `Sandbox`) | `matrix.config.json` | Optional: restricts accepted payloads to one App Store environment. Unset → both accepted (each row records its environment). |
| ASN V2 webhook URL registered in App Store Connect → `https://<gateway>/api/v1/iap/asn` | App Store Connect → App Information | Renewal/expiry/refund/revoke flips reaching the server. No shared secret — the webhook authenticates by its Apple-signed JWS chain (pinned root at `gateway/certs/AppleRootCA-G3.pem`). |

---

## First testnet transaction — runbook

The full chain is wired in code: **app → gateway → agent → dispatcher → security
gate → tool → chain**. To exercise it end-to-end on Base Sepolia:

1. **Check the security backend:**
   `python -c "import runtime.security as s; print(s.SECURITY_BACKEND)"` prints
   `noop` without the separately installed core (the gate allows what it is asked) and
   `morpheus_security` with it (section 5). Either runs this on testnet, but
   `noop` only with a non-production `MATRIX_ENV` (unset counts only for a direct
   `python -m gateway.server`; `docker-compose.yml` defaults it to production): a
   production gateway refuses to start on it.
2. **Set the values** (sections 1 and 3): for the deploy scripts `MATRIX_RPC_URL`,
   `MATRIX_PRIVATE_KEY` and `MATRIX_NEOSAFE_ADDRESS` (chain 84532 is their
   default); for the gateway `blockchain.rpc_url` (or `BASE_RPC_URL`),
   `blockchain.platform_wallet`, the platform signer key `MATRIX_PAYMASTER_KEY`,
   the attestation schema `blockchain.eas_schema` (step 5 attests), your model
   provider's key and `MATRIX_API_KEY`. `docker-compose.yml` passes every secret
   the gateway reads into the container from your shell or from a `.env` file
   beside it; values in the config file are stripped in production.
3. **Deploy the contracts:** `python -m scripts.deploy_all` (or `python scripts/deploy_all.py`).
   It compiles, deploys to Base Sepolia, attests each via EAS, and writes
   `deployment_manifest.json`. Copy addresses into `services.*` (section 7).
4. **Start the gateway:** it serves on `:18790`; front it with TLS. The two TLS
   routes this repository ships, the bundled `Caddyfile` through
   `docker-compose.prod.yml` and `k8s/ingress.yaml`, both run the gateway with
   `MATRIX_ENV=production`, so they need the security core installed in the
   image. Without the core, start the base stack alone with a non-production
   value (`MATRIX_ENV=testnet docker compose up -d`) and put your own TLS in
   front of it. `GET /health` to confirm.
5. **First tx, two paths:**
   - *Client-signed (non-custodial):* a wallet client builds a UserOperation,
     signs it with the user's own key and submits it to its bundler, sponsored
     through section 2 if that is configured. You get a real `userOpHash` —
     verify it on `sepolia.basescan.org`.
   - *Agent-routed:* `POST /chat` as Trinity with a read request → returns data.
     Ask for an execution → Trinity calls `request_execution` → the Morpheus gate
     evaluates (OBSERVE: logs, allows) → Neo executes via the service dispatcher →
     EAS attestation is written. Inspect the gateway logs for the
     `trinity->morpheus->neo` hand-off and the attestation tx.
6. **Confirm the boundary:** a `/chat` as Trinity asking to run a state-changing
   `platform_action` directly returns `[DENIED]` (she must use the hand-off) — proof
   the per-agent boundary is live.

> Everything above is **CREDENTIAL-GATED / UNVERIFIED** until these steps are
> done: the code is connected, but a real end-to-end testnet transaction can
> only be confirmed once credentials are in and the gateway is deployed. The
> security core, where it is installed, does not leave OBSERVE before a human
> security review (section 5).
