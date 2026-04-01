"""
ERC-8004 Agent Identity -- Component 9.

Implements on-chain agent identity registration, reputation tracking,
and safe update monitoring for autonomous AI agents on 0pnMatrx.
Compliant with the ERC-8004 agent identity standard.
"""

from runtime.blockchain.services.agent_identity.service import AgentIdentityService

__all__ = ["AgentIdentityService"]
