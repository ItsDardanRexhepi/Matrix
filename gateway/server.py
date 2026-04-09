"""
Gateway Server — the HTTP interface to 0pnMatrx.

Runs on port 18790 by default (configurable). Exposes endpoints for
chat, health, status, and memory operations. Handles CORS, API key
authentication, and per-IP rate limiting.
Logs all requests with timestamps.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import time
from collections import defaultdict
from pathlib import Path

from aiohttp import web

from runtime.react_loop import ReActLoop, ReActContext, Message
from runtime.time.temporal_context import TemporalContext

logger = logging.getLogger(__name__)

CONFIG_PATH = "openmatrix.config.json"
START_TIME = time.time()

# ─── Rate Limiter ────────────────────────────────────────────────────────────

class RateLimiter:
    """Token-bucket rate limiter per client IP."""

    def __init__(self, requests_per_minute: int = 60, burst: int = 10):
        self.rpm = requests_per_minute
        self.burst = burst
        self._buckets: dict[str, list] = defaultdict(lambda: [burst, time.time()])

    def allow(self, client_ip: str) -> bool:
        bucket = self._buckets[client_ip]
        now = time.time()
        elapsed = now - bucket[1]
        bucket[1] = now
        # Refill tokens based on elapsed time
        bucket[0] = min(self.burst, bucket[0] + elapsed * (self.rpm / 60.0))
        if bucket[0] >= 1.0:
            bucket[0] -= 1.0
            return True
        return False

    def cleanup(self):
        """Remove stale entries older than 5 minutes."""
        cutoff = time.time() - 300
        stale = [ip for ip, b in self._buckets.items() if b[1] < cutoff]
        for ip in stale:
            del self._buckets[ip]


def load_config() -> dict:
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.error(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    return json.loads(path.read_text())


class GatewayServer:
    """
    The main HTTP server for 0pnMatrx.

    Endpoints:
        POST /chat          — Send a message to an agent
        GET  /health        — Health check
        GET  /status        — Full platform status
        POST /memory/read   — Read agent memory
        POST /memory/write  — Write to agent memory
    """

    def __init__(self, config: dict):
        self.config = config
        self.react_loop = ReActLoop(config)
        self.temporal = TemporalContext(config.get("timezone", "America/Los_Angeles"))
        self.conversations: dict[str, list[Message]] = {}
        self.request_count = 0
        self._first_boot_sent: set[str] = set()

        # Auth: API key from config or environment
        gw = config.get("gateway", {})
        self.api_key = gw.get("api_key") or os.environ.get("OPENMATRIX_API_KEY", "")
        self.auth_enabled = bool(self.api_key)
        # Endpoints that don't require auth
        self._public_paths = {"/health"}

        # Rate limiting
        rpm = gw.get("rate_limit_rpm", 60)
        burst = gw.get("rate_limit_burst", 15)
        self.rate_limiter = RateLimiter(requests_per_minute=rpm, burst=burst)

    async def handle_chat(self, request: web.Request) -> web.Response:
        """POST /chat — {agent, message, session_id} -> {response, tool_calls, session_id}"""
        self.request_count += 1
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        message = body.get("message", "")
        if not isinstance(message, str):
            return web.json_response({"error": "message must be a string"}, status=400)
        message = message.strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)
        if len(message) > 100000:
            return web.json_response({"error": "message too long"}, status=400)

        session_id = str(body.get("session_id", "default"))[:100]
        agent = str(body.get("agent", "trinity"))[:50]
        valid_agents = {"neo", "trinity", "morpheus"}
        if agent not in valid_agents:
            return web.json_response({"error": f"invalid agent, must be one of: {', '.join(valid_agents)}"}, status=400)

        if session_id not in self.conversations:
            self.conversations[session_id] = []

        # Trinity first-boot message — once per session
        first_boot = None
        if agent == "trinity" and session_id not in self._first_boot_sent:
            self._first_boot_sent.add(session_id)
            first_boot = "Hi, my name is Trinity\n\nWelcome to the world of 0pnMatrx, I'll be by your side the entire time if you need me"

        self.conversations[session_id].append(Message(role="user", content=message))

        system_prompt = self.react_loop.get_agent_prompt(agent)
        time_context = self.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        context = ReActContext(
            agent_name=agent,
            conversation=self.conversations[session_id].copy(),
            system_prompt=full_prompt,
        )

        logger.info(f"[{agent}] session={session_id} message={message[:100]}")

        # Inject user context metadata so protocols can access it
        context.metadata["user_context"] = {
            "session_id": session_id,
            "agent": agent,
            "wallet_connected": body.get("wallet_connected", True),
            "network": body.get("network"),
            "balance": body.get("balance"),
            "jurisdiction": body.get("jurisdiction", ""),
            "total_transactions": body.get("total_transactions"),
        }

        try:
            result = await self.react_loop.run(context)
        except RuntimeError as e:
            logger.error(f"[{agent}] model error: {e}")
            return web.json_response({
                "response": "I'm having trouble connecting to my language model right now. Please try again shortly.",
                "error": str(e),
                "agent": agent,
                "session_id": session_id,
            }, status=503)

        response_text = result.response
        if first_boot:
            response_text = f"{first_boot}\n\n{response_text}"

        self.conversations[session_id].append(Message(role="assistant", content=result.response))

        # Trim conversation history
        if len(self.conversations[session_id]) > 100:
            self.conversations[session_id] = self.conversations[session_id][-50:]

        return web.json_response({
            "response": response_text,
            "tool_calls": result.tool_calls,
            "session_id": session_id,
            "agent": agent,
            "provider": result.provider,
        })

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /health — health check"""
        model_health = await self.react_loop.router.health_check()
        agents_config = self.config.get("agents", {})
        active = [name for name, cfg in agents_config.items() if cfg.get("enabled")]
        provider = self.config.get("model", {}).get("provider", "ollama")

        return web.json_response({
            "status": "ok",
            "agents": active,
            "model_provider": provider,
            "models": model_health,
        })

    async def handle_status(self, request: web.Request) -> web.Response:
        """GET /status — full platform status"""
        import resource
        agents_config = self.config.get("agents", {})
        active = [name for name, cfg in agents_config.items() if cfg.get("enabled")]
        uptime = time.time() - START_TIME

        try:
            mem_usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # On macOS, ru_maxrss is in bytes; on Linux, kilobytes
            if sys.platform == "darwin":
                mem_mb = mem_usage / (1024 * 1024)
            else:
                mem_mb = mem_usage / 1024
        except Exception:
            mem_mb = 0

        return web.json_response({
            "platform": "0pnMatrx",
            "version": "1.0.0",
            "agents": active,
            "model": {
                "provider": self.config.get("model", {}).get("provider", "unknown"),
                "primary": self.config.get("model", {}).get("primary", "unknown"),
            },
            "sessions": len(self.conversations),
            "total_requests": self.request_count,
            "uptime_seconds": round(uptime, 1),
            "memory_mb": round(mem_mb, 1),
        })

    async def handle_memory_read(self, request: web.Request) -> web.Response:
        """POST /memory/read — {agent} -> memory data"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        agent = body.get("agent", "neo")
        data = self.react_loop.memory.read(agent)
        return web.json_response({"agent": agent, "memory": data})

    async def handle_memory_write(self, request: web.Request) -> web.Response:
        """POST /memory/write — {agent, key, value} -> success"""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        agent = body.get("agent", "neo")
        key = body.get("key", "")
        value = body.get("value")

        if not key:
            return web.json_response({"error": "key is required"}, status=400)

        self.react_loop.memory.write(agent, key, value)
        return web.json_response({"success": True, "agent": agent, "key": key})

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[
            self._cors_middleware,
            self._auth_middleware,
            self._rate_limit_middleware,
            self._logging_middleware,
        ])
        app.router.add_post("/chat", self.handle_chat)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/status", self.handle_status)
        app.router.add_post("/memory/read", self.handle_memory_read)
        app.router.add_post("/memory/write", self.handle_memory_write)

        # Register all 30 blockchain service REST endpoints
        try:
            from gateway.service_routes import ServiceRoutes
            service_routes = ServiceRoutes(self.config)
            service_routes.register_routes(app)
            logger.info("Service routes registered successfully.")
        except Exception as e:
            logger.warning("Service routes registration skipped: %s", e)

        return app

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        """Validate API key on protected endpoints."""
        if not self.auth_enabled or request.path in self._public_paths:
            return await handler(request)
        if request.method == "OPTIONS":
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        provided_key = ""
        if auth_header.startswith("Bearer "):
            provided_key = auth_header[7:]
        elif request.query.get("api_key"):
            provided_key = request.query["api_key"]

        if not provided_key or not hmac.compare_digest(provided_key, self.api_key):
            return web.json_response(
                {"error": "unauthorized", "message": "Valid API key required. Set Authorization: Bearer <key>"},
                status=401,
            )
        return await handler(request)

    @web.middleware
    async def _rate_limit_middleware(self, request: web.Request, handler):
        """Enforce per-IP rate limits."""
        if request.method == "OPTIONS":
            return await handler(request)

        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            peername = request.transport.get_extra_info("peername")
            client_ip = peername[0] if peername else "unknown"

        if not self.rate_limiter.allow(client_ip):
            return web.json_response(
                {"error": "rate_limited", "message": "Too many requests. Please slow down."},
                status=429,
            )
        return await handler(request)

    @web.middleware
    async def _cors_middleware(self, request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        allowed_origins = self.config.get("gateway", {}).get("cors_origins", ["*"])
        origin = request.headers.get("Origin", "")
        if "*" in allowed_origins or origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @web.middleware
    async def _logging_middleware(self, request: web.Request, handler):
        start = time.time()
        try:
            response = await handler(request)
            elapsed = time.time() - start
            logger.info(f"{request.method} {request.path} -> {response.status} ({elapsed:.3f}s)")
            return response
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"{request.method} {request.path} -> ERROR ({elapsed:.3f}s): {e}")
            raise


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = load_config()
    server = GatewayServer(config)
    app = server.create_app()

    host = config.get("gateway", {}).get("host", "0.0.0.0")
    port = config.get("gateway", {}).get("port", 18790)

    logger.info(f"0pnMatrx gateway starting on {host}:{port}")
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
