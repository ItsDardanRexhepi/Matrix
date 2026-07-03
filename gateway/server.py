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
    # PORT (Railway/Heroku convention) takes precedence, then OPENMATRIX_PORT.
    port_val = os.environ.get("PORT") or os.environ.get("OPENMATRIX_PORT")
    if port_val:
        try:
            gw["port"] = int(port_val)
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

    # APNs push (Matrix deploy): the .p8 is MOUNTED as a file (never an env
    # value) at APNS_AUTH_KEY_P8_PATH; read its contents into the ios_push
    # channel config so the mounted secret is actually consumed. Absent path /
    # unreadable file leaves the channel unconfigured (push stays a no-op) —
    # fail-safe, never a crash.
    apns_path = os.environ.get("APNS_AUTH_KEY_P8_PATH")
    if apns_path:
        ios = (config.setdefault("notifications", {})
               .setdefault("channels", {}).setdefault("ios_push", {}))
        try:
            with open(apns_path, "r", encoding="utf-8") as fh:
                ios["auth_key_p8"] = fh.read()
        except (OSError, ValueError):
            # OSError: missing / a directory (bind-mount footgun) / no perm.
            # ValueError (incl. UnicodeDecodeError): a binary/DER .p8 or garbage
            # file. Either way push stays unconfigured — never crash config load.
            logger.warning("APNS_AUTH_KEY_P8_PATH set (%s) but not a readable "
                           "UTF-8 key — push stays unconfigured.", apns_path)
        for env_var, key in (("APNS_KEY_ID", "key_id"),
                             ("APNS_TEAM_ID", "team_id"),
                             ("APNS_BUNDLE_ID", "bundle_id")):
            if os.environ.get(env_var):
                ios[key] = os.environ[env_var]

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
    # is_file() (not exists()) — a Docker bind-mount of a MISSING source file
    # auto-creates a DIRECTORY at the path; exists() is True for it, but
    # read_text() would then raise IsADirectoryError. Treat a non-regular-file
    # path as the same clean, documented hard-exit as a missing file.
    if not path.is_file():
        logger.error("Config file not found or not a regular file: %s", CONFIG_PATH)
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
    except OSError as exc:
        # Unreadable / permission / racing directory swap — clean exit, no traceback.
        logger.error("Config file %s could not be read: %s", CONFIG_PATH, exc)
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


def attach_social_feed(react_loop, engine):
    """Attach the social feed engine to the ServiceDispatcher nested inside
    the ReAct ToolDispatcher (``react_loop.dispatcher.service_dispatcher``).

    The ToolDispatcher itself has no ``attach_feed_engine`` — the publisher
    lives on the nested ServiceDispatcher. Returns the ServiceDispatcher the
    engine was attached to, or ``None`` if unavailable (P0-1).
    """
    sd = getattr(getattr(react_loop, "dispatcher", None), "service_dispatcher", None)
    if sd is not None:
        sd.attach_feed_engine(engine)
    return sd


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
            "/security/phone/request", "/security/phone/verify",
            "/security/appattest/challenge", "/security/appattest/attest",
            "/api/v1/auth/apple", "/api/v1/auth/account",
            # IAP routes authenticate via the signed JWS chain itself (Apple's
            # webhook cannot send our API key; the app sends a session token).
            "/api/v1/iap/verify", "/api/v1/iap/asn",
            # Realtime (Phase 6): /ws serves the SAME public chat as POST /chat
            # (already public below); the SSE event stream carries feed/price
            # broadcasts and enforces its own per-IP capacity caps.
            "/ws", "/api/v1/events/stream",
            "/", "/chat", "/audit", "/marketplace",
            "/services/conversion",
            "/extensions/registry",
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
        # Morpheus security layer (the process-wide gate) + its durable-state flusher.
        self._morpheus = None
        self._security_flush_task: asyncio.Task | None = None
        # Security OTP services — phone verification (owner + consumer phone connect).
        try:
            from runtime.security import OTPService, OwnerVerification  # seam → morpheus_security or no-op
            self._otp = OTPService(self.config)
            self._owner = OwnerVerification(self.config, otp_service=self._otp)
        except Exception:
            logger.exception("Failed to initialise security OTP services")
            self._otp = None
            self._owner = None

        # App Attest verifier — seam-backed (real when morpheus_security is
        # installed, inert no-op otherwise). Reached only through runtime.security.
        try:
            from runtime.security import get_app_attest_verifier, SECURITY_BACKEND
            self._app_attest = get_app_attest_verifier(self.config)
            self._security_backend = SECURITY_BACKEND
        except Exception:
            logger.exception("Failed to initialise App Attest verifier")
            self._app_attest = None
            self._security_backend = "noop"

        # Sign in with Apple — JWKS cache for identity-token verification (P1-8).
        from gateway.apple_auth import AppleJWKSCache
        self._apple_jwks = AppleJWKSCache()

        # Phase 3: verified-IAP store (idempotency ledger + entitlements).
        from runtime.monetization.entitlement_store import EntitlementStore
        self._entitlements = EntitlementStore(self.react_loop.memory.db)

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

        # ── Platform subsystems ──────────────────────────────────────
        # Note: Stripe subscriptions moved to MTRX iOS (Apple IAP). This
        # backend exposes the platform but does not handle user billing.
        self.audit_service = None
        self.conversion_service = None
        self.plugin_marketplace = None
        self.a2a_marketplace = None
        self.social_manager = None
        self.social_feed_engine = None
        # Shared ServiceDispatcher (set at startup once the feed engine is
        # attached) — the mobile bridge reuses this instance so iOS direct
        # actions publish to the feed too (P0-1).
        self.service_dispatcher = None
        self.protocol_referrals = None
        self.badge_manager = None
        self.certification_manager = None

        # ── Notifications (unified 9-channel dispatcher) ────────────
        # Available channels: telegram, discord, slack, email, sms,
        # whatsapp, web_chat, ios_push, webhook. Configure with
        # `python setup_communications.py`. Every channel is optional;
        # the dispatcher is always instantiated so callers can rely on
        # it without guarding imports.
        try:
            from runtime.notifications import NotificationDispatcher
            self.notifier = NotificationDispatcher(config)
            enabled = self.notifier.list_enabled_channels()
            if enabled:
                logger.info("Notifications ready: %s", ", ".join(enabled))
            else:
                logger.info(
                    "Notifications: no channels configured. "
                    "Run `python setup_communications.py` to add Telegram, "
                    "Discord, Slack, SMS, Email, WhatsApp, iOS push, or webhooks."
                )
        except Exception as exc:
            logger.warning("NotificationDispatcher init failed: %s", exc)
            self.notifier = None

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

        # Inject user context metadata so protocols can access it. The identity and
        # client App Attest assertion are threaded so the Morpheus gate consulted in
        # ProtocolStack.pre_action can attribute and verify each tool call.
        context.metadata["user_context"] = {
            "session_id": session_id,
            "agent": agent,
            "wallet_connected": body.get("wallet_connected", True),
            "network": body.get("network"),
            "balance": body.get("balance"),
            "jurisdiction": body.get("jurisdiction", ""),
            "total_transactions": body.get("total_transactions"),
            "wallet_address": body.get("wallet") or body.get("wallet_address") or "",
            "apple_id": body.get("apple_id", ""),
            "app_attest": body.get("app_attest"),
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

    # ─── Social follow graph (P2-10) ──────────────────────────────────────

    def _follow_store(self):
        from runtime.social.follows import FollowStore
        return FollowStore(self.react_loop.memory.db)

    async def handle_social_follow(self, request: web.Request) -> web.Response:
        """POST /social/follow — {address}. Follower = X-Wallet-Address."""
        follower = request.headers.get("X-Wallet-Address", "").strip()
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        followee = str(body.get("address", "")).strip()
        if not follower or not followee:
            return web.json_response({"error": "address required"}, status=400)
        await self._follow_store().follow(follower, followee)
        return web.json_response({"success": True, "following": followee})

    async def handle_social_unfollow(self, request: web.Request) -> web.Response:
        follower = request.headers.get("X-Wallet-Address", "").strip()
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        followee = str(body.get("address", "")).strip()
        if not follower or not followee:
            return web.json_response({"error": "address required"}, status=400)
        await self._follow_store().unfollow(follower, followee)
        return web.json_response({"success": True, "unfollowed": followee})

    async def handle_social_followers(self, request: web.Request) -> web.Response:
        address = request.match_info.get("address", "").strip()
        followers = await self._follow_store().followers(address)
        return web.json_response({"address": address, "followers": followers,
                                  "count": len(followers)})

    async def handle_social_following(self, request: web.Request) -> web.Response:
        address = request.match_info.get("address", "").strip()
        following = await self._follow_store().following(address)
        return web.json_response({"address": address, "following": following,
                                  "count": len(following)})

    # ─── Sign in with Apple (P1-8) ────────────────────────────────────────

    async def handle_apple_auth(self, request: web.Request) -> web.Response:
        """POST /api/v1/auth/apple — verify Apple's identityToken and issue a
        session. Response is camelCase to match the client's AuthResponse.

        Fail-closed: if auth.apple.bundle_id is unconfigured -> 503 (never
        verifies against a wildcard audience)."""
        from gateway.apple_auth import (
            verify_apple_identity_token, AppleAuthError, AppleAuthNotConfigured,
        )
        from runtime.auth.siwe import create_session_token
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        identity_token = str(body.get("identityToken", "")).strip()
        if not identity_token:
            return web.json_response({"error": "identityToken required"}, status=400)

        try:
            claims = await verify_apple_identity_token(
                identity_token, config=self.config, jwks_cache=self._apple_jwks)
        except AppleAuthNotConfigured:
            return web.json_response({"error": "apple auth not configured"}, status=503)
        except AppleAuthError:
            return web.json_response({"error": "invalid Apple identity token"}, status=401)

        sub = str(claims.get("sub", "")).strip()
        if not sub:
            return web.json_response({"error": "invalid Apple identity token"}, status=401)

        # Session bound to a stable Apple user id (surrogate address "apple:<sub>").
        # A linked wallet, if any, is looked up from the wallet-link table; the
        # client's AuthResponse.walletAddress is non-optional so return "" when
        # none exists yet.
        user_key = f"apple:{sub}"
        wallet_address = ""
        try:
            existing = self.wallet_sessions.get_by_address(user_key) \
                if hasattr(self.wallet_sessions, "get_by_address") else None
            is_new_user = existing is None
        except Exception:
            is_new_user = True

        token = create_session_token()
        now = time.time()
        expires_at = now + self._wallet_session_ttl
        await self.wallet_sessions.add(
            token=token, address=user_key, issued_at=now, expires_at=expires_at)

        return web.json_response({
            "token": token,
            "userId": sub,
            "walletAddress": wallet_address,
            "expiresAt": expires_at,
            "isNewUser": is_new_user,
        })

    async def handle_account_delete(self, request: web.Request) -> web.Response:
        """DELETE /api/v1/auth/account — delete the caller's server-side data and
        (credential-gated) revoke the Apple token.

        Deleted here: the caller's wallet session (X-Wallet-Session) and every push
        token registered under that session. Apple token revocation runs only when
        auth.apple.{team_id,key_id,private_key_p8} are configured; otherwise local
        deletion still succeeds and revocation is skipped with a WARNING."""
        from gateway.apple_auth import apple_revocation_configured
        token = request.headers.get("X-Wallet-Session", "").strip()
        session = self.wallet_sessions.get(token) if token else None

        # Push tokens registered under this session.
        try:
            from runtime.notifications.token_store import PushTokenStore
            store = PushTokenStore(self.react_loop.memory.db)
            if session is not None:
                for dev in await store.tokens_for(session_id=token):
                    await store.remove(dev)
        except Exception:
            logger.debug("account delete: push-token cleanup skipped")

        # The wallet session itself.
        if token:
            try:
                await self.wallet_sessions.remove(token)
            except Exception:
                logger.debug("account delete: session removal skipped")

        if not apple_revocation_configured(self.config):
            logger.warning(
                "Account deleted locally; Apple token revocation SKIPPED "
                "(auth.apple.team_id/key_id/private_key_p8 not configured).")

        import datetime
        return web.json_response({
            "success": True,
            "deletedAt": datetime.datetime.utcnow().isoformat() + "Z",
        })

    # ─── IAP verification (Phase 3 monetization server) ──────────────────

    def _iap_user_key(self, request: web.Request) -> str:
        """Optional user binding: a valid wallet-session token (X-Wallet-Session,
        or the Authorization Bearer token the iOS client stores from
        /api/v1/auth/apple) maps the verified purchase to that session's user
        key; absent/invalid -> '' (recorded unbound — verification never
        depends on a session)."""
        candidates = [request.headers.get("X-Wallet-Session", "").strip()]
        auth = request.headers.get("Authorization", "").strip()
        if auth.startswith("Bearer "):
            candidates.append(auth[len("Bearer "):].strip())
        for token in candidates:
            session = self.wallet_sessions.get(token) if token else None
            if session:
                return str(session.get("address", ""))
        return ""

    async def handle_iap_verify(self, request: web.Request) -> web.Response:
        """POST /api/v1/iap/verify — verify a StoreKit ``signedTransaction``
        JWS (full x5c chain to the pinned Apple root + bundle-id check) and
        record it. Subscriptions upsert an entitlement row; the redos
        Consumable is recorded in the transaction ledger (never a tier).

        Idempotent on transactionId: replaying the same signed transaction
        returns 200 with replay=true and records nothing new. Fail-closed:
        unconfigured -> 503; any verification failure -> 401 (generic)."""
        from gateway.iap import (
            IAPError, IAPNotConfigured, check_bundle, check_environment,
            classify_product, transaction_fields, verify_signed_payload,
        )
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        jws = str(body.get("signedTransaction", "")).strip()
        if not jws:
            return web.json_response(
                {"error": "signedTransaction required"}, status=400)

        try:
            payload = verify_signed_payload(jws, config=self.config)
            check_bundle(payload.get("bundleId"), self.config)
            check_environment(payload.get("environment"), self.config)
        except IAPNotConfigured:
            return web.json_response({"error": "iap not configured"}, status=503)
        except IAPError:
            return web.json_response(
                {"error": "invalid signed transaction"}, status=401)

        tx = transaction_fields(payload)
        if not tx["transaction_id"]:
            return web.json_response(
                {"error": "invalid signed transaction"}, status=401)
        product_type, tier = classify_product(tx["product_id"], self.config)
        user_key = self._iap_user_key(request)

        try:
            fresh = await self._entitlements.record_transaction(
                transaction_id=tx["transaction_id"],
                original_transaction_id=tx["original_transaction_id"],
                product_id=tx["product_id"],
                product_type=product_type,
                user_key=user_key,
                quantity=tx["quantity"],
                purchase_date=tx["purchase_date"],
                environment=tx["environment"],
            )
            if product_type == "subscription" and tier:
                await self._entitlements.upsert_entitlement(
                    original_transaction_id=tx["original_transaction_id"],
                    product_id=tx["product_id"],
                    tier=tier,
                    user_key=user_key,
                    status="active",
                    purchase_date=tx["purchase_date"],
                    expires_date=tx["expires_date"],
                    environment=tx["environment"],
                )
        except Exception:
            logger.exception("iap verify: store write failed")
            return web.json_response({"error": "storage failure"}, status=503)

        return web.json_response({
            "status": "recorded",
            "replay": not fresh,
            "transactionId": tx["transaction_id"],
            "originalTransactionId": tx["original_transaction_id"],
            "productId": tx["product_id"],
            "productType": product_type,
            "tier": tier or "",
        })

    async def handle_iap_asn(self, request: web.Request) -> web.Response:
        """POST /api/v1/iap/asn — App Store Server Notifications V2 webhook.

        The whole request's authority is the ``signedPayload`` JWS: same
        pinned-root chain validation as /iap/verify, then the NESTED
        ``signedTransactionInfo`` is verified independently before any store
        write (a valid envelope cannot smuggle an unverified transaction).
        DID_RENEW extends, EXPIRED expires, REFUND flips to refunded (and
        marks consumable ledger rows), REVOKE revokes. Unverifiable -> 401
        so a spoofer learns nothing and real Apple retries surface."""
        from gateway.iap import (
            IAPError, IAPNotConfigured, check_bundle, classify_product,
            transaction_fields, verify_signed_payload,
        )
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)

        signed_payload = str(body.get("signedPayload", "")).strip()
        if not signed_payload:
            return web.json_response(
                {"error": "signedPayload required"}, status=400)

        try:
            envelope = verify_signed_payload(signed_payload, config=self.config)
            data = envelope.get("data") or {}
            check_bundle(data.get("bundleId"), self.config)
            tx_jws = str(data.get("signedTransactionInfo", "")).strip()
            if not tx_jws:
                raise IAPError("notification lacks signedTransactionInfo")
            tx_payload = verify_signed_payload(tx_jws, config=self.config)
            check_bundle(tx_payload.get("bundleId"), self.config)
        except IAPNotConfigured:
            return web.json_response({"error": "iap not configured"}, status=503)
        except IAPError:
            return web.json_response({"error": "invalid notification"}, status=401)

        notification_type = str(envelope.get("notificationType", ""))
        tx = transaction_fields(tx_payload)
        if not tx["transaction_id"]:
            return web.json_response({"error": "invalid notification"}, status=401)
        product_type, tier = classify_product(tx["product_id"], self.config)
        original_id = tx["original_transaction_id"]

        try:
            await self._entitlements.record_transaction(
                transaction_id=tx["transaction_id"],
                original_transaction_id=original_id,
                product_id=tx["product_id"],
                product_type=product_type,
                quantity=tx["quantity"],
                purchase_date=tx["purchase_date"],
                environment=tx["environment"],
            )
            if notification_type in ("SUBSCRIBED", "DID_RENEW") and \
                    product_type == "subscription" and tier:
                await self._entitlements.upsert_entitlement(
                    original_transaction_id=original_id,
                    product_id=tx["product_id"],
                    tier=tier,
                    status="active",
                    purchase_date=tx["purchase_date"],
                    expires_date=tx["expires_date"],
                    environment=tx["environment"],
                )
            elif notification_type == "EXPIRED":
                await self._entitlements.set_status(original_id, "expired")
            elif notification_type == "REFUND":
                await self._entitlements.set_status(original_id, "refunded")
                await self._entitlements.mark_transaction(
                    tx["transaction_id"], "refunded")
            elif notification_type == "REVOKE":
                await self._entitlements.set_status(original_id, "revoked")
                await self._entitlements.mark_transaction(
                    tx["transaction_id"], "revoked")
            elif notification_type == "REFUND_REVERSED":
                # Deliberately NOT auto-reactivated: terminal states are
                # sticky (a replayed reversal after a second refund must not
                # re-entitle). Rare enough to be a human decision — the
                # operator flips it with set_status(allow_terminal_override).
                logger.warning(
                    "iap asn: REFUND_REVERSED for lineage %s — terminal "
                    "state kept; manual review required to reactivate.",
                    original_id)
            else:
                logger.info("iap asn: %s acknowledged without a state flip",
                            notification_type or "<missing type>")
        except Exception:
            logger.exception("iap asn: store write failed")
            return web.json_response({"error": "storage failure"}, status=503)

        return web.json_response({"status": "ok",
                                  "notificationType": notification_type})

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
            # Optional client context (Phase 6 realtime client): the iOS app
            # sends the same temporal/language-mirroring context its REST path
            # sends, so a streamed reply is never lower-fidelity than /chat.
            client_context = str(payload.get("context", ""))[:8000].strip()
            if client_context:
                full_prompt = f"{full_prompt}\n\n{client_context}"

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

    async def _security_flush_loop(self, interval: float = 30.0) -> None:
        """Periodically persist the security layer's durable state (bans -> DB +
        on-chain, breach alerts -> SMS + on-chain)."""
        while True:
            try:
                await asyncio.sleep(interval)
                if self._morpheus is not None:
                    await self._morpheus.persist_security_state()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Security flush loop iteration failed")

    async def _start_cleanup_task(self, app: web.Application) -> None:
        """Initialise persistence and start background cleanup tasks."""
        # Open the SQLite database and load auth stores from disk.
        await self.react_loop.memory.initialize()
        await self.wallet_sessions.initialize()
        await self.wallet_nonces.initialize()
        # Security layer — create the process-wide Morpheus gate WITH the DB handle
        # and load durable bans before serving; then flush its durable state
        # (bans -> DB/on-chain, breach alerts -> SMS/on-chain) on a short timer.
        try:
            from runtime.security import get_morpheus_security  # seam → morpheus_security or no-op
            self._morpheus = get_morpheus_security(
                {**self.config, "db": self.react_loop.memory.db}
            )
            await self._morpheus.initialize()
            self._security_flush_task = asyncio.create_task(self._security_flush_loop())
            logger.info("Morpheus security layer initialised (mode=%s)", self._morpheus.mode.value)
        except Exception:
            logger.exception("Failed to initialise the Morpheus security layer")
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

        # ── Initialize platform subsystems ───────────────────────────
        # Stripe subscriptions live in MTRX iOS (Apple IAP). This backend
        # only initializes the plugin marketplace, A2A, social, badges,
        # certification, and professional services.
        try:
            from runtime.marketplace.plugin_store import PluginMarketplace
            from runtime.a2a.marketplace import A2AMarketplace
            from runtime.social.manager import SocialManager

            db = self.react_loop.memory.db
            self.plugin_marketplace = PluginMarketplace(self.config, db)
            await self.plugin_marketplace.initialize()
            self.a2a_marketplace = A2AMarketplace(self.config, db)
            await self.a2a_marketplace.initialize()
            self.social_manager = SocialManager(self.config)
            logger.info("Marketplace and social subsystems initialized.")
        except Exception as exc:
            logger.warning("Marketplace subsystems init skipped: %s", exc)

        # ── Initialize badges, certification, protocol referrals ─────
        try:
            from runtime.blockchain.protocol_referrals import ProtocolReferralCollector
            from runtime.badges.badge_manager import BadgeManager
            from runtime.certification.assessments import CertificationManager

            db = self.react_loop.memory.db
            self.protocol_referrals = ProtocolReferralCollector(db, self.config)
            await self.protocol_referrals.initialize()
            self.badge_manager = BadgeManager(db, self.config)
            await self.badge_manager.initialize()
            self.certification_manager = CertificationManager(db, self.config)
            await self.certification_manager.initialize()
            logger.info("Badge, certification, and protocol referral subsystems initialized.")
        except Exception as exc:
            logger.warning("Extended subsystems init skipped: %s", exc)

        # ── Social feed engine ─────────────────────────────────────────
        try:
            from runtime.social.feed_engine import SocialFeedEngine
            db = self.react_loop.memory.db
            self.social_feed_engine = SocialFeedEngine(db)
            # Attach to the ServiceDispatcher nested inside the ReAct
            # ToolDispatcher so state-modifying actions are automatically
            # published to the feed.
            service_dispatcher = attach_social_feed(self.react_loop, self.social_feed_engine)
            if service_dispatcher is not None:
                # Shared instance — the mobile bridge reuses this so iOS direct
                # actions publish to the feed too (see gateway/bridge.py
                # execute_action).
                self.service_dispatcher = service_dispatcher
            else:
                logger.warning("Social feed: no ServiceDispatcher available to attach to.")
            logger.info("Social feed engine initialized.")
        except Exception as exc:
            logger.warning("Social feed engine init skipped: %s", exc)

        # ── Push token store (P1-6) — give the notifier live device tokens ──
        try:
            from runtime.notifications.token_store import PushTokenStore
            if getattr(self, "notifier", None) is not None:
                self.notifier.set_token_store(PushTokenStore(self.react_loop.memory.db))
                logger.info("Push token store attached to notifier.")
        except Exception as exc:
            logger.warning("Push token store init skipped: %s", exc)

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

    # ── Security: phone OTP + owner verification ──────────────────────

    async def handle_otp_request(self, request: web.Request) -> web.Response:
        """POST /security/phone/request — {phone} -> {sent}. Consumer phone-connect OTP."""
        if self._otp is None:
            return web.json_response({"error": "OTP unavailable"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        phone = str(body.get("phone", "")).strip()
        if not phone:
            return web.json_response({"error": "phone is required"}, status=400)
        result = await self._otp.request(phone, purpose="phone_connect")
        return web.json_response(result)  # body carries sent/reason; 200 always

    async def handle_otp_verify(self, request: web.Request) -> web.Response:
        """POST /security/phone/verify — {phone, code} -> {verified}."""
        if self._otp is None:
            return web.json_response({"error": "OTP unavailable"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        phone = str(body.get("phone", "")).strip()
        code = str(body.get("code", "")).strip()
        if not (phone and code):
            return web.json_response({"error": "phone and code are required"}, status=400)
        result = await self._otp.verify(phone, code, purpose="phone_connect")
        return web.json_response(result)  # body carries verified/reason; 200 always

    async def handle_owner_otp_request(self, request: web.Request) -> web.Response:
        """POST /security/owner/request — {apple_id, wallet} -> {sent}. Owner OTP,
        sent only if the bound owner identity matches (never leaks to a non-owner)."""
        if self._owner is None:
            return web.json_response({"error": "owner verification unavailable"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        apple_id = str(body.get("apple_id", "")).strip()
        wallet = str(body.get("wallet", "")).strip()
        result = await self._owner.start_owner_otp(apple_id, wallet)
        return web.json_response(result)  # body carries sent/reason; never leaks owner state

    # ── Security: App Attest (device attestation) ─────────────────────
    #
    # Server half of the iOS App Attest client (P1-4). The verifier is reached
    # only through the seam (runtime.security), so this code has no direct
    # dependency on the private package. Under the noop backend the challenge
    # route reports 503 (unavailable) and attest returns verified:false with a
    # generic reason — never a 4xx that would break the client's decode path.

    async def handle_appattest_challenge(self, request: web.Request) -> web.Response:
        """GET /security/appattest/challenge?identity=… -> {"challenge": "<hex>"}."""
        if self._app_attest is None or self._security_backend == "noop":
            return web.json_response(
                {"error": "security backend not installed"}, status=503)
        identity = str(request.query.get("identity", "")).strip()
        try:
            challenge = await self._app_attest.new_challenge(identity)
        except Exception:
            # Real backend refused (e.g. store unavailable) — honest 503.
            logger.exception("App Attest challenge failed")
            return web.json_response(
                {"error": "challenge unavailable"}, status=503)
        return web.json_response({"challenge": challenge})

    async def handle_appattest_attest(self, request: web.Request) -> web.Response:
        """POST /security/appattest/attest — {key_id, attestation_obj_b64, challenge}
        -> {"verified": bool, "reason": str|null}. 200 on a clean rejection so the
        client's decode path works; 400 only on a malformed body."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        key_id = str(body.get("key_id", "")).strip()
        attestation_obj_b64 = str(body.get("attestation_obj_b64", "")).strip()
        challenge = str(body.get("challenge", "")).strip()
        if not (key_id and attestation_obj_b64 and challenge):
            return web.json_response(
                {"error": "key_id, attestation_obj_b64, challenge are required"},
                status=400)
        if self._app_attest is None or self._security_backend == "noop":
            return web.json_response(
                {"verified": False, "reason": "security backend not installed"})
        # Identity that the challenge was bound to — the authenticated wallet
        # header (mirrors the challenge request's identity), else a body field.
        identity = (request.headers.get("X-Wallet-Address")
                    or str(body.get("identity", ""))).strip()
        try:
            result = await self._app_attest.verify_attestation(
                identity=identity,
                key_id=key_id,
                attestation_obj_b64=attestation_obj_b64,
                challenge=challenge,
            )
        except Exception:
            logger.exception("App Attest attestation verification error")
            return web.json_response(
                {"verified": False, "reason": "verification_error"})
        return web.json_response({
            "verified": bool(result.get("verified", False)),
            "reason": result.get("reason") or None,
        })

    async def _on_cleanup(self, app: web.Application) -> None:
        """Run on aiohttp shutdown to cancel background tasks and log shutdown."""
        # Final flush of durable security state before shutting down.
        try:
            if self._morpheus is not None:
                await self._morpheus.persist_security_state()
        except Exception:
            logger.debug("Final security persist failed during shutdown")
        for attr in ("_cleanup_task", "_auth_cleanup_task", "_backup_task", "_security_flush_task"):
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
                self._security_context_middleware,
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
        app.router.add_post("/api/v1/auth/apple", self.handle_apple_auth)
        app.router.add_delete("/api/v1/auth/account", self.handle_account_delete)
        app.router.add_post("/api/v1/iap/verify", self.handle_iap_verify)
        app.router.add_post("/api/v1/iap/asn", self.handle_iap_asn)
        app.router.add_post("/security/phone/request", self.handle_otp_request)
        app.router.add_post("/security/phone/verify", self.handle_otp_verify)
        app.router.add_post("/security/owner/request", self.handle_owner_otp_request)
        app.router.add_get("/security/appattest/challenge", self.handle_appattest_challenge)
        app.router.add_post("/security/appattest/attest", self.handle_appattest_attest)
        app.router.add_get("/metrics", self.handle_metrics)
        app.router.add_get("/metrics/prom", self.handle_metrics_prometheus)

        # ── Web pages ─────────────────────────────────────────────────
        app.router.add_get("/", self.handle_landing)
        app.router.add_get("/chat", self.handle_chat_page)
        app.router.add_get("/audit", self.handle_audit_page)
        app.router.add_get("/marketplace", self.handle_marketplace_page)
        app.router.add_get("/services/conversion", self.handle_conversion_page)
        app.router.add_get("/privacy", self.handle_privacy_page)
        app.router.add_get("/terms", self.handle_terms_page)

        # ── Extensions registry ───────────────────────────────────────
        app.router.add_get("/extensions/registry", self.handle_extensions_registry)
        app.router.add_get("/extensions/registry/{component_id}", self.handle_extensions_component)

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
        # Follow graph (P2-10)
        app.router.add_post("/social/follow", self.handle_social_follow)
        app.router.add_post("/social/unfollow", self.handle_social_unfollow)
        app.router.add_get("/social/{address}/followers", self.handle_social_followers)
        app.router.add_get("/social/{address}/following", self.handle_social_following)

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

        # ── Learn & certification ─────────────────────────────────────
        app.router.add_get("/learn", self.handle_learn_page)
        app.router.add_get("/certification/tracks", self.handle_cert_tracks)
        app.router.add_post("/certification/start", self.handle_cert_start)
        app.router.add_post("/certification/submit", self.handle_cert_submit)
        app.router.add_get("/certification/{cert_id}", self.handle_cert_verify)

        # Register all blockchain service REST endpoints (44 services, 221 capabilities)
        service_routes = None
        try:
            from gateway.service_routes import ServiceRoutes
            service_routes = ServiceRoutes(self.config, metrics=self.metrics)
            service_routes.register_routes(app)
            # Expose the broadcaster so other subsystems (bridge,
            # service dispatchers, metrics) can push live events into
            # /api/v1/events/stream.
            self.event_broadcaster = service_routes.broadcaster
            # Connect the WebChatChannel so /api/v1/events/stream
            # receives notifications broadcast by the NotificationDispatcher.
            try:
                from runtime.notifications.web_chat import WebChatChannel
                WebChatChannel.set_broadcaster(self.event_broadcaster)
            except Exception as _exc:
                logger.debug("Web chat broadcaster not wired: %s", _exc)
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
    async def _security_context_middleware(self, request: web.Request, handler):
        """Bind the per-request security context (identity + client App Attest
        assertion) for privileged ``/api/v1/*`` actions, so the Morpheus gate at the
        service funnel can attribute and verify the request. Pass-through otherwise.

        This middleware makes NO security decision — it only carries context. It
        reads the JSON body once (aiohttp caches it for the handler). Identity comes
        from the ``X-Wallet-Address`` header or the body; the App Attest assertion
        rides in the request body (``app_attest``) per the client contract.
        """
        if request.method == "POST" and request.path.startswith("/api/v1/"):
            identity = request.headers.get("X-Wallet-Address", "") or ""
            apple_id = request.headers.get("X-Apple-Id", "") or ""
            app_attest = None
            try:
                body = await request.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                params = body.get("params") if isinstance(body.get("params"), dict) else body
                if not identity:
                    identity = (
                        body.get("wallet") or body.get("from") or body.get("sender")
                        or body.get("account")
                        or (params.get("from") if isinstance(params, dict) else "")
                        or ""
                    )
                apple_id = apple_id or body.get("apple_id", "") or ""
                app_attest = body.get("app_attest")
                if app_attest is None and isinstance(params, dict):
                    app_attest = params.get("app_attest")
            from gateway.security_gate import bind_request_security
            bind_request_security(
                identity=identity, app_attest=app_attest, apple_id=apple_id,
                session_id=request.headers.get("X-Session-Id", ""),
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
