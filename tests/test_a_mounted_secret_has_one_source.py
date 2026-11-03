"""A mounted secret's source is the mount. A copy in the config file is not one.

`gateway/server.py::load_config` promises that in production plaintext secrets
in the JSON file are stripped. `runtime/config/validation.py` keeps two
tables: SECRET_FIELDS, whose source is an env value and whose plaintext copies
`enforce_env_only_secrets` strips, and FILE_MOUNTED_SECRETS, whose source is a
mounted file — the APNs `.p8`, named by APNS_AUTH_KEY_P8_PATH. The second table
was counted as covered by the secrets census and never stripped, so a
production config carrying the APNs signing key in plaintext kept it, and
startup did not refuse: the one key this gateway itself writes from a mount
was the one the promise did not hold for.

The mount stays the documented way in. What changes is that the config file
stops being a second way: with a readable mount the file's value is replaced
by the mount's, and without one a plaintext copy is removed in production,
exactly as a SECRET_FIELDS entry's is. Development keeps what it is given.
"""

from __future__ import annotations

import pytest

from runtime.config.validation import SECRET_FIELDS, enforce_env_only_secrets

PEM = "-----BEGIN PRIVATE KEY-----\nMHcCAQEE\n-----END PRIVATE KEY-----\n"


@pytest.fixture
def production(monkeypatch):
    """Satisfy the secrets whose absence ABORTS a strict start, so each case
    measures the mounted secret and not the required-secret refusal."""
    for _path, env_var, required in SECRET_FIELDS:
        if required:
            monkeypatch.setenv(env_var, f"set-for-{env_var}")
    monkeypatch.delenv("APNS_AUTH_KEY_P8_PATH", raising=False)
    return monkeypatch


def _ios(config: dict) -> dict:
    return config.get("notifications", {}).get("ios_push", {})


def test_a_plaintext_apns_key_is_stripped_in_production(production):
    """THE DEFECT: no mount, a real-looking key in the file, strict mode."""
    config = {"notifications": {"ios_push": {"auth_key_p8": PEM, "key_id": "K"}}}
    enforce_env_only_secrets(config, strict=True)
    assert "auth_key_p8" not in _ios(config), (
        "a plaintext APNs signing key survived production config loading")
    assert _ios(config)["key_id"] == "K", "only the secret is removed"


def test_a_mounted_key_is_the_value_whatever_the_file_said(production, tmp_path):
    key = tmp_path / "AuthKey.p8"
    key.write_text(PEM)
    production.setenv("APNS_AUTH_KEY_P8_PATH", str(key))
    config = {"notifications": {"ios_push": {"auth_key_p8": "a copy in the file"}}}
    enforce_env_only_secrets(config, strict=True)
    assert _ios(config)["auth_key_p8"] == PEM


@pytest.mark.parametrize("bad", ["/nonexistent/AuthKey.p8", "DIRECTORY"])
def test_an_unreadable_mount_is_no_source_and_not_a_crash(production, tmp_path, bad):
    production.setenv("APNS_AUTH_KEY_P8_PATH",
                      str(tmp_path) if bad == "DIRECTORY" else bad)
    config = {"notifications": {"ios_push": {"auth_key_p8": PEM}}}
    enforce_env_only_secrets(config, strict=True)
    assert "auth_key_p8" not in _ios(config)


def test_development_keeps_what_it_is_given(production):
    """Lenient mode strips nothing real, for this table as for the other."""
    config = {"notifications": {"ios_push": {"auth_key_p8": PEM}}}
    enforce_env_only_secrets(config, strict=False)
    assert _ios(config)["auth_key_p8"] == PEM


def test_load_config_names_what_decides_which_secrets_are_stripped():
    """The promise names the tables that decide it, rather than saying "any"."""
    from gateway.server import load_config

    doc = load_config.__doc__ or ""
    assert "Any plaintext\n        copies in the JSON file are stripped" not in doc
    assert "SECRET_FIELDS" in doc and "FILE_MOUNTED_SECRETS" in doc


def test_the_gateway_and_the_loader_read_the_mount_the_same_way(production, tmp_path):
    """`_apply_env_overrides` reads the mount into the config before the loader
    runs, and the loader reads it again: one reader, so the two cannot disagree
    about what a mount contains."""
    from gateway.server import _apply_env_overrides

    key = tmp_path / "AuthKey.p8"
    key.write_text(PEM)
    production.setenv("APNS_AUTH_KEY_P8_PATH", str(key))
    config = enforce_env_only_secrets(_apply_env_overrides({}), strict=True)
    assert _ios(config)["auth_key_p8"] == PEM
