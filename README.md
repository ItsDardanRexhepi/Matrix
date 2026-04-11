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

- Convert any traditional contract into a self-executing smart contract, no lawyers, no delays, no broken promises
- Access DeFi loans starting at $10,000 with no bank, no credit check, and no gatekeeping
- Create NFTs and register your creative work with automatic royalty enforcement on every future sale, forever
- Co-own property, vehicles, and real-world assets with anyone in the world through legally enforceable smart contracts
- Own and control your digital identity, share only what you choose, with whom you choose, for as long as you choose
- Convert your business into a DAO with transparent governance, on-chain voting, and automatic treasury management
- Send money anywhere in the world instantly with zero fees
- Register and protect your intellectual property with an immutable on-chain timestamp that proves ownership forever
- Build and deploy blockchain applications and games, no Solidity required
- Trade tokenized securities 24 hours a day, 7 days a week, globally, with instant settlement
- Access parametric insurance that pays automatically when conditions are met, no claims, no adjusters, no waiting
- Stake your assets and earn yield at better rates than any major platform
- Verify the complete history of any product, property, or asset before you buy it
- Participate in governance and voting that is tamper-proof, transparent, and permanently recorded on-chain
- Watch the platform come alive through the real-time social feed — every deployment, swap, mint, and vote, ranked and streamed live
- And much more, all free, all yours, all open

Your companions Trinity, Morpheus, and Neo are with you every step of the way.

I genuinely hope this project changes your life the way building it has changed mine.

I would like to personally thank every community that is part of this journey, the developers, the creators, the builders, the dreamers, and everyone who believed that a better system was possible. You are why this exists.

And finally, there is one more thank you waiting at the very end of this repository. I'll leave it there for you to find. Some things are worth reading all the way to the last line.

From Neo and Dardan Rexhepi

Allow your imagination to meet your creativity.

---

## What is 0pnMatrx

0pnMatrx is a free, open source AI agent platform. It combines a personal AI agent with a complete blockchain financial infrastructure, developer ecosystem, legal infrastructure, identity system, and governance architecture — all in one release, all free.

**0pnMatrx** is the open source platform you are looking at now. **MTRX** is the iOS app that brings it all to your phone.

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
python setup.py
```

The interactive setup walks you through everything — model provider, blockchain network, agent configuration, API key generation, and security settings. It installs dependencies, verifies connectivity, and writes your config. One command, done.

After setup:

```bash
python -m gateway.server
```

Or use the install script:

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

0pnMatrx is **build-complete and offline-ready**. Every one of the 30
blockchain services is wired through `ServiceDispatcher` and exercised
by automated tests in `tests/test_e2e_flows.py` and
`tests/test_dispatch_integration.py`.

What works today, no chain required:

- **Trinity / Morpheus / Neo agents** — full ReAct loop, tool use, session memory
- **Contract Conversion pipeline** — pseudocode/Solidity/Vyper → optimised Solidity → Glasswing security audit → compile artifacts
- **All 30 blockchain services** — return a standardised
  `{"status": "not_deployed", ...}` response with a deployment guide
  whenever the chain is not yet configured. No fake addresses, no
  fabricated transaction hashes
- **NeoSafe revenue routing** — queues fees in-memory until live
- **Gateway** — REST + WebSocket, rate limiting, background cleanup,
  graceful shutdown, full middleware chain
- **EAS attestation client** — skips gracefully when offline

What activates the moment a chain is configured: actual contract
deployment, on-chain attestations, paymaster gas sponsorship, and the
NeoSafe ETH transfer. See `ROADMAP.md` → "Blockchain Activation" for the
checklist.

---

## The Security Layer

0pnMatrx has a closed-source security layer that governs all agent behavior. This layer is not in this repository by design. See `SECURITY_STUB.md` for details.

---

## The Unified Rexhepi Framework

Every decision made by every agent on 0pnMatrx passes through the Unified Rexhepi Framework. See `protocols/unified-rexhepi-framework.md`.

---

## Blockchain Infrastructure

30 core blockchain services run natively on Base (Ethereum L2) and
return a well-formed `{"status": "not_deployed", ...}` envelope
whenever a chain is not configured, so every flow is safe to exercise
offline. All transaction fees are covered by the platform paymaster
once deployed — users never pay gas. See
`blockchain/docs/components.md` and `ROADMAP.md` for the activation
checklist.

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
                                                              30 Blockchain Services
                                                              136 Platform Actions
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

See `docs/RUNBOOK.md` for the full on-call playbook and
`docs/api-reference.md` for the complete HTTP / WebSocket surface.

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

See `SPONSORS.md` for the full sponsor list and `docs/SPONSORSHIP.md` for details.

---

## Subscription Tiers

| Feature | Free | Pro ($4.99/mo) | Enterprise ($19.99/mo) |
|---------|------|----------------|----------------------|
| Contract conversions | 5/month | 100/month | Unlimited |
| NFT mints | 3/month | 50/month | Unlimited |
| DeFi loan volume | $5,000/month | $500,000/month | Unlimited |
| API calls | 20/min | 120/min | 600/min |
| Dashboard export | — | ✓ | ✓ |
| Team accounts | — | — | ✓ |
| Priority support | — | — | ✓ |

All tiers include a 3-day free trial. See `/pricing` for full details.

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

See `/glasswing` for the badge registry and `docs/SPONSORSHIP.md` for details.

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
