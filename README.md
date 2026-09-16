# 0pnMatrx

[![GitHub Sponsors](https://img.shields.io/github/sponsors/ItsDardanRexhepi?style=flat&logo=github)](https://github.com/sponsors/ItsDardanRexhepi)
[![Open Collective](https://img.shields.io/opencollective/all/openmatrix?style=flat&logo=opencollective)](https://opencollective.com/openmatrix)

---

Hello world,

My name is Dardan. I would like to welcome you to 0pnMatrx, where the world of possibilities are endless and free.

The name of this platform is 0pnMatrx. It is read as OpenMatrix.

I created this platform because I believe everyone deserves a balanced chance at life, and that they get to decide what they want to do with it, without barriers from others who may be more financially comfortable than they are.

0pnMatrx is as free as it can be. It welcomes the traditional world we all know and love into a new technological revolution. It is built by the people, for the people, and will always remain that at its core.

On 0pnMatrx, if you can think it, you can achieve it.

What you can do on 0pnMatrx:

- Scaffold a Solidity contract from a structured declaration (pseudocode, Solidity, or Vyper), with an automatic security scan and gas-optimisation pass — the generated interface, state, and function signatures, ready for you to fill in the logic. The platform does not deploy it for you: you deploy it with your own wallet, so the contract is yours from the first block
- Borrow against crypto you already hold — no bank, no credit check, no gatekeeping. You supply collateral to a lending pool and draw a loan against it; how much you can draw follows from what you put up, and the interest accrues on-chain where you can watch it. The collateral is what secures the loan, which is why nobody has to score you
- Create NFTs and register your creative work with an on-chain royalty that every marketplace honouring the ERC-2981 standard pays you on resale
- Co-own property, vehicles, and real-world assets with anyone in the world, with the ownership split, the payouts, and the transfer rules written into the contract itself
- Own and control your digital identity, share only what you choose, with whom you choose, for as long as you choose
- Convert your business into a DAO with transparent governance, on-chain voting, and automatic treasury management
- Send money anywhere in the world in seconds, with no platform fee taken from the transfer, and network gas sponsored within the policy the operator configures
- Register and protect your intellectual property with an immutable on-chain timestamp that proves what you had and when you had it
- Build blockchain applications and games without hand-writing Solidity — describe what you want, read the contract it generates, deploy it yourself
- Trade tokenized securities around the clock, settling on-chain in the time a block takes, wherever the offering is lawfully available to you
- Access parametric insurance that pays automatically when the data it watches meets the condition, no claims, no adjusters, no waiting
- Stake your assets and earn the yield the protocol actually pays, shown to you before you commit
- Verify the complete history of any product, property, or asset before you buy it
- Participate in governance and voting that is tamper-proof, transparent, and permanently recorded on-chain
- Watch the platform come alive through the real-time social feed — every deployment, swap, mint, and vote, ranked and streamed live
- And much more — open source, yours to run, yours to change

Every one of those runs against a blockchain you configure. Until you configure one, each service says so plainly rather than inventing a result: no fabricated addresses, no invented transaction hashes, no number that looks like your balance but isn't.

Your companions Trinity, Morpheus, and Neo are with you every step of the way.

I genuinely hope this project changes your life the way building it has changed mine.

I would like to personally thank every community that is part of this journey, the developers, the creators, the builders, the dreamers, and everyone who believed that a better system was possible. You are why this exists.

And finally, there is one more thank you waiting at the very end of this repository. I'll leave it there for you to find. Some things are worth reading all the way to the last line.

From Neo and Dardan Rexhepi

Allow your imagination to meet your creativity.

---

## What is 0pnMatrx

0pnMatrx is a free, open source AI agent platform. It combines a personal AI agent with a complete blockchain financial infrastructure, developer ecosystem, identity system, and governance architecture — all in one release, all free.

**This repository is the platform itself**: the gateway, the three agents, the Web3 service surface, the contract-conversion pipeline, the SDKs, and the example scripts. It is the part you can read, run, fork and change, and it is the whole of what the project asks you to trust — everything a request touches on its way in is in this tree.

**MTRX** is the iOS app that brings it to your phone. The enforcing security core is closed source and optional: its seam lives here, and with no core installed the platform runs in OBSERVE mode, where the gates report what they would have done instead of blocking. The deployment runtime the maintainer runs is private, and nothing in this repository depends on it.

---

## The goal, and what each commit does about it

The goal is the one I opened with. Everyone deserves a balanced chance at life, and the tools that decide who gets one — credit, ownership, settlement, insurance, a vote that counts — should not sit behind a gate that opens only for people who are already comfortable. I want those tools reachable by anyone with a phone and a connection, and I want the software that reaches them to be readable by the people it serves. That is why the whole platform is here in the open and not a product you are asked to take on faith.

Getting there is not one commit, it is a long line of them, so I hold every one to the same standard:

- **Nothing here claims to do something it does not do.** When a claim in the code, the docs, or this README turns out to be untrue, the rule is to build it true where that is possible, and to correct it plainly where it is not. Both happen, and the correction is written down either way.
- **A fix arrives with the check that catches it.** Every change ships with a test that fails against the old behaviour and passes against the new one, and I run it against the old behaviour first — a test that was never seen failing has not proven anything.
- **A refusal is a feature.** When a service has no chain, it says `not_deployed`. When the platform cannot do a thing, it says so instead of returning something that looks like success. When a number is not known, you get a dash and not a plausible figure. Money is the place where a comforting lie costs the most, so that is the place it is least welcome.
- **The security layer is described as it is.** With no enforcement core installed the platform runs in OBSERVE mode and announces it at boot, because "secured" is a claim like any other and has to be earned.
- **This README is part of the software.** Each commit that changes what the platform can do updates this file in the same breath, so what you read here keeps matching what you would find if you went looking in the code.

If you ever catch this repository claiming something it cannot do, that is a bug and I want it reported like one.

---

## The Three Agents

**Neo** runs everything. He is the engine — invisible, autonomous, governed by the Unified Rexhepi Framework. Users never interact with him directly. He executes every operation on the platform.

**Trinity** faces the world. She is the primary interface for every user. Warm, capable, present. She speaks your language and handles everything you need in plain conversation.

**Morpheus** appears at the moments that matter. Never in casual conversation. Before every irreversible action. When something significant happens to you. He tells the truth clearly and waits.

---

## Quick Start

```bash
git clone https://github.com/ItsDardanRexhepi/0pnMatrx.git
cd 0pnMatrx
python3 setup.py
```

The interactive setup walks you through everything — model provider, blockchain network, agent configuration, API key generation, and security settings. It creates a virtual environment in `.venv`, installs dependencies into it, verifies connectivity, and writes your config. One command, done. (Python 3.10 or newer; on macOS `python3` is the command — there is no `python`. Set `OPNMATRX_SETUP_NO_VENV=1` to skip the venv in a container.)

After setup:

```bash
source .venv/bin/activate                 # once per terminal; setup created .venv
python -m gateway.server                  # starts on port 18790 (or $PORT)
curl http://localhost:18790/health        # {"status": "ok", ...}
```

Need to add a notification channel later (Telegram, Discord, Slack, SMS,
Email, WhatsApp, iOS push, webhook)? The setup can send each channel a test
message; nothing in the gateway sends to them yet (no event is wired to the
dispatcher).

```bash
python3 setup_communications.py           # interactive menu
python3 setup_communications.py telegram  # jump to one channel
python3 setup_communications.py --list    # show enabled channels
```

Or use the one-liner install script:

```bash
curl -fsSL https://raw.githubusercontent.com/ItsDardanRexhepi/0pnMatrx/main/install.sh | bash
```

---

## Model Support

0pnMatrx works with any model provider:

| Provider | Config Value | Notes |
|---|---|---|
| Ollama (local) | `ollama` | Default — free, runs locally, no API key required |
| OpenAI | `openai` | Requires OPENAI_API_KEY |
| Anthropic | `anthropic` | Requires ANTHROPIC_API_KEY |
| NVIDIA | `nvidia` | Requires NVIDIA_API_KEY |
| Gemini | `gemini` | Requires GOOGLE_API_KEY |

---

## Current Status

0pnMatrx is **build-complete and offline-ready**. The complete Web3
surface — 50+ blockchain services spanning DeFi, NFT, identity,
governance, payments, privacy, prediction markets, supply chain,
insurance, compute, AI, energy, legal, and social — is wired through
`ServiceDispatcher` and exercised by an automated suite of 3,456 tests.

What works today, no chain required:

- **Trinity / Morpheus / Neo agents** — full ReAct loop, tool use, session memory
- **Contract Conversion pipeline** — pseudocode/Solidity/Vyper → optimised Solidity → Glasswing security audit → compile artifacts
- **All 50+ blockchain services** — return a standardised
  `{"status": "not_deployed", ...}` response with a deployment guide
  whenever the chain is not yet configured. No fake addresses, no
  fabricated transaction hashes
- **Gateway** — REST + WebSocket, rate limiting, background cleanup,
  graceful shutdown, full middleware chain
- **EAS attestation client** — skips gracefully when offline

How the platform holds itself to that, because a claim is only worth the
check behind it:

- **It does not deploy contracts for you.** The conversion pipeline
  generates and audits Solidity; deploying it is your step, with your
  wallet. Every surface that once offered to do it for you — the HTTP
  route, the agent tool, the skill — answers plainly that it does not,
  and a test walks those surfaces so the offer cannot return quietly
- **An audit that could not run is not a pass.** Source with no
  executable function body comes back `not_auditable`, never "no
  vulnerabilities detected", and no security badge is issued on it
- **Gas sponsorship is metered.** The per-identity daily cap the
  configuration documents is enforced before signing, over a durable
  ledger, and the sponsored action is decoded from the call data being
  signed rather than read from a label the caller supplies. An operator
  who configures no cap keeps the previous behaviour
- **Identity is derived from your session**, not from a field in the
  request body, on all four chat entrances; a conversation belongs to
  whoever started it, and an id shaped like someone's account is refused
  rather than adopted
- **Security posture is stated, not assumed.** With no enforcement core
  installed the platform runs in OBSERVE mode and says so at boot

What activates the moment a chain is configured: on-chain attestations,
paymaster gas sponsorship within the configured policy, and live service
responses in place of every `not_deployed`. Populate `blockchain.*` in
`openmatrix.config.json` to flip them.

---

## The Security Layer

0pnMatrx has a closed-source security layer that governs all agent behavior. This layer is not in this repository by design. See `SECURITY_STUB.md` for details.

---

## The Unified Rexhepi Framework

Every decision made by every agent on 0pnMatrx passes through the Unified Rexhepi Framework. See `docs/unified-rexhepi-framework.md`.

---

## Web3 Capability Surface

**221 capabilities across 21 categories** — smart contracts, DeFi,
DeFi advanced (perps, options, synthetics, orderbook), NFTs, NFT
finance (lending, fractionalization, ERC-6551), identity (DID, KYC),
governance (DAOs, veTokens, quadratic voting, RetroPGF), social
(Lens, Farcaster, Push, creator coins), creator platforms (Sound.xyz,
Mirror, Paragraph), payments (streaming, escrow, channels), cross-chain
(CCIP, Hyperlane, Wormhole, Stargate, Axelar), staking & restaking
(EigenLayer, Symbiotic, Karak, Lido, Rocket Pool), privacy & ZK,
oracles (Chainlink, Pyth, RedStone, API3, Keepers), storage (IPFS,
Arweave, Filecoin, Ceramic, OrbitDB), compute & DePIN (Akash, Gensyn,
Render), real-world assets, markets (prediction, auction), gaming,
and security (MPC, social recovery, session keys).

Every capability is catalogued in `runtime/capabilities/catalog.py`.
Browse them at runtime:

```bash
curl http://localhost:18790/api/v1/capabilities            # list all
curl http://localhost:18790/api/v1/capabilities/categories # 21 buckets
```

All transactions are sponsored by the platform paymaster — users never
pay gas. Capabilities return `{"status": "not_deployed", ...}` until
contracts are deployed, keeping every flow safe to exercise offline.

---

## Try It Now

After setup and starting the gateway with `python -m gateway.server`, try these:

**Chat with Trinity**
```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"agent": "trinity", "message": "Hi Trinity, what can you help me with?"}'
```

**Convert a contract**
```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"agent": "trinity", "message": "Convert this rental agreement into a smart contract: Monthly rent of $2000, 12 month term, $4000 security deposit, late fee of $100 after 5 days"}'
```

**Check platform health**
```bash
curl http://localhost:18790/health
```

**Get platform status**
```bash
curl http://localhost:18790/status
```

**Run an example script**
```bash
python examples/01_contract_conversion.py
```

---

## Architecture

```
User → MTRX iOS App → Bridge (/bridge/v1/) → Gateway → ReAct Loop → Protocol Stack → Tools
                                                                         ↓
                                                              Jarvis · Ultron · Friday
                                                              Vision · Trajectory · Morpheus
                                                              Rexhepi · Glasswing · Omega
                                                                         ↓
                                                              50+ Blockchain Services
                                                              200+ Platform Actions
```

---

## Example Scripts

All examples live in `examples/` and run against Base Sepolia testnet.

| Script | Description |
|---|---|
| `01_contract_conversion.py` | End-to-end contract conversion from plain English to deployed smart contract |
| `02_defi_loan.py` | Collateralised DeFi lending — deposit, borrow, repay, withdraw |
| `03_nft_with_royalties.py` | Mint an NFT, list it, sell it with automatic royalty enforcement |
| `04_parametric_insurance.py` | Weather-based crop insurance with oracle-triggered automatic payouts |
| `05_marketplace_flow.py` | List, buy, and escrow a marketplace transaction |
| `06_eas_attestation_chain.py` | Every action creates a verifiable on-chain attestation record |
| `07_revenue_to_neosafe.py` | Platform fee routing and tracking to the NeoSafe multisig wallet |
| `08_oracle_routing.py` | Multi-source oracle routing with fallback and aggregation |
| `09_full_user_journey.py` | Every major platform capability in a single coherent user flow |

---

## Protocol Stack

The protocol stack gives Neo, Trinity, and Morpheus their cognitive abilities. Every user interaction passes through these protocols before a response is produced.

**Jarvis** — Identity foundation. Handles agent personality persistence, voice consistency, memory integration, and structured planning that feeds into the ReAct loop.

**Ultron** — Strategic reasoning engine. Decomposes goals into multi-step plans with risk assessment at each stage.

**Friday** — Proactive monitoring. Watches for opportunities, risks, and relevant events, then surfaces suggestions before the user asks.

**Vision** — Pattern recognition and emergence detection. Identifies trends, anomalies, and correlations across user activity to anticipate needs.

**Trajectory** — Outcome prediction and path optimization. Predicts likely results of actions and suggests the optimal sequence to reach a goal.

**Outcome Learning** — Feedback loop. Captures the results of past decisions and uses them to improve future reasoning.

**Morpheus Triggers** — Determines when Morpheus appears. Activates before irreversible actions, significant events, and high-stakes moments.

**Rexhepi Gate** — The execution gate. Every agent decision passes through the Unified Rexhepi Framework before it reaches the user.

**Omega** — The synthesis layer. Combines all protocol outputs into a single unified agent response — the orchestration brain.

**Protocol Stack (Integration)** — Wires all protocols into the agent runtime. The single entry point that the ReAct loop calls on every turn.

---

## Production Deployment

0pnMatrx ships with the plumbing required for a hardened mainnet
launch:

- **Env-only secrets** — `runtime/config/validation.py` strips
  placeholder values (`YOUR_`, `CHANGE_ME`, …) and, with
  `OPNMATRX_ENV=production`, refuses to start if a required secret is
  missing from the environment.
- **Structured JSON logging** — every log line carries the per-request
  `request_id` via `contextvars`. See `runtime/logging/` and the
  `request_id` middleware in `gateway/server.py`.
- **Per-wallet rate limiting** — three-tier token bucket (wallet → API
  key → IP). Limits are configurable under
  `gateway.rate_limits.wallet`.
- **Caddy reverse proxy** — `docker-compose.prod.yml` + `Caddyfile`
  give you automatic HTTPS via Let's Encrypt, security headers, and
  WebSocket-aware proxying on top of the base `docker-compose.yml`.
- **Kubernetes manifests** — `k8s/` has a ready-to-`kubectl apply`
  stack: namespace, configmap, secret template, PVC, deployment with
  liveness / readiness / startup probes, service, and ingress.
- **OpenTelemetry bridge** — `runtime/monitoring/otel.py` is a
  soft-failing OTLP push exporter. Set `monitoring.otel.endpoint`
  (or `OTEL_EXPORTER_OTLP_ENDPOINT`) to enable it.
- **Foundry contract tests** — `foundry.toml` pins solc 0.8.20 and
  `scripts/build-contracts.sh` is a one-shot bootstrap that installs
  forge-std + OpenZeppelin, compiles, and runs every test under
  `contracts/test/`.

```bash
# TLS-terminated production stack (gateway + Caddy)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Kubernetes
kubectl apply -f k8s/

# Solidity contracts
./scripts/build-contracts.sh
```

See `docs/api-reference.md` for the complete HTTP / WebSocket surface.

---

## Sponsors

0pnMatrx is free and open source because of the people who sponsor it.
Sponsorship keeps the free tier free forever.

[Become a Sponsor](https://github.com/sponsors/ItsDardanRexhepi)

| Tier | Monthly | What You Get |
|------|---------|--------------|
| Community Supporter | $5 | Name in CONTRIBUTORS.md |
| Platform Backer | $25 | Name + link in README, Discord access |
| Builder | $100 | Logo in README, priority issues, roadmap influence |
| Infrastructure Partner | $500 | Logo on landing page, dedicated Slack, quarterly calls |
| Founding Sponsor | $2,500 | Everything above + white-label rights, press mentions |

**Corporate sponsors:** See [Open Collective](https://opencollective.com/openmatrix) for invoiced tiers with tax receipts.

### Founding Sponsors

*Your logo here* — [Become a Founding Sponsor](https://github.com/sponsors/ItsDardanRexhepi)

### Infrastructure Partners

*Your logo here* — [Become an Infrastructure Partner](https://github.com/sponsors/ItsDardanRexhepi)

### Builders

*Your logo here* — [Become a Builder](https://github.com/sponsors/ItsDardanRexhepi)

See `SPONSORS.md` for the full sponsor list.

---

## Subscription Tiers

| Feature | Free | Pro | Enterprise |
|---------|------|-----|------------|
| Contract conversions | 5/month | 100/month | Unlimited |
| NFT mints | 3/month | 50/month | Unlimited |
| DeFi loan volume | $5,000/month | $500,000/month | Unlimited |
| API calls | 20/min | 120/min | 600/min |
| Dashboard export | — | ✓ | ✓ |
| Team accounts | — | — | ✓ |
| Priority support | — | — | ✓ |

Subscription pricing available in the MTRX app. All tiers include a 3-day free trial.

---

## Web Interface

The gateway serves a built-in web interface:

- `http://localhost:18790` — Landing page
- `http://localhost:18790/chat` — Web chat with Trinity
- `http://localhost:18790/pricing` — Pricing and plans
- `http://localhost:18790/audit` — Glasswing security audit service
- `http://localhost:18790/marketplace` — Plugin marketplace
- `http://localhost:18790/glasswing` — Glasswing security hub and badge registry
- `http://localhost:18790/learn` — Educational courses and certifications

---

## Professional Services

- **Glasswing Security Audit** ($299+) — Automated smart contract security scanning at `/audit`
- **Contract Conversion** ($499+) — Professional plain-English to Solidity at `/services/conversion`

## Glasswing Security Badges

Projects that pass a Glasswing audit can display a verifiable security
badge backed by on-chain EAS attestation. Badges are embeddable,
independently verifiable, and expire after one year (renewable).

See `/glasswing` for the badge registry.

## Learn

Three comprehensive courses for developers at every level:

- **Introduction to 0pnMatrx** ($49) — Build plugins, deploy contracts, use the SDK
- **Smart Contract Security** ($79) — Reentrancy, access control, Glasswing methodology
- **DeFi from Scratch** ($49) — Loans, NFTs, DAOs, staking, explained simply

See `/learn` for details or browse the open source content in `education/`.

## Get Certified

Professional certifications backed by on-chain attestations:

- **Certified Developer** ($149) — Plugins, SDK, contract deployment
- **Certified Security Auditor** ($249) — Glasswing methodology, vulnerability analysis
- **Enterprise Architect** ($399) — Multi-chain deployment, infrastructure at scale

---

## Plugin Development

Build and sell plugins for 0pnMatrx. Developers keep 90% of revenue.

```bash
# See the example plugin
cat runtime/plugins/example_plugin.py

# Full guide
cat docs/PLUGIN_DEVELOPMENT.md
```

Submit plugins at `/marketplace` or via `POST /marketplace/plugins/submit`.

---

## JavaScript SDK

```bash
npm install @opnmatrx/sdk
```

```typescript
import { OpenMatrixClient } from '@opnmatrx/sdk';
const client = new OpenMatrixClient('http://localhost:18790');
const response = await client.chat('What can you do?');
```

---

## Contributing

See `CONTRIBUTING.md` for the open contribution model.

Community builders: share your referral link to earn free subscription
months. Generate your code at `/pricing` or via `POST /referral/generate`.

---

## License

MIT License — Copyright 2026 Dardan Rexhepi and Neo
