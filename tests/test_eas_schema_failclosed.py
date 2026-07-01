"""P2-9: EAS schema UIDs fail closed when unconfigured (no fabricated defaults)."""

import pytest

from runtime.blockchain.services.attestation import schemas


def test_defaults_are_empty():
    assert schemas.PRIMARY_SCHEMA_UID == ""
    assert all(v == "" for v in schemas.PLATFORM_SCHEMAS.values())


def test_get_schema_uid_fails_closed_when_unconfigured():
    with pytest.raises(ValueError):
        schemas.get_schema_uid("payments")  # no config -> empty -> raise


def test_get_schema_uid_rejects_malformed_override():
    with pytest.raises(ValueError):
        schemas.get_schema_uid(
            "payments", {"blockchain": {"schemas": {"payments": "0x1234"}}})  # too short


def test_get_schema_uid_accepts_valid_override():
    uid = "0x" + "ab" * 32  # 66 chars
    got = schemas.get_schema_uid(
        "payments", {"blockchain": {"schemas": {"payments": uid}}})
    assert got == uid


def test_schema_definitions_still_present():
    # Field definitions are the source of truth for registration — must remain.
    assert "timestamp" in schemas.get_schema_definition("payments")
