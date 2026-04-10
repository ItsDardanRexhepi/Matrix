"""Agent-to-agent communication protocol.

Defines the message format and data structures for inter-agent
service discovery, negotiation, and execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Status of an A2A job."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class ServiceCategory(str, Enum):
    """Categories for agent services."""
    ANALYSIS = "analysis"
    GENERATION = "generation"
    VERIFICATION = "verification"
    TRANSFORMATION = "transformation"
    INTEGRATION = "integration"
    MONITORING = "monitoring"


@dataclass
class ServiceListing:
    """An agent service available on the A2A marketplace."""
    service_id: str = field(default_factory=lambda: f"svc_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    name: str = ""
    description: str = ""
    category: str = ServiceCategory.ANALYSIS.value
    price_usd: float = 0.0
    price_type: str = "per_call"    # per_call, per_minute, flat_rate
    capabilities: list[str] = field(default_factory=list)
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    avg_response_time_ms: int = 5000
    success_rate: float = 1.0
    total_jobs: int = 0
    rating: float = 5.0
    available: bool = True
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise to dict for API responses."""
        return {
            "service_id": self.service_id,
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "price_usd": self.price_usd,
            "price_type": self.price_type,
            "capabilities": self.capabilities,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "avg_response_time_ms": self.avg_response_time_ms,
            "success_rate": self.success_rate,
            "total_jobs": self.total_jobs,
            "rating": self.rating,
            "available": self.available,
        }


@dataclass
class JobRequest:
    """A request from one agent to another for service execution."""
    job_id: str = field(default_factory=lambda: f"job_{uuid.uuid4().hex[:12]}")
    service_id: str = ""
    requester_agent_id: str = ""
    provider_agent_id: str = ""
    input_data: dict = field(default_factory=dict)
    max_price_usd: float = 0.0
    timeout_seconds: int = 300
    status: str = JobStatus.PENDING.value
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict:
        """Serialise to dict for API responses."""
        return {
            "job_id": self.job_id,
            "service_id": self.service_id,
            "requester": self.requester_agent_id,
            "provider": self.provider_agent_id,
            "status": self.status,
            "max_price_usd": self.max_price_usd,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class JobResult:
    """The result of a completed A2A job."""
    job_id: str = ""
    output_data: dict = field(default_factory=dict)
    actual_price_usd: float = 0.0
    execution_time_ms: int = 0
    success: bool = True
    error_message: str = ""

    def to_dict(self) -> dict:
        """Serialise to dict for API responses."""
        return {
            "job_id": self.job_id,
            "output": self.output_data,
            "price_usd": self.actual_price_usd,
            "execution_time_ms": self.execution_time_ms,
            "success": self.success,
            "error": self.error_message if not self.success else None,
        }
