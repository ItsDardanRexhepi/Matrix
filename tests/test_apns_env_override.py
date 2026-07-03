"""Phase 8: APNs .p8 env-override — the deploy mounts the key at
APNS_AUTH_KEY_P8_PATH; the gateway must read its CONTENTS into the ios_push
channel (else the Matrix compose mount is cosmetic). Fail-safe when absent.
"""

import os
import tempfile

import pytest

from gateway.server import _apply_env_overrides


@pytest.fixture
def clean_apns_env():
    keys = ("APNS_AUTH_KEY_P8_PATH", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_mounted_p8_contents_are_loaded(clean_apns_env, tmp_path):
    p8 = tmp_path / "apns_key.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\nCONTENTS\n-----END PRIVATE KEY-----\n")
    os.environ["APNS_AUTH_KEY_P8_PATH"] = str(p8)
    os.environ["APNS_KEY_ID"] = "K1"
    os.environ["APNS_TEAM_ID"] = "T1"
    os.environ["APNS_BUNDLE_ID"] = "com.opnmatrx.mtrx"
    ios = _apply_env_overrides({})["notifications"]["channels"]["ios_push"]
    assert "CONTENTS" in ios["auth_key_p8"]
    assert (ios["key_id"], ios["team_id"], ios["bundle_id"]) == ("K1", "T1", "com.opnmatrx.mtrx")


def test_absent_p8_leaves_channel_unconfigured(clean_apns_env):
    # No APNS_AUTH_KEY_P8_PATH -> the ios_push channel is untouched (no-op push).
    cfg = _apply_env_overrides({})
    channels = (cfg.get("notifications", {}).get("channels", {}))
    assert "auth_key_p8" not in channels.get("ios_push", {})


def test_unreadable_p8_fails_safe(clean_apns_env):
    os.environ["APNS_AUTH_KEY_P8_PATH"] = "/nonexistent/apns_key.p8"
    ios = _apply_env_overrides({})["notifications"]["channels"]["ios_push"]
    # No crash; contents never set -> push channel stays unavailable.
    assert "auth_key_p8" not in ios


def test_directory_p8_fails_safe(clean_apns_env, tmp_path):
    # Docker bind-mount footgun: a MISSING source file auto-creates a directory
    # at the mount path. Opening a directory must not crash config load.
    d = tmp_path / "apns_key.p8"
    d.mkdir()
    os.environ["APNS_AUTH_KEY_P8_PATH"] = str(d)
    ios = _apply_env_overrides({}).get("notifications", {}).get("channels", {}).get("ios_push", {})
    assert "auth_key_p8" not in ios


def test_binary_p8_fails_safe(clean_apns_env, tmp_path):
    # A binary/DER .p8 (non-UTF-8) raises UnicodeDecodeError (a ValueError),
    # which must be caught alongside OSError — never crash the gateway.
    p8 = tmp_path / "apns_key.p8"
    p8.write_bytes(b"\x30\x82\x01\x22\xff\xfe\x00\x80binary")
    os.environ["APNS_AUTH_KEY_P8_PATH"] = str(p8)
    ios = _apply_env_overrides({})["notifications"]["channels"]["ios_push"]
    assert "auth_key_p8" not in ios


def test_load_config_rejects_directory_path(tmp_path, monkeypatch):
    # P2 (bind-mount footgun): a DIRECTORY at CONFIG_PATH passes exists() but
    # must trigger the clean hard-exit, not an uncaught IsADirectoryError.
    from gateway import server
    cfg_dir = tmp_path / "openmatrix.config.json"
    cfg_dir.mkdir()
    monkeypatch.setattr(server, "CONFIG_PATH", str(cfg_dir))
    with pytest.raises(SystemExit) as ei:
        server.load_config()
    assert ei.value.code == 1
