"""Every secret in the shipped config goes through the one env-only table.

THE DEFECT, MEASURED. `runtime/config/validation.py` calls SECRET_FIELDS the
central table of "private keys and third-party API tokens [that] must come from
environment variables, never from the committed config file", and
`enforce_env_only_secrets` strips a plaintext copy of anything in it. Walking
`matrix.config.json.example` for secret-shaped settings found 38 of them and 27
in the table — 71%. The 11 outside it were:

    notifications.whatsapp.account_sid
    notifications.ios_push.auth_key_p8
    auth.apple.private_key_p8
    services.oracle_gateway.weather_api_key
    supply_chain.qr_secret
    social.twitter.api_key / api_secret / access_token / access_secret
    social.discord.webhook_url / announcements_webhook

Every one could sit in the committed config in production and stay there: an
Apple token-revocation signing key, a Twitter posting credential, the
supply-chain authenticity secret. Three of them (the Twitter four and the two
Discord webhooks) were read straight out of `os.environ` by their own client
modules instead, so the env var worked and the central table — the thing that
strips the plaintext copy and that an operator reads to learn what to set —
did not know they existed.

DERIVED, NOT LISTED. The gap was closed by adding the eleven, but a hand-kept
table drifts the day someone adds the twelfth. `secret_shaped_paths()` walks a
config dict and names every secret-shaped leaf in it, `uncovered_secret_paths()`
subtracts the table, `validate_config` reports what is left at startup, and the
first test below runs the census against the shipped example. A new secret is
covered or it is loud.

MEASURED on the unfixed tree: 48 failed, 1 passed; 49 passed after. The
headline census test walks the shipped example against SECRET_FIELDS using
nothing this change introduced, so on the unfixed tree it fails there naming
all eleven; the tests that exercise the new census functions fail with
ImportError. The one that passed before is the scope pin that a placeholder is
not reported as an escaped secret — before the fix nothing was reported at all,
so it passed for the wrong reason, and it is kept because it is the line that
keeps the new report readable.

RETARGETED LATER. `services.oracle_gateway.weather_api_key` — one of the
eleven — turned out to be a leaf nothing reads: the weather oracle reads
`oracle.weather.api_key`. The entry, the example and NEWLY_COVERED below now
name that path (tests/test_secret_fields_reach_the_paths_the_code_reads.py
measures it). The same pass added `signer_key` to the suffix list — the
paymaster's documented signer location, which the census did not see — so the
independent walk below carries it too; the two walks agreeing is the point.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from runtime.config.validation import (
    SECRET_FIELDS,
    enforce_env_only_secrets,
    validate_config,
)

# The census functions this change adds are imported INSIDE the tests that use
# them, so this file still collects against the unfixed tree and each test
# fails on its own terms rather than the whole module erroring at import.

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "matrix.config.json.example").read_text())

#: The eleven the audit found outside the table, with the env var each one now
#: loads from. Written out so this file names what changed rather than only
#: asserting a count.
NEWLY_COVERED = {
    "notifications.whatsapp.account_sid": "TWILIO_ACCOUNT_SID",
    "auth.apple.private_key_p8": "APPLE_PRIVATE_KEY_P8",
    "oracle.weather.api_key": "WEATHER_API_KEY",
    "supply_chain.qr_secret": "MATRIX_QR_SECRET",
    "social.twitter.api_key": "TWITTER_API_KEY",
    "social.twitter.api_secret": "TWITTER_API_SECRET",
    "social.twitter.access_token": "TWITTER_ACCESS_TOKEN",
    "social.twitter.access_secret": "TWITTER_ACCESS_SECRET",
    "social.discord.webhook_url": "DISCORD_WEBHOOK_URL",
    "social.discord.announcements_webhook": "DISCORD_ANNOUNCEMENTS_WEBHOOK",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in set(NEWLY_COVERED.values()) | {"MATRIX_ENV", "APNS_AUTH_KEY_P8_PATH"}:
        monkeypatch.delenv(var, raising=False)


def _table_paths() -> set[str]:
    return {path for path, _env, _req in SECRET_FIELDS}


#: The walk this test file does for itself, so the headline assertion below
#: needs nothing the fix introduced. `is_secret_shaped` is checked against it
#: separately — one of them being wrong is then visible, rather than both being
#: the same mistake agreeing with itself.
_SUFFIXES = ("api_key", "apikey", "secret", "password", "passwd", "_pass",
             "private_key", "auth_key", "signing_key", "signer_key", "_p8", "_token", "_sid",
             "_dsn", "webhook_url", "_webhook", "credential", "credentials",
             "passphrase", "mnemonic", "seed_phrase", "salt")


def _walk(config: dict, prefix: str = "") -> list[str]:
    out: list[str] = []
    for key, value in config.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.extend(_walk(value, path))
        elif not isinstance(value, list) and any(
                key.lower().endswith(s) for s in _SUFFIXES):
            out.append(path)
    return out


# ── the census ────────────────────────────────────────────────────────────

def test_every_secret_shaped_setting_in_the_shipped_config_is_covered():
    """DEFECT-PROVER. The whole item, in one assertion, against the file an
    operator actually copies — and against nothing this change wrote."""
    shaped = _walk(EXAMPLE)
    try:
        from runtime.config.validation import FILE_MOUNTED_SECRETS
        mounted = {path for path, _env in FILE_MOUNTED_SECRETS}
    except ImportError:
        mounted = set()
    covered = _table_paths() | mounted
    uncovered = sorted(p for p in shaped if p not in covered)

    assert uncovered == [], (
        f"{len(uncovered)} of {len(shaped)} secret-shaped settings in "
        "matrix.config.json.example are outside the env-only table — a "
        "plaintext copy of each survives production config loading:\n  "
        + "\n  ".join(uncovered))


def test_the_shipped_census_agrees_with_an_independent_walk():
    """§EB. `uncovered_secret_paths` is what the gateway reports from at
    startup; the assertion above is what this file believes. If they ever
    disagree, one of them is wrong and this says so."""
    from runtime.config.validation import secret_shaped_paths, uncovered_secret_paths

    assert sorted(secret_shaped_paths(EXAMPLE)) == sorted(_walk(EXAMPLE))
    assert uncovered_secret_paths(EXAMPLE) == ()


def test_the_census_finds_the_secrets_it_is_supposed_to_find():
    """§CT — an empty `uncovered` has two causes: everything is covered, or the
    walk found nothing to cover. This pins the second."""
    from runtime.config.validation import secret_shaped_paths

    shaped = secret_shaped_paths(EXAMPLE)
    assert len(shaped) >= 38, f"the census collapsed to {len(shaped)} paths"
    for path in NEWLY_COVERED:
        assert path in shaped, f"{path} is not even seen as a secret"


def test_a_secret_added_tomorrow_is_named_by_the_census():
    """DERIVED, NOT LISTED: the point of the census is the setting nobody has
    written yet."""
    from runtime.config.validation import secret_shaped_paths, uncovered_secret_paths

    invented = {"services": {"brand_new_vendor": {"api_key": "sk-live-1234"}},
                "integrations": {"pager": {"webhook_url": "https://x/y"}}}
    found = secret_shaped_paths(invented)
    assert "services.brand_new_vendor.api_key" in found
    assert "integrations.pager.webhook_url" in found
    assert uncovered_secret_paths(invented) == (
        "integrations.pager.webhook_url", "services.brand_new_vendor.api_key")


@pytest.mark.parametrize("name,shaped", [
    ("api_key", True), ("qr_secret", True), ("access_secret", True),
    ("private_key_p8", True), ("auth_key_p8", True), ("bot_token", True),
    ("account_sid", True), ("sentry_dsn", True), ("smtp_pass", True),
    ("announcements_webhook", True), ("webhook_url", True),
    # This codebase's other vocabulary: `token` is an ERC-20 symbol and
    # `authenticated` is a rate-limit tier. Naming them as secrets would make
    # the census noise, and noise is how a real one gets waved through.
    ("token", False), ("token_id", False), ("reward_token", False),
    ("mirror_author", False), ("rate_limit_rpm_authenticated", False),
    ("tokenization", False), ("points_to_token_ratio", False),
])
def test_the_shape_test_separates_secrets_from_this_codebases_other_nouns(name, shaped):
    from runtime.config.validation import is_secret_shaped

    assert is_secret_shaped(name) is shaped


# ── the table actually loads them ─────────────────────────────────────────

@pytest.mark.parametrize("path,env_var", sorted(NEWLY_COVERED.items()))
def test_each_newly_covered_secret_loads_from_its_environment(path, env_var,
                                                              monkeypatch):
    """Not "it is in a tuple" — the value arrives at the path the reader uses."""
    monkeypatch.setenv(env_var, "from-the-environment")
    config = enforce_env_only_secrets({}, strict=False)

    cursor = config
    for part in path.split("."):
        assert isinstance(cursor, dict) and part in cursor, f"{path} never landed"
        cursor = cursor[part]
    assert cursor == "from-the-environment"


@pytest.mark.parametrize("path,env_var", sorted(NEWLY_COVERED.items()))
def test_each_newly_covered_secret_is_stripped_from_a_production_config(
        path, env_var, monkeypatch):
    """The other half of env-only: in production the plaintext copy goes, with
    or without an env var to replace it."""
    # The one secret that is required in production, so strict loading gets
    # past its own precondition and this test measures the field it is about.
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", "0x" + "11" * 32)
    config: dict = {}
    cursor = config
    parts = path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = "a-real-looking-secret"

    enforce_env_only_secrets(config, strict=True)

    cursor = config
    for part in parts[:-1]:
        cursor = cursor.get(part, {})
    assert parts[-1] not in cursor, (
        f"{path} survived strict config loading as plaintext")


def test_a_mounted_key_is_covered_without_being_stripped():
    """`notifications.ios_push.auth_key_p8` is not env-only and must not be
    treated as if it were: the deploy MOUNTS the .p8 and gateway/server.py reads
    its contents into the config before validation runs (tests/
    test_apns_env_override.py pins that). Stripping it would silently disable
    push in exactly the deployment that configured it correctly. It is covered
    by FILE_MOUNTED_SECRETS, which the census counts and the stripper does not
    touch."""
    from runtime.config.validation import FILE_MOUNTED_SECRETS

    assert ("notifications.ios_push.auth_key_p8", "APNS_AUTH_KEY_P8_PATH") in \
        FILE_MOUNTED_SECRETS
    assert "notifications.ios_push.auth_key_p8" not in _table_paths()

    config = {"notifications": {"ios_push": {"auth_key_p8": "-----BEGIN PRIVATE KEY-----"}},
              "blockchain": {}}
    os.environ["MATRIX_PAYMASTER_KEY"] = "0x" + "11" * 32
    try:
        enforce_env_only_secrets(config, strict=True)
    finally:
        os.environ.pop("MATRIX_PAYMASTER_KEY", None)
    assert config["notifications"]["ios_push"]["auth_key_p8"].startswith("-----BEGIN")


# ── the startup report, which is what makes the census reachable ──────────

def test_production_refuses_a_plaintext_secret_the_table_does_not_know():
    """CONNECTED: `gateway.server.load_config` exits on a validation error, so
    an uncovered plaintext secret stops a production boot instead of sitting in
    the config file being ignored."""
    config = {
        "platform": "The Matrix", "gateway": {"host": "127.0.0.1", "port": 8080,
                                              "api_key": "k"},
        "model": {"provider": "ollama",
                  "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
        "vendor": {"acme": {"api_key": "sk-live-not-in-the-table"}},
    }
    report = validate_config(config, strict=True)

    assert report.has_errors
    assert any("vendor.acme.api_key" in issue.path for issue in report.errors), (
        report.format())


def test_development_says_so_without_refusing_to_start():
    """An operator running locally is told, not stopped — the posture every
    other check in this module takes."""
    config = {
        "platform": "The Matrix", "gateway": {"host": "127.0.0.1", "port": 8080},
        "model": {"provider": "ollama",
                  "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
        "vendor": {"acme": {"api_key": "sk-live-not-in-the-table"}},
    }
    report = validate_config(config, strict=False)

    assert not report.has_errors
    assert any("vendor.acme.api_key" in issue.path for issue in report.warnings)


def test_a_placeholder_is_not_reported_as_an_escaped_secret():
    """An unfilled slot is the placeholder sweep's business. Reporting it twice,
    once as "you have a secret outside the table", would train the operator to
    ignore the line that matters."""
    config = {
        "platform": "The Matrix", "gateway": {"host": "127.0.0.1", "port": 8080,
                                              "api_key": "k"},
        "model": {"provider": "ollama",
                  "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
        "vendor": {"acme": {"api_key": "YOUR_ACME_KEY"}, "beta": {"api_key": ""}},
    }
    report = validate_config(config, strict=True)
    assert not [i for i in report.errors if "vendor" in i.path], report.format()


# ── the clients that were reading os.environ behind the table's back ──────

def test_the_twitter_client_is_configured_through_the_central_table(monkeypatch):
    """CONNECTED, both ways. The client kept its own env fallback, so this
    passes for the wrong reason unless the env value is removed after loading.
    It is: the config the table produced is what makes the client available."""
    from runtime.social.twitter import TwitterClient

    for var, value in (("TWITTER_API_KEY", "k"), ("TWITTER_API_SECRET", "s"),
                       ("TWITTER_ACCESS_TOKEN", "t"),
                       ("TWITTER_ACCESS_SECRET", "a")):
        monkeypatch.setenv(var, value)
    config = enforce_env_only_secrets({}, strict=False)
    for var in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
                "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"):
        monkeypatch.delenv(var)

    assert TwitterClient(config).available is True


def test_the_discord_client_is_configured_through_the_central_table(monkeypatch):
    from runtime.social.discord import DiscordClient

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    config = enforce_env_only_secrets({}, strict=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL")

    assert DiscordClient(config).available is True


def test_the_qr_generator_is_configured_through_the_central_table(monkeypatch):
    """The supply-chain authenticity secret, which has no default any more:
    setting MATRIX_QR_SECRET is now enough to make the feature work."""
    from runtime.blockchain.services.supply_chain.qr_codes import QRCodeGenerator

    monkeypatch.setenv("MATRIX_QR_SECRET", "a-real-per-deployment-secret")
    config = enforce_env_only_secrets({}, strict=False)
    monkeypatch.delenv("MATRIX_QR_SECRET")

    assert QRCodeGenerator(config).secret_configured is True
