# The Matrix

[![GitHub Sponsors](https://img.shields.io/github/sponsors/ItsDardanRexhepi?style=flat&logo=github)](https://github.com/sponsors/ItsDardanRexhepi)
[![Open Collective](https://img.shields.io/opencollective/all/the-matrix?style=flat&logo=opencollective)](https://opencollective.com/the-matrix)

---

Hello world,

My name is Dardan. I would like to welcome you to The Matrix, where the world of possibilities are endless and free.

I created this platform because I believe everyone deserves a balanced chance at life, and that they get to decide what they want to do with it, without barriers from others who may be more financially comfortable than they are.

The Matrix is as free as it can be. It welcomes the traditional world we all know and love into a new technological revolution. It is built by the people, for the people, and will always remain that at its core.

On The Matrix, if you can think it, you can achieve it.

What you can do on The Matrix:

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

## What is The Matrix

The Matrix is a free, open source AI agent platform. It combines a personal AI agent with a complete blockchain financial infrastructure, developer ecosystem, identity system, and governance architecture — all in one release, all free.

**This repository is the platform itself**: the gateway, the three agents, the Web3 service surface, the contract-conversion pipeline, the SDKs, and the example scripts. It is the part you can read, run, fork and change, and it is the whole of what the project asks you to trust — everything a request touches on its way in is in this tree.

**MTRX** is the iOS app that brings it to your phone. The enforcing security core is closed source and optional: its seam lives here, and with no core installed the platform runs an inert no-op in OBSERVE mode: its gate allows every action it is asked about and applies none of the core's checks, the platform's own per-agent tool boundary still holds, and it says so at boot. The deployment runtime the maintainer runs is private, and nothing in this repository depends on it.

---

## The goal, and what each commit does about it

The goal is the one I opened with. Everyone deserves a balanced chance at life, and the tools that decide who gets one — credit, ownership, settlement, insurance, a vote that counts — should not sit behind a gate that opens only for people who are already comfortable. I want those tools reachable by anyone with a phone and a connection, and I want the software that reaches them to be readable by the people it serves. That is why the whole platform is here in the open and not a product you are asked to take on faith.

Getting there is not one commit, it is a long line of them, so I hold every one to the same standard:

- **Nothing here claims to do something it does not do.** When a claim in the code, the docs, or this README turns out to be untrue, the rule is to build it true where that is possible, and to correct it plainly where it is not. Both happen, and the correction is written down either way.
- **A fix arrives with the check that catches it.** Every change ships with a test that fails against the old behaviour and passes against the new one, and I run it against the old behaviour first — a test that was never seen failing has not proven anything.
- **A refusal is a feature.** When a service has no chain, it says `not_deployed`. When the platform cannot do a thing, it says so instead of returning something that looks like success. When a number is not known, you get a dash and not a plausible figure. Money is the place where a comforting lie costs the most, so that is the place it is least welcome.
- **A record says what happened, not what was attempted.** Anything here that outlives the call — an attestation, a public feed entry, a claimable balance, a billing counter, an invoice — is written from the verdict the thing it called actually returned. A batch of attestations is judged one attestation at a time, and the ones that did not land go back on the queue instead of being reported as written — except one that was sent and that no receipt confirmed in time, which leaves the queue and is logged under its hash rather than sent again, because a second send could put two claims on the chain where one was made. A transfer is `routed` when a receipt confirms it, `failed` when the chain reverted it, and `pending` when it was broadcast and nobody knows yet — and the attestation follows the receipt, because a claim put on a public chain cannot be taken back. That holds for every action that sends a transaction, not only the ones whose service remembers to wait: sending is not the same event as the chain accepting it, so a bridge, a channel close or a liquidation that has only been broadcast, or a transfer whose receipt did not arrive in time, is recorded as a broadcast, with its hash, and is neither attested on-chain as done nor announced on the feed as done — and not recorded as declined either, because it may still be mined. A KYC credential is issued when its receipt confirms it. The list of methods that send is not kept by hand: a test finds every one of them from the send itself, not from the word it answers with, and fails if any could be recorded as settled without a receipt; a second finds every one that waits for its receipt and holds that it waits through the one helper whose three answers are driven, because the two that waited on their own called a wait that ran out a refusal. Settled, sent, and refused are three different things, and the record says which one it was rather than rounding the middle one to either side. A method that writes a record and calls no contract says `recorded_unsettled` and says plainly that nothing moved, rather than `purchased`, `claimed`, `minted` or `attested`. Cashback you have not been paid stays claimable. A subscription counts the charges that settled. A job whose tools refused is not invoiced, and one whose tools disagree is not invoiced either — an outcome nobody established is not something to bill for, and it is not something to learn from.
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
git clone https://github.com/ItsDardanRexhepi/Matrix.git TheMatrix
cd TheMatrix
python3 setup.py
```

The interactive setup walks you through everything — model provider, blockchain network, agent configuration, API key generation, and security settings. It creates a virtual environment in `.venv`, installs dependencies into it, verifies connectivity, and writes your config. One command, done. (Python 3.10 or newer; on macOS `python3` is the command — there is no `python`. Set `MATRIX_SETUP_NO_VENV=1` to skip the venv in a container.)

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
curl -fsSL https://raw.githubusercontent.com/ItsDardanRexhepi/Matrix/main/install.sh | bash
```

---

## Model Support

Use whichever model you want, from whoever you want. Pick a provider during
setup and The Matrix asks it which models your key can use, newest first — so a
version released after this README was written is on the list. You can also
type any model id by hand, including one newer than the list.

| Provider | Config value | Notes | API key |
|---|---|---|---|
| Ollama | `ollama` | free, local, private — no API key, runs on your machine | — |
| Anthropic | `anthropic` | Claude models | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | GPT models | `OPENAI_API_KEY` |
| xAI | `xai` | Grok models | `XAI_API_KEY` |
| Nous Research | `nous` | Hermes models | `NOUS_API_KEY` |
| Google | `gemini` | Gemini models | `GOOGLE_API_KEY` |
| DeepSeek | `deepseek` | DeepSeek chat and reasoning models | `DEEPSEEK_API_KEY` |
| Mistral | `mistral` | Mistral and Magistral models | `MISTRAL_API_KEY` |
| Groq | `groq` | open models on Groq's fast inference | `GROQ_API_KEY` |
| Together AI | `together` | hundreds of open models, Hermes among them | `TOGETHER_API_KEY` |
| OpenRouter | `openrouter` | one key, most models on the market | `OPENROUTER_API_KEY` |
| Perplexity | `perplexity` | Sonar models with live web grounding | `PERPLEXITY_API_KEY` |
| Fireworks AI | `fireworks` | open models, fast serving | `FIREWORKS_API_KEY` |
| Cerebras | `cerebras` | open models on Cerebras inference | `CEREBRAS_API_KEY` |
| NVIDIA | `nvidia` | NVIDIA NIM endpoints (Hermes and many open models) | `NVIDIA_API_KEY` |
| Mythos | `mythos` | the platform's own Claude-backed profile | `ANTHROPIC_API_KEY` |
| Custom endpoint | `custom` | any OpenAI-compatible API — you give the base URL and model | `MATRIX_MODEL_API_KEY` |

Every provider talks to **its own endpoint with your own key** — nothing is
proxied through another company. The ones marked OpenAI-compatible in
`runtime/models/providers.py` share the request format the industry settled on
(`/chat/completions`), which is why they need no bespoke client; Anthropic,
Gemini, NVIDIA and Ollama each keep their own, because their format differs.
`custom` reaches any endpoint that speaks that format, so a provider missing
from this table is still usable today.

Keeping your model current, after setup:

```bash
matrix models            # what your provider serves right now, newest first
matrix models --check    # is the model you configured still served? (exit 1 if not)
matrix models --latest   # switch to the newest the provider reports
matrix models --set <id> # switch to any version you name
```

The provider list, the setup menu, the environment-variable bridge and the
example config all derive from one declaration in
`runtime/models/providers.py`, so they cannot drift apart — which is how ten
providers came to be missing from a list that claimed to work with "any
provider".

---

## Current Status

The Matrix is **build-complete and offline-ready**. The complete Web3
surface — 50+ blockchain services spanning DeFi, NFT, identity,
governance, payments, privacy, prediction markets, supply chain,
insurance, compute, AI, energy, legal, and social — is wired through
`ServiceDispatcher` and exercised by an automated suite of 4,468 tests,
run against the versions `requirements.txt` locks.

What works today, no chain required:

- **Trinity / Morpheus / Neo agents** — full ReAct loop, tool use, session
  memory. Trinity never holds Neo's execution tools; anything that moves
  value goes through the gated hand-off, and that channel says what
  happened to it. A denial by the security gate, a gate that could not be
  reached, an executor that was not wired and an execution that threw are
  each reported as the refusal they are, and when Neo does run, the
  hand-off relays Neo's own verdict rather than its own opinion of it
- **Contract Conversion pipeline** — pseudocode/Solidity/Vyper → optimised Solidity → Glasswing security audit → compile artifacts
- **All 50+ blockchain services** — return a standardised
  `{"status": "not_deployed", ...}` response with a deployment guide
  whenever the chain is not yet configured. No fake addresses, no
  fabricated transaction hashes. That refusal survives the trip out: the
  HTTP answer is a 503, not a 200, and every envelope the gateway builds
  states the verdict of the action in a `call_outcome` field of its own
  rather than letting its own `ok` stand in for it — on both `/api/v1`
  doors, the dedicated route and the capability-invoke one, which used to
  give opposite answers for the same refusal, and on the mobile bridge,
  where a wrapper that was not told the verdict reads it off the payload
  instead of defaulting to success. A stated verdict is believed over
  everything else, so a defaulted one would outrank the refusal sitting
  inside it, even one the dispatcher had already read and written down.
  No bridge route relayed a payload like that without stating its
  verdict, so the default never did it to a live response; it is gone so
  that the next route cannot. And a refusal the live feed
  does not announce is still written down as a decline, on whichever
  surface refused it: a trail has to show that the platform said no, not
  that nothing was ever asked. The field is spelled that way on purpose: the services here already use the word `outcome`
  for their own data — a prediction market's resolved outcome, a
  dispute's, a proposal's — and while the platform borrowed it, resolving
  a market *to* "failure" made the platform say the *call* had failed
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
- **Gas sponsorship is metered against what the EntryPoint can charge.**
  The per-identity daily cap the configuration documents is enforced
  before signing, over a durable ledger, and each request is priced at
  the EntryPoint v0.6 prefund for a sponsored operation — which counts
  the verification gas limit three times, not once, because that limit
  also bounds the paymaster's postOp — so the cap cannot authorise more
  real spend than it names. The sponsored action is decoded from the call
  data being signed rather than read from a label the caller supplies. An
  operator who configures no cap keeps the previous behaviour
- **The deployment tools will not put the old paymaster on a chain.** The
  paymaster the platform uses is the ERC-4337 verifying one, which pays
  gas out of its own EntryPoint deposit. Its predecessor can send any
  calldata to any address from any authorized key, nothing in the runtime
  calls it, and the tools used to deploy it as their first step and wire
  0.1 ETH to it. They deploy what they declare, they say out loud what
  they will not deploy and why, and a deployment manifest that names the
  old one stops the pipeline before a single address is configured or a
  single transfer is sent. Deploying it is now a deliberate act by hand,
  which is the only kind of act it should ever have been
- **Identity is derived from your session**, not from a field in the
  request body, on all four chat entrances; a conversation belongs to
  whoever started it, and an id shaped like someone's account is refused
  rather than adopted. Which agent answers is settled by one resolver, so
  a different spelling of a privileged agent's name is not a way past the
  operator check
- **A record names who the platform resolved, not who the request said.**
  The attestation, the decline record, the broadcast record and the public
  live feed are all attributed to the identity the entry point bound for
  that request, on the dispatcher's path and on the `/api/v1` path alike.
  An address written into the request body no longer outranks it, and
  where nothing was bound it is written down as a claim rather than
  promoted to the actor — so a caller who names somebody else shows up in
  the trail as exactly that, whichever of the three answers the record
  gives, instead of the platform quietly agreeing. The one deliberate
  exception is a privacy action refused on the `/api/v1` path: its decline
  is recorded with no actor and no claim, because naming who was refused
  is exactly what the privacy exclusion exists to prevent
- **Deleting your account is all or nothing.** The conversations, their
  claims, the scoped memory and the erasure record go in a single
  transaction; if any part of it fails the request answers 503 and
  removes nothing, rather than reporting success over data it left behind
- **A payment nobody confirmed is not a payment.** A subscription
  renewal is booked only when the payment gateway says plainly that the
  charge went through, and a gateway is not this platform: the rule that
  silence means success is measured over code written here, and so are
  the platform's own words for success, so neither is applied to a party
  whose way of saying yes or no we have never seen. A gateway answering
  `processing`, `refunded` or `cancelled` has not been paid, and a reply
  that says yes in one field and no in another is not a yes. A charge
  whose answer we cannot read leaves the counters where they are, does
  not push the subscription toward cancellation, and is not presented
  again — it may already have been taken, so it waits for someone to
  check it with the gateway. A renewal nobody tried to charge, because no
  gateway is configured, simply stays due
- **A batch request carries the credential it was sent with.** Each item
  inherits the batch's caller, so an operator's batch reaches what an
  operator reaches and an anonymous one does not borrow more than it
  brought
- **A batch item says what its call did, not that it came back.** The
  item used to carry the sub-route's HTTP status and nothing else about
  the outcome, and a refusal that is a domain answer keeps its `200` on
  purpose — so a refused loan and a granted one were the same item to
  everyone reading it. Each item now states the call's own verdict beside
  the status, and everything downstream reads that instead: the counts
  the platform publishes to its live feed are counts of calls that did
  the thing, and `abort_on_failure` stops at a refusal the transport
  delivered perfectly well. It also stops at an item whose outcome nobody
  established, even one that answered `200` — `pending`, `queued`, a
  record that says nothing settled — because the later items in a
  sequential batch are built on the earlier ones. The verdict is in each
  item for a client to read before it decodes the result; a client that
  decodes on the HTTP status alone still reads a refusal as a result. An
  item that timed out is neither counted nor refused — it was cancelled
  mid-flight, and it may have acted
- **The agent's shell runs only where someone said it may.** It has no
  sandbox: a command runs as the platform's own user, can read the
  platform process's environment and can reach the network. So it refuses
  unless `MATRIX_ENV` declares a development environment or an operator
  opts in, an unset `MATRIX_ENV` refuses too, and a test finds every file
  in this tree that starts the server — from the start command it names,
  not from a list kept by hand — and reads each of them, with the compose
  files and Kubernetes manifests that start it by image, to hold that none
  of them declares one.
  A command it does run gets an allowlisted environment with none of the
  platform's keys in it, which is not isolation, and is why it refuses by
  default
- **Security posture is stated, not assumed.** With no enforcement core
  installed the platform runs in OBSERVE mode and says so at boot

What activates the moment a chain is configured: on-chain attestations,
paymaster gas sponsorship within the configured policy, and live service
responses in place of every `not_deployed`. Populate `blockchain.*` in
`matrix.config.json` to flip them. `CREDENTIALS_NEEDED.md` lists what a
deployment needs, capability by capability: which key or address unlocks it,
where it is set, and what happens while it is unset.

---

## The Security Layer

The Matrix has a closed-source security layer that governs all agent behavior. This layer is not in this repository by design. See `SECURITY_STUB.md` for details.

---

## The Unified Rexhepi Framework

Every decision made by every agent on The Matrix passes through the Unified Rexhepi Framework. See `docs/unified-rexhepi-framework.md`.

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

Gas is sponsored by the platform paymaster **within the policy the
operator configures** — an allowlist of actions and a per-identity daily
cap, decided from the call data being signed. Inside that policy a user
pays no gas; past the cap, or for an action the allowlist does not cover,
sponsorship is refused rather than silently granted, and an operator who
configures no policy sponsors everything. Every transaction the platform
signs goes through that policy, including the ones the services send
through the shared web3 manager — if you configure an allowlist, list
`web3.send_transaction` or those will be refused. The only operations
exempt are the platform's own record-keeping writes, and they are listed
by name in `runtime/blockchain/sponsorship.py` so the exemptions can be
read rather than guessed at. Capabilities return
`{"status": "not_deployed", ...}` until contracts are deployed, keeping
every flow safe to exercise offline.

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
curl http://localhost:18790/health        # liveness: is this process serving?
curl http://localhost:18790/ready         # readiness: should it take traffic?
```

The `models` map in `/health` says which providers **answered**, not which ones
you configured a key for — each one is asked, with a short timeout, and they are
all asked at once so the probe costs one timeout rather than five. `/ready` is
the one an orchestrator should point at: it answers 503 when no provider
answered, or when the platform is running in production with security in
observe-only mode, and it deliberately tells you nothing else. Which check
failed is in the log against the request id, because a readiness endpoint that
announces what is not enforcing is telling whoever asks where to push.

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
| `01_contract_conversion.py` | Plain English to audited Solidity, ready for you to deploy with your own wallet |
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

**Outcome Learning** — Feedback loop. Captures the real result of each tool call and uses it to improve future reasoning. It learns from the outcome the tool actually reported, not from the absence of a crash: most things here refuse by returning a structure (`{"status": "not_deployed"}`, `{"ok": false}`), and a refusal is recorded as a refusal. Where a tool reports something that does not decide whether it worked — `pending` means "not paid" in one service and "record written" in another — the sample is left unlabelled and is not learned from at all. An unlabelled sample costs one data point; a mislabelled one corrupts the success rate and every confidence estimate built on it. It also reads through the platform's own envelopes: a layer that wraps a service's answer may report on the wrapping and never on what it wrapped, so a refusal relayed through the gateway, the bridge or the service dispatcher is still a refusal when it arrives. Where a layer knows something the reader cannot see, it says so in a field of its own instead of leaving it to be inferred — the service dispatcher knows whether an action changes state, which is what separates a call that failed from a successful read of a campaign whose own status is `failed`, and where those two cannot be told apart the answer is again "unknown" rather than a guess. That field is named so the services cannot collide with it, and it cannot talk a refusal into a success: a structure that states one thing and declares the opposite about itself in the same breath is left unlabelled. A check that ran and answered no is a call that worked — an unknown credential is answered, not errored, and a staking read for someone who never staked answers "no position" — while a check that could not look at all still says so. Tools that used to answer a failure in prose now refuse in a structure: `bash`, the file and web tools and every blockchain capability say when they did not do the thing, instead of handing back a sentence with no verdict in it. The same verdict is what a client is told about each tool call — and when nobody established one, the field goes out empty rather than as a tick.

**Morpheus Triggers** — Determines when Morpheus appears. Activates before irreversible actions, significant events, and high-stakes moments.

**Rexhepi Gate** — The execution gate. Every agent decision passes through the Unified Rexhepi Framework before it reaches the user.

**Omega** — The synthesis layer. Combines all protocol outputs into a single unified agent response — the orchestration brain.

**Protocol Stack (Integration)** — Wires all protocols into the agent runtime. The single entry point that the ReAct loop calls on every turn.

---

## Production Deployment

The Matrix ships with the plumbing required for a hardened mainnet
launch:

- **Env-only secrets, and a census that finds the ones that escape** —
  `runtime/config/validation.py` strips placeholder values (`YOUR_`,
  `CHANGE-ME`, … in either spelling) and, with `MATRIX_ENV=production`,
  refuses to start if a required secret is missing from the environment.
  It also walks the loaded config for secret-shaped settings and reports
  any that no env-only entry covers — in production that refusal stops
  the boot, so a new third-party key cannot quietly live in the
  committed file the way the Twitter and Apple ones did. Each entry
  targets the path the code reads: the paymaster's gas-sponsorship
  signer arrives as `MATRIX_PAYMASTER_SIGNER_KEY` at the location the
  example documents, and the oracle keys at `oracle.weather.api_key` and
  `oracle.sports.api_key` — an entry at a path nothing reads bridges a
  value to nowhere while calling the key handled.
- **Structured JSON logging** — every log line carries the per-request
  `request_id` via `contextvars`. See `runtime/logging/` and the
  `request_id` middleware in `gateway/server.py`.
- **Per-wallet rate limiting** — three-tier token bucket (wallet → API
  key → IP). Limits are configurable under
  `gateway.rate_limits.wallet`.
- **No production boot without enforcement** — with
  `MATRIX_ENV=production`, which `docker-compose.prod.yml` and
  `k8s/deployment.yaml` set and `docker-compose.yml` defaults to, the
  gateway refuses to start on the no-op security backend. The
  `Dockerfile` installs only the public requirements, so a production
  image needs the separately installed security core as well
  (`CREDENTIALS_NEEDED.md`, section 5).
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

See `docs/api-reference.md` for the complete HTTP / WebSocket surface, and
`docs/OPS.md` for the operator kit: the read-only checks to run before a
deploy (`./scripts/ops.sh preflight`) and the deploy commands themselves.

---

## Sponsors

The Matrix is free and open source because of the people who sponsor it.
Sponsorship keeps the free tier free forever.

[Become a Sponsor](https://github.com/sponsors/ItsDardanRexhepi)

| Tier | Monthly | What You Get |
|------|---------|--------------|
| Community Supporter | $5 | Name in CONTRIBUTORS.md |
| Platform Backer | $25 | Name + link in README, Discord access |
| Builder | $100 | Logo in README, priority issues, roadmap influence |
| Infrastructure Partner | $500 | Logo on landing page, dedicated Slack, quarterly calls |
| Founding Sponsor | $2,500 | Everything above + white-label rights, press mentions |

**Corporate sponsors:** See [Open Collective](https://opencollective.com/the-matrix) for invoiced tiers with tax receipts.

### Founding Sponsors

*Your logo here* — [Become a Founding Sponsor](https://github.com/sponsors/ItsDardanRexhepi)

### Infrastructure Partners

*Your logo here* — [Become an Infrastructure Partner](https://github.com/sponsors/ItsDardanRexhepi)

### Builders

*Your logo here* — [Become a Builder](https://github.com/sponsors/ItsDardanRexhepi)

See `SPONSORS.md` for the full sponsor list.

---

## What is free, and what is paid

The software in this repository is free, open source, and unlimited: clone
it, run it, change it, and nothing in it meters you. Everything below is the
hosted offering and the services built around it — a separate thing you may
ignore entirely. "All free" in my letter above means this platform; it does
not mean I run infrastructure for everyone at my own cost, and the two should
not be confused.

## Subscription Tiers (the hosted app)

These are the plan limits of the MTRX app's hosted service, not of this
repository. Self-hosting has none of them.

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
- `http://localhost:18790/audit` — Glasswing security audit service
- `http://localhost:18790/marketplace` — Plugin marketplace
- `http://localhost:18790/glasswing` — Glasswing security hub and badge registry
- `http://localhost:18790/learn` — Educational courses and certifications

---

## Professional Services

- **Glasswing Security Audit** — the automated scan itself is in this
  repository and runs locally as part of the conversion pipeline, free. The
  paid hosted service at `/audit` is **not live**: no audit backend is wired
  into the gateway, so `POST /audit/request` answers `503 not_available`
  rather than taking an order it cannot fill. The prices on that page
  describe the intended service, not one you can buy today.
- **Contract Conversion** — likewise: the pipeline is here and free to run;
  the hosted service page describes an offering that is not yet accepting
  work.

## Glasswing Security Badges

Projects that pass a Glasswing audit can display a verifiable security
badge backed by on-chain EAS attestation. Badges are embeddable,
independently verifiable, and expire after one year (renewable).

See `/glasswing` for the badge registry.

## Learn

Three comprehensive courses for developers at every level:

- **Introduction to The Matrix** ($49) — Build plugins, deploy contracts with your own wallet, use the SDK
- **Smart Contract Security** ($79) — Reentrancy, access control, Glasswing methodology
- **DeFi from Scratch** ($49) — Loans, NFTs, DAOs, staking, explained simply

See `/learn` for details or browse the open source content in `education/`.

## Get Certified

Professional certifications backed by on-chain attestations:

- **Certified Developer** ($149) — Plugins, SDK, deploying what the pipeline generates
- **Certified Security Auditor** ($249) — Glasswing methodology, vulnerability analysis
- **Enterprise Architect** ($399) — Multi-chain deployment, infrastructure at scale

---

## Plugin Development

Build and sell plugins for The Matrix. Developers keep 90% of revenue.

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
npm install @the-matrix/sdk
```

```typescript
import { MatrixClient } from '@the-matrix/sdk';
const client = new MatrixClient('http://localhost:18790');
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
