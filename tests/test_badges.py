"""Tests for the Glasswing Security Badge system."""

import asyncio
import hashlib
import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from runtime.badges.badge_manager import BadgeManager


# ── Helpers ──────────────────────────────────────────────────────────


class FakeDB:
    """Minimal async SQLite wrapper matching Database interface."""

    def __init__(self, db_path=":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=(), commit=True):
        self.conn.execute(sql, params)
        if commit:
            self.conn.commit()

    async def executemany(self, sql, seq):
        self.conn.executemany(sql, seq)
        self.conn.commit()

    async def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


@pytest.fixture
def fake_db():
    """Provide a fresh in-memory SQLite database."""
    return FakeDB()


@pytest.fixture
def badge_manager(fake_db):
    """Provide an initialised BadgeManager."""
    mgr = BadgeManager(fake_db)
    asyncio.run(mgr.initialize())
    return mgr


# D-045 / §CD: the manager no longer accepts a verdict. These fixtures are
# SOURCE, and the audit that decides whether a badge is issued is the one the
# platform runs over them here.

CLEAN_SOURCE = """
pragma solidity 0.8.20;

contract TestVault {
    mapping(address => uint256) private balances;
    address private immutable owner;

    constructor() { owner = msg.sender; }

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function balanceOf(address who) external view returns (uint256) {
        return balances[who];
    }

    function withdraw(uint256 amount) external {
        require(msg.sender == owner, "not owner");
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount;
        payable(msg.sender).transfer(amount);
    }
}
"""

CRITICAL_SOURCE = """
pragma solidity 0.8.20;

contract BrokenVault {
    mapping(address => uint256) public balances;

    function withdraw() external {
        (bool ok, ) = msg.sender.call{value: balances[msg.sender]}("");
        require(ok, "send failed");
        balances[msg.sender] = 0;
    }

    function kill() external {
        selfdestruct(payable(msg.sender));
    }
}
"""

# No executable body at all — the §CT case: zero findings because there was
# nothing to examine, which must never read as a pass.
UNAUDITABLE_SOURCE = """
pragma solidity 0.8.20;
interface ITestVault {
    function deposit() external payable;
}
"""


def _platform_report(mgr, source=CLEAN_SOURCE, name="TestVault"):
    """The report the manager itself will produce and hash for this source."""
    return mgr._platform_audit(source, name)


# ── Badge Issuance Tests ────────────────────────────────────────────


class TestBadgeIssuance:
    """Tests for issuing new Glasswing badges."""

    @pytest.mark.asyncio
    async def test_issue_badge_returns_correct_id_format(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0xAbC123", "TestVault", report, "dev@example.com"
        )
        year = time.strftime("%Y")
        assert result["badge_id"] == f"GLASSWING-{year}-0001"

    @pytest.mark.asyncio
    async def test_issue_badge_sequential_ids(self, badge_manager):
        report = CLEAN_SOURCE
        r1 = await badge_manager.issue_badge(
            "0xABC1", "Vault1", report, "a@x.com"
        )
        r2 = await badge_manager.issue_badge(
            "0xABC2", "Vault2", report, "b@x.com"
        )
        r3 = await badge_manager.issue_badge(
            "0xABC3", "Vault3", report, "c@x.com"
        )
        year = time.strftime("%Y")
        assert r1["badge_id"] == f"GLASSWING-{year}-0001"
        assert r2["badge_id"] == f"GLASSWING-{year}-0002"
        assert r3["badge_id"] == f"GLASSWING-{year}-0003"

    @pytest.mark.asyncio
    async def test_issue_badge_stores_all_fields(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0xDeAdBeEf",
            "SecureToken",
            report,
            "team@project.io",
            project_url="https://project.io",
        )
        assert result["contract_address"] == "0xDeAdBeEf"
        assert result["contract_name"] == "SecureToken"
        assert result["contact_email"] == "team@project.io"
        assert result["project_url"] == "https://project.io"
        assert result["status"] == "valid"
        assert result["renewal_count"] == 0

    @pytest.mark.asyncio
    async def test_issue_badge_computes_report_hash(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0x111", "HashTest", report, "h@x.com"
        )
        # The hash is over the report the PLATFORM produced — the thing that is
        # supposed to be the record of what was audited. Before D-045 it was a
        # hash of whatever dict the caller sent.
        expected_hash = hashlib.sha256(
            json.dumps(result["audit_report"], sort_keys=True).encode()
        ).hexdigest()
        assert result["audit_report_hash"] == expected_hash
        assert result["audit_report"]["audited_by"] == "matrix-glasswing"

    @pytest.mark.asyncio
    async def test_issue_badge_one_year_expiry(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0x222", "ExpiryTest", report, "e@x.com"
        )
        expected_expiry = result["issued_at"] + (365 * 86400)
        assert abs(result["expires_at"] - expected_expiry) < 1.0

    @pytest.mark.asyncio
    async def test_issue_badge_returns_verification_url(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0x333", "UrlTest", report, "u@x.com"
        )
        assert result["badge_id"] in result["verification_url"]
        assert result["verification_url"].startswith("https://")

    @pytest.mark.asyncio
    async def test_issue_badge_returns_embed_code(self, badge_manager):
        report = CLEAN_SOURCE
        result = await badge_manager.issue_badge(
            "0x444", "EmbedTest", report, "e@x.com"
        )
        assert "<script" in result["embed_code"]
        assert result["badge_id"] in result["embed_code"]
        assert "widget.js" in result["embed_code"]

    @pytest.mark.asyncio
    async def test_a_caller_cannot_supply_the_verdict(self, badge_manager):
        """The defect, stated as a property: there is no parameter through
        which a conclusion can be passed in.

        Before D-045 the only check was that the caller had written
        status:"passed" in their own request body, and that same dict was then
        hashed as the record of what had been audited.
        """
        import inspect
        for name in ("issue_badge", "renew_badge"):
            params = inspect.signature(getattr(badge_manager, name)).parameters
            assert "audit_report" not in params and "new_audit_report" not in params, (
                f"{name} takes a caller-supplied verdict again")
            assert "source_code" in params, f"{name} does not audit its own source"

    @pytest.mark.asyncio
    async def test_no_source_is_refused(self, badge_manager):
        with pytest.raises(ValueError, match="source is required"):
            await badge_manager.issue_badge("0x555", "NoSource", "", "p@x.com")


# ── Failing Audit Rejection Tests ───────────────────────────────────


class TestFailingAuditRejection:
    """Tests that non-passing audits cannot receive badges."""

    @pytest.mark.asyncio
    async def test_a_critical_finding_refuses_the_badge(self, badge_manager):
        with pytest.raises(ValueError, match="did not pass"):
            await badge_manager.issue_badge(
                "0xBAD", "BadContract", CRITICAL_SOURCE, "bad@x.com"
            )

    @pytest.mark.asyncio
    async def test_source_with_no_executable_body_refuses_the_badge(self, badge_manager):
        """§CT — zero findings because there was nothing to examine must never
        be issued as a badge. This is the state the auditor used to summarise
        as "No vulnerabilities detected. Contract passed all security checks."
        """
        with pytest.raises(ValueError, match="no executable function body"):
            await badge_manager.issue_badge(
                "0xBAD2", "JustAnInterface", UNAUDITABLE_SOURCE, "n@x.com"
            )

    @pytest.mark.asyncio
    async def test_renewal_refuses_a_source_that_now_fails(self, badge_manager):
        """Renewal is where a stale badge is supposed to be caught."""
        issued = await badge_manager.issue_badge(
            "0xREN2", "WasClean", CLEAN_SOURCE, "r@x.com")
        with pytest.raises(ValueError, match="did not pass"):
            await badge_manager.renew_badge(issued["badge_id"], CRITICAL_SOURCE)


# ── Badge Verification Tests ────────────────────────────────────────


class TestBadgeVerification:
    """Tests for verifying badge status."""

    @pytest.mark.asyncio
    async def test_verify_valid_badge(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xAAA", "VerifyMe", report, "v@x.com"
        )
        result = await badge_manager.verify_badge(issued["badge_id"])
        assert result["status"] == "valid"
        assert result["verified"] is True
        assert result["time_until_expiry"] > 0
        assert result["contract_name"] == "VerifyMe"
        assert result["contract_address"] == "0xAAA"

    @pytest.mark.asyncio
    async def test_verify_returns_all_fields(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xBBB", "FieldCheck", report, "f@x.com", "https://fc.io"
        )
        result = await badge_manager.verify_badge(issued["badge_id"])
        assert result["badge_id"] == issued["badge_id"]
        assert result["audit_report_hash"] == issued["audit_report_hash"]
        assert result["contact_email"] == "f@x.com"
        assert result["project_url"] == "https://fc.io"
        assert "verification_url" in result

    @pytest.mark.asyncio
    async def test_verify_nonexistent_badge_raises(self, badge_manager):
        with pytest.raises(ValueError, match="not found"):
            await badge_manager.verify_badge("GLASSWING-9999-0001")


# ── Badge Expiry Tests ──────────────────────────────────────────────


class TestBadgeExpiry:
    """Tests for badge expiry detection."""

    @pytest.mark.asyncio
    async def test_expired_badge_detected(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xEXP", "ExpiredBadge", report, "exp@x.com"
        )
        # Manually set expires_at to the past
        await badge_manager.db.execute(
            "UPDATE security_badges SET expires_at = ? WHERE badge_id = ?",
            (time.time() - 100, issued["badge_id"]),
            commit=True,
        )
        result = await badge_manager.verify_badge(issued["badge_id"])
        assert result["status"] == "expired"
        assert result["verified"] is False
        assert result["time_until_expiry"] == 0.0


# ── Badge Revocation Tests ──────────────────────────────────────────


class TestBadgeRevocation:
    """Tests for badge revocation."""

    @pytest.mark.asyncio
    async def test_revoke_badge(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xREV", "RevokeMe", report, "r@x.com"
        )
        result = await badge_manager.revoke_badge(
            issued["badge_id"], "Security vulnerability discovered"
        )
        assert result["status"] == "revoked"
        assert result["reason"] == "Security vulnerability discovered"

    @pytest.mark.asyncio
    async def test_revoked_badge_shows_revoked_on_verify(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xREV2", "RevVerify", report, "rv@x.com"
        )
        await badge_manager.revoke_badge(issued["badge_id"], "Critical bug found")
        result = await badge_manager.verify_badge(issued["badge_id"])
        assert result["status"] == "revoked"
        assert result["verified"] is False

    @pytest.mark.asyncio
    async def test_revoke_preserves_record(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xREV3", "PreserveMe", report, "pm@x.com"
        )
        await badge_manager.revoke_badge(issued["badge_id"], "Policy violation")
        # Record should still be accessible
        result = await badge_manager.verify_badge(issued["badge_id"])
        assert result["contract_name"] == "PreserveMe"
        assert result["contract_address"] == "0xREV3"

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_raises(self, badge_manager):
        with pytest.raises(ValueError, match="not found"):
            await badge_manager.revoke_badge("GLASSWING-0000-9999", "no reason")


# ── Badge Renewal Tests ─────────────────────────────────────────────


class TestBadgeRenewal:
    """Tests for badge renewal."""

    @pytest.mark.asyncio
    async def test_renew_badge_extends_expiry(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xREN", "RenewMe", report, "ren@x.com"
        )
        renewed = await badge_manager.renew_badge(
            issued["badge_id"], CLEAN_SOURCE
        )
        assert renewed["expires_at"] > issued["expires_at"]
        expected_expiry = renewed["expires_at"]
        # Should be roughly now + 365 days
        assert abs(expected_expiry - (time.time() + 365 * 86400)) < 2.0

    @pytest.mark.asyncio
    async def test_renew_increments_renewal_count(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xCNT", "CountTest", report, "cnt@x.com"
        )
        assert issued["renewal_count"] == 0

        r1 = await badge_manager.renew_badge(
            issued["badge_id"], CLEAN_SOURCE
        )
        assert r1["renewal_count"] == 1

        r2 = await badge_manager.renew_badge(
            issued["badge_id"], CLEAN_SOURCE
        )
        assert r2["renewal_count"] == 2

    @pytest.mark.asyncio
    async def test_renew_updates_audit_hash(self, badge_manager):
        issued = await badge_manager.issue_badge(
            "0xHSH", "HashUpdate", CLEAN_SOURCE, "hu@x.com"
        )
        renewed = await badge_manager.renew_badge(issued["badge_id"], CLEAN_SOURCE)
        expected_hash = hashlib.sha256(
            json.dumps(renewed["audit_report"], sort_keys=True).encode()
        ).hexdigest()
        assert renewed["audit_report_hash"] == expected_hash
        # Same source, different audit: the timestamp of WHEN it was audited is
        # part of the record, which is what makes a renewal a fresh claim.
        assert renewed["audit_report_hash"] != issued["audit_report_hash"]

    @pytest.mark.asyncio
    async def test_renew_sets_status_to_valid(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xSTAT", "StatusReset", report, "sr@x.com"
        )
        # Expire it first
        await badge_manager.db.execute(
            "UPDATE security_badges SET expires_at = ? WHERE badge_id = ?",
            (time.time() - 100, issued["badge_id"]),
            commit=True,
        )
        # Renew should set it back to valid
        renewed = await badge_manager.renew_badge(
            issued["badge_id"], CLEAN_SOURCE
        )
        assert renewed["status"] == "valid"

    @pytest.mark.asyncio
    async def test_renew_with_failing_audit_raises(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xFAIL", "FailRenew", report, "fr@x.com"
        )
        with pytest.raises(ValueError, match="did not pass"):
            await badge_manager.renew_badge(
                issued["badge_id"], CRITICAL_SOURCE
            )

    @pytest.mark.asyncio
    async def test_renew_nonexistent_raises(self, badge_manager):
        with pytest.raises(ValueError, match="not found"):
            await badge_manager.renew_badge(
                "GLASSWING-0000-9999", CLEAN_SOURCE
            )


# ── Badge Listing Tests ─────────────────────────────────────────────


class TestBadgeListing:
    """Tests for listing badges."""

    @pytest.mark.asyncio
    async def test_list_valid_badges(self, badge_manager):
        report = CLEAN_SOURCE
        await badge_manager.issue_badge("0xL1", "Listed1", report, "l1@x.com")
        await badge_manager.issue_badge("0xL2", "Listed2", report, "l2@x.com")
        badges = await badge_manager.list_badges(status="valid")
        assert len(badges) == 2
        names = {b["contract_name"] for b in badges}
        assert names == {"Listed1", "Listed2"}

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty(self, badge_manager):
        badges = await badge_manager.list_badges(status="valid")
        assert badges == []

    @pytest.mark.asyncio
    async def test_list_revoked_badges(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xLR", "RevokedOne", report, "lr@x.com"
        )
        await badge_manager.revoke_badge(issued["badge_id"], "testing")
        valid = await badge_manager.list_badges(status="valid")
        revoked = await badge_manager.list_badges(status="revoked")
        assert len(valid) == 0
        assert len(revoked) == 1
        assert revoked[0]["contract_name"] == "RevokedOne"

    @pytest.mark.asyncio
    async def test_list_badges_includes_verification_url(self, badge_manager):
        report = CLEAN_SOURCE
        await badge_manager.issue_badge("0xLU", "UrlBadge", report, "lu@x.com")
        badges = await badge_manager.list_badges()
        assert len(badges) == 1
        assert "verification_url" in badges[0]
        assert badges[0]["badge_id"] in badges[0]["verification_url"]


# ── Embed Code Tests ────────────────────────────────────────────────


class TestEmbedCode:
    """Tests for embed code generation."""

    @pytest.mark.asyncio
    async def test_get_embed_code(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xEMB", "EmbedBadge", report, "emb@x.com"
        )
        code = await badge_manager.get_badge_embed_code(issued["badge_id"])
        assert "<script" in code
        assert issued["badge_id"] in code
        assert "widget.js" in code
        assert "data-badge" in code

    @pytest.mark.asyncio
    async def test_embed_code_matches_issue_response(self, badge_manager):
        report = CLEAN_SOURCE
        issued = await badge_manager.issue_badge(
            "0xMATCH", "MatchEmbed", report, "m@x.com"
        )
        code = await badge_manager.get_badge_embed_code(issued["badge_id"])
        assert code == issued["embed_code"]

    @pytest.mark.asyncio
    async def test_embed_code_nonexistent_raises(self, badge_manager):
        with pytest.raises(ValueError, match="not found"):
            await badge_manager.get_badge_embed_code("GLASSWING-0000-0000")
