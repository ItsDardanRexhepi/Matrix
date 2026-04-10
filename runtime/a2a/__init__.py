"""Agent-to-agent commerce protocol for 0pnMatrx.

Enables agents to discover, negotiate, and transact services with
each other. Implements a marketplace where agents can list capabilities
and purchase services from other agents.
"""

from runtime.a2a.protocol import ServiceListing, JobRequest, JobResult
from runtime.a2a.marketplace import A2AMarketplace
from runtime.a2a.coordinator import A2ACoordinator

__all__ = [
    "A2AMarketplace",
    "A2ACoordinator",
    "ServiceListing",
    "JobRequest",
    "JobResult",
]
