"""A2A service marketplace.

Agents register their capabilities and discover services offered
by other agents. The marketplace handles service discovery, matching,
and basic reputation tracking.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from runtime.a2a.protocol import (
    ServiceListing,
    ServiceCategory,
    JobRequest,
    JobResult,
    JobStatus,
)

logger = logging.getLogger(__name__)


# Built-in services provided by the platform's three agents
BUILTIN_SERVICES: list[dict] = [
    {
        "agent_id": "trinity",
        "name": "Natural Language Contract Specification",
        "description": "Convert plain English requirements into structured smart contract specifications",
        "category": ServiceCategory.GENERATION.value,
        "price_usd": 0.0,
        "capabilities": ["contract_spec", "requirements_analysis", "solidity_generation"],
    },
    {
        "agent_id": "neo",
        "name": "Smart Contract Deployment",
        "description": "Deploy and verify smart contracts on Base and other EVM chains",
        "category": ServiceCategory.INTEGRATION.value,
        "price_usd": 0.0,
        "capabilities": ["contract_deployment", "verification", "gas_estimation"],
    },
    {
        "agent_id": "morpheus",
        "name": "Transaction Risk Assessment",
        "description": "Evaluate the risk of blockchain transactions before execution",
        "category": ServiceCategory.VERIFICATION.value,
        "price_usd": 0.0,
        "capabilities": ["risk_scoring", "fraud_detection", "compliance_check"],
    },
    {
        "agent_id": "trinity",
        "name": "Security Audit Analysis",
        "description": "Analyse smart contracts for security vulnerabilities using Glasswing",
        "category": ServiceCategory.ANALYSIS.value,
        "price_usd": 0.0,
        "capabilities": ["vulnerability_scan", "gas_analysis", "best_practices"],
    },
    {
        "agent_id": "neo",
        "name": "Multi-Chain Bridge Routing",
        "description": "Find optimal routes for cross-chain asset transfers",
        "category": ServiceCategory.INTEGRATION.value,
        "price_usd": 0.0,
        "capabilities": ["bridge_routing", "fee_comparison", "chain_selection"],
    },
]


class A2AMarketplace:
    """Agent-to-agent service marketplace.

    Manages service listings, job submissions, and result delivery.
    Backed by SQLite for persistence.
    """

    def __init__(self, config: dict | None = None, db=None):
        """Initialise the marketplace.

        Parameters
        ----------
        config : dict, optional
            Platform configuration.
        db : Database, optional
            SQLite database for persistence.
        """
        self.config = config or {}
        self.db = db
        self.services: dict[str, ServiceListing] = {}
        self.jobs: dict[str, JobRequest] = {}
        self.results: dict[str, JobResult] = {}
        self._initialised = False

    async def initialize(self) -> None:
        """Create tables and register built-in services."""
        if self._initialised:
            return

        if self.db:
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS a2a_services (
                    service_id      TEXT PRIMARY KEY,
                    agent_id        TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    description     TEXT,
                    category        TEXT,
                    price_usd       REAL DEFAULT 0.0,
                    price_type      TEXT DEFAULT 'per_call',
                    capabilities    TEXT,
                    total_jobs      INTEGER DEFAULT 0,
                    rating          REAL DEFAULT 5.0,
                    available       INTEGER DEFAULT 1,
                    created_at      REAL NOT NULL
                )
                """,
                commit=True,
            )
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS a2a_jobs (
                    job_id          TEXT PRIMARY KEY,
                    service_id      TEXT NOT NULL,
                    requester       TEXT NOT NULL,
                    provider        TEXT NOT NULL,
                    input_data      TEXT,
                    output_data     TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    price_usd       REAL DEFAULT 0.0,
                    created_at      REAL NOT NULL,
                    completed_at    REAL
                )
                """,
                commit=True,
            )

        # Register built-in services
        for svc_data in BUILTIN_SERVICES:
            svc = ServiceListing(
                agent_id=svc_data["agent_id"],
                name=svc_data["name"],
                description=svc_data["description"],
                category=svc_data["category"],
                price_usd=svc_data["price_usd"],
                capabilities=svc_data["capabilities"],
            )
            self.services[svc.service_id] = svc

        self._initialised = True
        logger.info("A2A marketplace initialised with %d built-in services", len(BUILTIN_SERVICES))

    async def register_service(self, listing: ServiceListing) -> ServiceListing:
        """Register a new service on the marketplace."""
        self.services[listing.service_id] = listing

        if self.db:
            await self.db.execute(
                """
                INSERT OR REPLACE INTO a2a_services
                    (service_id, agent_id, name, description, category,
                     price_usd, price_type, capabilities, available, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing.service_id, listing.agent_id, listing.name,
                    listing.description, listing.category, listing.price_usd,
                    listing.price_type, json.dumps(listing.capabilities),
                    1, listing.created_at,
                ),
                commit=True,
            )

        logger.info("Registered A2A service: %s (%s)", listing.name, listing.service_id)
        return listing

    async def list_services(
        self,
        category: str | None = None,
        agent_id: str | None = None,
        available_only: bool = True,
    ) -> list[dict]:
        """List available services, optionally filtered."""
        services = list(self.services.values())

        if available_only:
            services = [s for s in services if s.available]
        if category:
            services = [s for s in services if s.category == category]
        if agent_id:
            services = [s for s in services if s.agent_id == agent_id]

        return [s.to_dict() for s in services]

    async def get_service(self, service_id: str) -> dict | None:
        """Get a specific service by ID."""
        svc = self.services.get(service_id)
        return svc.to_dict() if svc else None

    async def submit_job(self, job: JobRequest) -> JobRequest:
        """Submit a job request to a service."""
        self.jobs[job.job_id] = job

        if self.db:
            await self.db.execute(
                """
                INSERT INTO a2a_jobs
                    (job_id, service_id, requester, provider, input_data,
                     status, price_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id, job.service_id, job.requester_agent_id,
                    job.provider_agent_id, json.dumps(job.input_data),
                    job.status, job.max_price_usd, job.created_at,
                ),
                commit=True,
            )

        logger.info("A2A job submitted: %s -> %s", job.job_id, job.service_id)
        return job

    async def get_job(self, job_id: str) -> dict | None:
        """Get a job by ID."""
        job = self.jobs.get(job_id)
        if not job:
            return None
        result = job.to_dict()
        if job_id in self.results:
            result["result"] = self.results[job_id].to_dict()
        return result

    async def complete_job(self, result: JobResult) -> None:
        """Mark a job as completed with results."""
        self.results[result.job_id] = result

        if result.job_id in self.jobs:
            job = self.jobs[result.job_id]
            job.status = JobStatus.COMPLETED.value if result.success else JobStatus.FAILED.value
            job.completed_at = time.time()

            # Update service stats
            svc = self.services.get(job.service_id)
            if svc:
                svc.total_jobs += 1

        if self.db:
            await self.db.execute(
                """
                UPDATE a2a_jobs
                SET status = ?, output_data = ?, completed_at = ?, price_usd = ?
                WHERE job_id = ?
                """,
                (
                    JobStatus.COMPLETED.value if result.success else JobStatus.FAILED.value,
                    json.dumps(result.output_data),
                    time.time(),
                    result.actual_price_usd,
                    result.job_id,
                ),
                commit=True,
            )
