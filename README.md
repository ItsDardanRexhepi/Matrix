# The Matrix

---

Hello world,

My name is Dardan. I would like to welcome you to The Matrix, where the world of possibilities are endless and free.

I created this platform because I believe everyone deserves a balanced chance at life, and that they get to decide what they want to do with it, without barriers from others who may be more financially comfortable than they are.

The Matrix is as free as it can be. It welcomes the traditional world we all know and love into a new technological revolution. It is built by the people, for the people, and will always remain that at its core.

On The Matrix, if you can think it, you can achieve it.

What you can do on The Matrix:

- Scaffold a Solidity contract from a structured declaration (pseudocode, Solidity, or Vyper), with an automatic security scan — the generated interface, state, and function signatures, a draft for you to read, fill in and compile. The platform does not deploy it for you: you deploy it with your own wallet, so the contract is yours from the first block
- Borrow against crypto you already hold — no bank, no credit check, no gatekeeping. You supply collateral to a lending pool and draw a loan against it; how much you can draw follows from what you put up, and the interest accrues on-chain where you can watch it. The collateral is what secures the loan, which is why nobody has to score you
- Create NFTs and register your creative work with an on-chain royalty that every marketplace honouring the ERC-2981 standard pays you on resale
- Co-own property, vehicles, and real-world assets with anyone in the world, with the ownership split, the payouts, and the transfer rules written into the contract itself
- Own and control your digital identity, share only what you choose, with whom you choose, for as long as you choose
- Convert your business into a DAO with transparent governance, on-chain voting, and automatic treasury management
- Record payments today, and send them once settlement is built: the stablecoin-transfer capability records a transfer on its service's in-memory ledger with a tiered fee (0.1% or less by default), and the cross-border payment capability records the payment instruction, keeping no balances, with a flat 0.5% fee. Both answer `recorded_unsettled` — no value moves and no transaction is sent — and a cross-border payment the compliance check stops answers `compliance_hold`. The stablecoin ledger starts empty and only a test helper funds it, so a transfer there is refused for insufficient balance. Neo's own chain tools are a different path, and they do send: with a chain configured, and within the sponsorship policy, `payment` sends ETH or an ERC-20 token and `stablecoin` a stablecoin it lists for the network, each from the platform wallet's own balance and with no fee, and other Neo tools sign ETH and token transfers from that wallet too. Naming Neo takes the operator key on a gateway that has one set, and the Python SDK's `send_payment()` is a chat message asking Neo to use `payment` for ETH and `stablecoin` for a token. The fees the code is known to take are listed under Fees in `docs/blockchain.md`, and network gas is sponsored within the policy the operator configures
- Register and protect your intellectual property with an immutable on-chain timestamp that proves what you had and when you had it
- Build blockchain applications and games with less hand-written Solidity — write the contract as structured pseudocode, read the Solidity draft it generates, compile and deploy it yourself
- Trade tokenized securities around the clock, settling on-chain in the time a block takes, wherever the offering is lawfully available to you
- Access parametric insurance that pays automatically when the data it watches meets the condition, no claims, no adjusters, no waiting
- Stake your assets and earn the yield the protocol actually pays, shown to you before you commit
- Verify the complete history of any product, property, or asset before you buy it
- Participate in governance and voting that is tamper-proof, transparent, and permanently recorded on-chain
- Watch the platform come alive through the real-time social feed — every deployment, swap, mint, and vote, ranked and streamed live
- And much more — open source, yours to run, yours to change

The ones that write to a chain run against a blockchain you configure, and until you configure one, each says so plainly rather than inventing a result: no fabricated addresses, no invented transaction hashes, no number that looks like your balance but isn't. The ones that keep their own records, like the payment ledgers above, run with or without a chain and say that nothing moved.

Your companions Trinity, Morpheus, and Neo are with you every step of the way.

I genuinely hope this project changes your life the way building it has changed mine.

I would like to personally thank every community that is part of this journey, the developers, the creators, the builders, the dreamers, and everyone who believed that a better system was possible. You are why this exists.

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

**Morpheus** appears at the moments that matter. Never in casual conversation. The first time you use a kind of capability, and on an action that cannot be undone. When something significant happens to you. He tells the truth clearly and stops: his note is added to the result of the call it concerns, so it reaches you with that result, after the call has run, and nothing waits for an answer to it.

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

It installs into `~/.the-matrix` (or `$MATRIX_DIR`) and, when there is no
config there yet, starts the same setup. Piped like this, the setup reads your answers from your terminal, not from the pipe. Run
where there is no terminal (a CI job, a provisioning script), it installs,
then stops with a non-zero exit and the command to run setup yourself. The
setup itself, run with its input redirected or closed, stops the same way at
its first unanswered question instead of ending in a traceback.

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
from this table is still usable today. Each client sends the platform's tools
in its provider's own format, whichever of the two shapes a tool is registered
in (`tool_function` in `runtime/models/model_interface.py`).

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
surface — 45 blockchain services spanning DeFi, NFT, identity,
governance, payments, privacy, prediction markets, supply chain,
insurance, compute, AI, energy, legal, and social — is listed in one
service registry (`runtime/blockchain/services/registry.py`).
`ServiceDispatcher`, the agents' way in, reaches 44 of them;
the forty-fifth, real-estate escrow, is reached only by its own routes,
which answer 403 while it is disabled. All of it is exercised by an
automated suite of 6,258 tests, run against the versions
`requirements.txt` locks.

What works today, no chain required:

- **Trinity / Morpheus / Neo agents** — full ReAct loop, tool use, session
  memory. Trinity never holds Neo's execution tools; anything that moves
  value goes through the gated hand-off, and that channel says what
  happened to it. A denial by the security gate, a gate that could not be
  reached, an executor that was not wired and an execution that threw are
  each reported as the refusal they are, and when Neo does run, the
  hand-off relays Neo's own verdict rather than its own opinion of it.
  Every tool call asks the security seam with the caller identity the
  request's entry point bound, never one the model wrote into its
  arguments, and the hand-off's gate is told the same identity, so a
  decision the core makes about who is calling can bind at both. On every
  chat entrance that identity comes from the session the caller presents;
  only an operator integration may name the user it acts for, and an
  anonymous caller has none. A wallet address has one spelling wherever
  the platform names a caller (`0x` and its digits in lower case,
  `runtime/auth/identity.py`), so a wallet that signs in with its address
  in another case is still the same caller, an owner a record holds in
  another case is still its owner, what the gateway stored under a wallet
  before that rule is rewritten in it the first time the gateway opens its
  database (one wallet stored under two spellings becomes one, its turns in
  order), and the gateway starts the security core's gate only when the
  core names a caller by the same rule
- **Contract Conversion pipeline** — pseudocode/Solidity/Vyper → generated Solidity draft → Glasswing security audit; it compiles and deploys the result only where an operator turns on `conversion.auto_deploy`
- **Blockchain services, with no chain configured** — answer with what
  happened rather than a success: a stake returns a standardised
  `{"status": "not_deployed", ...}` response with a deployment guide, a
  cross-border payment is recorded and says nothing moved
  (`recorded_unsettled`), and a swap quote is computed from the service's
  own pools. No fake addresses, no fabricated transaction hashes. A
  not_deployed refusal survives the trip out: the
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
  vulnerabilities detected", and no security badge is issued on it. The
  agent's `audit_contract` skill says NOT AUDITABLE too, and it lists a
  contract's findings by rule id instead of failing on them
- **A skill runs on the server's configuration, not the model's.** The
  agent's chain skills (balance, transaction lookup, gas estimate) read the
  chain this gateway is configured for, through the platform's shared
  connection; a `config` the model writes into a tool call is dropped
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
- **What a tool brings back is marked as data, not orders.** When an
  agent reads a page, a file or another service, the text reaches the model
  inside an envelope that names the tool, says the content is untrusted
  and not an instruction, and closes on a random marker the content cannot
  know, so nothing inside it can pass itself off as being outside it. That
  is a label, not a lock: a model can still be talked into things by text
  it was told not to trust, and what is enforced — the security gate,
  which tools each agent may hold, the shell's refusal outside a declared
  development environment — is enforced elsewhere
- **No request can have the platform's key sign or revoke an attestation
  it wrote.** An attestation that an agent did something is written when
  the platform executes the action, never composed from a request. The
  agent-identity tool and the general attestation tool (`eas`) sign none
  on demand, and `eas` revokes none because a request names it. The
  services layer's attestation actions (`create_attestation`,
  `batch_attest`, `revoke_attestation`) are refused the same way at every
  door that dispatches them — capability invoke, `/bridge/v1/action`,
  Trinity's escalation to Neo and Neo's `platform_action` — whoever is
  asking, the operator key included; so are two more that signed a
  statement the request wrote: `submit_retropgf`, an application attested
  under the platform's own schema by default, and `issue_kyc_credential`,
  which read the verification it attested from the request itself. Nor
  can a request aim the platform's key at the EAS contract directly:
  `smart_contract`'s `send`, which signed any call the request composed,
  the EAS contract's own `attest` and `revoke` included, is refused by the
  tool and, before the tool runs, by the tool dispatcher, whoever asks. A
  test drives that call through the tool, the dispatcher, all four chat
  entrances with the operator key, capability invoke, `/bridge/v1/action`
  and both hand-offs, under the default sponsorship policy, and reads what
  reaches the chain. A registration names one of the
  platform's own three agents, and verifying one checks that the
  attestation is the platform's own registration of that agent, not merely
  one that exists. Every other attestation a blockchain tool signs has a
  fixed statement, and the address it is about — an identity
  registration, an achievement, an IP registration, an investor
  whitelisting — can be no address but the one your session is bound to;
  the same holds for a DeFi supply or borrow made for you, and for the
  account an NFT or game-item transfer moves from. A cross-border
  payment's compliance record names no address at all, since that call
  pays nobody. Tests trace, in the source, each value that reaches the
  statement or the subject of an attestation these tools make back to a
  constant or to the request as it was written, through the shapes they
  name (a field of the request, local names bound by an assignment, a loop,
  `with` or `match`, the `self` attributes the module writes, conversions),
  and report as a failure a value in any other form; report a request
  written into before its field is read — directly, or through a name bound
  to it by an assignment, an `and`/`or`, a conditional or a `match` capture
  — or handed to code they do not read; report each way of reaching the
  attestation they name and cannot read; walk every call the platform's
  wallet signs (next point); and drive every one of those doors. They read
  the shapes they name and no others, and do not claim those are every
  shape: reviews have found shapes past them before, and each found is now
  named and planted. Four limits, stated: the next
  point's (a timelock's or a governor's inner call, which that contract
  makes as itself); a record about your own
  address is still your word (the platform checks no achievement and no
  investor's eligibility); the records the services layer writes about
  operations it ran (a cross-border payment, an insurance claim, a
  royalty) carry what that operation was asked, and no test walks those
  yet; and a reading of the source cannot see code replaced while the
  platform runs
- **No request composes a call or a message in a transaction the
  platform's wallet signs, in the shapes a test reads.** Every transaction
  the platform's wallet signs, as that test reads it, calls a function
  named in its own code (or, with `conversion.auto_deploy` on, deploys a contract the
  conversion pipeline generated and its audit passed), and none carries
  a call or a message the request wrote — calldata for another call, a
  cross-chain message — except the limit named below (an attestation's
  statement is the point above). The few request-written bytes a signed
  call does carry are listed in the test by name, each with the reason
  it is neither (an address encoded as bytes; the input an automation
  job hands the contract the request named for it). A request may supply
  other arguments. At the blockchain tools the ones that must be your own
  address are checked, as above. In the services layer a test lists every
  address it reads a request supplying to a call the platform signs, 26,
  each with what it is — 14 name who receives, holds or is credited with
  what the platform's own call pays, lends, stakes, delegates, mints or
  creates (a reward's recipient, a loan's on-behalf-of account, a keeper
  job's upkeep, a restaking receiver, a payment channel's partner among
  them), 8 name which of the platform's own tokens or contracts the call
  uses, 2 name the contract the call itself is sent to (a breeding
  contract and a Sound.xyz drop), and 2 sit behind a pair every door
  refuses; two more, a token bridge's receiver and a Stargate recipient,
  travel encoded as bytes and are listed with them. A new one fails the
  test until it is read. A user session is refused every action the next
  point's test finds reaching one of them, by its own method or by one it
  hands the call to, or held to its own address (next point); for the
  operator's key they are the platform's value moving where a request
  says, which is the security gate's to evaluate and which, with no
  enforcement core installed, it observes and does not refuse. The `smart_contract` tool compiles, reads and verifies
  and signs nothing: its `send` let a request pick the contract, the
  function, the arguments and the value, and the tool dispatcher now
  refuses it before the tool runs, for every caller. A token-bound account's
  `execute_as_tba` is refused: it signed the request's call, a
  delegatecall if asked, from the platform's wallet and with the
  platform's ETH, to whatever contract the request named as the account.
  The four cross-chain message sends (`send_cross_chain_message`,
  `bridge_hyperlane`, `bridge_wormhole`, `bridge_axelar`) are refused,
  because the receiving chain reads the platform's wallet as their
  sender, and a CCIP token bridge carries no message: it refuses a
  request that brings one. Nor does the platform's wallet hand an account
  to a new owner or a new key: `recover_wallet` and `create_session_key`
  sent their module call from the platform's wallet with the addresses the
  request named, so the platform's standing with the module, not the
  account holder's, authorized it. `execute_as_tba`, the four sends and
  those two are each refused in the service and at every door, whoever
  asks, and the component registry the app reads offers none of them, nor
  any other action every door refuses. A configured
  sponsorship allowlist binds with or without a daily cap. A test walks
  every `sign_transaction` and `send_transaction` call in `runtime/` and
  `gateway/`, follows each bytes input a named function carries through
  the binding forms it names, and fails on one it cannot read as a
  constant unless it is listed with its reason; it fails on a transaction
  written into through any target or method it names, or handed on — to a
  call, a container, an attribute or another name, directly or through
  `or` or a conditional — before it is signed; and every other key
  signature there is listed where it is made. It reads the shapes it names
  and no others, and does not claim those are every shape. The limits, stated: `governance`'s timelock schedule and execute
  and a `dao` proposal carry an inner call the request wrote, which the
  timelock or governor makes as itself under whatever role the platform
  holds there, a deployment fact this repository cannot see; those are
  Neo's tools, which no chat without the operator key reaches. The
  paymaster signs, with a platform key, a digest of a user operation the
  request composes, which commits the paymaster's deposit to that
  operation's gas and makes the platform the sender of nothing: the
  operation runs only if its own account's validation accepts it, and
  without a session the daily cap is metered against an address the
  caller writes. And a function the code names can be sent to a contract
  the request names, whose own code then runs with the platform's wallet
  as its caller: the test reads that contract where the function builds
  it from what it was handed, and lists the two it finds (a user session
  is refused both, next point); one stored on `self` by another request,
  or taken from another object's state, it does not read. A platform
  credential other than the wallet's key — the operator's MPC cluster, a
  publishing account, a storage node, a provider account — signs or
  publishes off the chain, which this test does not read. The next
  point's test walks every HTTP request a services-layer method sends, in
  the shapes it names, and a user session is refused each action it finds
  reaching one a platform credential makes on what the request names; the
  operator's key keeps those over `/bridge/v1/action` and Neo's
  `platform_action`
- **A user session does not have the platform act on what it names.** In
  the services layer the platform's wallet signs, and credentials the
  operator configured act, for whoever reaches them. A user session — the
  app's credential — and chat acting for one (Trinity's hand-off to Neo,
  and `platform_action`) are refused, at capability invoke,
  `/bridge/v1/action` and the tool dispatcher, each action the test below
  finds, in the shapes it reads, in which the platform's wallet or a
  platform credential would sign, pay, publish or authorise while the
  request names the payee, the account, the asset, the contract the call
  is sent to, the key, the digest or the content, or in which the
  platform's server would send, with a platform credential, a request
  whose address, method, headers, query names or body the request writes:
  the platform's funds
  sent to a payee the request names or spent on an asset it names (a
  compute reward's recipient, a token bridge's receiver, a Stargate
  recipient, a loan's on-behalf-of account, a keeper job's upkeep, a
  restaking receiver or operator, a payment channel's partner, a delegate,
  an auction's or a bribe's token, a token-bound account's NFT among
  them); a call from the platform's wallet to a breeding contract the
  request names (`breed_nft`); a threshold
  signature the operator's MPC cluster makes over the request's digest
  under the key id it names (`mpc_sign`); a post under the platform's
  publishing account, a cast through a Farcaster signer the platform's key
  reaches, a write to the platform's storage node or database, a job or a
  lease on its provider account, a payment from its payment node, a KYC
  applicant opened or read with its KYC credential; and an oracle request
  that would have the platform's server send what the request wrote to
  the address it names (`custom`) or read its sports provider, with its
  key, at a path the request writes; a read of the RedStone gateway with
  the platform's API key at the data-service path the request writes
  (`redstone_request`); an oracle type sent as anything but
  a price, a weather reading or randomness, of whatever type, is refused,
  not raised on. The refusal is decided on the method an action reaches,
  not on the name it is called by: an action whose method hands the call
  on, inside the services layer, to one of those is refused with it —
  `compute_job_submit` is privacy's own name for the compute job, and
  privacy's `decentralized_store` and `ipfs_pin` hand the call to the
  Filecoin store — and so is a
  `platform_action` `service` override onto such a method. The operator's
  key keeps each of them over `/bridge/v1/action` and Neo's
  `platform_action`; capability invoke runs, for any caller, only what the
  catalog marks available, and it marks only those three of them so.
  Where the one address a request names is the one the platform acts for
  and it spends only gas on it — a Lens profile, a social or creator
  token, a Push subscription — the action is kept for a session and bound:
  it must name the session's own address, and a session bound to no wallet
  is refused. The list is derived, not only written: a test takes every
  address a request supplies to a call the services layer signs, as the
  signing census reads them, walks every HTTP request a services-layer
  method sends, through the shapes it names, and reads what rides in each
  part of each of those requests: a value the request wrote, the
  platform's configuration, a credential read from it. It follows each
  method a dispatch can run to what that method hands the call on to
  inside the services layer: another method of its class, a function, a
  method of another service or of an object the service holds, the
  object's class read from what builds it and carried through the forms
  its docstring names, and a method or a function held on `self`, in a
  class or a module table, in a lambda or handed to another object that
  holds it. It fails on any action that reaches what the walks find and
  is not refused, handed on, bound, held or listed with its reason; on an
  action that reaches a request whose URL or method the request writes,
  or that carries a platform credential beside a header, a query name or
  a body the request writes (or, on anything but a read, a query value),
  and is not refused, handed on, bound or held, whether or not it is
  listed as a read; on a table entry the walks do not find; on a call in
  that reach on an object it cannot place whose method has the name of
  one that reaches a send; and on a call through a callable held on
  `self` that it cannot place. A read that carries a platform credential
  and only query values the request writes, to an address the platform
  fixes, is kept for a session and listed with its reason: the weather
  reading and the cross-chain message tracker. It does not read an
  amount, an object handed in from outside the services layer, code
  outside it, or a shape it does not name.
  `POST /api/v1/stablecoin/transfer` is not a session route, and
  `transfer_stablecoin` is refused to a session at every dispatcher
  with it: each takes its sender from the request, and nothing binds that
  sender to the caller. The route records nothing, for any caller: its
  handler hands the service's transfer `sender` and `recipient`, which it
  does not take (it takes `from_addr` and `to_addr`), so a body with the
  four fields the handler requires and an amount that is a number is
  answered 400, and one whose amount is null, a list, an object or a
  string that is not a number is answered 500. The capability
  records only on the service's in-memory ledger, which starts empty and
  which only a test helper funds, so for the operator's key it answers
  that the balance is insufficient. The component registry the app reads offers
  none of the actions `runtime/access_policy.py` refuses a session, itself
  or with what it hands the call to; it still offers 22 actions whose
  dedicated routes a session is refused, `transfer_stablecoin` among them,
  and every dispatcher refuses a session each of those as its route does.
  The capability invoke route runs nothing the catalog marks unavailable,
  whoever asks
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
- **Durable execution is off unless it is turned on.** With
  `engines.durable.mode` (or `MATRIX_DURABLE_MODE`) at `off`, the default,
  nothing below runs and every action behaves as it did before it existed.
  At `shadow`, each state-modifying action the service dispatcher runs, and
  each platform-key signing call of the blockchain tools, gets a run in
  `workflow_runs` (START, RUNNING, then COMPLETE, FAIL or ABORT) with its
  steps in `workflow_steps`; the attestation and the feed entry the
  dispatcher delivers get `outbox` rows; an `Idempotency-Key` sent to
  `POST /bridge/v1/action` is recorded in `idempotency_keys` against the
  first run that used it; and every answer is the one `off` gives, a replay
  included. Rows written, and the time it takes to write them (below), are
  shadow's only effects: it refuses nothing, and `GET /ready` does not read
  it, so a shadow instance whose engine or loop fails keeps serving as `off`
  would, and says so in its log. At `on`, for
  the actions of the canary, the run is the only way they run: it is written
  before the action is called, and an action whose run cannot be written is
  not called. The canary moves in two stages, first the blockchain tools'
  signing calls, then every state-modifying action of the service
  dispatcher; `engines.durable.canary` (or `MATRIX_DURABLE_CANARY`) says how
  far it has moved, `twins` for the first stage alone or
  `twins,state_modifying`, the default, for both, and any other value moves
  nothing. The outbox's one loop sends the attestation, trying again with
  backoff, up to five attempts in all, only while an answer says it did not
  land and was not sent (one sent and not confirmed is never sent again),
  and publishes the feed entry once. It sends only a record the attestation
  service would have queued: one the service refuses, such as one under a
  schema that is not configured, is refused as it is at `off`. A replayed
  `Idempotency-Key` runs nothing and gets the first answer, or, when that
  answer is no longer held (it is kept in memory by the process that gave
  it, for up to 24 hours and at most the latest 4,096), an error that says
  so. A key belongs to the kind of credential and its subject, in the
  platform's one spelling of a caller: every spelling of one wallet address
  is one caller, and an `apple:` subject or a name is kept as given. A run
  whose process died mid-call is closed FAIL with its effect marked
  unknown, and is never run again. At `on`, an engine that cannot be built
  does not leave the gateway serving as `off`: every action it would own is
  refused, as one whose run cannot be written is, and `GET /ready` answers
  503, as it does while the loop is not running or has stopped making
  progress. The four tables hold digests and fixed words, never a raw
  address, parameter or answer. A row the engine did not write never makes
  it call or deliver anything: an outbox row it does not hold is given up
  undelivered. Its own rows changed by hand are met where a change can be
  seen: a replay is compared with the request its held answer was given to
  as well as with the row, so it is never handed another request's answer,
  and a run moved back to START whose steps say its call began keeps its
  key. What no table can stand against is what was written being removed,
  the key's own row or the step that says a call began: whoever can write
  the database can make a replay run again. Nothing in it asks or overrides
  the security gate. The dedicated `/api/v1` service routes call services
  without the dispatcher and are not journaled; `POST
  /api/v1/capabilities/{id}/invoke` goes through the dispatcher and is,
  without reading an `Idempotency-Key`. The four tables are schema
  migration 11, after the one-spelling rewrite of stored callers (10): a
  database left at either earlier schema gets the tables, and the rewrite
  exactly once, and so does one a build of this work from before the
  renumbering left with the tables recorded as 10 and nothing recorded as
  11. Two other kinds of database come only from unreleased builds of this
  work and are not healed: one that recorded 11 after that, which never
  takes the rewrite, and one whose tables an earlier build created in
  another shape, which the engine will not run over. Discard either. What
  the mode costs is measured, not assumed
  (`tests/baseline/durable_g6_latency.json`, 5,000 calls a cell, on the
  machine it names, over stand-in services that answer at once, with the
  outbox loop's deliveries outside the timed calls). It times the service
  dispatcher, the bridge's keyed sequence after the gate and a twin tool's
  signing call; not the gate, where no durable code runs, and not the HTTP
  route. `shadow` and `on` write a run of two transactions around each
  journaled dispatch, which puts its p95 at several times that of the same
  dispatch at `off`: at `on` about 8.6 times for the service dispatcher
  (18.9 to 161.8 microseconds), 9.8 times for the bridge's keyed sequence
  and 2.8 times for a twin tool's signing call, and 8.3, 9.7 and 3.0 times
  at `shadow`. That is over the +10 percent latency budget. At `off` a
  dispatch costs about a microsecond more than on the tree this work
  merges into, timed in two interpreters taking turns block by block:
  1.082 times its p95 (17.1 to 18.5 microseconds), between 1.039 and 1.093
  over five stretches of the run, within the budget; the `off` cell timed
  in one interpreter between `shadow` and `on` blocks came to 1.105 times,
  just over it. The budget is the project owner's decision, still open:
  this phase of the engines work can merge dark, with the mode `off` by
  default, and is not closed until that gate, G6, holds. The other two exit gates hold at `on`.
  G7, the plan's crash matrix at its ten Phase 2 cells (the bridge request
  at W2 and W4, the dispatch at W1, W2 and W4, the attestation at W1, W2 and
  W3, the feed entry at W1 and W2), is 100 seeded crashes a cell, 20 of them
  child interpreters killed at the instant, each recovered over the same file
  by a fresh engine holding nothing in memory: no
  run is lost and no effect is made without its record, recovery continues
  nothing, no effect happens twice, and two recoveries of one file reach
  the same state (`tests/baseline/durable_g7_crash_matrix.json`, which also
  says what the plan asks that the matrix does not measure). G8: of 1,104
  bodies each sent twice to `POST /bridge/v1/action`, the 1,032 of the
  172 actions a request may have dispatched act once each, and the 72 of
  the twelve every door refuses on request (`REFUSED_ON_REQUEST` in
  `runtime/access_policy.py`) are answered 403 before the gate and act not
  at all (`tests/baseline/durable_g8_replay.json`)

What activates the moment a chain is configured: on-chain attestations,
paymaster gas sponsorship within the configured policy, and live service
responses in place of every `not_deployed`. Populate `blockchain.*` in
`matrix.config.json` to flip them. `CREDENTIALS_NEEDED.md` lists what a
deployment needs, capability by capability: which key or address unlocks it,
where it is set, and what happens while it is unset.

---

## The Security Layer

The Matrix has a closed-source security layer that enforces agent boundaries in a deployment that installs it. It is not in this repository by design, and without it the seam here runs an inert no-op, as described above. See `SECURITY_STUB.md` for details.

---

## The Unified Rexhepi Framework

Every tool call an agent makes passes through the Unified Rexhepi Framework before it is dispatched. Its operational layer is open source, in `runtime/protocols/urf.py`. See `docs/unified-rexhepi-framework.md`.

---

## Web3 Capability Surface

**195 capabilities across 20 categories** — smart contracts
(conversion to Solidity scaffolding, a conversion fee quote, templates),
DeFi (loans against collateral, token swaps), DeFi advanced (an
orderbook and Pyth pull prices), NFTs (minting, trading, rights,
royalties, fractionalization, rentals, soulbound), NFT finance
(NFT-backed loans, breeding, ERC-6551 accounts), identity (DIDs,
credentials, reputation, KYC, agent registry, attestations), governance
(DAOs, proposals, multisig, veTokens, quadratic voting, RetroPGF,
disputes), social (profiles, messaging, Lens, Farcaster, Push, creator
coins), creator platforms (Sound.xyz, Mirror, Paragraph, IP licensing),
payments (records of payments, stablecoin transfers and cross-border
remittances, and state channels), cross-chain (CCIP, Hyperlane,
Wormhole, Stargate, Axelar),
staking & restaking (EigenLayer, Symbiotic, Karak, Lido, Rocket Pool),
privacy & ZK (ZK proofs, and MPC signing, social recovery and session
keys, all three catalogued as not yet available, and the last two
refused at every door), oracles (Chainlink,
Pyth, RedStone, API3, Keepers), storage (IPFS, Filecoin, Ceramic,
OrbitDB), compute & DePIN (Akash, device rentals), real-world assets
(tokenization, supply chain, carbon credits, insurance), markets
(prediction markets, auctions, fundraising, securities, marketplace,
loyalty, subscriptions), gaming, and infrastructure (AI agents, models,
training data). Many are catalogued with `available: false`;
`docs/blockchain.md` lists every capability by category and says which.
The catalog also declares a Security & Wallets category that holds none.
The 195 are served by 43 of the 45 services in the service registry.

Every capability is catalogued in `runtime/capabilities/catalog.py`.
Browse them at runtime, with the gateway API key setup generated
(`gateway.api_key` in `matrix.config.json`):

```bash
curl http://localhost:18790/api/v1/capabilities -H "Authorization: Bearer YOUR_API_KEY"             # list all
curl http://localhost:18790/api/v1/capabilities/categories -H "Authorization: Bearer YOUR_API_KEY"  # 21 buckets, one (Security & Wallets) empty
```

Gas is sponsored by the platform paymaster **within the policy the
operator configures**, and with no paymaster key configured nothing is
sponsored. What is checked depends on who signs:

- a smart-account operation the paymaster signs
  (`POST /api/v1/paymaster/sign`) is checked against the allowlist, with
  its actions decoded from the call data being signed, and against the
  cap when one is set; past either, sponsorship is refused rather than
  silently granted;
- a transaction the platform signs itself for a capability, including
  the ones the services send through the shared web3 manager, is checked
  against the allowlist whenever one is configured, with or without a
  daily cap, and, when a cap is set, against the cap and a signed-in
  identity; one that fails is refused with the reason rather than
  charged to the user. With neither an allowlist nor a cap it is signed
  without a limit. With an allowlist, list `web3.send_transaction` or
  those will be refused;
- an attestation you ask for is metered the same way, under its own
  `<capability>.<method>` name and against your identity: 10 actions of
  Neo's blockchain tools `agent_identity`, `identity`,
  `crossborder_payment`, `gaming`, `insurance`, `ip_royalties`,
  `securities` and `supply_chain`. The `create_attestation`,
  `batch_attest` and `revoke_attestation` capabilities are refused at
  every door, whoever asks, and are metered, as `attestation.attest`,
  `attestation.batch_attest` and `attestation.revoke`, only where the
  platform's own code calls them in process; the `eas`
  tool's `attest`, `batch_attest` and `revoke` are refused too. The
  platform's key signs no attestation a request composes and revokes
  none a request names;
- the platform's own records are exempt from the policy. They are listed
  by name in `UNMETERED_PLATFORM_OPERATIONS`
  (`runtime/blockchain/sponsorship.py`), so the exemptions can be read
  rather than guessed at, and are signed with the platform key whatever
  the allowlist and the cap say: the service dispatcher's own record of
  each state-modifying action it completes, queued and signed once 50
  have gathered (with `engines.durable.mode` at `on`, sent by the durable
  outbox loop as soon as its run ends instead); `convert_contract`'s attestation of a contract it
  deployed, with `conversion.auto_deploy` on; and the real-estate routes'
  attestations, with `services.real_estate.enabled` set. The list also
  holds `GasSponsor.sponsor_transaction`, which signs whatever it is
  handed and which nothing calls. `docs/blockchain.md` lists every path by
  file and function, and the callers that reach the same code and sign
  nothing.

Some operations carry a platform fee: the platform contracts pay theirs
to each contract's `platformFeeRecipient`, which `scripts/deploy_all.py`
sets to the configured NeoSafe address. The fees the code is known to
take, with their rates, are listed under Fees in `docs/blockchain.md`,
checked against the code by a test that finds a fee by its name. Capabilities return
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
curl -X POST http://localhost:18790/api/v1/contracts/convert \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"source_lang": "pseudocode", "source_code": "contract Rental\n    state landlord: address\n    state tenant: address\n    state monthlyRent: uint256\n\n    function constructor(tenantAddr: address, rent: uint256)\n        landlord = msg.sender\n        tenant = tenantAddr\n        monthlyRent = rent\n\n    payable function payRent()\n        require(msg.sender == tenant, \"Only tenant can pay rent\")\n        require(msg.value == monthlyRent, \"Must pay exact rent\")\n"}'
```

`YOUR_API_KEY` is the key setup generated (`gateway.api_key`). The
converter reads structured pseudocode, Solidity or Vyper, not a
description in prose; it answers with the Solidity draft and Glasswing's
report on it. Unless the operator has turned on `conversion.auto_deploy`,
it deploys nothing.

**Check platform health**
```bash
curl http://localhost:18790/health        # liveness: is this process serving?
curl http://localhost:18790/ready         # readiness: should it take traffic?
```

The `models` map in `/health` says which providers **answered**, not which ones
you configured a key for — each one is asked, with a short timeout, and they are
all asked at once so the probe costs one timeout rather than five. `/ready` is
the one an orchestrator should point at: it answers 503 when no provider
answered, when the platform is running in production with security in
observe-only mode, when the security gate the gateway builds at startup did
not come up or the loop that writes its state back has stopped, or, with
`engines.durable.mode` at `on`, when durable execution could not be built or
its outbox loop has stopped or stopped making progress, and it deliberately
tells you nothing else. Which check failed is in the log against the request id, because a
readiness endpoint that announces what is not enforcing is telling whoever
asks where to push.

**Get platform status** (it needs the API key; `/health` and `/ready` do not)
```bash
curl http://localhost:18790/status -H "Authorization: Bearer YOUR_API_KEY"
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
                                                              Rexhepi · Glasswing
                                                              (Omega: built, never called)
                                                                         ↓
                                                              45 Blockchain Services
                                                              253 Platform Actions
```

---

## Example Scripts

All examples live in `examples/`. Each calls the platform's services, through the dispatcher or, for example 07, directly; a step reaches Base Sepolia only through the RPC and keys in `matrix.config.json`, and example 05 completes with no chain configured.

| Script | Description |
|---|---|
| `01_contract_conversion.py` | A rental agreement written as pseudocode, converted to a Solidity draft with its Glasswing report, for you to compile and deploy with your own wallet |
| `02_defi_loan.py` | Collateralised DeFi lending: create a loan, read it back, repay it |
| `03_nft_with_royalties.py` | An ERC-721 collection with an EIP-2981 royalty: create it, mint, list and sell a token |
| `04_parametric_insurance.py` | Crop insurance: a policy, the weather oracle's reading, and a claim the service judges against oracle data it fetches itself |
| `05_marketplace_flow.py` | List, search and buy: the sale is recorded with its fee split; no escrow, and nothing moves on chain |
| `06_eas_attestation_chain.py` | Attest sample records through the attestation capabilities (where `blockchain.eas_schema` is a well-formed bytes32 UID, queued unless time-critical), batch them, verify one |
| `07_revenue_to_neosafe.py` | Inject a fee into a generated contract, record sample fees with the NeoSafe router (in memory, nothing moves), and where the platform's fees actually go |
| `08_oracle_routing.py` | The oracle gateway: price feeds, a weather reading and a VRF request |
| `09_full_user_journey.py` | One user through seven services (DID, DAO, tokenization, NFT, governance, fundraising, staking) |

---

## Protocol Stack

The protocol stack gives Neo, Trinity, and Morpheus their cognitive abilities. Every turn reaches Jarvis, Friday and Vision, which can add to what the model is given before it is called, and Jarvis adjusts the reply's voice before it goes out. Outcome Learning adds the patterns it has learned on a turn whose request matches a known action. Trajectory, Ultron, the Morpheus Triggers and the Rexhepi Gate run only on a tool call: each call the model makes is scored by the Rexhepi Gate before it is dispatched and, if the gate lets it run, assessed by the other three, and Outcome Learning then records its outcome when the call reports one. A turn with no tool call does not reach them. Omega is built and never called.

**Jarvis** — Identity foundation. Handles agent personality persistence, voice consistency, memory integration, and structured planning that feeds into the ReAct loop.

**Ultron** — Strategic reasoning engine. Decomposes goals into multi-step plans with risk assessment at each stage.

**Friday** — Proactive monitoring. Watches for opportunities, risks, and relevant events, then surfaces suggestions before the user asks.

**Vision** — Pattern recognition and emergence detection. Identifies trends, anomalies, and correlations across user activity to anticipate needs.

**Trajectory** — Outcome prediction and path optimization. Predicts likely results of actions and suggests the optimal sequence to reach a goal.

**Outcome Learning** — Feedback loop. Captures the real result of each tool call and uses it to improve future reasoning. It learns from the outcome the tool actually reported, not from the absence of a crash: most things here refuse by returning a structure (`{"status": "not_deployed"}`, `{"ok": false}`), and a refusal is recorded as a refusal. Where a tool reports something that does not decide whether it worked — `pending` means "not paid" in one service and "record written" in another — the sample is left unlabelled and is not learned from at all. An unlabelled sample costs one data point; a mislabelled one corrupts the success rate and every confidence estimate built on it. It also reads through the platform's own envelopes: a layer that wraps a service's answer may report on the wrapping and never on what it wrapped, so a refusal relayed through the gateway, the bridge or the service dispatcher is still a refusal when it arrives. Where a layer knows something the reader cannot see, it says so in a field of its own instead of leaving it to be inferred — the service dispatcher knows whether an action changes state, which is what separates a call that failed from a successful read of a campaign whose own status is `failed`, and where those two cannot be told apart the answer is again "unknown" rather than a guess. That field is named so the services cannot collide with it, and it cannot talk a refusal into a success: a structure that states one thing and declares the opposite about itself in the same breath is left unlabelled. A check that ran and answered no is a call that worked — an unknown credential is answered, not errored, and a staking read for someone who never staked answers "no position" — while a check that could not look at all still says so. Tools that used to answer a failure in prose now refuse in a structure: `bash`, the file and web tools and every blockchain capability say when they did not do the thing, instead of handing back a sentence with no verdict in it. The same verdict is what a client is told about each tool call — and when nobody established one, the field goes out empty rather than as a tick.

**Morpheus Triggers** — Determines when Morpheus appears. Activates before irreversible actions, significant events, and high-stakes moments.

**Rexhepi Gate** — The execution gate. Every tool call an agent makes is scored by the Unified Rexhepi Framework before it is dispatched, and only an EXECUTE outcome lets it run. The agent's reply to the user does not pass through it.

**Omega** — A synthesis layer (`runtime/protocols/omega.py`) written to run Jarvis, Ultron, Vision, Friday, the Morpheus triggers and the Rexhepi Gate in sequence and merge what they return into one response. Nothing calls it. The protocol stack constructs an `OmegaMind` and counts it among the protocols it loaded, but the ReAct loop calls only the stack's `pre_process`, `pre_action`, `post_action` and `post_process`, and the reply the user gets is the model's, not Omega's.

**Protocol Stack (Integration)** — Wires the protocols above, Omega apart, into the agent runtime. The single entry point that the ReAct loop calls on every turn.

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
- **Per-wallet rate limiting** — three token buckets, keyed by the
  wallet session, then the operator key, then the client IP. Each has
  its own limit: `gateway.rate_limit_rpm_wallet` and
  `gateway.rate_limit_burst_wallet`; `…_authenticated` for the operator
  key, which `gateway.rate_limit_rpm` and `gateway.rate_limit_burst`
  also set and which the wallet bucket follows when it has no limit of
  its own; and `…_anonymous` per IP.
- **No production boot without enforcement** — with
  `MATRIX_ENV=production`, which `docker-compose.prod.yml` and
  `k8s/deployment.yaml` set and `docker-compose.yml` defaults to, the
  gateway refuses to start on the no-op security backend, and refuses
  to start when the security core is installed but its gate cannot be
  built or cannot load its saved state at startup, or when the core does
  not name a caller the way the platform does. The gate is built
  once, by the gateway, from its whole configuration. Outside production
  a gate that did not come up leaves the gateway running and not ready,
  and the platform hands no caller a gate and asks no other policy in its
  place: every request the gate would decide is refused, reads included,
  and so is every agent tool call, until a gateway starts with the gate
  up. A gate that did come up and then faults on a single call is a
  different case. With the security core installed, a call the gate could
  not decide is refused under ENFORCE, reads included; under OBSERVE it is
  refused when it could move value or change state, and a plain read goes
  through. When the gate raises instead of answering, the HTTP gate and the
  tool-call check refuse the call if it could move value and a plain read goes
  through, in either mode; Trinity's hand-off to Neo refuses every request it
  escalates then, reads included. The `Dockerfile`
  installs only the public requirements, so a production image needs the
  separately installed security core as well (`CREDENTIALS_NEEDED.md`,
  section 5).
- **Caddy reverse proxy** — `docker-compose.prod.yml` + `Caddyfile`
  give you automatic HTTPS via Let's Encrypt, security headers, and
  WebSocket-aware proxying on top of the base `docker-compose.yml`.
  Caddy's admin API is off; its container healthcheck asks a plain-HTTP
  listener bound to the container's own loopback (port 2020, never
  published) instead.
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

There is no way to sponsor The Matrix yet. GitHub Sponsors is not set up for
my account, and the project has no Open Collective, so nothing here links to
either. There are no sponsor tiers, perks or channels to offer, and no
sponsors. `SPONSORS.md` says the same.

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
- `http://localhost:18790/audit` — Glasswing audit: what the scan checks and the report it returns
- `http://localhost:18790/marketplace` — Plugin marketplace
- `http://localhost:18790/glasswing` — Glasswing security hub and badge registry
- `http://localhost:18790/learn` — Educational courses and certifications

---

## Professional Services

- **Glasswing Security Audit** — the automated scan itself is in this
  repository and runs locally as part of the conversion pipeline, free. A
  paid hosted audit is **not live**: no audit backend is wired into the
  gateway, so `POST /audit/request` answers `503 not_available` rather than
  taking an order it cannot fill. The page at `/audit` describes the scan
  and the report it returns; it offers no tiers and takes no order.
- **Contract Conversion** — likewise: the pipeline is here and free to run
  (`POST /api/v1/contracts/convert`). The page at `/services/conversion`
  describes what a conversion returns; it offers no plans and takes no
  order.

## Glasswing Security Badges

A contract whose source passes the platform's own Glasswing audit can be
issued a security badge with `POST /badge/issue` (behind the gateway's API
key); the gateway audits the source itself, so a request cannot supply the
verdict. A badge is a record in the gateway's database, stored with a hash of
that audit report, with a page (`/badge/{badge_id}`), a status endpoint and an
embed snippet. No EAS attestation is written for a badge, so the gateway that
issued it is the only place to check one. The registry at `/badges` is public,
but the badge page, its status, its embed and `/badge/widget.js` are not in the
gateway's public set: with an API key set, a visitor without the key is
answered 401 on each. A badge expires after one year; `BadgeManager` has a
renewal method, but no route calls it.

See `/glasswing` for the badge registry.

## Learn

Three courses, free and open source in `education/`, exercises and
solutions included; nothing sells them:

- **Introduction to The Matrix** — Build plugins, deploy contracts with your own wallet, use the SDK
- **Smart Contract Security** — Reentrancy, access control, Glasswing methodology
- **DeFi from Scratch** — Loans, NFTs, DAOs, staking, explained simply

See `/learn` for details.

## Get Certified

The gateway has three certification tracks (`GET /certification/tracks`,
`POST /certification/start`, `POST /certification/submit`). It serves no
exam questions yet: `start` opens an attempt and answers with the track's
intended question count and time limit, and `submit` scores the answers
against the track's 10 sample questions in
`runtime/certification/assessments.py`, with no time limit enforced. A
passing score records a certificate with an ID that `GET /certification/{cert_id}` looks
up. No on-chain attestation is written for a certificate: the record has an
`eas_uid` field that nothing fills. The exam routes take no payment; the
prices below are the intended fees, as the tracks list them:

- **Certified Developer** ($149) — Plugins, SDK, deploying what the pipeline generates
- **Certified Security Auditor** ($249) — Glasswing methodology, vulnerability analysis
- **Enterprise Architect** ($399) — Multi-chain deployment, infrastructure at scale

---

## Plugin Development

Build plugins for The Matrix. The plugin loader (`runtime/plugins/loader.py`)
can import a package from `plugins/installed/`, but nothing in the gateway loads
one: placing a package there runs nothing today. You can load one yourself with
`PluginLoader.load_all()`. The marketplace lists plugins and does not install
them. A paid plugin cannot be bought yet: no purchase path completes one, so the
purchase route answers `501` for a paid plugin, and nothing on this server takes
a payment or pays a developer. The platform commission on paid plugins is an
operator setting (`plugin_marketplace.commission_rate`); the published Terms of
Service state 10%.

```bash
# See the example plugin
cat runtime/plugins/example_plugin.py

# Full guide
cat docs/PLUGIN_DEVELOPMENT.md
```

Submit a listing with `POST /marketplace/plugins/submit` and the gateway's API
key (the `/marketplace` page cannot submit one). The listing is stored as
`pending`; nothing in this gateway reviews, approves or activates it.

---

## JavaScript SDK

`sdk-js/` is not published to npm. Build it from your clone (`cd sdk-js &&
npm install && npm run build`) and install it into your app from that
directory (`npm install <path to your clone>/sdk-js`).

```typescript
import { MatrixClient } from '@the-matrix/sdk';
const client = new MatrixClient('http://localhost:18790');
const response = await client.chat('What can you do?');
```

---

## Contributing

See `CONTRIBUTING.md` for the open contribution model.

---

## License

MIT License — Copyright 2026 Dardan Rexhepi and Neo
