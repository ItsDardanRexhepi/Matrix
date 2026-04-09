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
from runtime.auth.session_store import (
    WalletSessionStore,
    NonceStore,
    run_cleanup_loop,
)
from runtime.db.backup import BackupManager, run_backup_loop
from runtime.monitoring.metrics import MetricsCollector
from runtime.monitoring.sentry import initialize_sentry

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

    def allow(self, key: str) -> bool:
        bucket = self._buckets[key]
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


def _load_dotenv() -> None:
    """Load environment variables from .env if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.debug("python-dotenv not installed; skipping .env load")
        return
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
        logger.info("Loaded environment from .env")


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides on top of the JSON config.

    Recognised vars:
        OPENMATRIX_API_KEY               -> gateway.api_key
        OPENMATRIX_PORT                  -> gateway.port
        OPENMATRIX_HOST                  -> gateway.host
        OPENAI_API_KEY                   -> model.providers.openai.api_key
        ANTHROPIC_API_KEY                -> model.providers.anthropic.api_key
                                            (and mythos)
        NVIDIA_API_KEY                   -> model.providers.nvidia.api_key
        GOOGLE_API_KEY                   -> model.providers.gemini.api_key
        BASE_RPC_URL                     -> blockchain.rpc_url
        TELEGRAM_BOT_TOKEN               -> notifications.telegram.bot_token
    """
    gw = config.setdefault("gateway", {})
    if os.environ.get("OPENMATRIX_API_KEY"):
        gw["api_key"] = os.environ["OPENMATRIX_API_KEY"]
    if os.environ.get("OPENMATRIX_PORT"):
        try:
            gw["port"] = int(os.environ["OPENMATRIX_PORT"])
        except ValueError:
            pass
    if os.environ.get("OPENMATRIX_HOST"):
        gw["host"] = os.environ["OPENMATRIX_HOST"]

    providers = config.setdefault("model", {}).setdefault("providers", {})
    env_to_provider = {
        "OPENAI_API_KEY": "openai",
        "ANTHROPIC_API_KEY": "anthropic",
        "NVIDIA_API_KEY": "nvidia",
        "GOOGLE_API_KEY": "gemini",
    }
    for env_var, name in env_to_provider.items():
        if os.environ.get(env_var):
            providers.setdefault(name, {})["api_key"] = os.environ[env_var]
    # Mythos shares the Anthropic key
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers.setdefault("mythos", {})["api_key"] = os.environ["ANTHROPIC_API_KEY"]

    if os.environ.get("BASE_RPC_URL"):
        config.setdefault("blockchain", {})["rpc_url"] = os.environ["BASE_RPC_URL"]

    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        config.setdefault("notifications", {}).setdefault("telegram", {})["bot_token"] = (
            os.environ["TELEGRAM_BOT_TOKEN"]
        )

    return config


def load_config() -> dict:
    _load_dotenv()
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.error(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    config = json.loads(path.read_text())
    return _apply_env_overrides(config)


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

        # Hydrate conversations cache from disk
        self._conv_loaded: set[str] = set()

        # Auth: API key from config or environment
        gw = config.get("gateway", {})
        self.api_key = gw.get("api_key") or os.environ.get("OPENMATRIX_API_KEY", "")
        self.auth_enabled = bool(self.api_key)
        # Endpoints that don't require auth
        self._public_paths = {"/health", "/auth/nonce", "/auth/verify"}

        # SIWE auth stores (SQLite-backed). Initialised in the on_startup
        # hook once the underlying memory database has been opened.
        self.wallet_sessions = WalletSessionStore(self.react_loop.memory.db)
        self.wallet_nonces = NonceStore(self.react_loop.memory.db)
        self._wallet_session_ttl = gw.get("wallet_session_ttl_seconds", 86400)
        self._auth_cleanup_task: asyncio.Task | None = None

        # Daily SQLite backup. Disabled when ``backup.enabled`` is false.
        backup_cfg = self.config.get("backup", {}) if isinstance(self.config, dict) else {}
        self._backup_enabled = bool(backup_cfg.get("enabled", True))
        self._backup_dir = backup_cfg.get(
            "directory",
            str(Path(self.react_loop.memory.db.db_path).parent / "backups"),
        )
        self._backup_retention = int(backup_cfg.get("retention", 7))
        self._backup_interval = float(backup_cfg.get("interval_seconds", 24 * 60 * 60))
        self.backup_manager: BackupManager | None = None
        self._backup_task: asyncio.Task | None = None

        # In-process metrics collector and (optional) Sentry reporter
        self.metrics = MetricsCollector()
        initialize_sentry(self.config)

        # Rate limiting — separate buckets for authenticated and anonymous
        auth_rpm = gw.get("rate_limit_rpm_authenticated", gw.get("rate_limit_rpm", 120))
        auth_burst = gw.get("rate_limit_burst_authenticated", gw.get("rate_limit_burst", 30))
        anon_rpm = gw.get("rate_limit_rpm_anonymous", 20)
        anon_burst = gw.get("rate_limit_burst_anonymous", 5)
        self.rate_limiter_auth = RateLimiter(requests_per_minute=auth_rpm, burst=auth_burst)
        self.rate_limiter_anon = RateLimiter(requests_per_minute=anon_rpm, burst=anon_burst)

    async def handle_chat(self, request: web.Request) -> web.Response:
        """POST /chat — {agent, message, session_id} -> {response, tool_calls, session_id}"""
        self.request_count += 1
        self.metrics.incr("chat.requests")
        try:
            body = await request.json()
        except json.JSONDecodeError:
            self.metrics.incr("chat.errors.invalid_json")
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

        # Load conversation from disk on first access (write-through cache)
        if session_id not in self._conv_loaded:
            stored = self.react_loop.memory.load_conversation(session_id)
            if stored:
                self.conversations[session_id] = [
                    Message(role=m["role"], content=m["content"]) for m in stored
                ]
            else:
                self.conversations[session_id] = []
            self._conv_loaded.add(session_id)
        elif session_id not in self.conversations:
            self.conversations[session_id] = []

        # Trinity first-boot message — once per session
        first_boot = None
        if agent == "trinity" and not self.react_loop.memory.is_first_boot_sent(session_id):
            await self.react_loop.memory.mark_first_boot_sent(session_id)
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
            with self.metrics.timer("chat.latency"):
                result = await self.react_loop.run(context)
        except RuntimeError as e:
            self.metrics.incr("chat.errors.model")
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

        # Persist updated conversation to disk
        try:
            await self.react_loop.memory.save_conversation(
                session_id,
                [{"role": m.role, "content": m.content} for m in self.conversations[session_id]],
            )
        except Exception as exc:
            logger.warning(f"Failed to persist conversation {session_id}: {exc}")

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

        subsystems = await self._subsystem_health()

        return web.json_response({
            "platform": "0pnMatrx",
            "version": "1.0.0",
            "agents": active,
            "model": {
                "provider": self.config.get("model", {}).get("provider", "unknown"),
                "primary": self.config.get("model", {}).get("primary", "unknown"),
            },
            "sessions": len(self.conversations),
            "wallet_sessions": len(self.wallet_sessions),
            "total_requests": self.request_count,
            "uptime_seconds": round(uptime, 1),
            "memory_mb": round(mem_mb, 1),
            "subsystems": subsystems,
        })

    async def _subsystem_health(self) -> dict:
        """Probe each major subsystem and return its health state."""
        result: dict = {}

        # Model providers
        try:
            result["models"] = await self.react_loop.router.health_check()
        except Exception as exc:
            result["models"] = {"error": str(exc)}

        # Memory store: writable & directory exists
        try:
            mem_dir = self.react_loop.memory.memory_dir
            result["memory"] = {
                "ok": mem_dir.exists() and os.access(str(mem_dir), os.W_OK),
                "dir": str(mem_dir),
            }
        except Exception as exc:
            result["memory"] = {"ok": False, "error": str(exc)}

        # Blockchain RPC configured
        rpc_url = self.config.get("blockchain", {}).get("rpc_url", "")
        if rpc_url and not rpc_url.startswith("YOUR_"):
            result["blockchain"] = {"configured": True}
        else:
            result["blockchain"] = {"configured": False}

        # Protocol stack
        try:
            stack = getattr(self.react_loop, "protocol_stack", None)
            if stack is not None:
                protocols = list(getattr(stack, "_protocols", {}).keys())
                result["protocols"] = {"ok": True, "loaded": protocols}
            else:
                result["protocols"] = {"ok": False, "loaded": []}
        except Exception as exc:
            result["protocols"] = {"ok": False, "error": str(exc)}

        return result

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """GET /metrics — JSON snapshot of counters/gauges/histograms."""
        return web.json_response(self.metrics.snapshot())

    async def handle_metrics_prometheus(self, request: web.Request) -> web.Response:
        """GET /metrics/prom — Prometheus text exposition format."""
        body = self.metrics.format_prometheus()
        return web.Response(
            text=body,
            content_type="text/plain",
            charset="utf-8",
        )

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

        await self.react_loop.memory.write(agent, key, value)
        return web.json_response({"success": True, "agent": agent, "key": key})

    # ─── SIWE Authentication ─────────────────────────────────────────────

    async def handle_auth_nonce(self, request: web.Request) -> web.Response:
        """POST /auth/nonce — {address} -> {nonce, message}

        Issues a one-time nonce for the wallet to sign. Returns the
        canonical EIP-4361 message text the client should present to the
        user for signing.
        """
        from runtime.auth.siwe import generate_nonce, build_siwe_message

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        address = str(body.get("address", "")).strip()
        if not address or not address.startswith("0x") or len(address) != 42:
            return web.json_response({"error": "valid 0x address required"}, status=400)

        nonce = generate_nonce()
        await self.wallet_nonces.add(nonce)

        gw = self.config.get("gateway", {})
        domain = gw.get("siwe_domain", "0pnmatrx.local")
        uri = gw.get("siwe_uri", f"https://{domain}")
        chain_id = self.config.get("blockchain", {}).get("chain_id", 84532)

        message = build_siwe_message(
            address=address,
            nonce=nonce,
            domain=domain,
            chain_id=chain_id,
            uri=uri,
        )

        return web.json_response({"nonce": nonce, "message": message})

    async def handle_auth_verify(self, request: web.Request) -> web.Response:
        """POST /auth/verify — {address, message, signature, nonce} -> {token}

        Verifies the SIWE signature and issues a wallet session token to be
        sent in the ``X-Wallet-Session`` header on subsequent requests.
        """
        from runtime.auth.siwe import verify_signature, create_session_token

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        address = str(body.get("address", "")).strip()
        message = str(body.get("message", ""))
        signature = str(body.get("signature", ""))
        nonce = str(body.get("nonce", ""))

        if not (address and message and signature and nonce):
            return web.json_response(
                {"error": "address, message, signature, and nonce required"},
                status=400,
            )

        # Nonce must be one we issued and still valid
        if nonce not in self.wallet_nonces:
            return web.json_response({"error": "unknown or expired nonce"}, status=401)
        # Nonce must be embedded in the signed message
        if f"Nonce: {nonce}" not in message:
            return web.json_response({"error": "nonce mismatch"}, status=401)
        # Single-use
        await self.wallet_nonces.consume(nonce)

        if not verify_signature(address, message, signature):
            return web.json_response({"error": "invalid signature"}, status=401)

        token = create_session_token()
        now = time.time()
        expires_at = now + self._wallet_session_ttl
        await self.wallet_sessions.add(
            token=token,
            address=address,
            issued_at=now,
            expires_at=expires_at,
        )

        return web.json_response({
            "token": token,
            "address": address,
            "expires_at": expires_at,
        })

    # ─── Streaming ────────────────────────────────────────────────────────

    async def handle_chat_stream(self, request: web.Request) -> web.StreamResponse:
        """POST /chat/stream — Server-Sent Events stream of a chat response.

        Same body shape as ``/chat`` but emits incremental ``data:`` events
        as the agent produces output. Final event is ``event: done``.
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        message = str(body.get("message", "")).strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)
        if len(message) > 100000:
            return web.json_response({"error": "message too long"}, status=400)

        session_id = str(body.get("session_id", "default"))[:100]
        agent = str(body.get("agent", "trinity"))[:50]
        valid_agents = {"neo", "trinity", "morpheus"}
        if agent not in valid_agents:
            return web.json_response(
                {"error": f"invalid agent, must be one of: {', '.join(valid_agents)}"},
                status=400,
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        async def emit(event: str, data: dict) -> None:
            payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            await response.write(payload.encode("utf-8"))

        # Hydrate conversation
        if session_id not in self._conv_loaded:
            stored = self.react_loop.memory.load_conversation(session_id)
            if stored:
                self.conversations[session_id] = [
                    Message(role=m["role"], content=m["content"]) for m in stored
                ]
            else:
                self.conversations[session_id] = []
            self._conv_loaded.add(session_id)
        elif session_id not in self.conversations:
            self.conversations[session_id] = []

        self.conversations[session_id].append(Message(role="user", content=message))

        await emit("start", {"session_id": session_id, "agent": agent})

        system_prompt = self.react_loop.get_agent_prompt(agent)
        time_context = self.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        context = ReActContext(
            agent_name=agent,
            conversation=self.conversations[session_id].copy(),
            system_prompt=full_prompt,
        )
        context.metadata["user_context"] = {
            "session_id": session_id,
            "agent": agent,
            "wallet_connected": body.get("wallet_connected", True),
            "network": body.get("network"),
        }

        try:
            result = await self.react_loop.run(context)
        except RuntimeError as e:
            await emit("error", {"error": str(e)})
            await emit("done", {})
            await response.write_eof()
            return response

        # Chunk response into ~80-char tokens for incremental delivery
        text = result.response
        chunk_size = 80
        for i in range(0, len(text), chunk_size):
            await emit("token", {"text": text[i:i + chunk_size]})

        self.conversations[session_id].append(Message(role="assistant", content=text))
        if len(self.conversations[session_id]) > 100:
            self.conversations[session_id] = self.conversations[session_id][-50:]
        try:
            await self.react_loop.memory.save_conversation(
                session_id,
                [{"role": m.role, "content": m.content} for m in self.conversations[session_id]],
            )
        except Exception as exc:
            logger.warning(f"Failed to persist streamed conversation {session_id}: {exc}")

        await emit("done", {
            "session_id": session_id,
            "agent": agent,
            "tool_calls": result.tool_calls,
            "provider": result.provider,
        })
        await response.write_eof()
        return response

    # ─── WebSocket ────────────────────────────────────────────────────────

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """GET /ws — bidirectional chat socket.

        Client sends JSON frames: ``{"type":"chat","message":"...","agent":"trinity","session_id":"..."}``
        Server responds with ``{"type":"token","text":"..."}`` events and a final
        ``{"type":"done", ...}`` frame.
        """
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "error": "invalid JSON"})
                continue

            if payload.get("type") != "chat":
                await ws.send_json({"type": "error", "error": "unsupported message type"})
                continue

            message = str(payload.get("message", "")).strip()
            if not message:
                await ws.send_json({"type": "error", "error": "message required"})
                continue
            if len(message) > 100000:
                await ws.send_json({"type": "error", "error": "message too long"})
                continue

            session_id = str(payload.get("session_id", "default"))[:100]
            agent = str(payload.get("agent", "trinity"))[:50]
            if agent not in {"neo", "trinity", "morpheus"}:
                await ws.send_json({"type": "error", "error": "invalid agent"})
                continue

            if session_id not in self._conv_loaded:
                stored = self.react_loop.memory.load_conversation(session_id)
                self.conversations[session_id] = [
                    Message(role=m["role"], content=m["content"]) for m in stored
                ] if stored else []
                self._conv_loaded.add(session_id)
            elif session_id not in self.conversations:
                self.conversations[session_id] = []

            self.conversations[session_id].append(Message(role="user", content=message))

            system_prompt = self.react_loop.get_agent_prompt(agent)
            time_context = self.temporal.get_context_string()
            full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

            context = ReActContext(
                agent_name=agent,
                conversation=self.conversations[session_id].copy(),
                system_prompt=full_prompt,
            )
            context.metadata["user_context"] = {
                "session_id": session_id,
                "agent": agent,
            }

            try:
                result = await self.react_loop.run(context)
            except RuntimeError as e:
                await ws.send_json({"type": "error", "error": str(e)})
                continue

            text = result.response
            for i in range(0, len(text), 80):
                await ws.send_json({"type": "token", "text": text[i:i + 80]})

            self.conversations[session_id].append(Message(role="assistant", content=text))
            if len(self.conversations[session_id]) > 100:
                self.conversations[session_id] = self.conversations[session_id][-50:]
            try:
                await self.react_loop.memory.save_conversation(
                    session_id,
                    [{"role": m.role, "content": m.content} for m in self.conversations[session_id]],
                )
            except Exception as exc:
                logger.warning(f"Failed to persist ws conversation {session_id}: {exc}")

            await ws.send_json({
                "type": "done",
                "session_id": session_id,
                "agent": agent,
                "provider": result.provider,
                "tool_calls": result.tool_calls,
            })

        return ws

    async def _start_cleanup_task(self, app: web.Application) -> None:
        """Initialise persistence and start background cleanup tasks."""
        # Open the SQLite database and load auth stores from disk.
        await self.react_loop.memory.initialize()
        await self.wallet_sessions.initialize()
        await self.wallet_nonces.initialize()
        # Rate-limiter bucket sweeper
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        # Wallet session / nonce sweeper
        self._auth_cleanup_task = asyncio.create_task(
            run_cleanup_loop(self.wallet_sessions, self.wallet_nonces)
        )
        # Daily database backup
        if self._backup_enabled:
            try:
                self.backup_manager = BackupManager(
                    self.react_loop.memory.db,
                    backup_dir=self._backup_dir,
                    retention=self._backup_retention,
                )
                self._backup_task = asyncio.create_task(
                    run_backup_loop(self.backup_manager, self._backup_interval)
                )
                logger.info(
                    "Backup loop scheduled: dir=%s retention=%d interval=%.0fs",
                    self._backup_dir, self._backup_retention, self._backup_interval,
                )
            except Exception as exc:
                logger.warning("Failed to start backup loop: %s", exc)

    async def _cleanup_loop(self) -> None:
        """Periodically prune stale rate-limiter buckets and service caches."""
        while True:
            try:
                await asyncio.sleep(300)
                self.rate_limiter_auth.cleanup()
                self.rate_limiter_anon.cleanup()
                # Sweep stale oracle/service caches so expired entries
                # left behind for ``get_stale`` don't accumulate.
                dispatcher = getattr(self.react_loop, "dispatcher", None)
                prune = getattr(dispatcher, "prune_caches", None)
                if prune is not None:
                    try:
                        evicted = await prune(grace_seconds=300.0)
                        if evicted:
                            self.metrics.incr("caches.evicted", evicted)
                    except Exception as exc:
                        logger.warning("Service cache prune failed: %s", exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Rate limiter cleanup failed: %s", exc)

    async def _on_cleanup(self, app: web.Application) -> None:
        """Run on aiohttp shutdown to cancel background tasks and log shutdown."""
        for attr in ("_cleanup_task", "_auth_cleanup_task", "_backup_task"):
            task = getattr(self, attr, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        try:
            await self.react_loop.memory.close()
        except Exception as exc:
            logger.warning("Memory close failed: %s", exc)
        logger.info("Gateway shutting down cleanly.")

    def create_app(self) -> web.Application:
        app = web.Application(middlewares=[
            self._cors_middleware,
            self._auth_middleware,
            self._rate_limit_middleware,
            self._logging_middleware,
        ])
        app.on_startup.append(self._start_cleanup_task)
        app.on_cleanup.append(self._on_cleanup)
        app.router.add_post("/chat", self.handle_chat)
        app.router.add_post("/chat/stream", self.handle_chat_stream)
        app.router.add_get("/ws", self.handle_websocket)
        app.router.add_get("/health", self.handle_health)
        app.router.add_get("/status", self.handle_status)
        app.router.add_post("/memory/read", self.handle_memory_read)
        app.router.add_post("/memory/write", self.handle_memory_write)
        app.router.add_post("/auth/nonce", self.handle_auth_nonce)
        app.router.add_post("/auth/verify", self.handle_auth_verify)
        app.router.add_get("/metrics", self.handle_metrics)
        app.router.add_get("/metrics/prom", self.handle_metrics_prometheus)

        # Register all 30 blockchain service REST endpoints
        try:
            from gateway.service_routes import ServiceRoutes
            service_routes = ServiceRoutes(self.config)
            service_routes.register_routes(app)
            logger.info("Service routes registered successfully.")
        except Exception as e:
            logger.warning("Service routes registration skipped: %s", e)

        # Register MTRX iOS bridge endpoints
        try:
            from gateway.bridge import BridgeRoutes
            bridge = BridgeRoutes(self.config, self)
            bridge.register_routes(app)
            logger.info("Bridge routes registered under /bridge/v1/")
        except Exception as e:
            logger.warning("Bridge routes registration skipped: %s", e)

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
        """Enforce rate limits. Uses API key as bucket when authenticated, IP otherwise."""
        if request.method == "OPTIONS":
            return await handler(request)

        # Determine rate limit key and limiter
        auth_header = request.headers.get("Authorization", "")
        api_key = ""
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
        elif request.query.get("api_key"):
            api_key = request.query["api_key"]

        if api_key and self.auth_enabled and hmac.compare_digest(api_key, self.api_key):
            # Authenticated: use API key as bucket, higher limits
            rate_key = f"key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
            limiter = self.rate_limiter_auth
        else:
            # Anonymous: use IP as bucket, stricter limits
            client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if not client_ip:
                peername = request.transport.get_extra_info("peername")
                client_ip = peername[0] if peername else "unknown"
            rate_key = f"ip:{client_ip}"
            limiter = self.rate_limiter_anon

        if not limiter.allow(rate_key):
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
        # cors_origins: [] blocks all cross-origin. ["*"] allows all. Otherwise list specific origins.
        allowed_origins = self.config.get("gateway", {}).get("cors_origins", [])
        origin = request.headers.get("Origin", "")
        if allowed_origins:
            if "*" in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin or "*"
            elif origin in allowed_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Wallet-Session"
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
    web.run_app(app, host=host, port=port, print=None, shutdown_timeout=30)


if __name__ == "__main__":
    main()
