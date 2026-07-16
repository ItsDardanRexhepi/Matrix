# Real-Estate Escrow Engine (Component 46) — v1 design

Buy a property through the app with the escrow document pipeline compressed
from 30+ days to seconds: every closing document is pre-uploaded, content-
hashed, attested on-chain, and freshness-tracked per property. When every
document is fresh + verified and the buyer's proof-of-funds is current, the
property is **transaction-ready** — and a verified buyer executes the purchase
in one action: funds lock and settle **atomically** against the property's
deed token, with a full attestation trail.

**Feature-gated and dark by default:** `services.real_estate.enabled = false`
(the server-side analogue of the app's mvpMode gating for regulated features).
While off, every route returns an honest 403 and every service method refuses.

## Where things live

| Piece | Path |
|---|---|
| Service (registered like the other 45) | `runtime/blockchain/services/real_estate/service.py` |
| Pure readiness + freshness engine | `runtime/blockchain/services/real_estate/readiness.py` |
| Durable SQLite store | `runtime/blockchain/services/real_estate/store.py` |
| Routes (all through `_call → gate_action`) | `gateway/service_routes.py` (`/api/v1/realestate/*`) |
| Escrow contract | `contracts/PropertyEscrow.sol` (+ `contracts/test/PropertyEscrow.t.sol`) |
| Deed token (ERC-721) | `contracts/PropertyDeed.sol` (+ `contracts/test/PropertyDeed.t.sol`) |
| EAS schema (20th, `document_verification`) | `runtime/blockchain/services/attestation/schemas.py` |
| Config block | `openmatrix.config.json` → `services.real_estate` |

## Document types + freshness windows (config-driven defaults)

Config: `services.real_estate.freshness_days`. Staleness is **computed on
read** from the stored `expires_at` — no cron, no cached verdicts. The window
is `[uploaded_at, expires_at)`: the expiry instant itself is already stale, so
an exact-boundary read can never stretch a window. An unknown document type
gets the **shortest** default window (conservative, never generous).

| Document type | Window |
|---|---|
| `title_report` | 30 days |
| `inspection` | 90 days |
| `pest_roof_inspection` | 90 days |
| `appraisal` | 120 days |
| `seller_disclosures` | 180 days |
| `hoa_documents` | 90 days |
| `insurance_binder` | 30 days |
| buyer `proof_of_funds` | 30 days (`proof_of_funds_days`) |

`GET /api/v1/realestate/documents/expiring?days=N` lists current documents
expiring within N days (already-expired ones are readiness blockers, not
reminders) — the feed for future re-upload notifications.

## The document pipeline (upload → hash → store → attest)

1. **Hash** — sha256 computed server-side from the uploaded content, always
   real. (A caller may register a pre-computed hash without the blob; that is
   recorded as `hash_only`, never dressed up as stored.)
2. **Store** — via the existing `storage` service (`store_filecoin`,
   Lighthouse/web3.storage). Genuinely wired but **credential-gated**: with no
   `services.storage.filecoin_api_key` the document records
   `storage_status: not_stored` — a fabricated CID is never invented (the
   privacy-service IPFS/Arweave stubs are deliberately NOT used).
3. **Attest** — EAS attestation through the live attestation system using the
   new `document_verification` schema (the 20th, following the existing 19;
   testnet). The EAS path is **fail-closed**: until the schema UID is
   registered on-chain (a human step — same runbook as the other 19: run
   `scripts/register_eas_schemas.py`, register from a funded signer, paste the
   UID into `blockchain.schemas.document_verification`), attestation attempts
   record `attestation_status: unattested`. **Only `attested` satisfies
   readiness** — an unattested document is a named blocker, never invisible.
4. **Supersession** — a re-upload inserts a new version and stamps the prior
   version's `superseded_by`; full history is retained forever. The "current"
   document per type is the single non-superseded row.

## Transaction readiness (the heart)

`readiness.evaluate_readiness(documents, buyer_verification, now, required)` —
a **pure function** (no I/O, no clock reads; callers inject `now`). Verdict:

```
TransactionReadiness { ready: bool, blockers: [{item, reason, days_stale?}] }
```

- Every required document must be **present**, **fresh**, and **attested**.
- The buyer's proof-of-funds must be **present**, **fresh**, and **verified**.
- Each failure is one named blocker: `missing` / `stale` (with whole days
  stale, rounded up — one second past expiry reads 1, never 0) / `unverified`.
- **`ready` is structurally derived as `len(blockers) == 0`** — it is never
  assigned independently, so there is no code path where `ready=true` with any
  blocker present. This is enforced by construction and locked by tests.

## The escrow state machine

```
initiated → funds_locked → settled → offchain_recording_pending → complete
     └──────────┴──────────→ refunded            (terminal states: complete, refunded)
```

Transitions are enforced by a single table (`VALID_TRANSITIONS`); anything
else raises. History is append-only on the escrow record, together with the
readiness snapshot at purchase time, every attestation reference, and every
transaction hash.

## One-tap purchase + the atomicity guarantee

`POST /api/v1/realestate/purchase {buyer, property_id}`:

1. **Re-verify readiness server-side at execution time** — a cached green is
   never trusted. Not ready → honest `not_ready` with the full blocker list.
2. Contracts not deployed / deed not minted → honest `not_deployed` naming the
   exact missing config keys. **No state is created on a refusal.**
3. Otherwise: create the escrow record (`initiated`), snapshot + attest the
   readiness verdict, and return the prepared **`lockAndSettle`** calldata.

**Non-custodial by construction:** the platform never moves buyer funds. The
buyer's own account submits the settlement — gas-sponsorable through the
existing `/api/v1/paymaster/sign` path so the buyer pays no gas. On-chain,
`PropertyEscrow.lockAndSettle` executes funds-lock + deed-transfer + release
in **one transaction, all-or-nothing**:

- funds release to the seller **only** in the same transaction that transfers
  the deed to the buyer;
- a zero readiness-attestation UID is refused;
- if the deed leg fails (seller revoked approval, deed moved), the payment
  reverts with it; if the payment leg fails (rejecting seller wallet), the
  deed transfer reverts with it — proven by forge tests in both directions;
- reentrancy is guarded (`nonReentrant` + checks-effects-interactions);
- **there is no owner and no backdoor**: PropertyEscrow has no owner role, no
  pause, and no function that can move locked funds anywhere except
  settlement-to-seller (buyer-executed) or refund-to-buyer (buyer-only, after
  the immutable lock timeout).

`POST /api/v1/realestate/escrow/{id}/confirm {tx_hash}` verifies the receipt
**on-chain** and advances state ONLY if the receipt genuinely settled *this*
escrow: status success **AND** emitted by our `escrow_contract` **AND** carrying
a `Settled(escrowId, buyer, …)` log whose indexed id equals this escrow's id.
An arbitrary successful transaction (e.g. a 1-wei self-transfer whose hash the
buyer supplies) is rejected as `not_settlement` — it can never fabricate a sale.
A reverted / unmined / unrelated receipt changes nothing and says so. Only then
does it walk the machine truthfully — `funds_locked → settled →
offchain_recording_pending` — attest the settlement, and mark the property sold.
Concurrent duplicate confirms settle exactly once (an in-flight guard plus the
state-machine's `only-from-initiated` rule).

## The honest off-chain bridge

County recording and notarization are real-world steps this system does not
control. They are modelled as the explicit `offchain_recording_pending` state
with an operator endpoint (`POST /api/v1/realestate/escrow/{id}/recording-complete`)
to mark genuine completion — **never pretended away, and never blocking the
on-chain settlement's honesty about what it is**: funds settled + deed token
transferred + trail attested; legal recording status shown truthfully as
pending/complete.

## Buyer verification (proof-of-funds)

- **`wallet_balance` (v1, real, automatic):** the buyer's on-chain balance is
  read via the shared Web3Manager and compared to the threshold. The **proven
  balance** is recorded, and readiness compares it against the **property
  price** — so a buyer cannot self-select a tiny threshold (verify $1) and pass
  readiness on an expensive property; underfunded → `proof_of_funds`
  `insufficient` blocker. Insufficient balance vs. the threshold records an
  honest `insufficient_funds`; no RPC configured → honest `not_deployed`, no
  record fabricated. (An unreachable RPC is detected via the real Web3Manager
  interface — `available` / `w3.is_connected()` — so a live node is never
  mis-reported as down.)
- **`external` (honest stub):** operator-attested external verification (bank
  integration) returns **501 not_implemented** — never fakes.
- 30-day expiry; re-verification supersedes with history retained.

## Gating summary (defense in depth)

| Layer | Behavior when off/unconfigured |
|---|---|
| `services.real_estate.enabled=false` | routes 403; service methods refuse (covers batch/dispatcher paths) |
| EAS schema unregistered | documents record `unattested` → readiness blocker |
| Storage uncredentialed | `not_stored` recorded; hash still real |
| Contracts undeployed | `not_deployed` naming exact config keys; no state created |
| No RPC | verification/confirmation refuse honestly; state unchanged |

## What v1 genuinely does vs. honest out-of-scope

**Does:** document pipeline with real hashing + credential-gated real storage
+ fail-closed attestation; config-driven freshness with on-read staleness;
pure exhaustively-tested readiness; non-custodial atomic escrow settlement
(written + forge-tested, NOT deployed — testnet deploy is a separate,
explicitly-triggered step; mainnet is lawyer-gated); gas-sponsored one-tap
flow; tracked off-chain recording bridge; honest buyer verification.

**Out of scope in v1 (future phases, not faked):**
- **Financing / mortgages** — v1 is cash-equivalent (full escrow amount).
- **Title insurance integration** — the title report is a document type;
  binding an insurer is not wired.
- **County recording automation** — recording is tracked, not automated;
  e-recording APIs are a future phase.
- **Bank-account proof-of-funds** — the `external` method 501s until a real
  integration exists.
- **At-rest blob encryption** — content hashes anchor integrity on-chain and
  storage is credential-gated; a dedicated document-encryption layer (beyond
  the storage provider's) is future work, stated plainly.
- **Legal effect** — the deed token records the on-chain side of a transfer;
  legal ownership additionally requires the real-world recording steps above.

## Deploy (later, user-triggered — nothing deployed now)

`PropertyDeed` + `PropertyEscrow` are registered in `scripts/deploy_all.py`
(escrow constructor arg: `escrow_lock_timeout_seconds`, default 7 days,
immutable after deploy). After the explicit testnet deploy, paste the
addresses into `services.real_estate.deed_contract` / `.escrow_contract` and
register the `document_verification` EAS schema UID. Seller-side listing flow
must approve the escrow contract on the deed token before settlement.
