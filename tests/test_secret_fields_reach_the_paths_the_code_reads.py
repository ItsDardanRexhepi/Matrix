"""Two secrets the env-only table missed, found by reading what the code reads.

THE PAYMASTER SIGNER. ``gateway/paymaster.py`` resolves the gas-sponsorship
signing key from ``blockchain.paymaster.signer_key`` FIRST — the location
``matrix.config.json.example`` documents — and falls back to the env-bridged
``blockchain.paymaster_private_key`` only when that is absent. SECRET_FIELDS
knew the fallback and not the documented location, so a real signing key
written at ``blockchain.paymaster.signer_key`` survived production config
loading unstripped, was the key the paymaster signed with, and no environment
variable could put one there. MEASURED on the tree before this change, with
``MATRIX_PAYMASTER_KEY`` set and a real-looking key in the file:
``enforce_env_only_secrets(config, strict=True)`` returned the file's key in
place, and ``paymaster_config`` resolved it over the environment's.

THE WEATHER KEY. The example shipped ``services.oracle_gateway.weather_api_key``
and nothing in the tree reads that path — the whole ``services.oracle_gateway``
block except ``enabled`` is read by nothing; the providers read ``oracle.*``.
The weather oracle (``runtime/blockchain/services/oracle_gateway/weather_oracle.py``)
reads ``oracle.weather.api_key``; the oracle gateway reads
``oracle.sports.api_key`` beside it. A key set at the documented leaf, by file
or by environment, never reached the oracle. The leaf is RETARGETED to where the
oracle reads — not deleted — because the oracle is live behind
``oracle_weather_query`` and the insurance triggers, and an operator who reads
the example must be able to configure it. The sports key is the sibling on the
same axis and gets the same entry.

THE SUFFIX HALF. The secret census (``SECRET_NAME_SUFFIXES``) recognises a leaf
by how its name ends. ``signer_key`` is added as the whole word, on purpose:
a bare ``key`` would name every leaf that ends in it — a public key, a cache
key — as a secret, and a census that cries wolf is one that stops being read.
``key_id`` (App Attest) and ``vrf_key_hash`` (a public Chainlink parameter)
stay out of the census, and the test pins both.

MEASURED on the unfixed tree: 13 failed, 3 passed; 16 passed after. The three
that pass before are regression guards (the flat key still feeds the signer;
a placeholder weather key reads as unset; the census names nothing public) and
say so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.config import validation
from runtime.config.validation import (
    SECRET_FIELDS, enforce_env_only_secrets, validate_config,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "matrix.config.json.example"

FILE_SIGNER = "0x" + "1a" * 32     # real-looking, never a placeholder
ENV_SIGNER = "0x" + "3c" * 32
FLAT = "0x" + "2b" * 32
DOCUMENTED = "blockchain.paymaster.signer_key"
LEGACY_TOP_LEVEL = "paymaster.signer_key"
ADDRESS = "0x0E393e90af2DAb65e60318F110270f045B125880"

ALL_VARS = ("MATRIX_PAYMASTER_SIGNER_KEY", "MATRIX_PAYMASTER_KEY",
            "WEATHER_API_KEY", "SPORTS_API_KEY", "MATRIX_ENV")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def _example() -> dict:
    return json.loads(EXAMPLE.read_text())


def _paymaster_config() -> dict:
    return {
        "blockchain": {
            "paymaster": {
                "address": ADDRESS,
                "signer_key": FILE_SIGNER,
                "policy": {"allowed_actions": ["transfer"], "daily_cap_usd": 50},
            },
        },
    }


def _entries_for(path: str) -> list[tuple[str, str, bool]]:
    return [e for e in SECRET_FIELDS if e[0] == path]


def _minimal_valid() -> dict:
    return {
        "platform": "The Matrix",
        "gateway": {"host": "127.0.0.1", "port": 8080, "api_key": "k"},
        "model": {"provider": "ollama", "providers": {"ollama": {"base_url": "http://x"}}},
        "database": {"path": "data/x.db"},
    }


# ── the documented signer location ───────────────────────────────────────────

def test_the_documented_signer_key_location_is_stripped_in_production(monkeypatch):
    """DEFECT-PROVER. A plaintext signing key at the location the example
    documents does not survive strict loading, and the paymaster signs with the
    environment's key, not the file's. Before: the file's key survived and won."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)   # the one required secret
    from gateway.paymaster import paymaster_config

    config = enforce_env_only_secrets(_paymaster_config(), strict=True)
    assert validation._get(config, DOCUMENTED) is None, (
        "a plaintext signer_key in the committed config survived strict loading")
    resolved = paymaster_config(config)
    assert resolved.get("signer_key") == FLAT, (
        "the paymaster still signs with the key read from the config file")
    # The rest of the block is what it was — stripping the secret must not
    # take the address or the policy with it.
    assert resolved.get("address") == ADDRESS
    assert resolved.get("policy", {}).get("daily_cap_usd") == 50


def test_the_signer_key_arrives_from_the_environment(monkeypatch):
    """DEFECT-PROVER. The variable lands at the location the paymaster reads
    first, so an operator configures the documented block without writing a
    key into a file. Before: no variable reached that path."""
    monkeypatch.setenv("MATRIX_PAYMASTER_SIGNER_KEY", ENV_SIGNER)
    from gateway.paymaster import paymaster_config, signer_configured

    config = enforce_env_only_secrets({"blockchain": {"paymaster": {"address": ADDRESS}}},
                                      strict=False)
    assert paymaster_config(config).get("signer_key") == ENV_SIGNER
    assert signer_configured(config)


def test_the_entry_names_the_documented_location_with_its_own_env_var():
    entries = _entries_for(DOCUMENTED)
    assert len(entries) == 1, f"{DOCUMENTED} is covered {len(entries)} times"
    _path, env_var, required = entries[0]
    assert env_var == "MATRIX_PAYMASTER_SIGNER_KEY"
    # Not required: an operator using the flat MATRIX_PAYMASTER_KEY for both
    # roles keeps working (paymaster_config falls back to it), and a
    # deployment without gas sponsorship answers 503 on /paymaster/sign
    # rather than refusing to boot.
    assert required is False


def test_a_dedicated_signer_key_outranks_the_flat_key_and_the_file(monkeypatch):
    """DEFECT-PROVER. Both variables set and a key in the file: the paymaster
    signs with the dedicated variable — the separation the example describes
    ("the platform signing key, never user funds"): the deployer/funder key and
    the sponsorship signer may be different keys. Before: the file's key won."""
    monkeypatch.setenv("MATRIX_PAYMASTER_SIGNER_KEY", ENV_SIGNER)
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    from gateway.paymaster import paymaster_config

    config = enforce_env_only_secrets(_paymaster_config(), strict=True)
    assert paymaster_config(config).get("signer_key") == ENV_SIGNER
    assert validation._get(config, "blockchain.paymaster_private_key") == FLAT


def test_the_legacy_top_level_shape_is_not_bridged_by_the_same_variable(monkeypatch):
    """``paymaster_config`` prefers a top-level ``paymaster`` block over
    ``blockchain.paymaster`` when one exists. Bridging the env var to BOTH
    locations would create a top-level block holding only the key, which would
    then shadow the documented block's address and policy — the operator who
    set the variable would get a 503 for it. The variable lands in the
    documented block and nowhere else."""
    monkeypatch.setenv("MATRIX_PAYMASTER_SIGNER_KEY", ENV_SIGNER)
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    from gateway.paymaster import paymaster_config

    config = enforce_env_only_secrets(_paymaster_config(), strict=True)
    assert "paymaster" not in config, "the env bridge created a shadowing top-level block"
    assert not _entries_for(LEGACY_TOP_LEVEL)
    resolved = paymaster_config(config)
    assert resolved.get("signer_key") == ENV_SIGNER
    assert resolved.get("address") == ADDRESS


def test_a_plaintext_key_in_the_legacy_top_level_shape_stops_a_production_boot(monkeypatch):
    """The legacy shape is not bridged, so it is not stripped either — and that
    is fine only because the census now names it: a real key at
    ``paymaster.signer_key`` is reported as an uncovered secret, which in
    production is an error and the gateway does not start. Before: ``signer_key``
    was not secret-shaped, so the key sat there unreported."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    config = {**_minimal_valid(), "paymaster": {"address": ADDRESS, "signer_key": FILE_SIGNER}}
    enforce_env_only_secrets(config, strict=True)
    report = validate_config(config, strict=True)
    assert any(i.path == LEGACY_TOP_LEVEL for i in report.errors), report.format()


def test_the_flat_key_still_feeds_the_signer_when_no_signer_key_is_set(monkeypatch):
    """Regression guard, passes on both sides: MATRIX_PAYMASTER_KEY alone is
    still a complete configuration for the paymaster signer."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    from gateway.paymaster import paymaster_config

    config = {"blockchain": {"paymaster": {"address": ADDRESS, "signer_key": ""}}}
    config = enforce_env_only_secrets(config, strict=True)
    assert paymaster_config(config).get("signer_key") == FLAT


# ── the suffix is targeted ───────────────────────────────────────────────────

def test_signer_key_is_secret_shaped_and_key_id_is_not():
    from runtime.config.validation import SECRET_NAME_SUFFIXES, is_secret_shaped

    assert "signer_key" in SECRET_NAME_SUFFIXES
    assert "_key" not in SECRET_NAME_SUFFIXES and "key" not in SECRET_NAME_SUFFIXES
    assert is_secret_shaped("signer_key")
    # None of these is a secret, and none is named: an App Attest key
    # identifier, a public Chainlink VRF gas-lane hash, a feed symbol, a
    # coordinator address.
    for public_leaf in ("key_id", "vrf_key_hash", "key_hash", "eth_usd", "vrf_coordinator"):
        assert not is_secret_shaped(public_leaf), public_leaf
    # And the census is unchanged where it already answered correctly.
    for secret_leaf in ("api_key", "paymaster_private_key", "qr_secret", "webhook_url"):
        assert is_secret_shaped(secret_leaf), secret_leaf


def test_the_example_paymaster_block_is_named_by_the_census_and_covered():
    from runtime.config.validation import secret_shaped_paths, uncovered_secret_paths

    named = set(secret_shaped_paths(_example()))
    assert DOCUMENTED in named
    assert "blockchain.paymaster.address" not in named
    assert "notifications.ios_push.key_id" not in named
    assert "services.oracle_gateway.vrf_key_hash" not in named
    assert DOCUMENTED not in uncovered_secret_paths(_example())


# ── the weather key lives where the oracle reads it ──────────────────────────

def test_the_weather_key_is_bridged_to_where_the_oracle_reads_it(monkeypatch):
    """DEFECT-PROVER. Before: WEATHER_API_KEY landed at a path no module reads,
    and the oracle saw nothing. Now it lands at ``oracle.weather.api_key`` and
    the oracle sees it."""
    monkeypatch.setenv("WEATHER_API_KEY", "owm-live-key-7f3a")
    from runtime.blockchain.services.oracle_gateway.weather_oracle import WeatherOracle

    config = enforce_env_only_secrets({"oracle": {"weather": {}}}, strict=False)
    assert WeatherOracle(config)._api_key == "owm-live-key-7f3a"


def test_the_sports_key_is_bridged_the_same_way(monkeypatch):
    """Sibling axis, same module: the oracle gateway reads ``oracle.sports.api_key``
    and the example never documented it either."""
    monkeypatch.setenv("SPORTS_API_KEY", "sports-live-key-9c1d")
    from runtime.blockchain.services.oracle_gateway import OracleGateway

    config = enforce_env_only_secrets({"oracle": {"sports": {"api_base": "https://x"}}},
                                      strict=False)
    assert OracleGateway(config)._sports_api_key == "sports-live-key-9c1d"


def test_a_plaintext_weather_key_at_the_path_the_oracle_reads_is_stripped_in_production(
        monkeypatch):
    """DEFECT-PROVER, the other half of env-only. Before: nothing covered the
    path the oracle reads, so a real key written there stayed in the file."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    config = {"oracle": {"weather": {"api_key": "owm-real-key-in-the-file"},
                         "sports": {"api_key": "sports-real-key-in-the-file"}}}
    enforce_env_only_secrets(config, strict=True)
    assert "api_key" not in config["oracle"]["weather"]
    assert "api_key" not in config["oracle"]["sports"]


def test_the_example_config_documents_the_key_at_the_path_the_oracle_reads():
    example = _example()
    assert "weather_api_key" not in example["services"]["oracle_gateway"], (
        "the example still ships a weather key at a path nothing reads")
    assert validation._get(example, "oracle.weather.api_key") is not None
    assert validation._get(example, "oracle.sports.api_key") is not None


def test_no_secret_entry_targets_the_dead_leaf():
    """Nothing reads ``services.oracle_gateway.*``, so an env-only entry there
    bridges a value to nowhere and tells the operator the key is handled when
    it is not."""
    dead = [p for p, _e, _r in SECRET_FIELDS if p.startswith("services.oracle_gateway.")]
    assert not dead, dead
    assert len(_entries_for("oracle.weather.api_key")) == 1
    assert _entries_for("oracle.weather.api_key")[0][1] == "WEATHER_API_KEY"
    assert len(_entries_for("oracle.sports.api_key")) == 1
    assert _entries_for("oracle.sports.api_key")[0][1] == "SPORTS_API_KEY"


def test_a_placeholder_weather_key_is_dropped_so_the_oracle_says_unconfigured(monkeypatch):
    """Regression guard, passes on both sides (before, the example had no
    ``oracle`` block at all): the example's placeholder at the retargeted path
    is read as unset, in both modes, so the oracle refuses plainly instead of
    sending YOUR_… to a weather API."""
    monkeypatch.setenv("MATRIX_PAYMASTER_KEY", FLAT)
    from runtime.blockchain.services.oracle_gateway.weather_oracle import WeatherOracle

    for strict in (True, False):
        config = enforce_env_only_secrets(_example(), strict=strict)
        assert not WeatherOracle(config)._api_key, strict


def test_the_census_still_names_nothing_public_in_the_example():
    """Regression guard, passes on both sides: the retarget and the new suffix
    add no false positives to the shipped example."""
    from runtime.config.validation import secret_shaped_paths

    named = secret_shaped_paths(_example())
    for public in ("services.oracle_gateway.vrf_key_hash",
                   "services.oracle_gateway.vrf_subscription_id",
                   "services.oracle_gateway.chainlink_feeds.eth_usd",
                   "notifications.ios_push.key_id", "auth.apple.key_id",
                   "blockchain.paymaster.address", "blockchain.paymaster.entry_point"):
        assert public not in named, public
