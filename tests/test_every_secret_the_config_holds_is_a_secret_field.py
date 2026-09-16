"""`load_config` promises: "Any plaintext copies in the JSON file are stripped."

The stripping is table-driven. `enforce_env_only_secrets` iterates
:data:`SECRET_FIELDS` and nothing else, so "any" means "the ones somebody
remembered to list". A sweep of the shipped example config finds 38
secret-shaped keys and 11 of them were absent from that table, including
`notifications.ios_push.auth_key_p8` — the APNs signing key that
`gateway/server.py::_apply_env_overrides` itself writes into the config from a
mounted file — and `auth.apple.private_key_p8`, the Sign in with Apple team
key. A production deployment carrying either in plaintext was not stripped and
startup did not refuse.

The class check below is the point: it is not a list of eleven fixes, it is the
rule that a secret-shaped key in the example config must be a SECRET_FIELDS
entry. Add a new credential to the example and forget the table, and this
fails.

One field is supplied as a FILE rather than a value: the APNs .p8 is mounted
and `APNS_AUTH_KEY_P8_PATH` names it. Listing that field without teaching the
loader about the path form would have made strict mode strip the key the mount
had just installed — the documented deploy breaking because its secret finally
became a secret. So `<ENV>_PATH` is a first-class source for every entry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from runtime.config.validation import SECRET_FIELDS, enforce_env_only_secrets

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "matrix.config.json.example"


@pytest.fixture
def required_secrets_present(monkeypatch):
    """Satisfy the entries that ABORT a strict start, so each case below tests
    stripping rather than the required-secret refusal (which has its own
    tests)."""
    for path, env_var, required in SECRET_FIELDS:
        if required:
            monkeypatch.setenv(env_var, f"set-for-{env_var}")
    return monkeypatch


#: Key names that name a credential. Kept deliberately blunt: a false positive
#: costs one table entry, a false negative costs a leaked secret.
SECRET_SHAPED = re.compile(
    r"(private_key|_p8|secret|token|api_key|password|passwd|"
    r"auth_key|signer_key|_sid|dsn|webhook_url)$",
    re.IGNORECASE,
)


def _secret_shaped_keys() -> list[str]:
    config = json.loads(EXAMPLE.read_text())
    found: list[str] = []

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key.endswith("//"):
                continue
            here = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                walk(value, here)
            elif SECRET_SHAPED.search(key):
                found.append(here)

    walk(config)
    return found


def test_every_secret_shaped_key_in_the_example_config_is_stripped():
    covered = {path for path, _, _ in SECRET_FIELDS}
    uncovered = sorted(set(_secret_shaped_keys()) - covered)
    assert not uncovered, (
        "load_config promises any plaintext secret in the JSON is stripped, "
        "and enforce_env_only_secrets iterates SECRET_FIELDS only. These "
        "secret-shaped config keys are not in it, so a production config "
        "carrying them in plaintext keeps them:\n  " + "\n  ".join(uncovered))


def test_the_sweep_finds_the_keys_it_is_meant_to_find():
    """A zero from this sweep must mean coverage, not a broken detector."""
    keys = _secret_shaped_keys()
    assert len(keys) >= 30, keys
    for expected in ("notifications.ios_push.auth_key_p8",
                     "auth.apple.private_key_p8",
                     "blockchain.paymaster_private_key",
                     "social.twitter.access_secret"):
        assert expected in keys, (expected, keys)


def test_a_listed_secret_is_actually_stripped_in_strict_mode(required_secrets_present):
    config = {"notifications": {"ios_push": {"auth_key_p8": "-----BEGIN KEY-----"}},
              "auth": {"apple": {"private_key_p8": "-----BEGIN KEY-----"}}}
    enforce_env_only_secrets(config, strict=True)
    assert "auth_key_p8" not in config["notifications"]["ios_push"]
    assert "private_key_p8" not in config["auth"]["apple"]


def test_a_secret_mounted_as_a_file_survives_strict_mode(
        tmp_path, required_secrets_present):
    """The documented APNs deploy: the .p8 is a mounted FILE, named by
    APNS_AUTH_KEY_P8_PATH. Listing the field must not strip what the mount
    installed."""
    monkeypatch = required_secrets_present
    key = tmp_path / "AuthKey.p8"
    key.write_text("-----BEGIN PRIVATE KEY-----\nMHc\n-----END PRIVATE KEY-----")
    monkeypatch.setenv("APNS_AUTH_KEY_P8_PATH", str(key))
    monkeypatch.delenv("APNS_AUTH_KEY_P8", raising=False)

    config = {"notifications": {"ios_push": {"auth_key_p8": "whatever was here"}}}
    enforce_env_only_secrets(config, strict=True)
    assert config["notifications"]["ios_push"]["auth_key_p8"] == key.read_text().strip()


def test_an_env_value_still_wins_over_a_path(tmp_path, required_secrets_present):
    monkeypatch = required_secrets_present
    key = tmp_path / "AuthKey.p8"
    key.write_text("from-the-file")
    monkeypatch.setenv("APNS_AUTH_KEY_P8_PATH", str(key))
    monkeypatch.setenv("APNS_AUTH_KEY_P8", "from-the-env")
    config = {}
    enforce_env_only_secrets(config, strict=True)
    assert config["notifications"]["ios_push"]["auth_key_p8"] == "from-the-env"


@pytest.mark.parametrize("bad", ["/nonexistent/path/AuthKey.p8", ""])
def test_an_unreadable_path_is_not_a_crash(bad, required_secrets_present):
    monkeypatch = required_secrets_present
    monkeypatch.setenv("APNS_AUTH_KEY_P8_PATH", bad)
    monkeypatch.delenv("APNS_AUTH_KEY_P8", raising=False)
    config = {"notifications": {"ios_push": {"auth_key_p8": "plaintext"}}}
    enforce_env_only_secrets(config, strict=True)
    # Stripped, because no env source supplied one — never a raise.
    assert not config["notifications"]["ios_push"].get("auth_key_p8")


def test_the_docstring_does_not_promise_more_than_the_table_holds():
    from gateway.server import load_config

    doc = load_config.__doc__ or ""
    assert "SECRET_FIELDS" in doc, (
        "the guarantee says 'any plaintext copies' without naming the table "
        "that decides which ones")
