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

from gateway.error_contract import client_error, sse_error_frame

from runtime.react_loop import (  # noqa: F401 — CLIENT_CONTEXT_FENCE re-exported
    CLIENT_CONTEXT_FENCE, CLIENT_CONTEXT_MAX_CHARS, ReActLoop, ReActContext, Message,
)
from runtime.time.temporal_context import TemporalContext
from runtime.auth.session_store import (
    WalletSessionStore,
    NonceStore,
    run_cleanup_loop,
    AppleUserStore,
)
from gateway.session_routes import session_may_reach
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

#: The four entrances to the one chat flow. They share ONE auth posture (all
#: public — see ``_public_paths``) and ONE per-turn context
#: (``GatewayServer._chat_user_context``). Written once so an entrance cannot
#: be left behind again: /chat/stream was, and the gateway's own public web
#: chat page (GET /chat → web/index.html) calls it, so that page answered 401
#: on every gateway with a key configured.
CHAT_ENTRANCES: tuple[str, ...] = ("/chat", "/chat/stream", "/ws", "/bridge/v1/chat")

#: The bounds of one chat turn's input, the same on every entrance (see
#: GatewayServer._chat_turn_input). The message cap is characters after strip.
CHAT_MESSAGE_MAX_CHARS = 100_000
CHAT_AGENTS: tuple[str, ...] = ("neo", "trinity", "morpheus")

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


def _body_key(body: dict, *keys: str) -> str:
    """Return the first present key's value as a stripped string.

    The MTRX iOS client encodes EVERY request body with
    ``keyEncodingStrategy = .convertToSnakeCase``, so a camelCase field like
    ``signedTransaction`` reaches the server as ``signed_transaction``. The
    SDK and Apple's own webhook payloads, by contrast, are camelCase. Routes
    that take a client-supplied key therefore accept BOTH spellings — pass the
    canonical camelCase first, then the snake_case fallback."""
    for k in keys:
        v = body.get(k)
        if v:
            return str(v).strip()
    return ""


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
        # The working set of conversation histories: completed turns only,
        # hydrated from the store on first touch, bounded in the number of
        # conversations (see _conversation_history).
        self.conversations: dict[str, list[Message]] = {}
        self._conversation_cap = max(1, int(config.get("conversation_cache", 1024)))
        self.request_count = 0

        # Auth: API key from config or environment
        gw = config.get("gateway", {})
        self.api_key = gw.get("api_key") or os.environ.get("OPENMATRIX_API_KEY", "")
        self.auth_enabled = bool(self.api_key)
        # Endpoints that don't require auth
        self._public_paths = {
            # RUN-7: /ready must be public for the same reason /health is — a
            # kubelet probe sends no Authorization header, so a /ready behind
            # auth would 401 every readiness check and NO POD WOULD EVER BECOME
            # READY once a key is configured. That is precisely why its body
            # carries no detail (see handle_ready): the endpoint has to be
            # reachable anonymously, so it must disclose nothing.
            "/ready",
            "/health", "/auth/nonce", "/auth/verify",
            "/security/phone/request", "/security/phone/verify",
            "/security/appattest/challenge", "/security/appattest/attest",
            "/api/v1/auth/apple", "/api/v1/auth/account",
            # IAP routes authenticate via the signed JWS chain itself (Apple's
            # webhook cannot send our API key; the app sends a session token).
            "/api/v1/iap/verify", "/api/v1/iap/asn",
            # The chat: POST /chat, POST /chat/stream, GET /ws, POST
            # /bridge/v1/chat — one flow, one posture (CHAT_ENTRANCES). Clients
            # are anonymous (the iOS app and the web chat page carry no
            # operator key; rate limiting caps abuse). Public admits the turn;
            # it grants no identity — that comes only from a presented session
            # (_chat_user_context), and naming Neo or Morpheus still takes the
            # operator key. GET /chat is also the web chat page.
            *CHAT_ENTRANCES,
            # The SSE event stream carries feed/price broadcasts and enforces
            # its own per-IP capacity caps.
            "/api/v1/events/stream",
            "/", "/audit", "/marketplace",
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
        self.apple_users = AppleUserStore(self.react_loop.memory.db)
        self._wallet_session_ttl = gw.get("wallet_session_ttl_seconds", 86400)
        self._auth_cleanup_task: asyncio.Task | None = None
        # Morpheus security layer (the process-wide gate) + its durable-state flusher.
        self._morpheus = None
        self._security_flush_task: asyncio.Task | None = None
        # Security OTP services — phone verification (owner + consumer phone connect).
        #
        # H2's principle applied to THIS branch: a security service that fails to
        # construct is a normal local state and an unacceptable production one.
        # Morpheus's own production guards raise here (OPNMATRX_OTP_PEPPER unset,
        # for one); swallowing them booted a production gateway with phone and
        # owner verification silently off — /security/phone/* answered 503 and
        # nothing refused. In production: refuse, naming the cause. Elsewhere:
        # run without the surface, honestly unavailable.
        try:
            from runtime.security import OTPService, OwnerVerification  # seam → morpheus_security or no-op
            self._otp = OTPService(self.config)
            self._owner = OwnerVerification(self.config, otp_service=self._otp)
        except Exception as exc:
            if is_production_mode():
                raise RuntimeError(
                    "OPNMATRX_ENV=production but the security OTP services failed to "
                    f"initialise: {exc}. Refusing to start rather than running with "
                    "phone and owner verification silently unavailable. Fix the named "
                    "cause, or unset OPNMATRX_ENV for a non-production run."
                ) from exc
            logger.exception("Failed to initialise security OTP services")
            self._otp = None
            self._owner = None

        # App Attest verifier — seam-backed (real when morpheus_security is
        # installed, inert no-op otherwise). Reached only through runtime.security.
        # If its construction raises (Morpheus's own production guards do, e.g.
        # OPNMATRX_STATE_BACKEND=memory under production), the backend is
        # relabelled noop and H2 below refuses — carrying THIS cause, not the
        # generic "not installed" one, so the loudest message names the real reason.
        self._security_backend_cause: str | None = None
        try:
            from runtime.security import get_app_attest_verifier, SECURITY_BACKEND
            self._app_attest = get_app_attest_verifier(self.config)
            self._security_backend = SECURITY_BACKEND
        except Exception as exc:
            logger.exception("Failed to initialise App Attest verifier")
            self._app_attest = None
            self._security_backend = "noop"
            self._security_backend_cause = f"the App Attest verifier failed to initialise: {exc}"

        # H2/RUN-11: production must not BOOT with no enforcement.
        #
        # /ready (RUN-7) takes such an instance out of rotation, but that is a
        # second line of defence — it depends on an orchestrator actually
        # probing it, and a process that is running is a process something can
        # reach. If the deployment is declared production and the security core
        # is not live, the honest outcome is refusing to start: loud, at the
        # earliest possible moment, and impossible to route around.
        if is_production_mode() and self._security_backend == "noop":
            cause = self._security_backend_cause or (
                "morpheus_security is not installed or failed to load"
            )
            raise RuntimeError(
                "OPNMATRX_ENV=production but the security backend is 'noop' — "
                f"{cause}, so nothing is enforcing. Refusing to start. Install the "
                "private security package and fix the named cause, or unset "
                "OPNMATRX_ENV for a non-production run."
            )

        # NEW-26: production must not BOOT with the credential wall down.
        #
        # `auth_enabled = bool(self.api_key)`, and `_auth_middleware` opens with
        # `if not self.auth_enabled: return await handler(request)` — it waves
        # EVERY protected route through when no key is configured. The shipped
        # openmatrix.config.json carries `"api_key": ""`, so an operator who
        # copies the example and starts the gateway without OPENMATRIX_API_KEY
        # serves the entire surface anonymously, having chosen nothing.
        #
        # This is H2's disease one layer up: a fail-open where nothing refuses
        # to serve. The fix is the same shape and uses the same
        # is_production_mode() convention as RUN-7 and H2 rather than inventing
        # a new one. Anonymous in dev is useful; anonymous in production that
        # nobody selected is the bug.
        #
        # Note the deliberate non-fix: shipping a key in the example config
        # would be its own vulnerability — a public credential — and would trade
        # one hole for another. The example stays empty; production refuses.
        if is_production_mode() and not self.auth_enabled:
            raise RuntimeError(
                "OPNMATRX_ENV=production but no gateway API key is configured, so "
                "authentication is DISABLED and every protected route would serve "
                "anonymously. Refusing to start. Set OPENMATRIX_API_KEY (or "
                "gateway.api_key in the config), or unset OPNMATRX_ENV for a "
                "non-production run."
            )

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

        message, agent, invalid = self._chat_turn_input(body)
        if invalid:
            return web.json_response({"error": invalid}, status=400)
        forbidden = self._agent_forbidden_for_caller(request, agent)
        if forbidden:
            return web.json_response({"error": "forbidden", "message": forbidden}, status=403)

        session_id, session_error = self._resolve_session_id(request, body.get("session_id"))
        if session_error:
            return web.json_response({"error": "session_required", "message": session_error}, status=400)
        denied = self._conversation_denied(request, session_id)
        if denied:
            return web.json_response({"error": "forbidden", "message": denied}, status=403)

        # Trinity first-boot message — once per session
        first_boot = None
        if agent == "trinity" and not self.react_loop.memory.is_first_boot_sent(session_id):
            await self.react_loop.memory.mark_first_boot_sent(session_id)
            first_boot = "Hi, my name is Trinity\n\nWelcome to the world of 0pnMatrx, I'll be by your side the entire time if you need me"

        system_prompt = self.react_loop.get_agent_prompt(agent)
        time_context = self.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        context = ReActContext(
            agent_name=agent,
            conversation=self._turn_conversation(session_id, message),
            system_prompt=full_prompt,
        )

        logger.info(f"[{agent}] session={session_id} message={message[:100]}")

        # What the gate, the dispatcher and the protocols decide with — one
        # builder for all four chat entrances (see _chat_user_context).
        context.metadata["user_context"] = self._chat_user_context(
            request, session_id=session_id, agent=agent, body=body)
        context.metadata["client_context"] = self._client_turn_context(body)

        try:
            with self.metrics.timer("chat.latency"):
                result = await self.react_loop.run(context)
        except RuntimeError as e:
            # RUN-5: `"error": str(e)` shipped the whole provider failure chain
            # to the caller — host, port, model names, retry structure. In the
            # sandbox that was localhost:11434; with Anthropic or OpenAI
            # configured the same field carries endpoint URLs, org ids, key
            # prefixes and quota detail. The graceful `response` string was
            # always fine; the field beside it was the leak.
            self.metrics.incr("chat.errors.model")
            status, err = client_error(
                e, request.get("request_id"), what=f"Chat[{agent}]"
            )
            return web.json_response({
                "response": "I'm having trouble connecting to my language model right now. Please try again shortly.",
                **err,
                "agent": agent,
                "session_id": session_id,
            }, status=status)

        response_text = result.response
        if first_boot:
            response_text = f"{first_boot}\n\n{response_text}"

        await self._record_turn(session_id, message, result.response)

        return web.json_response({
            "response": response_text,
            "tool_calls": result.tool_calls,
            "session_id": session_id,
            "agent": agent,
            "provider": result.provider,
        })

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /health — LIVENESS only. 200 whenever the process can serve.

        Deliberately unconditional: liveness answers "should I restart this
        process?", and restarting will not make an unreachable model provider
        reachable. Whether this instance should receive TRAFFIC is a different
        question, answered by ``/ready``.

        RUN-7: before that split existed, this route was the only health
        surface and every Kubernetes probe — liveness, readiness AND startup —
        pointed at it. Because it returns a literal ``"status": "ok"`` no matter
        what ``model_health`` says, readiness could never fail, so traffic was
        routed to instances with zero working providers. The reported model
        health was right there in the body and nothing consulted it.
        """
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

    async def handle_ready(self, request: web.Request) -> web.Response:
        """GET /ready — READINESS. 503 when this instance must not take traffic.

        RUN-7. The audit described ``/ready`` as returning 200 when it should
        not; in fact **no readiness endpoint existed at all** — the symptom was
        real and worse than the diagnosis, because every probe shared the
        always-ok liveness route. This is the missing half.

        Two conditions fail closed:

        * **No model provider reachable.** Every chat path terminates at the
          router; an instance whose providers are all down cannot serve its
          primary function and should be taken out of rotation, not restarted.
        * **``SECURITY_BACKEND == "noop"`` in production.** The no-op backend
          means the private ``morpheus_security`` package failed to load and
          the platform is running with security in OBSERVE — no enforcement.
          That is a legitimate local/dev state and a NON-STARTER in production,
          so it is only fatal when ``OPNMATRX_ENV=production``.

        THE BODY DELIBERATELY CARRIES NO DETAIL. The first version of this
        endpoint returned each check with its values — `"backend": "noop"`,
        the full model-provider inventory, whether the instance considers
        itself production. A review of that first version
        caught it: a readiness probe that announces `backend: "noop"` is telling
        any caller that NOTHING IS ENFORCING, which is a targeting signal, not a
        health signal. Combined with NEW-26 (auth disabled whenever no key is
        set) that caller need not be authenticated at all.

        So `/ready` answers the question it exists to answer — ready or not —
        and nothing else. The reason a probe failed is logged server-side
        against the correlation id, exactly as RUN-5 relocates error detail:
        the information is not destroyed, it moves to where only the operator
        can reach it.
        """
        from runtime.config.validation import is_production_mode
        from runtime.logging.json_formatter import get_request_id

        failed: list[str] = []

        model_health = await self.react_loop.router.health_check()
        providers_up = [name for name, ok in model_health.items() if ok]
        if not providers_up:
            failed.append("model_providers")

        backend = getattr(self, "_security_backend", None)
        if backend is None:
            try:
                from runtime.security import SECURITY_BACKEND

                backend = SECURITY_BACKEND
            except (ImportError, ModuleNotFoundError):
                backend = "noop"
        production = is_production_mode()
        if production and backend == "noop":
            failed.append("security_backend")

        ready = not failed
        ref = get_request_id() or "-"
        if not ready:
            # Full detail, server-side only, correlated by the same ref the
            # client can quote.
            logger.error(
                "Readiness FAILED [ref=%s] checks=%s | providers_reachable=%s "
                "probed=%s | security_backend=%s production=%s",
                ref, failed, providers_up, sorted(model_health), backend, production,
            )

        return web.json_response(
            {"ready": ready, "ref": ref},
            status=200 if ready else 503,
        )

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

        # T2.4: a wallet proven by SIWE while holding an Apple session is linked
        # to that Apple user, so wallet-keyed services see the wallet — not
        # "apple:<sub>" — on the app's later requests.
        apple_sub = self._session_apple_id(request)
        if apple_sub:
            await self.apple_users.link_wallet(apple_sub, address)

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
        follower = self._caller_identity(request)
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
        follower = self._caller_identity(request)
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

        # The MTRX client's snake_case encoder sends identity_token; the SDK
        # sends identityToken. Accept either.
        identity_token = _body_key(body, "identityToken", "identity_token")
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
        # T2.4: first sign-in and the linked wallet are read back from the
        # apple_users table — before this, isNewUser was always true and
        # walletAddress always "" (a get_by_address the store never had).
        is_new_user = await self.apple_users.touch(sub)
        wallet_address = self.apple_users.wallet_for(sub)

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
        # The iOS app presents its Apple session as ``Authorization: Bearer``
        # (client :786); this handler read only ``X-Wallet-Session``, so the
        # app's own "delete account" found no session and deleted NOTHING
        # server-side while answering 200 "Account deleted locally" — the
        # App Store 5.1.1(v) path was a no-op. Both headers are honoured now.
        token, session = self._wallet_session_token(request)

        # Push tokens the account registered. This looked them up by the bearer
        # TOKEN string as a session id; /bridge/v1/push/register files a device
        # under the conversation id (user:<subject>, or the client's own), so it
        # matched nothing and every device stayed registered while the docs
        # said deletion removed them. Tokens now carry their owner.
        try:
            from runtime.notifications.token_store import PushTokenStore
            store = PushTokenStore(self.react_loop.memory.db)
            if session is not None:
                owner = str(session.get("address", ""))
                devices = set(await store.tokens_for(owner=owner)) if owner else set()
                devices |= set(await store.tokens_for(session_id=token))
                for dev in devices:
                    await store.remove(dev)
        except Exception:
            logger.debug("account delete: push-token cleanup skipped")

        # The account's conversations and scoped agent memory (T3 / C2b: erasure
        # can identify a user's rows now that conversations carry an owner).
        if session is not None:
            try:
                subject = str(session.get("address", ""))
                erased = await self.react_loop.memory.erase_owner(subject)
                # The store and the memory manager's cache were cleared; the
                # gateway's own working-set copy was not, so the next caller to
                # name the id — ownerless now — was handed the history.
                self._forget_conversations(erased)
            except Exception:
                logger.debug("account delete: conversation erasure skipped")

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
        session = self._wallet_session_from_request(request)
        return str(session.get("address", "")) if session else ""

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

        # The MTRX client's snake_case encoder sends signed_transaction; the
        # SDK sends signedTransaction. Accept either.
        jws = _body_key(body, "signedTransaction", "signed_transaction")
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

        message, agent, invalid = self._chat_turn_input(body)
        if invalid:
            return web.json_response({"error": invalid}, status=400)
        forbidden = self._agent_forbidden_for_caller(request, agent)
        if forbidden:
            return web.json_response({"error": "forbidden", "message": forbidden}, status=403)

        session_id, session_error = self._resolve_session_id(request, body.get("session_id"))
        if session_error:
            return web.json_response({"error": "session_required", "message": session_error}, status=400)
        denied = self._conversation_denied(request, session_id)
        if denied:
            return web.json_response({"error": "forbidden", "message": denied}, status=403)

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

        await emit("start", {"session_id": session_id, "agent": agent})

        system_prompt = self.react_loop.get_agent_prompt(agent)
        time_context = self.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        context = ReActContext(
            agent_name=agent,
            conversation=self._turn_conversation(session_id, message),
            system_prompt=full_prompt,
        )
        context.metadata["user_context"] = self._chat_user_context(
            request, session_id=session_id, agent=agent, body=body)
        context.metadata["client_context"] = self._client_turn_context(body)

        try:
            result = await self.react_loop.run(context)
        except Exception as e:
            # NEW-17 / RUN-5b: this was `emit("error", {"error": str(e)})` — the
            # raw exception went straight into the stream. RUN-5 missed it
            # because it grepped for str(e) in json_response call shapes and an
            # SSE frame is neither.
            #
            # A stream cannot set a status once its headers are out, so the
            # contract travels IN the frame: same redaction, same ref, plus the
            # status the request would have carried.
            #
            # Widened from `except RuntimeError` deliberately. A non-RuntimeError
            # escaping here aborted the stream with NO error frame at all,
            # leaving the client on a truncated response with nothing to show —
            # the streaming equivalent of a silent failure.
            _status, _err = client_error(e, None, what="Chat stream")
            await emit("error", {**_err, "status": _status})
            await emit("done", {})
            await response.write_eof()
            return response

        # Chunk response into ~80-char tokens for incremental delivery
        text = result.response
        chunk_size = 80
        for i in range(0, len(text), chunk_size):
            await emit("token", {"text": text[i:i + chunk_size]})

        await self._record_turn(session_id, message, text)

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

            if not isinstance(payload, dict) or payload.get("type") != "chat":
                await ws.send_json({"type": "error", "error": "unsupported message type"})
                continue

            message, agent, invalid = self._chat_turn_input(payload)
            if invalid:
                await ws.send_json({"type": "error", "error": invalid})
                continue
            forbidden = self._agent_forbidden_for_caller(request, agent)
            if forbidden:
                await ws.send_json({"type": "error", "error": "forbidden", "message": forbidden})
                continue

            session_id, session_error = self._resolve_session_id(request, payload.get("session_id"))
            if session_error:
                await ws.send_json({"type": "error", "error": "session_required", "message": session_error})
                continue
            denied = self._conversation_denied(request, session_id)
            if denied:
                await ws.send_json({"type": "error", "error": "forbidden", "message": denied})
                continue

            system_prompt = self.react_loop.get_agent_prompt(agent)
            time_context = self.temporal.get_context_string()
            full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

            context = ReActContext(
                agent_name=agent,
                conversation=self._turn_conversation(session_id, message),
                system_prompt=full_prompt,
            )
            # The handshake request carries the session (Authorization /
            # X-Wallet-Session); the frame carries the turn.
            context.metadata["user_context"] = self._chat_user_context(
                request, session_id=session_id, agent=agent, body=payload)
            context.metadata["client_context"] = self._client_turn_context(payload)

            try:
                result = await self.react_loop.run(context)
            except Exception as e:
                # NEW-17 / RUN-5b: same leak as /chat/stream, on the channel
                # RUN-5 never looked at. A WebSocket has no status after the
                # handshake, so — as with SSE — the contract travels in the
                # payload. Widened from RuntimeError for the same reason: an
                # unexpected exception here killed the socket silently.
                _status, _err = client_error(e, None, what="WebSocket chat")
                await ws.send_json({"type": "error", **_err, "status": _status})
                continue

            text = result.response
            for i in range(0, len(text), 80):
                await ws.send_json({"type": "token", "text": text[i:i + 80]})

            await self._record_turn(session_id, message, text)

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
        # Refuse BEFORE preparing the response, as /api/v1/events/stream does:
        # once a 200 text/event-stream is out, a rejection can only travel as a
        # field inside an error event on a successful response. This prepared
        # first, so the broadcaster's mandated 429/503 — and a missing
        # broadcaster — reached every client and proxy as 200.
        broadcaster = getattr(self, "event_broadcaster", None)
        if broadcaster is None:
            raise web.HTTPServiceUnavailable(
                text=json.dumps({"error": "Feed stream is unavailable."}),
                content_type="application/json",
                headers={"Retry-After": "30"},
            )

        # NEW-6: this called broadcaster.register(ip=...) synchronously. Three
        # faults in one line: the parameter is `remote_ip`, not `ip`; register
        # is `async` and was never awaited; and BroadcasterCapacityError — which
        # the method's own docstring tells callers to translate — was unhandled.
        from gateway.event_broadcaster import BroadcasterCapacityError

        peer = request.remote or "unknown"
        try:
            sub = await broadcaster.register(
                remote_ip=peer,
                types={"feed.new_event"},
            )
        except BroadcasterCapacityError as exc:
            # Per the broadcaster's contract: global cap -> 503, per-IP -> 429
            # (Retry-After as the sibling route sets it).
            error = web.HTTPTooManyRequests if exc.scope == "per_ip" else web.HTTPServiceUnavailable
            raise error(
                text=json.dumps({"error": "Feed stream is at capacity. Try again shortly.",
                                 "scope": exc.scope}),
                content_type="application/json",
                headers={"Retry-After": "30" if exc.scope == "per_ip" else "5"},
            )

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
        try:
            await response.prepare(request)
        except BaseException:
            await broadcaster.unregister(sub)
            raise

        # The slot this stream holds is given back however it ends. Two faults
        # kept it: the broadcaster's unregister is async and was called without
        # await (the coroutine never ran, so the subscriber was never removed),
        # and iter_events yields None as a keep-alive every quiet interval,
        # which this loop dereferenced — so every feed stream died after 15
        # quiet seconds, leaking its slot on the way out. The broadcaster is
        # shared with /api/v1/events/stream and caps slots per peer address.
        try:
            async for event in broadcaster.iter_events(sub):
                if event is None:
                    chunk = ": keepalive\n\n"
                else:
                    payload = json.dumps(event.to_dict())
                    chunk = f"id: {event.event_id}\nevent: feed\ndata: {payload}\n\n"
                await response.write(chunk.encode())
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            await broadcaster.unregister(sub)

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
        wallet = self._caller_identity(request) or "anonymous"
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
        wallet = self._caller_identity(request) or "anonymous"
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
        """GET /badge/{badge_id}/status — JSON badge status.

        NEW-7: an unknown badge id produced HTTP 500. The badge subsystem is
        not broken and nothing is missing — verify_badge() correctly raises
        ValueError("Badge '<id>' not found"), which is the right domain
        behaviour. The handler simply never caught it, so a legitimate
        not-found escaped as an unhandled server error. 404 is the answer;
        the reason stays server-side (RUN-5 shape).
        """
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        badge_id = request.match_info.get("badge_id", "")
        try:
            result = await self.badge_manager.verify_badge(badge_id)
        except ValueError:
            return web.json_response(
                {"status": "not_found", "badge_id": badge_id,
                 "error": "No badge with that id."},
                status=404,
            )
        except Exception:
            logger.exception("Badge status failed for %s", badge_id)
            return web.json_response(
                {"status": "error", "error": "Badge status is unavailable."},
                status=503,
            )
        return web.json_response(result)

    async def handle_badge_embed(self, request: web.Request) -> web.Response:
        """GET /badge/{badge_id}/embed — return embed code.

        NEW-7: same shape as handle_badge_status — an unknown id raised out of
        the handler as a 500 instead of an honest 404.
        """
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        badge_id = request.match_info.get("badge_id", "")
        try:
            code = await self.badge_manager.get_badge_embed_code(badge_id)
        except ValueError:
            return web.json_response(
                {"status": "not_found", "badge_id": badge_id,
                 "error": "No badge with that id."},
                status=404,
            )
        except Exception:
            logger.exception("Badge embed failed for %s", badge_id)
            return web.json_response(
                {"status": "error", "error": "Badge embed is unavailable."},
                status=503,
            )
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
        """POST /badge/issue — issue a badge after audit payment.

        Takes `source_code`, not an `audit_report`: the platform runs the audit
        and issues on its own verdict. See BadgeManager.issue_badge.
        """
        if not self.badge_manager:
            return web.json_response({"status": "not_available"}, status=503)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid JSON"}, status=400)
        # NEW-7: issue_badge raises ValueError on a rejected/invalid request
        # (e.g. a missing contract address or an audit report that does not
        # qualify). Uncaught, that surfaced as HTTP 500 — the server blaming
        # itself for the caller's bad input. 400 is the honest code.
        try:
            if "audit_report" in body:
                # Not honoured, and not silently dropped either: a caller that
                # sends one is trying to supply the conclusion the badge is
                # supposed to attest.
                logger.warning(
                    "badge issue: ignoring a caller-supplied audit_report — the "
                    "platform audits the source itself")
            result = await self.badge_manager.issue_badge(
                contract_address=str(body.get("contract_address", "")),
                contract_name=str(body.get("contract_name", "")),
                source_code=str(body.get("source_code", "")),
                contact_email=str(body.get("contact_email", "")),
                project_url=str(body.get("project_url", "")),
            )
        except ValueError as exc:
            # The message here describes the CALLER's input, not our internals.
            return web.json_response(
                {"status": "rejected", "error": str(exc)}, status=400
            )
        except Exception:
            logger.exception("Badge issue failed")
            return web.json_response(
                {"status": "error", "error": "Badge issuance is unavailable."},
                status=503,
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
        await self.apple_users.initialize()
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

    def _rate_limiters(self) -> list:
        """Every RateLimiter the server keys buckets in."""
        return [v for v in vars(self).values() if isinstance(v, RateLimiter)]

    async def _cleanup_loop(self) -> None:
        """Periodically prune stale rate-limiter buckets and service caches."""
        while True:
            try:
                await asyncio.sleep(300)
                # Every limiter this server holds, derived rather than listed:
                # the list named auth and anon and forgot rate_limiter_wallet,
                # whose buckets — one per SIWE address, and addresses are free
                # to mint — were never pruned.
                for limiter in self._rate_limiters():
                    limiter.cleanup()
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
        identity = (self._caller_identity(request) or str(body.get("identity", ""))).strip()
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
        app.router.add_get("/ready", self.handle_ready)
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
        """Validate the credential on protected endpoints.

        Two credentials exist. The operator key opens every route. A wallet
        session — the token ``/api/v1/auth/apple`` or ``/auth/verify`` issued,
        presented as ``Authorization: Bearer`` or ``X-Wallet-Session`` — opens
        only the routes the app reaches (``gateway/session_routes.py``, derived
        from the client's own calls; anything else answers 403). T2 / path A:
        before this, the app's Apple Bearer was refused on every key-gated
        route it calls.
        """
        if not self.auth_enabled or request.path in self._public_paths:
            return await handler(request)
        if request.method == "OPTIONS":
            return await handler(request)

        if self._is_operator(request):
            request["auth"] = {"kind": "operator"}
            return await handler(request)

        session = self._wallet_session_from_request(request)
        if session is not None:
            resource = getattr(request.match_info.route, "resource", None)
            canonical = getattr(resource, "canonical", "") if resource is not None else ""
            if canonical and session_may_reach(canonical):
                request["auth"] = {"kind": "session", "subject": str(session.get("address", ""))}
                return await handler(request)
            if canonical:
                return web.json_response(
                    {"error": "forbidden",
                     "message": "This route is not available to a user session; it requires the operator key."},
                    status=403,
                )

        return web.json_response(
            {"error": "unauthorized", "message": "Valid API key required. Set Authorization: Bearer <key>"},
            status=401,
        )

    # ─── T2 · the Apple session as a credential (path A) ──────────────────

    def _presented_api_key(self, request: web.Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        # getattr: a request object without `query` presents no key. (A
        # /api/v1/batch item is header-less; its `query` is the item path's.)
        return getattr(request, "query", {}).get("api_key", "") or ""

    def _is_operator(self, request: web.Request) -> bool:
        """The operator key was presented — or auth is off (development), where
        whoever runs the gateway is the operator."""
        if not self.auth_enabled:
            return True
        key = self._presented_api_key(request)
        return bool(key) and hmac.compare_digest(key, self.api_key)

    def _wallet_session_from_request(self, request: web.Request):
        """The live wallet session the request presents: ``X-Wallet-Session``,
        or the ``Authorization: Bearer`` token the iOS client stores from
        ``/api/v1/auth/apple``. None when absent, unknown or expired."""
        return self._wallet_session_token(request)[1]

    def _wallet_session_token(self, request: web.Request):
        """``(token, session)`` for the live wallet session the request presents
        (``X-Wallet-Session`` first, then the Bearer); ``("", None)`` otherwise."""
        candidates = [request.headers.get("X-Wallet-Session", "").strip()]
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.startswith("Bearer "):
            candidates.append(auth_header[7:].strip())
        for token in candidates:
            if not token:
                continue
            try:
                session = self.wallet_sessions.get(token)
            except Exception as exc:  # defensive — store unavailable
                logger.debug("wallet session lookup failed: %s", exc)
                session = None
            if session:
                return token, session
        return "", None

    def _session_apple_id(self, request: web.Request) -> str:
        session = self._wallet_session_from_request(request)
        subject = str(session.get("address", "")) if session else ""
        return subject[len("apple:"):] if subject.startswith("apple:") else ""

    def _session_identity(self, request: web.Request) -> str:
        """Identity DERIVED from the presented session: the wallet linked to the
        Apple user when there is one, else the session subject (``0x…`` for
        SIWE, ``apple:<sub>`` for Apple). Empty without a session."""
        session = self._wallet_session_from_request(request)
        if not session:
            return ""
        subject = str(session.get("address", ""))
        if subject.startswith("apple:"):
            linked = self.apple_users.wallet_for(subject[len("apple:"):])
            return linked or subject
        return subject

    def _caller_identity(self, request: web.Request) -> str:
        """Session-derived identity when a session is presented; otherwise the
        self-asserted ``X-Wallet-Address`` header (anonymous and dev flows)."""
        return self._session_identity(request) or request.headers.get("X-Wallet-Address", "").strip()

    def _agent_forbidden_for_caller(self, request: web.Request, agent: str):
        """On a user-facing chat surface the agent is Trinity. Naming Neo or
        Morpheus takes the operator key; a user or anonymous caller who does is
        refused explicitly (403), never silently redirected. Unknown names
        return None so the existing 400 answers them."""
        if agent in ("neo", "morpheus") and not self._is_operator(request):
            return (f"agent '{agent}' requires the operator key; users talk to Trinity "
                    "(omit 'agent' or send 'trinity')")
        return None

    # ─── T3 · one session per caller, never one for everyone ─────────────

    def _session_subject(self, request: web.Request) -> str:
        """The raw subject of the presented wallet session (``apple:<sub>`` or
        the SIWE address) — stable for the account, unlike the linked wallet."""
        session = self._wallet_session_from_request(request)
        return str(session.get("address", "")) if session else ""

    def _resolve_session_id(self, request: web.Request, requested):
        """``(session_id, error)`` for a chat, push or action request.

        The body's own id wins unless it is the shared ``"default"`` — the one
        conversation every caller who omitted an id landed in, persisted and
        replayed to a tool-enabled agent (register entry::DV-CONV-INJECT-2).
        Then the presented wallet session names the conversation
        (``user:<subject>``). With neither, production refuses (400) and
        development keeps ``"default"`` for local runs and the suite.
        """
        session_id = str(requested or "").strip()[:100]
        if session_id and session_id != "default":
            return session_id, None
        subject = self._session_subject(request)
        if subject:
            return f"user:{subject}"[:100], None
        if is_production_mode():
            return "", ('a per-user session_id is required: "default" is one conversation shared '
                        "by every caller; sign in, or send the session id your client created")
        return "default", None

    def _memory_scope(self, request: web.Request, session_id: str) -> str:
        """What the agent's memory and protocol state are keyed by for this
        caller: the account subject when signed in, else the conversation."""
        return self._session_subject(request) or session_id

    def _conversation_denied(self, request: web.Request, session_id: str):
        """Ownership (C2b): a conversation with an owner is continued only by
        that identity; an ownerless one is claimed by the first signed-in
        caller. Returns the refusal message, or None."""
        memory = self.react_loop.memory
        owner = memory.conversation_owner(session_id)
        identity = self._session_subject(request)
        if owner and owner != identity:
            return "this conversation belongs to another account"
        if not owner and identity:
            memory.claim_conversation(session_id, identity)
        return None

    def _conversation_held_elsewhere(self, request: web.Request, session_id: str):
        """The read-only half of ``_conversation_denied``: the refusal message
        when *session_id* names a conversation another account owns, else None.
        Claims nothing — for the legs of the flow that describe a conversation
        or attach something to it without continuing it."""
        if not session_id:
            return None
        owner = self.react_loop.memory.conversation_owner(session_id)
        if owner and owner != self._session_subject(request):
            return "this conversation belongs to another account"
        return None

    # ─── One chat turn, four entrances ───────────────────────────────────

    #: Body fields that DESCRIBE the caller to the gates: ``wallet_connected``,
    #: ``network`` and ``balance`` feed the Rexhepi safety verdict,
    #: ``jurisdiction`` its compliance verdict, ``total_transactions`` when
    #: Morpheus steps in. Only the operator's body may state them.
    _OPERATOR_STATED_CONTEXT = ("wallet_connected", "network", "balance",
                                "jurisdiction", "total_transactions")

    #: Default when a server is built without __init__ (unit-test fakes).
    _conversation_cap = 1024

    def _conversation_history(self, session_id: str) -> list:
        """The completed turns of *session_id*: the working-set entry,
        hydrated from the store on a miss — one path for all four entrances.

        Bounded in the number of conversations. Each entrance takes the id from
        the caller and created the entry on first touch; the history of one
        conversation was trimmed, the number held never was, so every id any
        caller named stayed in memory for the life of the process. Dict order
        is recency (a touch re-inserts the key) and the least recently used
        entry past ``conversation_cache`` is dropped. That loses nothing: an
        entry only ever holds turns _record_turn has persisted, and a miss
        reloads them (the owner reloads with them — see claim_conversation).
        """
        conversations = self.conversations
        history = conversations.pop(session_id, None)
        if history is None:
            stored = self.react_loop.memory.load_conversation(session_id)
            history = [Message(role=m["role"], content=m["content"]) for m in stored or []]
        conversations[session_id] = history
        cap = max(1, int(getattr(self, "_conversation_cap", 1024)))
        while len(conversations) > cap:
            oldest = next(iter(conversations))
            if oldest == session_id:
                break
            del conversations[oldest]
        return history

    def _turn_conversation(self, session_id: str, message: str) -> list:
        """What the model sees for this turn: the history plus the new message.
        The message joins the stored history only when the turn completes, so
        a failed turn leaves nothing behind that the store does not also hold."""
        return [*self._conversation_history(session_id), Message(role="user", content=message)]

    async def _record_turn(self, session_id: str, message: str, reply: str) -> None:
        """Append a completed turn, trim, and write the conversation through to
        the store with its owner."""
        history = self._conversation_history(session_id)
        history.append(Message(role="user", content=message))
        history.append(Message(role="assistant", content=reply))
        if len(history) > 100:
            del history[:-50]
        memory = self.react_loop.memory
        try:
            await memory.save_conversation(
                session_id,
                [{"role": m.role, "content": m.content} for m in history],
                owner=memory.conversation_owner(session_id),
            )
        except Exception as exc:
            logger.warning(f"Failed to persist conversation {session_id}: {exc}")

    def _forget_conversations(self, session_ids) -> None:
        """Drop the working-set copies of *session_ids* (account erasure)."""
        for sid in session_ids or ():
            self.conversations.pop(sid, None)

    @staticmethod
    def _chat_turn_input(body):
        """``(message, agent, error)`` — the bounds of one chat turn's input,
        checked HERE, once, for /chat, /chat/stream, /ws and /bridge/v1/chat,
        before anything is resolved, claimed or stored.

        Three entrances checked these by hand and the fourth not at all:
        /bridge/v1/chat — public and anonymous — took a message of any length
        up to the 1 MiB body cap into the shared conversation store (and into
        every later turn's model context), raised AttributeError (500) on a
        non-string message, and ran whatever agent name it was sent. /chat
        refused a non-string message while /chat/stream and /ws coerced it
        with ``str()``. One set of answers now: the body is an object, the
        message a non-empty string of at most CHAT_MESSAGE_MAX_CHARS, the agent
        one of CHAT_AGENTS (default ``trinity``).
        """
        if not isinstance(body, dict):
            return "", "", "request body must be a JSON object"
        message = body.get("message", "")
        if not isinstance(message, str):
            return "", "", "message must be a string"
        message = message.strip()
        if not message:
            return "", "", "message is required"
        if len(message) > CHAT_MESSAGE_MAX_CHARS:
            return "", "", f"message too long (at most {CHAT_MESSAGE_MAX_CHARS} characters)"
        agent = body.get("agent", "trinity")
        if not isinstance(agent, str) or agent not in CHAT_AGENTS:
            return "", "", f"invalid agent, must be one of: {', '.join(CHAT_AGENTS)}"
        return message, agent, None

    def _chat_user_context(self, request: web.Request, *, session_id: str,
                           agent: str, body) -> dict:
        """The ``user_context`` a chat turn hands the ReAct loop — built HERE,
        once, for /chat, /chat/stream, /ws and /bridge/v1/chat.

        It is what the loop decides with: ``wallet_address`` becomes the
        dispatcher's ``caller_identity`` (and so the identity the sponsorship
        cap meters and a service decides ownership on) and the identity the
        seam's beneficiary check compares a platform-signed action against;
        ``apple_id`` and ``app_attest`` are what the Morpheus gate attributes
        and verifies; the fields in ``_OPERATOR_STATED_CONTEXT`` feed gate
        verdicts. Four hand-built copies of this dict disagreed: /chat took
        every one of them from the body of a PUBLIC route, /ws bound no
        identity at all.

        Identity is derived from the presented session, never from the body
        (§EE — a verdict may not rest on what the caller writes about itself).
        The body speaks for the user only when the operator key is presented
        (development, where auth is off, counts as operator): an operator
        integration names the user it acts for. ``app_attest`` is taken from
        the body for everyone because it is not a claim — it is a signed
        assertion the gate verifies.

        What is NOT known is left out rather than invented: an anonymous caller
        has no wallet, and no balance or jurisdiction is looked up here. The
        Rexhepi safety and compliance checks therefore do not fire on those
        inputs for a non-operator chat — which is exactly as much protection as
        they gave before, when any caller could omit or rewrite them.
        """
        body = body if isinstance(body, dict) else {}
        operator = self._is_operator(request)
        identity = self._session_identity(request)
        apple_id = self._session_apple_id(request)
        if not identity and operator:
            identity = str(body.get("wallet") or body.get("wallet_address") or "").strip()
            apple_id = apple_id or str(body.get("apple_id") or "").strip()
        context: dict = {
            "session_id": session_id,
            "memory_scope": self._memory_scope(request, session_id),
            "agent": agent,
            "wallet_address": identity,
            "apple_id": apple_id,
            "app_attest": body.get("app_attest"),
        }
        # A wallet is connected when the platform knows one is behind the
        # caller: a SIWE subject, or the wallet linked to the Apple user.
        if identity and not identity.startswith("apple:"):
            context["wallet_connected"] = True
        if operator:
            for key in self._OPERATOR_STATED_CONTEXT:
                if key in body:
                    context[key] = body[key]
        return context

    @staticmethod
    def _client_turn_context(body) -> str:
        """The client's per-turn ``context`` (language directive, recap,
        portfolio line), honoured identically on all four chat entrances.

        /ws and the bridge appended it to the system prompt; /chat and
        /chat/stream dropped it, so the same body produced a different prompt
        depending on the transport. Decided once: it reaches the model on every
        entrance, in its own message under CLIENT_CONTEXT_FENCE (runtime/
        react_loop.py) rather than spliced into the platform's instructions —
        caller-authored text is carried, and labelled as caller-authored.
        """
        if not isinstance(body, dict):
            return ""
        return str(body.get("context") or "")[:CLIENT_CONTEXT_MAX_CHARS].strip()

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
            # T2: an authenticated session's subject is the identity — a header
            # or body field the caller wrote is consulted only when there is no
            # session (anonymous and dev flows). Derived, not asserted.
            identity = self._session_identity(request) or request.headers.get("X-Wallet-Address", "") or ""
            apple_id = self._session_apple_id(request) or request.headers.get("X-Apple-Id", "") or ""
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
                if not apple_id:
                    apple_id = body.get("apple_id", "") or ""
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

    # Binding every interface is the right default for a containerised gateway —
    # the container's network namespace is the boundary, and the operator sets
    # gateway.host to narrow it. Reviewed, intentional, and configurable.
    host = config.get("gateway", {}).get("host", "0.0.0.0")  # nosec B104
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
