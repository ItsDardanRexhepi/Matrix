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
from runtime.logging import (
    configure_logging,
    generate_request_id,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from runtime.monitoring.metrics import MetricsCollector
from runtime.monitoring.otel import OTelMetricsBridge
from runtime.monitoring.sentry import initialize_sentry
from runtime.config.validation import (
    ConfigValidationError,
    enforce_env_only_secrets,
    is_production_mode,
    validate_config,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = "openmatrix.config.json"
START_TIME = time.time()

# ─── Rate Limiter ────────────────────────────────────────────────────────────

class RateLimiter:
    """Token-bucket rate limiter.

    The caller supplies the bucket *key* on every ``allow`` call, which
    lets the same limiter serve multiple key shapes (per-IP for
    anonymous traffic, per-API-key for bearer auth, per-wallet-address
    for SIWE-authenticated wallets). Buckets are created on first
    touch and garbage-collected periodically via :meth:`cleanup`.
    """

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
    """Load, env-override, enforce secret-env rules, and validate the config.

    In **production mode** (``OPNMATRX_ENV=production``):
      - Secrets must come from environment variables. Any plaintext
        copies in the JSON file are stripped.
      - Validation errors abort startup.
      - Missing required env secrets abort startup.

    In **development/testnet mode** (default):
      - Placeholder values are treated as "not configured" so the
        blockchain services degrade gracefully.
      - Validation errors are logged but do not abort.
    """
    _load_dotenv()
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.error("Config file not found: %s", CONFIG_PATH)
        sys.exit(1)

    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.error(
            "Config file %s is not valid JSON: %s (line %d col %d)",
            CONFIG_PATH,
            exc.msg,
            exc.lineno,
            exc.colno,
        )
        sys.exit(1)

    config = _apply_env_overrides(config)

    strict = is_production_mode()
    try:
        config = enforce_env_only_secrets(config, strict=strict)
    except ConfigValidationError as exc:
        logger.error("Secret loading failed:\n%s", exc)
        sys.exit(1)

    report = validate_config(config, strict=strict)
    if report.errors:
        logger.error("Config validation failed:\n%s", report.format())
        if strict:
            sys.exit(1)
    if report.warnings:
        logger.warning("Config validation warnings:\n%s", report.format())

    return config


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
        self._public_paths = {
            "/health", "/auth/nonce", "/auth/verify",
            "/", "/chat", "/pricing", "/audit", "/marketplace",
            "/services/conversion",
            "/extensions/registry",
            "/subscription/webhook",
            "/a2a/services",
            "/sponsor", "/glasswing", "/learn",
            "/badges", "/privacy", "/terms",
            "/social", "/social/feed", "/social/feed/stream",
            "/social/trending", "/social/stats",
        }

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
        # Optional OTel push exporter — no-op unless both the config
        # flag and the opentelemetry packages are present.
        self.otel_bridge = OTelMetricsBridge(self.metrics, self.config)

        # ── Subscription system ──────────────────────────────────────
        self.subscription_store = None
        self.usage_tracker = None
        self.feature_gate_instance = None
        self.stripe_client = None
        self.audit_service = None
        self.conversion_service = None
        self.plugin_marketplace = None
        self.a2a_marketplace = None
        self.social_manager = None
        self.social_feed_engine = None
        self.referral_manager = None
        self.metered_billing = None
        self.protocol_referrals = None
        self.badge_manager = None
        self.certification_manager = None
        self.revenue_reporter = None

        # Rate limiting — three buckets:
        #   - ``rate_limiter_auth``   : API-key bearer auth (operator tokens)
        #   - ``rate_limiter_wallet`` : per-SIWE-address, keyed by wallet
        #   - ``rate_limiter_anon``   : per-IP, for unauthenticated traffic
        auth_rpm = gw.get("rate_limit_rpm_authenticated", gw.get("rate_limit_rpm", 120))
        auth_burst = gw.get("rate_limit_burst_authenticated", gw.get("rate_limit_burst", 30))
        wallet_rpm = gw.get("rate_limit_rpm_wallet", auth_rpm)
        wallet_burst = gw.get("rate_limit_burst_wallet", auth_burst)
        anon_rpm = gw.get("rate_limit_rpm_anonymous", 20)
        anon_burst = gw.get("rate_limit_burst_anonymous", 5)
        self.rate_limiter_auth = RateLimiter(requests_per_minute=auth_rpm, burst=auth_burst)
        self.rate_limiter_wallet = RateLimiter(
            requests_per_minute=wallet_rpm, burst=wallet_burst
        )
        self.rate_limiter_anon = RateLimiter(requests_per_minute=anon_rpm, burst=anon_burst)

        # Request timeout (seconds) applied via middleware. ``0`` disables.
        self.request_timeout = float(gw.get("request_timeout_seconds", 120))

        # WebSocket configuration — frame size limit and heartbeat.
        ws_cfg = gw.get("websocket", {}) if isinstance(gw.get("websocket"), dict) else {}
        self.ws_max_message_size = int(ws_cfg.get("max_message_size", 1 << 20))  # 1 MiB
        self.ws_heartbeat_seconds = float(ws_cfg.get("heartbeat_seconds", 30))

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
        ws = web.WebSocketResponse(
            heartbeat=self.ws_heartbeat_seconds,
            max_msg_size=self.ws_max_message_size,
        )
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

    # ─── Web Pages ───────────────────────────────────────────────────

    async def handle_landing(self, request: web.Request) -> web.Response:
        """GET / — serve the landing page."""
        return self._serve_html("web/landing.html")

    async def handle_chat_page(self, request: web.Request) -> web.Response:
        """GET /chat — serve the web chat interface."""
        return self._serve_html("web/index.html")

    async def handle_pricing_page(self, request: web.Request) -> web.Response:
        """GET /pricing — serve the pricing page."""
        return self._serve_html("web/pricing.html")

    async def handle_audit_page(self, request: web.Request) -> web.Response:
        """GET /audit — serve the audit service page."""
        return self._serve_html("web/audit.html")

    async def handle_marketplace_page(self, request: web.Request) -> web.Response:
        """GET /marketplace — serve the plugin marketplace page."""
        return self._serve_html("web/marketplace.html")

    async def handle_conversion_page(self, request: web.Request) -> web.Response:
        """GET /services/conversion — serve the conversion service page."""
        return self._serve_html("web/conversion-service.html")

    async def handle_privacy_page(self, request: web.Request) -> web.Response:
        """GET /privacy — serve the privacy policy page."""
        return self._serve_html("web/privacy.html")

    async def handle_terms_page(self, request: web.Request) -> web.Response:
        """GET /terms — serve the terms of service page."""
        return self._serve_html("web/terms.html")

    def _serve_html(self, path: str) -> web.Response:
        """Serve a static HTML file."""
        filepath = Path(path)
        if filepath.exists():
            return web.Response(
                text=filepath.read_text(encoding="utf-8"),
                content_type="text/html",
            )
        return web.Response(text="Page not found", status=404)

    # ─── Extensions Registry ─────────────────────────────────────────

    async def handle_extensions_registry(self, request: web.Request) -> web.Response:
        """GET /extensions/registry — serve the component registry JSON."""
        registry_path = Path("extensions/registry.json")
        if not registry_path.exists():
            return web.json_response({"error": "Registry not found"}, status=404)
        import json as _json
        data = _json.loads(registry_path.read_text(encoding="utf-8"))
        return web.json_response(data)

    async def handle_extensions_component(self, request: web.Request) -> web.Response:
        """GET /extensions/registry/{component_id} — single component."""
        component_id = request.match_info.get("component_id", "")
        registry_path = Path("extensions/registry.json")
        if not registry_path.exists():
            return web.json_response({"error": "Registry not found"}, status=404)
        import json as _json
        data = _json.loads(registry_path.read_text(encoding="utf-8"))
        for comp in data.get("components", []):
            if comp.get("id") == component_id:
                return web.json_response(comp)
        return web.json_response({"error": "Component not found"}, status=404)

    # ─── Subscription Endpoints ──────────────────────────────────────

    async def handle_subscription_checkout(self, request: web.Request) -> web.Response:
        """POST /subscription/checkout — create a Stripe checkout session."""
        if not self.stripe_client or not self.stripe_client.available:
            return web.json_response({
                "status": "not_configured",
                "message": "Stripe is not configured. Contact support to upgrade.",
            })
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        tier = str(body.get("tier", "pro"))
        wallet = str(body.get("wallet_address", ""))
        success_url = str(body.get("success_url", "http://localhost:18790/pricing?status=success"))
        cancel_url = str(body.get("cancel_url", "http://localhost:18790/pricing?status=cancelled"))
        result = await self.stripe_client.create_checkout_session(tier, wallet, success_url, cancel_url)
        return web.json_response(result)

    async def handle_subscription_webhook(self, request: web.Request) -> web.Response:
        """POST /subscription/webhook — receive Stripe webhook events."""
        if not self.stripe_client:
            return web.json_response({"status": "not_configured"}, status=503)
        payload = await request.read()
        sig = request.headers.get("Stripe-Signature", "")
        result = await self.stripe_client.handle_webhook(payload, sig)
        if result.get("status") == "error":
            return web.json_response(result, status=400)
        # Update subscription store on successful events
        if self.subscription_store and result.get("wallet_address"):
            tier = result.get("tier", "free")
            if result.get("cancelled"):
                tier = "free"
            await self.subscription_store.upsert(
                result["wallet_address"], tier,
                {"customer_id": result.get("customer_id"),
                 "subscription_id": result.get("subscription_id"),
                 "status": result.get("status_value", "active"),
                 "current_period_end": result.get("current_period_end"),
                 "trial_end": result.get("trial_end")},
            )
        return web.json_response(result)

    async def handle_subscription_status(self, request: web.Request) -> web.Response:
        """GET /subscription/status — current tier and usage."""
        wallet = request.headers.get("X-Wallet-Address", "")
        if not wallet:
            wallet_token = request.headers.get("X-Wallet-Session", "").strip()
            if wallet_token:
                try:
                    session = self.wallet_sessions.get(wallet_token)
                    if session:
                        wallet = str(session.get("address", ""))
                except Exception:
                    pass
        tier = "free"
        usage = {}
        is_trial = False
        if self.subscription_store and wallet:
            from runtime.subscriptions.tiers import SubscriptionTier
            tier_enum = await self.subscription_store.get_tier(wallet)
            tier = tier_enum.value
            is_trial = await self.subscription_store.is_trial(wallet)
        if self.usage_tracker and wallet:
            usage = await self.usage_tracker.get_summary(wallet)
        return web.json_response({
            "tier": tier,
            "usage": usage,
            "is_trial": is_trial,
        })

    # ─── Audit Endpoints ─────────────────────────────────────────────

    async def handle_audit_request(self, request: web.Request) -> web.Response:
        """POST /audit/request — submit a contract for audit."""
        if not self.audit_service:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        source = str(body.get("source_code", ""))
        name = str(body.get("contract_name", "Contract"))
        email = str(body.get("email", ""))
        tier = str(body.get("tier", "standard"))
        if not source:
            return web.json_response({"error": "source_code is required"}, status=400)
        result = await self.audit_service.create_audit_request(source, name, email, tier)
        return web.json_response(result)

    async def handle_audit_report(self, request: web.Request) -> web.Response:
        """GET /audit/{audit_id} — get an audit report."""
        if not self.audit_service:
            return web.json_response({"status": "not_available"}, status=503)
        audit_id = request.match_info.get("audit_id", "")
        result = await self.audit_service.get_audit_report(audit_id)
        return web.json_response(result)

    # ─── Social Endpoints ────────────────────────────────────────────

    async def handle_social_post(self, request: web.Request) -> web.Response:
        """POST /social/post — post to social media."""
        if not self.social_manager or not self.social_manager.available:
            return web.json_response({"status": "not_configured",
                                      "message": "No social media platforms configured."})
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        content = str(body.get("content", ""))
        platform = str(body.get("platform", "all"))
        if not content:
            return web.json_response({"error": "content is required"}, status=400)
        result = await self.social_manager.post(content=content, platform=platform,
                                                 metadata=body.get("metadata"))
        return web.json_response(result)

    # ─── Social Feed Endpoints ──────────────────────────────────────

    async def handle_social_feed_page(self, request: web.Request) -> web.Response:
        """GET /social — serve the social feed UI."""
        return self._serve_html("web/social.html")

    async def handle_social_feed(self, request: web.Request) -> web.Response:
        """GET /social/feed — return ranked feed events as JSON."""
        if not self.social_feed_engine:
            return web.json_response({"events": [], "message": "Feed not initialised"})
        limit = min(int(request.query.get("limit", "50")), 200)
        offset = int(request.query.get("offset", "0"))
        event_type = request.query.get("type")
        component = request.query.get("component")
        actor = request.query.get("actor")
        min_score = float(request.query.get("min_score", "0"))

        comp_int = int(component) if component else None

        from runtime.social.feed_formatter import FeedFormatter
        events = await self.social_feed_engine.get_feed(
            limit=limit, offset=offset, event_type=event_type,
            component=comp_int, actor=actor, min_score=min_score,
        )
        return web.json_response({
            "events": FeedFormatter.format_feed(events),
            "count": len(events),
            "offset": offset,
            "limit": limit,
        })

    async def handle_social_feed_stream(self, request: web.Request) -> web.StreamResponse:
        """GET /social/feed/stream — SSE stream of live feed events.

        Uses the :class:`EventBroadcaster` to push new
        ``feed.new_event`` broadcasts to connected clients.
        """
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        broadcaster = getattr(self, "event_broadcaster", None)
        if broadcaster is None:
            await response.write(b"event: error\ndata: {\"error\":\"broadcaster not available\"}\n\n")
            return response

        peer = request.remote or "unknown"
        sub = broadcaster.register(
            ip=peer,
            types={"feed.new_event"},
        )

        try:
            async for event in broadcaster.iter_events(sub):
                payload = json.dumps(event.to_dict())
                chunk = f"id: {event.event_id}\nevent: feed\ndata: {payload}\n\n"
                await response.write(chunk.encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            broadcaster.unregister(sub)

        return response

    async def handle_social_trending(self, request: web.Request) -> web.Response:
        """GET /social/trending — trending actions over a time window."""
        if not self.social_feed_engine:
            return web.json_response({"trending": []})
        window = int(request.query.get("hours", "24"))
        trending = await self.social_feed_engine.get_trending(window_hours=window)
        return web.json_response({"trending": trending, "window_hours": window})

    async def handle_social_actor(self, request: web.Request) -> web.Response:
        """GET /social/actor/{wallet} — activity for a specific wallet."""
        if not self.social_feed_engine:
            return web.json_response({"events": []})
        wallet = request.match_info.get("wallet", "")
        limit = min(int(request.query.get("limit", "50")), 200)
        from runtime.social.feed_formatter import FeedFormatter
        events = await self.social_feed_engine.get_actor_feed(wallet=wallet, limit=limit)
        return web.json_response({
            "actor": wallet,
            "events": FeedFormatter.format_feed(events),
            "count": len(events),
        })

    async def handle_social_stats(self, request: web.Request) -> web.Response:
        """GET /social/stats — global feed statistics."""
        if not self.social_feed_engine:
            return web.json_response({"stats": {}})
        stats = await self.social_feed_engine.get_stats()
        return web.json_response({"stats": stats})

    # ─── A2A Endpoints ───────────────────────────────────────────────

    async def handle_a2a_services(self, request: web.Request) -> web.Response:
        """GET /a2a/services — list available agent services."""
        if not self.a2a_marketplace:
            return web.json_response({"services": []})
        category = request.query.get("category")
        services = await self.a2a_marketplace.list_services(category=category)
        return web.json_response({"services": services})

    async def handle_a2a_submit_job(self, request: web.Request) -> web.Response:
        """POST /a2a/jobs — submit a job to an agent service."""
        if not self.a2a_marketplace:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        from runtime.a2a.protocol import JobRequest
        job = JobRequest(
            service_id=str(body.get("service_id", "")),
            requester_agent_id=str(body.get("requester", "user")),
            provider_agent_id=str(body.get("provider", "")),
            input_data=body.get("input", {}),
            max_price_usd=float(body.get("max_price_usd", 0)),
        )
        await self.a2a_marketplace.submit_job(job)
        return web.json_response(job.to_dict(), status=201)

    async def handle_a2a_get_job(self, request: web.Request) -> web.Response:
        """GET /a2a/jobs/{job_id} — get job status."""
        if not self.a2a_marketplace:
            return web.json_response({"status": "not_available"}, status=503)
        job_id = request.match_info.get("job_id", "")
        result = await self.a2a_marketplace.get_job(job_id)
        if not result:
            return web.json_response({"error": "Job not found"}, status=404)
        return web.json_response(result)

    # ─── Marketplace Endpoints ───────────────────────────────────────

    async def handle_marketplace_list(self, request: web.Request) -> web.Response:
        """GET /marketplace/plugins — list plugins."""
        if not self.plugin_marketplace:
            return web.json_response({"plugins": []})
        tier = request.query.get("tier")
        category = request.query.get("category")
        plugins = await self.plugin_marketplace.list_plugins(tier=tier, category=category)
        return web.json_response({"plugins": plugins})

    async def handle_marketplace_plugin(self, request: web.Request) -> web.Response:
        """GET /marketplace/plugins/{plugin_id} — single plugin."""
        if not self.plugin_marketplace:
            return web.json_response({"error": "Not available"}, status=503)
        plugin_id = request.match_info.get("plugin_id", "")
        plugin = await self.plugin_marketplace.get_plugin(plugin_id)
        if not plugin:
            return web.json_response({"error": "Plugin not found"}, status=404)
        return web.json_response(plugin)

    async def handle_marketplace_purchase(self, request: web.Request) -> web.Response:
        """POST /marketplace/plugins/{plugin_id}/purchase — purchase a plugin."""
        if not self.plugin_marketplace:
            return web.json_response({"error": "Not available"}, status=503)
        plugin_id = request.match_info.get("plugin_id", "")
        wallet = request.headers.get("X-Wallet-Address", "anonymous")
        result = await self.plugin_marketplace.purchase(wallet, plugin_id)
        return web.json_response(result)

    async def handle_marketplace_submit(self, request: web.Request) -> web.Response:
        """POST /marketplace/plugins/submit — submit a plugin for review."""
        if not self.plugin_marketplace:
            return web.json_response({"error": "Not available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        author = body.get("author", "anonymous")
        result = await self.plugin_marketplace.submit_listing(author, body)
        return web.json_response(result)

    async def handle_marketplace_purchased(self, request: web.Request) -> web.Response:
        """GET /marketplace/purchased — plugins owned by wallet."""
        if not self.plugin_marketplace:
            return web.json_response({"plugins": []})
        wallet = request.headers.get("X-Wallet-Address", "anonymous")
        plugins = await self.plugin_marketplace.get_purchased(wallet)
        return web.json_response({"plugins": plugins})

    # ─── Sponsor Redirect ────────────────────────────────────────

    async def handle_sponsor_redirect(self, request: web.Request) -> web.Response:
        """GET /sponsor — redirect to GitHub Sponsors."""
        raise web.HTTPFound("https://github.com/sponsors/ItsDardanRexhepi")

    # ─── Glasswing & Badge Endpoints ─────────────────────────────

    async def handle_glasswing_page(self, request: web.Request) -> web.Response:
        """GET /glasswing — serve the Glasswing security hub page."""
        return self._serve_html("web/glasswing.html")

    async def handle_badge_page(self, request: web.Request) -> web.Response:
        """GET /badge/{badge_id} — serve the badge verification page."""
        return self._serve_html("web/badge.html")

    async def handle_badge_status(self, request: web.Request) -> web.Response:
        """GET /badge/{badge_id}/status — JSON badge status."""
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        badge_id = request.match_info.get("badge_id", "")
        result = await self.badge_manager.verify_badge(badge_id)
        return web.json_response(result)

    async def handle_badge_embed(self, request: web.Request) -> web.Response:
        """GET /badge/{badge_id}/embed — return embed code."""
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        badge_id = request.match_info.get("badge_id", "")
        code = await self.badge_manager.get_badge_embed_code(badge_id)
        return web.json_response({"badge_id": badge_id, "embed_code": code})

    async def handle_badge_widget_js(self, request: web.Request) -> web.Response:
        """GET /badge/widget.js — serve the embeddable badge widget."""
        filepath = Path("web/badge-widget.js")
        if filepath.exists():
            return web.Response(
                text=filepath.read_text(encoding="utf-8"),
                content_type="application/javascript",
            )
        return web.Response(text="// widget not found", status=404,
                            content_type="application/javascript")

    async def handle_badges_list(self, request: web.Request) -> web.Response:
        """GET /badges — public registry of valid Glasswing badges."""
        if not self.badge_manager:
            return web.json_response({"badges": []})
        status = request.query.get("status", "valid")
        badges = await self.badge_manager.list_badges(status=status)
        return web.json_response({"badges": badges})

    async def handle_badge_issue(self, request: web.Request) -> web.Response:
        """POST /badge/issue — issue a badge after audit payment."""
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        result = await self.badge_manager.issue_badge(
            contract_address=str(body.get("contract_address", "")),
            contract_name=str(body.get("contract_name", "")),
            audit_report=body.get("audit_report", {}),
            contact_email=str(body.get("contact_email", "")),
            project_url=str(body.get("project_url", "")),
        )
        return web.json_response(result)

    # ─── Referral Endpoints ──────────────────────────────────────

    async def handle_referral_generate(self, request: web.Request) -> web.Response:
        """POST /referral/generate — generate or return referral code."""
        if not self.referral_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        wallet = str(body.get("wallet_address", ""))
        if not wallet:
            return web.json_response({"error": "wallet_address required"}, status=400)
        code = await self.referral_manager.generate_code(wallet)
        return web.json_response({"code": code, "wallet_address": wallet})

    async def handle_referral_stats(self, request: web.Request) -> web.Response:
        """GET /referral/stats — referral stats for authenticated wallet."""
        if not self.referral_manager:
            return web.json_response({"status": "not_available"}, status=503)
        wallet = request.headers.get("X-Wallet-Address", "")
        if not wallet:
            return web.json_response({"error": "wallet required"}, status=400)
        stats = await self.referral_manager.get_referral_stats(wallet)
        return web.json_response(stats)

    async def handle_referral_apply(self, request: web.Request) -> web.Response:
        """POST /referral/apply — apply a referral code."""
        if not self.referral_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        code = str(body.get("code", ""))
        wallet = str(body.get("wallet_address", ""))
        tier = str(body.get("tier", "pro"))
        if not code or not wallet:
            return web.json_response({"error": "code and wallet_address required"}, status=400)
        result = await self.referral_manager.apply_referral(code, wallet, tier)
        return web.json_response(result)

    async def handle_referral_validate(self, request: web.Request) -> web.Response:
        """GET /referral/{code} — validate a referral code (public)."""
        if not self.referral_manager:
            return web.json_response({"status": "not_available"}, status=503)
        code = request.match_info.get("code", "")
        result = await self.referral_manager.validate_code(code)
        if not result:
            return web.json_response({"valid": False}, status=404)
        return web.json_response({"valid": True, "code": result["code"]})

    # ─── Learn & Certification ───────────────────────────────────

    async def handle_learn_page(self, request: web.Request) -> web.Response:
        """GET /learn — serve the education landing page."""
        return self._serve_html("web/learn.html")

    async def handle_cert_tracks(self, request: web.Request) -> web.Response:
        """GET /certification/tracks — list certification tracks."""
        if not self.certification_manager:
            return web.json_response({"status": "not_available"}, status=503)
        from runtime.certification.assessments import CERTIFICATION_TRACKS
        tracks = []
        for key, val in CERTIFICATION_TRACKS.items():
            tracks.append({"id": key, **val})
        return web.json_response({"tracks": tracks})

    async def handle_cert_start(self, request: web.Request) -> web.Response:
        """POST /certification/start — start a certification exam."""
        if not self.certification_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        wallet = str(body.get("wallet_address", ""))
        track = str(body.get("track", ""))
        if not wallet or not track:
            return web.json_response({"error": "wallet_address and track required"}, status=400)
        result = await self.certification_manager.start_exam(wallet, track)
        return web.json_response(result)

    async def handle_cert_submit(self, request: web.Request) -> web.Response:
        """POST /certification/submit — submit exam answers."""
        if not self.certification_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        attempt_id = str(body.get("attempt_id", ""))
        answers = body.get("answers", [])
        if not attempt_id:
            return web.json_response({"error": "attempt_id required"}, status=400)
        result = await self.certification_manager.submit_exam(attempt_id, answers)
        return web.json_response(result)

    async def handle_cert_verify(self, request: web.Request) -> web.Response:
        """GET /certification/{cert_id} — verify a certification (public)."""
        if not self.certification_manager:
            return web.json_response({"status": "not_available"}, status=503)
        cert_id = request.match_info.get("cert_id", "")
        result = await self.certification_manager.verify_certification(cert_id)
        return web.json_response(result)

    # ─── Metered API ─────────────────────────────────────────────

    async def handle_metered_usage(self, request: web.Request) -> web.Response:
        """GET /metered/usage — get metered API usage for an API key."""
        if not self.metered_billing:
            return web.json_response({"status": "not_available"}, status=503)
        api_key = request.query.get("api_key", "")
        month = request.query.get("month")
        if not api_key:
            return web.json_response({"error": "api_key required"}, status=400)
        usage = await self.metered_billing.get_monthly_usage(api_key, month)
        return web.json_response(usage)

    async def handle_metered_invoice(self, request: web.Request) -> web.Response:
        """GET /metered/invoice — calculate invoice for an API key."""
        if not self.metered_billing:
            return web.json_response({"status": "not_available"}, status=503)
        api_key = request.query.get("api_key", "")
        month = request.query.get("month", "")
        if not api_key or not month:
            return web.json_response({"error": "api_key and month required"}, status=400)
        invoice = await self.metered_billing.calculate_invoice(api_key, month)
        return web.json_response(invoice)

    async def _start_cleanup_task(self, app: web.Application) -> None:
        """Initialise persistence and start background cleanup tasks."""
        # Open the SQLite database and load auth stores from disk.
        await self.react_loop.memory.initialize()
        await self.wallet_sessions.initialize()
        await self.wallet_nonces.initialize()
        # Optional OTel push exporter (no-op unless configured + installed)
        try:
            self.otel_bridge.start()
        except Exception as exc:
            logger.warning("OTel bridge failed to start: %s", exc)
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

        # ── Initialize subscription subsystems ───────────────────────
        try:
            from runtime.subscriptions.usage_tracker import UsageTracker
            from runtime.subscriptions.feature_gate import FeatureGate as FeatureGateImpl
            from runtime.subscriptions.subscription_store import SubscriptionStore
            from runtime.subscriptions.stripe_client import StripeClient
            from runtime.subscriptions.audit_service import ProfessionalAuditService
            from runtime.subscriptions.conversion_service import ConversionService
            from runtime.marketplace.plugin_store import PluginMarketplace
            from runtime.a2a.marketplace import A2AMarketplace
            from runtime.social.manager import SocialManager

            db = self.react_loop.memory.db
            self.usage_tracker = UsageTracker(db)
            await self.usage_tracker.initialize()
            self.feature_gate_instance = FeatureGateImpl(self.config, self.usage_tracker)
            self.subscription_store = SubscriptionStore(db)
            await self.subscription_store.initialize()
            self.stripe_client = StripeClient(self.config)
            self.audit_service = ProfessionalAuditService(self.config, self.stripe_client, db)
            await self.audit_service.initialize()
            self.conversion_service = ConversionService(self.config, self.stripe_client, db)
            await self.conversion_service.initialize()
            self.plugin_marketplace = PluginMarketplace(self.config, db, self.stripe_client)
            await self.plugin_marketplace.initialize()
            self.a2a_marketplace = A2AMarketplace(self.config, db)
            await self.a2a_marketplace.initialize()
            self.social_manager = SocialManager(self.config)
            logger.info("Subscription and marketplace subsystems initialized.")
        except Exception as exc:
            logger.warning("Subscription subsystems init skipped: %s", exc)

        # ── Initialize referral, badge, certification, metered, revenue ──
        try:
            from runtime.referrals.referral_manager import ReferralManager
            from runtime.subscriptions.metered_billing import MeteredBillingManager
            from runtime.blockchain.protocol_referrals import ProtocolReferralCollector
            from runtime.badges.badge_manager import BadgeManager
            from runtime.certification.assessments import CertificationManager
            from runtime.subscriptions.revenue_reporter import RevenueReporter

            db = self.react_loop.memory.db
            self.referral_manager = ReferralManager(db, self.config)
            await self.referral_manager.initialize()
            self.metered_billing = MeteredBillingManager(db, self.config)
            await self.metered_billing.initialize()
            self.protocol_referrals = ProtocolReferralCollector(db, self.config)
            await self.protocol_referrals.initialize()
            self.badge_manager = BadgeManager(db, self.config)
            await self.badge_manager.initialize()
            self.certification_manager = CertificationManager(db, self.config)
            await self.certification_manager.initialize()
            self.revenue_reporter = RevenueReporter(db, self.config)
            await self.revenue_reporter.initialize()
            logger.info("Referral, badge, certification, metered, and revenue subsystems initialized.")
        except Exception as exc:
            logger.warning("Extended subsystems init skipped: %s", exc)

        # ── Social feed engine ─────────────────────────────────────────
        try:
            from runtime.social.feed_engine import SocialFeedEngine
            db = self.react_loop.memory.db
            self.social_feed_engine = SocialFeedEngine(db)
            # Attach to the service dispatcher so state-modifying actions
            # are automatically published to the feed.
            dispatcher = getattr(self.react_loop, "dispatcher", None)
            if dispatcher is not None:
                dispatcher.attach_feed_engine(self.social_feed_engine)
            logger.info("Social feed engine initialized.")
        except Exception as exc:
            logger.warning("Social feed engine init skipped: %s", exc)

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
            bridge = getattr(self, "otel_bridge", None)
            if bridge is not None:
                bridge.shutdown()
        except Exception as exc:
            logger.debug("OTel bridge shutdown raised: %s", exc)
        try:
            await self.react_loop.memory.close()
        except Exception as exc:
            logger.warning("Memory close failed: %s", exc)
        logger.info("Gateway shutting down cleanly.")

    def create_app(self) -> web.Application:
        app = web.Application(
            middlewares=[
                self._request_id_middleware,
                self._cors_middleware,
                self._auth_middleware,
                self._rate_limit_middleware,
                self._timeout_middleware,
                self._logging_middleware,
            ],
            client_max_size=self.ws_max_message_size,
        )
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

        # ── Web pages ─────────────────────────────────────────────────
        app.router.add_get("/", self.handle_landing)
        app.router.add_get("/chat", self.handle_chat_page)
        app.router.add_get("/pricing", self.handle_pricing_page)
        app.router.add_get("/audit", self.handle_audit_page)
        app.router.add_get("/marketplace", self.handle_marketplace_page)
        app.router.add_get("/services/conversion", self.handle_conversion_page)
        app.router.add_get("/privacy", self.handle_privacy_page)
        app.router.add_get("/terms", self.handle_terms_page)

        # ── Extensions registry ───────────────────────────────────────
        app.router.add_get("/extensions/registry", self.handle_extensions_registry)
        app.router.add_get("/extensions/registry/{component_id}", self.handle_extensions_component)

        # ── Subscription ──────────────────────────────────────────────
        app.router.add_post("/subscription/checkout", self.handle_subscription_checkout)
        app.router.add_post("/subscription/webhook", self.handle_subscription_webhook)
        app.router.add_get("/subscription/status", self.handle_subscription_status)

        # ── Audit service ─────────────────────────────────────────────
        app.router.add_post("/audit/request", self.handle_audit_request)
        app.router.add_get("/audit/{audit_id}", self.handle_audit_report)

        # ── Social media ──────────────────────────────────────────────
        app.router.add_post("/social/post", self.handle_social_post)

        # ── Social feed ──────────────────────────────────────────────
        app.router.add_get("/social", self.handle_social_feed_page)
        app.router.add_get("/social/feed", self.handle_social_feed)
        app.router.add_get("/social/feed/stream", self.handle_social_feed_stream)
        app.router.add_get("/social/trending", self.handle_social_trending)
        app.router.add_get("/social/actor/{wallet}", self.handle_social_actor)
        app.router.add_get("/social/stats", self.handle_social_stats)

        # ── A2A commerce ──────────────────────────────────────────────
        app.router.add_get("/a2a/services", self.handle_a2a_services)
        app.router.add_post("/a2a/jobs", self.handle_a2a_submit_job)
        app.router.add_get("/a2a/jobs/{job_id}", self.handle_a2a_get_job)

        # ── Plugin marketplace ────────────────────────────────────────
        app.router.add_get("/marketplace/plugins", self.handle_marketplace_list)
        app.router.add_get("/marketplace/plugins/{plugin_id}", self.handle_marketplace_plugin)
        app.router.add_post("/marketplace/plugins/{plugin_id}/purchase", self.handle_marketplace_purchase)
        app.router.add_post("/marketplace/plugins/submit", self.handle_marketplace_submit)
        app.router.add_get("/marketplace/purchased", self.handle_marketplace_purchased)

        # ── Sponsor redirect ─────────────────────────────────────────
        app.router.add_get("/sponsor", self.handle_sponsor_redirect)

        # ── Glasswing & badges ────────────────────────────────────────
        app.router.add_get("/glasswing", self.handle_glasswing_page)
        app.router.add_get("/badge/widget.js", self.handle_badge_widget_js)
        app.router.add_get("/badge/{badge_id}", self.handle_badge_page)
        app.router.add_get("/badge/{badge_id}/status", self.handle_badge_status)
        app.router.add_get("/badge/{badge_id}/embed", self.handle_badge_embed)
        app.router.add_get("/badges", self.handle_badges_list)
        app.router.add_post("/badge/issue", self.handle_badge_issue)

        # ── Referral program ─────────────────────────────────────────
        app.router.add_post("/referral/generate", self.handle_referral_generate)
        app.router.add_get("/referral/stats", self.handle_referral_stats)
        app.router.add_post("/referral/apply", self.handle_referral_apply)
        app.router.add_get("/referral/{code}", self.handle_referral_validate)

        # ── Learn & certification ─────────────────────────────────────
        app.router.add_get("/learn", self.handle_learn_page)
        app.router.add_get("/certification/tracks", self.handle_cert_tracks)
        app.router.add_post("/certification/start", self.handle_cert_start)
        app.router.add_post("/certification/submit", self.handle_cert_submit)
        app.router.add_get("/certification/{cert_id}", self.handle_cert_verify)

        # ── Metered API ───────────────────────────────────────────────
        app.router.add_get("/metered/usage", self.handle_metered_usage)
        app.router.add_get("/metered/invoice", self.handle_metered_invoice)

        # Register all 30 blockchain service REST endpoints
        service_routes = None
        try:
            from gateway.service_routes import ServiceRoutes
            service_routes = ServiceRoutes(self.config, metrics=self.metrics)
            service_routes.register_routes(app)
            # Expose the broadcaster so other subsystems (bridge,
            # service dispatchers, metrics) can push live events into
            # /api/v1/events/stream.
            self.event_broadcaster = service_routes.broadcaster
            logger.info("Service routes registered successfully.")
        except Exception as e:
            logger.warning("Service routes registration skipped: %s", e)

        # Register MTRX iOS bridge endpoints
        try:
            from gateway.bridge import BridgeRoutes
            bridge = BridgeRoutes(self.config, self)
            bridge.register_routes(app)
            # Let the batch dispatcher know about the bridge so
            # /api/v1/batch can forward /bridge/v1/* items through the
            # same in-process fast path used for /api/v1/* items.
            if service_routes is not None:
                service_routes.attach_bridge_routes(bridge)
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
        """Enforce rate limits, keyed by the strongest identity available.

        Precedence:
          1. ``X-Wallet-Session`` header → per-wallet-address bucket
             (SIWE-authenticated traffic).
          2. ``Authorization: Bearer <api_key>`` → per-API-key bucket
             (operator / integration tokens).
          3. Fall back to the client IP for anonymous traffic.
        """
        if request.method == "OPTIONS":
            return await handler(request)

        rate_key: str
        limiter: RateLimiter

        wallet_token = request.headers.get("X-Wallet-Session", "").strip()
        wallet_session = None
        if wallet_token:
            try:
                wallet_session = self.wallet_sessions.get(wallet_token)
            except Exception as exc:  # defensive — store unavailable, etc.
                logger.debug("wallet session lookup failed: %s", exc)

        if (
            wallet_session
            and float(wallet_session.get("expires_at", 0)) > time.time()
        ):
            # Per-wallet-address bucket — cap each signer individually.
            address = str(wallet_session.get("address", "")).lower() or "unknown"
            rate_key = f"wallet:{address}"
            limiter = self.rate_limiter_wallet
        else:
            auth_header = request.headers.get("Authorization", "")
            api_key = ""
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:]
            elif request.query.get("api_key"):
                api_key = request.query["api_key"]

            if (
                api_key
                and self.auth_enabled
                and hmac.compare_digest(api_key, self.api_key)
            ):
                rate_key = (
                    f"key:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
                )
                limiter = self.rate_limiter_auth
            else:
                client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                if not client_ip:
                    peername = request.transport.get_extra_info("peername")
                    client_ip = peername[0] if peername else "unknown"
                rate_key = f"ip:{client_ip}"
                limiter = self.rate_limiter_anon

        if not limiter.allow(rate_key):
            self.metrics.incr("requests.rate_limited")
            return web.json_response(
                {"error": "rate_limited", "message": "Too many requests. Please slow down."},
                status=429,
            )
        return await handler(request)

    @web.middleware
    async def _request_id_middleware(self, request: web.Request, handler):
        """Bind a request ID to the contextvar scope and response headers."""
        incoming = request.headers.get("X-Request-ID", "").strip()
        request_id = incoming or generate_request_id()
        token = set_request_id(request_id)
        try:
            response = await handler(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)

    @web.middleware
    async def _timeout_middleware(self, request: web.Request, handler):
        """Enforce a per-request wall-clock timeout."""
        timeout = self.request_timeout
        if timeout <= 0 or request.path == "/ws":
            # WebSocket upgrades are long-lived; don't time them out.
            return await handler(request)
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout)
        except asyncio.TimeoutError:
            self.metrics.incr("requests.timeout")
            logger.warning(
                "request timed out after %.1fs: %s %s",
                timeout,
                request.method,
                request.path,
            )
            return web.json_response(
                {
                    "error": "request_timeout",
                    "message": f"Request exceeded {timeout:.0f}s budget.",
                },
                status=504,
            )

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
            # Record per-endpoint latency histogram (truncate to 2 decimals)
            self.metrics.observe(
                f"http.duration.{request.method.lower()}",
                elapsed,
            )
            self.metrics.incr(f"http.status.{response.status}")
            logger.info(
                "%s %s -> %d (%.3fs)",
                request.method,
                request.path,
                response.status,
                elapsed,
                extra={
                    "http_method": request.method,
                    "http_path": request.path,
                    "http_status": response.status,
                    "duration_ms": round(elapsed * 1000, 3),
                },
            )
            return response
        except Exception as exc:
            elapsed = time.time() - start
            self.metrics.incr("http.exceptions")
            logger.error(
                "%s %s -> EXCEPTION (%.3fs): %s",
                request.method,
                request.path,
                elapsed,
                exc,
                extra={
                    "http_method": request.method,
                    "http_path": request.path,
                    "duration_ms": round(elapsed * 1000, 3),
                    "exception_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise


def main():
    # Emit JSON logs by default in production, plain text otherwise.
    json_logs = os.environ.get("OPNMATRX_LOG_FORMAT", "").strip().lower() == "json" or (
        is_production_mode()
        and os.environ.get("OPNMATRX_LOG_FORMAT", "").strip().lower() != "text"
    )
    configure_logging(
        level=os.environ.get("OPNMATRX_LOG_LEVEL", "INFO").upper(),
        json_format=json_logs,
    )

    config = load_config()
    server = GatewayServer(config)
    app = server.create_app()

    host = config.get("gateway", {}).get("host", "0.0.0.0")
    port = config.get("gateway", {}).get("port", 18790)

    logger.info(
        "0pnMatrx gateway starting",
        extra={
            "host": host,
            "port": port,
            "production_mode": is_production_mode(),
            "json_logs": json_logs,
        },
    )
    web.run_app(app, host=host, port=port, print=None, shutdown_timeout=30)


if __name__ == "__main__":
    main()
