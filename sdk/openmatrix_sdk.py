"""
0pnMatrx SDK — Python client for the 0pnMatrx platform.

Provides both synchronous and asynchronous clients for interacting
with a running 0pnMatrx gateway.
"""

import json
import uuid
from dataclasses import dataclass

import aiohttp
import requests


@dataclass
class ChatResponse:
    """Response from a chat request."""
    text: str
    agent: str
    session_id: str
    raw: dict


class OpenMatrixClient:
    """
    Synchronous client for 0pnMatrx.

    Usage:
        client = OpenMatrixClient("http://localhost:18790")
        response = client.chat("Hello Trinity")
        print(response.text)
    """

    def __init__(self, base_url: str = "http://localhost:18790", session_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id or uuid.uuid4().hex[:12]

    def chat(self, message: str, agent: str = "trinity") -> ChatResponse:
        """Send a message and get a response."""
        resp = requests.post(
            f"{self.base_url}/chat",
            json={
                "message": message,
                "agent": agent,
                "session_id": self.session_id,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        return ChatResponse(
            text=data.get("response", ""),
            agent=data.get("agent", agent),
            session_id=data.get("session_id", self.session_id),
            raw=data,
        )

    def health(self) -> dict:
        """Check system health."""
        resp = requests.get(f"{self.base_url}/health", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def status(self) -> dict:
        """Get system status."""
        resp = requests.get(f"{self.base_url}/status", timeout=10)
        resp.raise_for_status()
        return resp.json()

    def new_session(self) -> "OpenMatrixClient":
        """Create a new client with a fresh session ID."""
        return OpenMatrixClient(self.base_url)


class AsyncOpenMatrixClient:
    """
    Asynchronous client for 0pnMatrx.

    Usage:
        async with AsyncOpenMatrixClient("http://localhost:18790") as client:
            response = await client.chat("Hello Trinity")
            print(response.text)
    """

    def __init__(self, base_url: str = "http://localhost:18790", session_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    async def _ensure_session(self):
        if not self._session:
            self._session = aiohttp.ClientSession()

    async def chat(self, message: str, agent: str = "trinity") -> ChatResponse:
        """Send a message and get a response."""
        await self._ensure_session()

        async with self._session.post(
            f"{self.base_url}/chat",
            json={
                "message": message,
                "agent": agent,
                "session_id": self.session_id,
            },
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return ChatResponse(
            text=data.get("response", ""),
            agent=data.get("agent", agent),
            session_id=data.get("session_id", self.session_id),
            raw=data,
        )

    async def health(self) -> dict:
        """Check system health."""
        await self._ensure_session()

        async with self._session.get(
            f"{self.base_url}/health",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def status(self) -> dict:
        """Get system status."""
        await self._ensure_session()

        async with self._session.get(
            f"{self.base_url}/status",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def close(self):
        """Close the underlying HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None
