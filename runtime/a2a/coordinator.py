"""A2A job coordinator.

Orchestrates the execution of A2A jobs by routing requests to the
appropriate agent and managing the job lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from runtime.a2a.protocol import JobRequest, JobResult, JobStatus
from runtime.a2a.marketplace import A2AMarketplace

logger = logging.getLogger(__name__)


class A2ACoordinator:
    """Coordinates agent-to-agent job execution.

    Routes job requests to the appropriate agent, monitors execution,
    and handles timeouts and failures.
    """

    def __init__(self, marketplace: A2AMarketplace, react_loop=None):
        """Initialise the coordinator.

        Parameters
        ----------
        marketplace : A2AMarketplace
            The service marketplace.
        react_loop : ReActLoop, optional
            The platform's ReAct loop for executing agent tasks.
        """
        self.marketplace = marketplace
        self.react_loop = react_loop
        self._running_jobs: dict[str, asyncio.Task] = {}

    async def execute_job(self, job: JobRequest) -> JobResult:
        """Execute a job request.

        Submits the job to the marketplace, executes it through
        the appropriate agent, and returns the result.

        Parameters
        ----------
        job : JobRequest
            The job to execute.

        Returns
        -------
        JobResult
            The execution result.
        """
        # Submit to marketplace
        await self.marketplace.submit_job(job)

        # Look up the service
        service = await self.marketplace.get_service(job.service_id)
        if not service:
            result = JobResult(
                job_id=job.job_id,
                success=False,
                error_message=f"Service {job.service_id} not found",
            )
            await self.marketplace.complete_job(result)
            return result

        start_time = time.time()

        try:
            # Execute through the ReAct loop if available
            if self.react_loop:
                from runtime.react_loop import ReActContext, Message

                context = ReActContext(
                    agent_name=service.get("agent_id", "trinity"),
                    conversation=[
                        Message(
                            role="user",
                            content=f"Execute A2A service '{service.get('name', '')}': {job.input_data}",
                        )
                    ],
                    system_prompt="You are executing an agent-to-agent service request. Provide a structured response.",
                )

                loop_result = await asyncio.wait_for(
                    self.react_loop.run(context),
                    timeout=job.timeout_seconds,
                )

                execution_time = int((time.time() - start_time) * 1000)

                result = JobResult(
                    job_id=job.job_id,
                    output_data={
                        "response": loop_result.response,
                        "tool_calls": loop_result.tool_calls,
                    },
                    actual_price_usd=service.get("price_usd", 0.0),
                    execution_time_ms=execution_time,
                    success=True,
                )
            else:
                # No ReAct loop — return a placeholder
                result = JobResult(
                    job_id=job.job_id,
                    output_data={"message": "Job accepted but execution engine not available"},
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    success=True,
                )

        except asyncio.TimeoutError:
            result = JobResult(
                job_id=job.job_id,
                success=False,
                error_message=f"Job timed out after {job.timeout_seconds}s",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as exc:
            logger.error("A2A job %s failed: %s", job.job_id, exc)
            result = JobResult(
                job_id=job.job_id,
                success=False,
                error_message=str(exc),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        await self.marketplace.complete_job(result)
        return result

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            del self._running_jobs[job_id]

        job = self.marketplace.jobs.get(job_id)
        if job and job.status in (JobStatus.PENDING.value, JobStatus.ACCEPTED.value):
            job.status = JobStatus.CANCELLED.value
            return True
        return False
