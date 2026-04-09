# Changelog

All notable changes to 0pnMatrx are documented here.

---

## [0.2.0] — 2026-04-08

### Glasswing Integration

- Security audit layer: 12 vulnerability checks run on every contract before deployment
- Reentrancy, unchecked calls, tx.origin, selfdestruct, delegatecall, unbounded loops, integer overflow, floating pragma, locked ether, access control, front-running, timestamp dependence
- Audit gate on deploy: critical vulnerabilities block deployment
- Audit report included in every contract conversion response
- Morpheus enforces audit findings — no unsafe contracts reach the chain
- Claude Mythos Preview added as model provider (Glasswing frontier model)
- Security configuration in openmatrix.config.json
- HiveMind security instance type for collective vulnerability reasoning
- Ultron deploy planning now includes mandatory security audit step
- Friday monitors security vulnerability events
- Vision tracks security patterns across user activity
- Omniversal protocol tracks security as an expansion domain

---

## [0.1.0] — 2026-04-01

### Initial Release

- Three-agent architecture: Neo, Trinity, Morpheus
- ReAct reasoning loop with full tool dispatch
- File-backed memory system
- HTTP gateway on configurable port
- 36 skills loaded via skills loader
- HiveMind shared state across all agents
- 20 blockchain capabilities on Base (Ethereum L2)
- Unified Rexhepi Framework governing all agent decisions
- Full SDK for external integrations
- Migration system for upgrading between versions
- Support for Ollama (local), OpenAI, Anthropic, NVIDIA, Gemini
- One-command install and start scripts
- MIT licensed
