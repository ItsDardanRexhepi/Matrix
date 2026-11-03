"""A badge names the source it was audited on, an address that is an address,
and a renewal of the same source.

THE DEFECTS (pre-existing on The Matrix ``main``). A badge was issued on the
platform's own audit of the submitted source, but its record could not say
WHICH source: the stored ``audit_report_hash`` covered the report (findings,
counts, the time), so two different sources with the same findings left the
same record, and nothing tied the badge to what was audited. The address was
whatever the request wrote, an empty string included. ``renew_badge`` revived a
revoked badge on any clean source, audited it under the name ``unknown`` and
accepted a different contract than the one the badge was issued on. And
``POST /badge/issue`` took a body carrying its own ``audit_report``, ignored it
and issued a badge anyway, with nothing in the answer to say so.

Now the report a badge rests on carries ``source_sha256``, the digest of the
exact source audited, and the badge stores it beside the report hash; the
address must be a 20-byte hex address; a renewal re-audits the badge's own
source under its own name and refuses a revoked badge; and a body that brings
an ``audit_report`` is answered 400. What the badge still does not check, and
says, is that the contract deployed at the address was compiled from that
source.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_badges import CLEAN_SOURCE, FakeDB  # noqa: E402

from runtime.badges.badge_manager import BadgeManager  # noqa: E402

ADDRESS = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20


@pytest.fixture
def manager():
    mgr = BadgeManager(FakeDB())
    asyncio.run(mgr.initialize())
    return mgr


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize("address", ["", "   ", "0xREN2", "0x555", "not-an-address", "0x" + "g" * 40])
async def test_a_badge_is_issued_only_for_an_address(manager, address):
    """[control] An empty or malformed address was recorded as written."""
    with pytest.raises(ValueError, match="address"):
        await manager.issue_badge(address, "Vault", CLEAN_SOURCE, "a@x.com")


async def test_the_record_names_the_source_that_was_audited(manager, monkeypatch):
    """[control] Two sources with the same findings left the same record."""
    monkeypatch.setattr(time, "time", lambda: 1_800_000_000.0)
    renamed = CLEAN_SOURCE.replace("TestVault", "OtherVault") + "\n// another source\n"
    one = await manager.issue_badge(ADDRESS, "Vault", CLEAN_SOURCE, "a@x.com")
    two = await manager.issue_badge(OTHER, "Vault", renamed, "a@x.com")
    assert one["audit_report"]["source_sha256"] == _sha(CLEAN_SOURCE)
    assert two["audit_report"]["source_sha256"] == _sha(renamed)
    assert one["audit_report_hash"] != two["audit_report_hash"]
    for issued, source in ((one, CLEAN_SOURCE), (two, renamed)):
        assert issued["source_sha256"] == _sha(source)
        seen = await manager.verify_badge(issued["badge_id"])
        assert seen["source_sha256"] == _sha(source)
        listed = {b["badge_id"]: b for b in await manager.list_badges()}
        assert listed[issued["badge_id"]]["source_sha256"] == _sha(source)


async def test_a_revoked_badge_is_not_renewed(manager):
    """[control] Renewal returned a revoked badge to valid."""
    issued = await manager.issue_badge(ADDRESS, "Vault", CLEAN_SOURCE, "a@x.com")
    await manager.revoke_badge(issued["badge_id"], "contract exploited")
    with pytest.raises(ValueError, match="revoked"):
        await manager.renew_badge(issued["badge_id"], CLEAN_SOURCE)
    assert (await manager.verify_badge(issued["badge_id"]))["status"] == "revoked"


async def test_a_renewal_re_audits_the_badge_s_own_source_under_its_name(manager):
    """[control] Any clean source renewed any badge, audited as 'unknown'."""
    issued = await manager.issue_badge(ADDRESS, "Vault", CLEAN_SOURCE, "a@x.com")
    other = CLEAN_SOURCE.replace("TestVault", "Elsewhere")
    with pytest.raises(ValueError, match="source"):
        await manager.renew_badge(issued["badge_id"], other)
    renewed = await manager.renew_badge(issued["badge_id"], CLEAN_SOURCE)
    assert renewed["audit_report"]["contract_name"] == "Vault"
    assert renewed["source_sha256"] == _sha(CLEAN_SOURCE)
    assert renewed["renewal_count"] == 1


async def test_a_badge_without_a_recorded_source_is_not_renewed(manager):
    """[guard] A row from before the source was recorded has nothing to renew against."""
    issued = await manager.issue_badge(ADDRESS, "Vault", CLEAN_SOURCE, "a@x.com")
    await manager.db.execute("UPDATE security_badges SET source_sha256 = NULL WHERE badge_id = ?",
                             (issued["badge_id"],))
    with pytest.raises(ValueError, match="source"):
        await manager.renew_badge(issued["badge_id"], CLEAN_SOURCE)


async def test_an_existing_table_gains_the_column(manager):
    """[guard] A database made before the column existed is migrated on open."""
    db = FakeDB()
    await db.execute("""CREATE TABLE security_badges (
        badge_id TEXT PRIMARY KEY, contract_address TEXT NOT NULL, contract_name TEXT NOT NULL,
        audit_report_hash TEXT, eas_uid TEXT, issued_at REAL NOT NULL, expires_at REAL NOT NULL,
        renewal_count INTEGER DEFAULT 0, status TEXT DEFAULT 'valid', contact_email TEXT,
        project_url TEXT)""")
    await db.execute("INSERT INTO security_badges (badge_id, contract_address, contract_name, "
                     "issued_at, expires_at) VALUES ('GLASSWING-2026-0001', ?, 'Old', 1, 2)", (ADDRESS,))
    mgr = BadgeManager(db)
    await mgr.initialize()
    await mgr.initialize()
    old = await mgr.verify_badge("GLASSWING-2026-0001")
    assert old["source_sha256"] is None


async def test_the_issue_route_refuses_a_body_that_brings_its_own_report(tmp_path):
    """[control] The route ignored the report and issued anyway; the guard:
    a body with the source and an address is issued, and says on what."""
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    server = GatewayServer({"memory_dir": str(tmp_path / "m"),
                            "database": {"path": str(tmp_path / "s.db")},
                            "gateway": {"api_key": "k"}})
    auth = {"Authorization": "Bearer k"}
    async with TestClient(TestServer(server.create_app())) as client:
        body = {"contract_address": ADDRESS, "contract_name": "Vault",
                "source_code": CLEAN_SOURCE, "contact_email": "a@x.com"}
        resp = await client.post("/badge/issue", json={**body, "audit_report": {"status": "passed"}},
                                 headers=auth)
        assert resp.status == 400, (resp.status, await resp.text())
        resp = await client.post("/badge/issue", json=body, headers=auth)
        assert resp.status == 200, (resp.status, await resp.text())
        issued = await resp.json()
        assert issued["source_sha256"] == _sha(CLEAN_SOURCE)
        assert issued["audit_report"]["verdict"] == "passed"
