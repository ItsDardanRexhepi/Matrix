"""
OpenMatrixClient — the main SDK client for interacting with 0pnMatrx.

Provides sync and async methods for:
- Chat (single message and streaming)
- Memory operations (read/write)
- Blockchain operations (all 20 capabilities)
- Platform status and health checks
- Session management
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    """Response from a chat request."""
    text: str
    agent: str
    tool_calls: list[dict] = field(default_factory=list)
    session_id: str = ""
    provider: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class HealthStatus:
    """Platform health status."""
    status: str
    agents: list[str]
    model_provider: str
    models: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class PlatformStatus:
    """Full platform status."""
    version: str
    agents: list[str]
    sessions: int
    total_requests: int
    uptime_seconds: float
    memory_mb: float
    model: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class OpenMatrixClient:
    """
    Python SDK client for the 0pnMatrx platform.

    Example:
        client = OpenMatrixClient("http://localhost:18790")

        # Chat with Trinity
        response = client.chat("Hello!")
        print(response.text)

        # Execute with Neo
        response = client.chat("Deploy a smart contract", agent="neo")
        print(response.tool_calls)

        # Check platform health
        health = client.health()
        print(health.status)
    """

    def __init__(self, base_url: str = "http://localhost:18790", session_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._async_session = None

    # ─── Sync API ──────────────────────────────────────────────────────────

    def chat(self, message: str, agent: str = "trinity", session_id: str | None = None) -> ChatResponse:
        """Send a chat message (synchronous)."""
        return self._run(self.achat(message, agent, session_id))

    def health(self) -> HealthStatus:
        """Check platform health (synchronous)."""
        return self._run(self.ahealth())

    def status(self) -> PlatformStatus:
        """Get full platform status (synchronous)."""
        return self._run(self.astatus())

    def memory_read(self, agent: str = "neo") -> dict:
        """Read agent memory (synchronous)."""
        return self._run(self.amemory_read(agent))

    def memory_write(self, agent: str, key: str, value: Any) -> bool:
        """Write to agent memory (synchronous)."""
        return self._run(self.amemory_write(agent, key, value))

    def blockchain(self, capability: str, **params) -> dict:
        """Execute a blockchain capability (synchronous)."""
        return self._run(self.ablockchain(capability, **params))

    # ─── Async API ─────────────────────────────────────────────────────────

    async def achat(self, message: str, agent: str = "trinity", session_id: str | None = None) -> ChatResponse:
        """Send a chat message (async)."""
        data = await self._post("/chat", {
            "message": message,
            "agent": agent,
            "session_id": session_id or self.session_id,
        })
        return ChatResponse(
            text=data.get("response", ""),
            agent=data.get("agent", agent),
            tool_calls=data.get("tool_calls", []),
            session_id=data.get("session_id", self.session_id),
            provider=data.get("provider", ""),
            raw=data,
        )

    async def ahealth(self) -> HealthStatus:
        """Check platform health (async)."""
        data = await self._get("/health")
        return HealthStatus(
            status=data.get("status", "unknown"),
            agents=data.get("agents", []),
            model_provider=data.get("model_provider", ""),
            models=data.get("models", {}),
            raw=data,
        )

    async def astatus(self) -> PlatformStatus:
        """Get full platform status (async)."""
        data = await self._get("/status")
        return PlatformStatus(
            version=data.get("version", ""),
            agents=data.get("agents", []),
            sessions=data.get("sessions", 0),
            total_requests=data.get("total_requests", 0),
            uptime_seconds=data.get("uptime_seconds", 0),
            memory_mb=data.get("memory_mb", 0),
            model=data.get("model", {}),
            raw=data,
        )

    async def amemory_read(self, agent: str = "neo") -> dict:
        """Read agent memory (async)."""
        data = await self._post("/memory/read", {"agent": agent})
        return data.get("memory", {})

    async def amemory_write(self, agent: str, key: str, value: Any) -> bool:
        """Write to agent memory (async)."""
        data = await self._post("/memory/write", {"agent": agent, "key": key, "value": value})
        return data.get("success", False)

    async def ablockchain(self, capability: str, **params) -> dict:
        """
        Execute a blockchain capability via Neo.

        Args:
            capability: Name of the blockchain capability (e.g., "smart_contract", "defi", "nft")
            **params: Parameters for the capability

        Returns:
            Result from the blockchain operation
        """
        message = f"Use the {capability} tool with these parameters: {json.dumps(params)}"
        response = await self.achat(message, agent="neo")
        return {
            "response": response.text,
            "tool_calls": response.tool_calls,
            "agent": response.agent,
        }

    async def astream_chat(self, message: str, agent: str = "trinity") -> AsyncIterator[str]:
        """
        Stream a chat response (async generator).
        Falls back to single response if streaming not supported.
        """
        # The gateway currently returns complete responses
        # This wraps it as a stream for API compatibility
        response = await self.achat(message, agent)
        yield response.text

    # ─── Convenience Methods ───────────────────────────────────────────────

    async def deploy_contract(self, source_code: str, **kwargs) -> dict:
        """Deploy a smart contract. Gas covered by platform."""
        return await self.ablockchain("smart_contract", action="deploy", source_code=source_code, **kwargs)

    async def send_payment(self, to: str, amount: str, token: str = "ETH") -> dict:
        """Send a payment. Gas covered by platform."""
        if token == "ETH":
            return await self.ablockchain("payment", action="send_eth", to=to, amount=amount)
        return await self.ablockchain("stablecoin", action="transfer", token=token, to=to, amount=amount)

    async def mint_nft(self, contract_address: str, to: str, token_uri: str = "") -> dict:
        """Mint an NFT. Gas covered by platform."""
        return await self.ablockchain("nft", action="mint", contract_address=contract_address, to=to, token_uri=token_uri)

    async def get_price(self, pair: str = "ETH/USD") -> dict:
        """Get price from Chainlink oracle."""
        return await self.ablockchain("oracle", action="get_price", pair=pair)

    async def create_attestation(self, action: str, agent: str = "neo", **details) -> dict:
        """Create an EAS attestation. Gas covered by platform."""
        return await self.ablockchain("eas", action="attest", data={"action": action, "agent": agent, **details})

    # ─── Session Management ────────────────────────────────────────────────

    def new_session(self) -> str:
        """Start a new conversation session."""
        self.session_id = uuid.uuid4().hex[:12]
        return self.session_id

    # ─── Internal ──────────────────────────────────────────────────────────

    async def _get(self, path: str) -> dict:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}{path}") as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {text}")
                return await resp.json()

    async def _post(self, path: str, data: dict) -> dict:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}{path}",
                json=data,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {text}")
                return await resp.json()

    def _run(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return loop.run_in_executor(pool, asyncio.run, coro)
        except RuntimeError:
            return asyncio.run(coro)

    def __repr__(self):
        return f"OpenMatrixClient(base_url='{self.base_url}', session_id='{self.session_id}')"
