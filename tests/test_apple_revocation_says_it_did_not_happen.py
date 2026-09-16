"""The two-branch behaviour the Apple docstrings describe has one branch.

`gateway/apple_auth.py` opened with: "Revocation on account deletion needs a
client-secret JWT signed with the team's .p8 — only performed when those
credentials are configured; otherwise local data is still deleted and
revocation is skipped with a WARNING."

Only the "otherwise" branch exists. No client-secret JWT is built anywhere in
this tree, `APPLE_REVOKE_URL` had zero callers, and `handle_account_delete`
logs the SKIPPED warning when revocation is UNCONFIGURED and does nothing at
all when it IS configured — it deletes local data and answers 200. Strictly,
"only performed when configured" is vacuously satisfied by never performing it;
the behaviour a reader takes from the sentence does not exist.

The consequence is not cosmetic. Apple's Sign in with Apple account-deletion
requirement (App Store 5.1.1(v)) is unmet, the user's Apple token stays live
after they delete the account, and the operator who filled in team_id, key_id
and private_key_p8 precisely to meet it is told nothing at all — silence being
the shape a working revocation would also have.

`gateway.doctor` repeated the claim as "revocation READY".

Why this is a correction and not a build: Apple's /auth/revoke takes a refresh
or access token, which comes only from exchanging the `authorizationCode` at
/auth/token. The client sends that code (MTRXAPIClient.authenticateWithApple)
and `handle_apple_auth` discards it, so building the revocation true means
exchanging and then STORING a user's Apple refresh token server-side. That is a
new stored secret with its own schema and threat model, not a docstring repair,
and it is owed rather than done here.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import gateway.apple_auth as apple_auth  # noqa: E402
import gateway.doctor as doctor  # noqa: E402
from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

CONFIGURED_APPLE = {
    "auth": {"apple": {
        "bundle_id": "com.themat.rix",
        "team_id": "TEAM123456",
        "key_id": "ABC1234567",
        "private_key_p8": "-----BEGIN PRIVATE KEY-----\nMHc\n-----END PRIVATE KEY-----",
    }}
}


def _server(config_extra: dict) -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="the-matrix-apple-revoke-")
    return GatewayServer({**SWEEP_CONFIG, **config_extra,
                          "memory_dir": scratch, "db_path": f"{scratch}/m.db"})


async def _session(server: GatewayServer, subject: str) -> dict:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(
        token=token, address=subject, issued_at=now, expires_at=now + 3600)
    return {"Authorization": f"Bearer {token}"}


# ── 1. the operator who configured it is told it did not happen ────────────

async def test_a_configured_deployment_is_told_revocation_did_not_run(caplog):
    server = _server(CONFIGURED_APPLE)
    assert apple_auth.apple_revocation_configured(server.config) is True
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, "apple:configured")
        with caplog.at_level(logging.WARNING):
            resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "revocation" in text.lower(), (
        "the credentials for Apple token revocation are configured, no "
        "revocation was performed, and the operator was told nothing — which "
        "is exactly what a working revocation would also look like from "
        "here:\n" + text)
    assert "not implemented" in text.lower(), text


async def test_an_unconfigured_deployment_still_says_so(caplog):
    server = _server({})
    async with TestClient(TestServer(server.create_app())) as client:
        account = await _session(server, "apple:unconfigured")
        with caplog.at_level(logging.WARNING):
            resp = await client.delete("/api/v1/auth/account", headers=account)
        assert resp.status == 200, await resp.text()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "revocation" in text.lower(), text


# ── 2. nothing claims the revocation is ready ──────────────────────────────

def test_doctor_does_not_report_revocation_ready():
    _, _, detail = doctor.check_apple_auth(CONFIGURED_APPLE)
    assert "revocation READY" not in detail, (
        "doctor reports a revocation that no code in this tree performs: " + detail)
    assert "NOT implemented" in detail, detail


def test_the_module_does_not_describe_a_branch_it_does_not_have():
    head = apple_auth.__doc__ or ""
    assert "only performed when those credentials are configured" not in head, head
    assert "not implemented" in head.lower(), head


# ── 3. no dead definition stands in for the missing half ───────────────────

def test_the_revoke_endpoint_constant_is_connected_or_absent():
    """A module-level URL with no caller reads as a capability that exists."""
    import subprocess

    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if not hasattr(apple_auth, "APPLE_REVOKE_URL"):
        return
    hits = subprocess.run(
        ["git", "grep", "-n", "APPLE_REVOKE_URL", "--", "*.py"],
        cwd=str(root), capture_output=True, text=True).stdout.strip().splitlines()
    callers = [h for h in hits if "APPLE_REVOKE_URL =" not in h]
    assert callers, (
        "gateway/apple_auth.py defines APPLE_REVOKE_URL and nothing in the "
        "repository reaches it: the constant is the whole of the revocation")


@pytest.mark.parametrize("cfg,expected", [
    ({}, False),
    (CONFIGURED_APPLE, True),
    ({"auth": {"apple": {"bundle_id": "x", "team_id": "T"}}}, False),
])
def test_the_credential_predicate_still_reads_the_credentials(cfg, expected):
    assert apple_auth.apple_revocation_configured(cfg) is expected
