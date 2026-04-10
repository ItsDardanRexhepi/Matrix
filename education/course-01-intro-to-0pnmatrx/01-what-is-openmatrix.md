# Module 01: What is OpenMatrix?

## The Problem

Blockchain technology has a barrier problem. To deploy a smart contract today, you need to know Solidity, understand gas mechanics, navigate wallet management, and parse transaction hashes. To interact with DeFi protocols, you need to understand liquidity pools, slippage tolerances, and approval transactions. The technical overhead keeps most people locked out.

0pnMatrx (read as "OpenMatrix") exists to remove those barriers entirely.

## What 0pnMatrx Is

0pnMatrx is a free, open-source AI agent platform that provides blockchain infrastructure through natural conversation. Instead of writing Solidity code, you describe what you want in plain English. Instead of navigating DeFi interfaces, you chat with an AI agent that handles the complexity for you.

The platform runs on **Base**, an Ethereum Layer 2 network, which means lower gas fees and faster transactions while inheriting Ethereum's security. It provides **30 blockchain services** -- from token deployment to DAO governance to NFT minting -- all accessible through conversation or API calls.

## The Three Agents

0pnMatrx is powered by three distinct AI agents, each with a specific role:

### Neo -- The Execution Engine

Neo is the backbone. When a task needs to be performed -- deploying a contract, querying a balance, executing a swap -- Neo handles it. You never interact with Neo directly. Neo operates inside a ReAct (Reasoning + Acting) loop: it receives a task, reasons about the steps required, selects the appropriate tools, executes them, observes the results, and iterates until the task is complete. Neo has access to all 30 blockchain services and executes them with precision.

### Trinity -- The Conversational Interface

Trinity is who you talk to. She translates your natural language requests into structured tasks that Neo can execute. When you say "deploy an ERC-20 token called MatrixCoin with a supply of 1 million," Trinity parses that intent, validates the parameters, and hands the structured task to Neo. She also translates Neo's technical output back into human-readable responses. Trinity is available through the REST API, WebSocket connections, and the MTRX command-line interface.

### Morpheus -- The Guardian

Morpheus appears only before irreversible actions. If you are about to deploy a contract to mainnet, transfer tokens, or execute a transaction that cannot be undone, Morpheus intervenes with a confirmation step. He presents exactly what is about to happen, the costs involved, and the consequences. Nothing irreversible executes without your explicit approval through Morpheus.

## Architecture Overview

The data flow through 0pnMatrx follows a clear path:

```
User
  |
  v
MTRX CLI / Web Interface
  |
  v
Gateway (port 18790)
  |
  v
Trinity (conversation parsing)
  |
  v
Neo (ReAct Loop)
  |
  +---> Tool Selection
  |       |
  |       v
  |     30 Blockchain Services (Base L2)
  |       |
  |       v
  +<--- Results
  |
  v
Response to User
```

The **Gateway** is the central server. It receives requests via REST or WebSocket, authenticates them, applies rate limiting, and routes them to the agent pipeline. Every request gets a unique ID for tracing.

The **ReAct Loop** is how Neo works. For each task, Neo cycles through: Thought (what needs to happen), Action (which tool to call), Observation (what the tool returned), and repeats until the task is complete.

The **30 Services** are the actual blockchain operations: token deployment, contract auditing, NFT creation, DeFi interactions, DAO management, staking, bridging, and more. Each service is a self-contained module that Neo can invoke.

## Why This Matters

The gap between "I want to create a token" and actually creating one has historically been weeks of learning, thousands of dollars in developer costs, and significant risk of security vulnerabilities. 0pnMatrx collapses that gap to a single conversation.

This is not about dumbing down blockchain. The smart contracts deployed through 0pnMatrx are real Solidity contracts, audited by the Glasswing security engine, attested on-chain through EAS (Ethereum Attestation Service), and deployed to real networks. The technical rigor is preserved -- the complexity is just handled for you.

For developers, 0pnMatrx provides a plugin system and SDK that lets you extend the platform, build on top of it, and distribute your tools through the marketplace. Plugin developers keep 90% of revenue from the marketplace, with a 90/10 split that prioritizes creators.

## Key Takeaways

- 0pnMatrx is a free AI agent platform for blockchain operations on Base (Ethereum L2)
- Three agents: Neo (execution), Trinity (conversation), Morpheus (confirmation of irreversible actions)
- 30 blockchain services accessible through natural language or API
- The gateway runs on port 18790 and serves as the central coordination point
- Plugin marketplace with 90/10 revenue split (developers keep 90%)

---

**Next:** [Quick Start](./02-quick-start.md) -- get 0pnMatrx running on your machine in under 10 minutes.
