"""Pre-flight configuration validation and secret loading.

The gateway must never start with obviously-broken config. This
module centralises two responsibilities:

1. **Env-only secret loading.** Private keys and third-party API tokens
   must come from environment variables, never from the committed
   config file. :func:`enforce_env_only_secrets` removes any such
   fields from the loaded config dict and replaces them with the
   corresponding environment variable value, or raises
   :class:`ConfigValidationError` if the field is required and unset.

2. **Pre-flight validation.** :func:`validate_config` walks the
   assembled config and returns a structured report of *all* missing
   or obviously-wrong fields, so the operator sees every problem in
   one shot instead of fixing-and-retrying.

Usage from ``gateway/server.py``::

    from runtime.config.validation import (
        enforce_env_only_secrets,
        validate_config,
        ConfigValidationError,
    )

    config = _apply_env_overrides(json.loads(path.read_text()))
    config = enforce_env_only_secrets(config, strict=production_mode)
    report = validate_config(config, strict=production_mode)
    if report.has_errors:
        raise ConfigValidationError(report.format())
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class ConfigValidationError(RuntimeError):
    """Raised when the config is unusable and the gateway must not start."""


# ── Env-only secret paths ────────────────────────────────────────────
#
# Each entry is ``(dotted.config.path, ENV_VAR, required_in_production)``.
# ``required_in_production`` means: if ``strict=True`` (production mode)
# and neither the env var nor the config field is set, the loader will
# raise. Non-required secrets can safely be absent in offline/testnet
# mode; the downstream code short-circuits to ``not_deployed`` or its
# equivalent.

def _provider_secret_fields() -> tuple[tuple[str, str, bool], ...]:
    from runtime.models.providers import secret_fields
    return secret_fields()


SECRET_FIELDS: tuple[tuple[str, str, bool], ...] = (
    # Blockchain signer keys
    ("blockchain.paymaster_private_key", "MATRIX_PAYMASTER_KEY", True),
    # The gas-sponsorship signer at the location matrix.config.json.example
    # documents. gateway/paymaster.py reads THIS first and falls back to the
    # flat key above only when it is absent — so a real key written here
    # survived production loading unstripped, and no variable could set it.
    # Not required: the flat key alone still configures the signer, and a
    # deployment without sponsorship answers 503 on /paymaster/sign.
    ("blockchain.paymaster.signer_key", "MATRIX_PAYMASTER_SIGNER_KEY", False),
    ("blockchain.demo_wallet_private_key", "MATRIX_DEMO_WALLET_KEY", False),
    # Model provider API keys (fallback to the per-provider env vars
    # that ``_apply_env_overrides`` in gateway/server.py already reads)
    # Every provider declared in runtime/models/providers.py that takes a key,
    # so a provider added there is reachable by env var the same day. Listing
    # them by hand is how Grok, Hermes and eight others ended up unreachable.
    *_provider_secret_fields(),
    # Notifications (unified notifications tree — see runtime/notifications/)
    ("notifications.telegram.bot_token",    "TELEGRAM_BOT_TOKEN",    False),
    ("notifications.discord.webhook_url",   "DISCORD_WEBHOOK_URL",   False),
    ("notifications.slack.webhook_url",     "SLACK_WEBHOOK_URL",     False),
    ("notifications.email.smtp_pass",       "SMTP_PASS",             False),
    ("notifications.sms.auth_token",        "TWILIO_AUTH_TOKEN",     False),
    ("notifications.sms.account_sid",       "TWILIO_ACCOUNT_SID",    False),
    ("notifications.sms.from_number",       "TWILIO_FROM_NUMBER",    False),
    ("notifications.whatsapp.auth_token",   "TWILIO_AUTH_TOKEN",     False),
    ("notifications.webhook.bearer_token",  "NOTIFY_WEBHOOK_BEARER", False),
    ("notifications.whatsapp.account_sid",  "TWILIO_ACCOUNT_SID",    False),
    # NOTE: owner-verification secrets (OWNER_APPLE_ID / OWNER_WALLET /
    # OWNER_PHONE_NUMBER) are declared and validated by the private security
    # package (morpheus_security), not here — the public platform never references
    # the owner-auth factors. All env-only; never committed.
    # Sign in with Apple: the .p8 that signs token-revocation requests
    # (gateway/apple_auth.py). It had no env bridge at all, so the only place to
    # put it was the committed config file.
    ("auth.apple.private_key_p8", "APPLE_PRIVATE_KEY_P8", False),
    # Third-party service keys. These were read directly from os.environ by the
    # modules that use them (runtime/social/twitter.py, runtime/social/discord.py)
    # — which works, and leaves the plaintext copy in the config file untouched
    # in production, and leaves this table unable to tell an operator what to set.
    ("social.twitter.api_key",        "TWITTER_API_KEY",        False),
    ("social.twitter.api_secret",     "TWITTER_API_SECRET",     False),
    ("social.twitter.access_token",   "TWITTER_ACCESS_TOKEN",   False),
    ("social.twitter.access_secret",  "TWITTER_ACCESS_SECRET",  False),
    ("social.discord.webhook_url",    "DISCORD_WEBHOOK_URL",    False),
    ("social.discord.announcements_webhook",
     "DISCORD_ANNOUNCEMENTS_WEBHOOK", False),
    # Oracle API keys, at the paths the oracle gateway READS
    # (runtime/blockchain/services/oracle_gateway/: weather_oracle.py reads
    # oracle.weather.api_key, gateway.py reads oracle.sports.api_key). The
    # weather entry used to target services.oracle_gateway.weather_api_key, a
    # leaf the example shipped and nothing read — WEATHER_API_KEY bridged a
    # value to nowhere while the census called the key handled.
    ("oracle.weather.api_key", "WEATHER_API_KEY", False),
    ("oracle.sports.api_key",  "SPORTS_API_KEY",  False),
    # Supply-chain authenticity. There is no default: without this the QR
    # generator refuses to issue or verify codes
    # (runtime/blockchain/services/supply_chain/qr_codes.py).
    ("supply_chain.qr_secret", "MATRIX_QR_SECRET", False),
    # Observability
    ("monitoring.sentry_dsn", "SENTRY_DSN", False),
    # Gateway auth
    ("gateway.api_key", "MATRIX_API_KEY", False),
)

#: Secrets whose material arrives as a MOUNTED FILE rather than an env value,
#: read into the config by ``gateway/server.py`` before validation runs.
#: ``(config path, the env var naming the file)``.
#:
#: They belong in the census — an operator asking "is this secret handled?" must
#: get yes — but NOT in SECRET_FIELDS, because the stripper would delete the
#: contents the mount just supplied and silently disable the channel in exactly
#: the deployment that configured it properly.
FILE_MOUNTED_SECRETS: tuple[tuple[str, str], ...] = (
    ("notifications.ios_push.auth_key_p8", "APNS_AUTH_KEY_P8_PATH"),
)

#: How a secret-shaped setting is recognised, by the END of its leaf name.
#: Derived rather than listed: the census below walks whatever config it is
#: handed, so a secret added to the shipped example — or to an operator's own
#: file — is named without anyone remembering to add it anywhere.
#:
#: ``signer_key`` is the whole word on purpose. A bare ``key`` would name every
#: leaf that ends in it — a public key, a cache key — as a secret, and a census
#: that cries wolf is one that stops being read.
SECRET_NAME_SUFFIXES: tuple[str, ...] = (
    "api_key", "apikey", "secret", "password", "passwd", "_pass",
    "private_key", "auth_key", "signing_key", "signer_key", "_p8", "_token", "_sid",
    "_dsn", "webhook_url", "_webhook", "credential", "credentials",
    "passphrase", "mnemonic", "seed_phrase", "salt",
)

#: Leaf names that END like a secret and are not one. In this codebase `token`
#: is an ERC-20 symbol — `reward_token`, `token_out`, `payment_token` are asset
#: names in ordinary service config. Listing them here keeps the census quiet
#: enough to be read; a census nobody reads is a census that hides the one line
#: that mattered.
NOT_SECRET_LEAVES: frozenset[str] = frozenset({
    "token", "token_id", "token_in", "token_out", "token_a", "token_b",
    "token_name", "token_symbol", "token_address", "token_uri", "token_type",
    "reward_token", "payment_token", "collateral_token", "base_token",
    "quote_token", "stake_token", "lp_token", "governance_token",
    "from_token", "to_token", "native_token",
})


def is_secret_shaped(name: str) -> bool:
    """Does this leaf config key name a secret?"""
    leaf = str(name or "").strip().lower()
    if not leaf or leaf in NOT_SECRET_LEAVES:
        return False
    return any(leaf.endswith(suffix) for suffix in SECRET_NAME_SUFFIXES)


def secret_shaped_paths(config: dict) -> tuple[str, ...]:
    """Every dotted path in *config* whose leaf key names a secret, sorted.

    Values are not inspected: a secret that is currently empty or still holding
    a placeholder is exactly the one an operator is about to fill in.
    """
    found: list[str] = []

    def _walk(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                _walk(value, path)
            elif not isinstance(value, list) and is_secret_shaped(str(key)):
                found.append(path)

    _walk(config or {}, "")
    return tuple(sorted(found))


def uncovered_secret_paths(config: dict) -> tuple[str, ...]:
    """Secret-shaped settings in *config* that no entry in this module covers.

    Covered means: in SECRET_FIELDS (loaded from an env var, plaintext copy
    stripped in production) or in FILE_MOUNTED_SECRETS (supplied by a mount).
    Anything else is a secret this module does not know about, which means
    nothing strips it, nothing documents it, and nothing tells the operator
    where it is supposed to come from.
    """
    covered = {path for path, _env, _req in SECRET_FIELDS}
    covered |= {path for path, _env in FILE_MOUNTED_SECRETS}
    return tuple(p for p in secret_shaped_paths(config) if p not in covered)

# Fields that MUST exist and be non-placeholder in production.
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("platform", "platform name (e.g. 'The Matrix')"),
    ("gateway.host", "HTTP listen host (use 0.0.0.0 inside containers)"),
    ("gateway.port", "HTTP listen port"),
    ("model.provider", "default model provider name"),
    ("database.path", "SQLite database path"),
)

# Both separators, because both are shipped: the config example writes
# `CHANGE-ME-long-random-per-deployment-value` with hyphens, which the
# underscore-only list read as a real value — so the placeholder sweep stayed
# quiet about the one secret an operator is most likely to leave unset.
PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "YOUR_", "YOUR-", "CHANGE_ME", "CHANGE-ME", "REPLACE_", "REPLACE-", "xxx-")
PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {"", "0x0000000000000000000000000000000000000000"}
)


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    path: str
    severity: str  # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.path}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def add_error(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, "error", message))

    def add_warning(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, "warning", message))

    def format(self) -> str:
        lines: list[str] = []
        if self.errors:
            lines.append(f"{len(self.errors)} configuration error(s):")
            lines.extend(f"  - {i.path}: {i.message}" for i in self.errors)
        if self.warnings:
            lines.append(f"{len(self.warnings)} configuration warning(s):")
            lines.extend(f"  - {i.path}: {i.message}" for i in self.warnings)
        return "\n".join(lines) if lines else "Config OK"


# ── Helpers ──────────────────────────────────────────────────────────


def _get(config: dict, path: str) -> Any:
    """Look up a dotted path in *config*. Returns ``None`` if missing."""
    parts = path.split(".")
    cursor: Any = config
    for part in parts:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
        if cursor is None:
            return None
    return cursor


def _set(config: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = config
    for part in parts[:-1]:
        next_cursor = cursor.get(part)
        if not isinstance(next_cursor, dict):
            next_cursor = {}
            cursor[part] = next_cursor
        cursor = next_cursor
    cursor[parts[-1]] = value


def _delete(config: dict, path: str) -> None:
    parts = path.split(".")
    cursor = config
    for part in parts[:-1]:
        cursor = cursor.get(part) if isinstance(cursor, dict) else None
        if cursor is None:
            return
    if isinstance(cursor, dict):
        cursor.pop(parts[-1], None)


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        if value in PLACEHOLDER_VALUES:
            return True
        for prefix in PLACEHOLDER_PREFIXES:
            if value.startswith(prefix):
                return True
    return False


def is_placeholder(value: Any) -> bool:
    """Is *value* an unfilled slot rather than a configured value?

    Public because it is the platform's one answer to "has the operator chosen
    this?", and callers outside config loading need it: a secret with a
    placeholder in it is NOT configured, and code that fails closed on an unset
    secret has to fail closed on `CHANGE-ME-...` too, or the fix lasts exactly
    as long as it takes someone to copy the example file.
    """
    return _is_placeholder(value)


def is_production_mode() -> bool:
    """Return ``True`` if the environment says we're running in production.

    Controlled by the ``MATRIX_ENV`` env var: set it to ``production``
    (case-insensitive) to enable the strict validation path. Anything
    else — unset, ``development``, ``testnet``, etc. — uses lenient
    mode so local testing and Sepolia runs don't need a fully-wired
    secret stack.
    """
    return os.environ.get("MATRIX_ENV", "").strip().lower() == "production"


# ── Public API ───────────────────────────────────────────────────────


def enforce_env_only_secrets(
    config: dict,
    *,
    strict: bool | None = None,
) -> dict:
    """Load secrets from env vars, stripping any plaintext copies from config.

    For each entry in :data:`SECRET_FIELDS`:

    - If the environment variable is set, its value wins and is copied
      into the config dict (overwriting whatever was there).
    - If the environment variable is unset and the config already has a
      non-placeholder value, we leave it alone (lenient mode) or
      **delete it and raise** (strict mode, required fields).
    - If neither source provides a value and the field is required in
      production, :class:`ConfigValidationError` is raised.

    Mutates and returns *config*.
    """
    if strict is None:
        strict = is_production_mode()

    missing_required: list[str] = []

    for path, env_var, required_in_prod in SECRET_FIELDS:
        env_value = os.environ.get(env_var, "").strip()
        current = _get(config, path)

        if env_value:
            _set(config, path, env_value)
            continue

        if strict:
            if current is not None and not _is_placeholder(current):
                # Production mode: plaintext secrets in the committed
                # config are forbidden. Strip the value and require the
                # env var instead.
                logger.warning(
                    "Secret %s found in config file; removing in strict "
                    "mode. Set %s in the environment instead.",
                    path,
                    env_var,
                )
                _delete(config, path)
                current = None
            elif _is_placeholder(current):
                # A placeholder is indistinguishable from "not set" in
                # strict mode — drop it so downstream code sees ``None``.
                _delete(config, path)
                current = None
            if current is None and required_in_prod:
                missing_required.append(f"{path} (env: {env_var})")
        else:
            # Lenient mode: placeholder → remove so downstream code sees
            # "not configured". Real values pass through untouched.
            if _is_placeholder(current):
                _delete(config, path)

    if missing_required:
        raise ConfigValidationError(
            "Required secrets are not set in the environment:\n"
            + "\n".join(f"  - {item}" for item in missing_required)
            + "\n\nSet these via environment variables (or a secrets manager) "
            "and restart the gateway."
        )

    return config


def validate_config(
    config: dict,
    *,
    strict: bool | None = None,
) -> ValidationReport:
    """Walk the assembled config and return every issue in one report."""
    if strict is None:
        strict = is_production_mode()

    report = ValidationReport()

    # Required fields
    for path, description in REQUIRED_FIELDS:
        value = _get(config, path)
        if value is None:
            report.add_error(path, f"missing — {description}")
        elif _is_placeholder(value):
            report.add_error(path, f"placeholder value '{value}' — {description}")

    # Gateway host/port sanity
    port = _get(config, "gateway.port")
    if port is not None:
        try:
            port_int = int(port)
            if port_int < 1 or port_int > 65535:
                report.add_error("gateway.port", f"{port!r} is not a valid port")
        except (TypeError, ValueError):
            report.add_error("gateway.port", f"{port!r} is not an integer")

    # Rate limiter sanity
    for path in (
        "gateway.rate_limit_rpm",
        "gateway.rate_limit_rpm_authenticated",
        "gateway.rate_limit_rpm_anonymous",
        "gateway.rate_limit_burst",
    ):
        value = _get(config, path)
        if value is None:
            continue
        try:
            as_int = int(value)
            if as_int <= 0:
                report.add_error(path, f"{value!r} must be positive")
        except (TypeError, ValueError):
            report.add_error(path, f"{value!r} is not an integer")

    # CORS origins should be a list
    cors = _get(config, "gateway.cors_origins")
    if cors is not None and not isinstance(cors, list):
        report.add_error(
            "gateway.cors_origins",
            "must be a list (use [] to block cross-origin, ['*'] to allow all)",
        )

    # Auth must be enabled in production
    api_key = _get(config, "gateway.api_key")
    if strict and not api_key:
        report.add_error(
            "gateway.api_key",
            "must be set in production (via MATRIX_API_KEY env var)",
        )

    # TLS termination should happen externally in production
    if strict and not _get(config, "gateway.tls_terminated_externally"):
        report.add_warning(
            "gateway.tls_terminated_externally",
            "not set — the gateway speaks plain HTTP and assumes a "
            "reverse proxy (Caddy/nginx/cloud LB) terminates TLS. "
            "Set to true to acknowledge.",
        )

    # Blockchain RPC sanity
    rpc_url = _get(config, "blockchain.rpc_url")
    if rpc_url and _is_placeholder(rpc_url):
        report.add_warning(
            "blockchain.rpc_url",
            f"placeholder '{rpc_url}' — blockchain services will return "
            "not_deployed until a real RPC is configured",
        )

    # Model providers: at least one must be usable
    providers = _get(config, "model.providers") or {}
    if isinstance(providers, dict):
        usable = []
        for name, cfg in providers.items():
            if not isinstance(cfg, dict):
                continue
            if name == "ollama":
                if cfg.get("base_url"):
                    usable.append(name)
                continue
            api_key_val = cfg.get("api_key")
            if api_key_val and not _is_placeholder(api_key_val):
                usable.append(name)
        if not usable:
            report.add_warning(
                "model.providers",
                "no usable model provider found — set at least one "
                "provider's api_key or run ollama locally",
            )

    # Secrets that escaped the central table. `enforce_env_only_secrets` has
    # already run by the time load_config gets here, so anything still holding a
    # real value at a secret-shaped path is a secret this module does not know
    # how to keep out of the config file. In production that is an error and the
    # gateway does not start; in development it is said once and life goes on.
    # Placeholders are left to the sweep below — reporting an unfilled slot as an
    # escaped secret is how a report stops being read.
    for path in uncovered_secret_paths(config):
        value = _get(config, path)
        if value is None or _is_placeholder(value):
            continue
        message = (
            "holds a secret that no env-only entry covers — add it to "
            "SECRET_FIELDS (runtime/config/validation.py) with the environment "
            "variable it should come from, so the committed config never "
            "carries it"
        )
        if strict:
            report.add_error(path, message)
        else:
            report.add_warning(path, message)

    # Placeholder sweep — warn about anything still sporting YOUR_ or
    # similar so operators see the full list once at startup.
    for path, value in _walk_placeholders(config):
        report.add_warning(path, f"placeholder value '{value}'")

    return report


def _walk_placeholders(
    config: dict,
    prefix: str = "",
) -> Iterable[tuple[str, Any]]:
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _walk_placeholders(value, path)
        elif isinstance(value, str) and _is_placeholder(value) and value:
            yield path, value


__all__ = [
    "ConfigValidationError",
    "FILE_MOUNTED_SECRETS",
    "NOT_SECRET_LEAVES",
    "SECRET_FIELDS",
    "SECRET_NAME_SUFFIXES",
    "REQUIRED_FIELDS",
    "is_secret_shaped",
    "secret_shaped_paths",
    "uncovered_secret_paths",
    "ValidationIssue",
    "ValidationReport",
    "enforce_env_only_secrets",
    "is_placeholder",
    "is_production_mode",
    "validate_config",
]
