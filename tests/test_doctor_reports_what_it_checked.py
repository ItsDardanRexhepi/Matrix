"""`gateway.doctor` is the tool an operator runs INSTEAD of starting the gateway.

Every one of its answers is therefore a claim about a system it is not running,
and four of them were claims it had not checked.

1. `check_paymaster` printed "signer configured (platform key, gas-only)". The
   key it resolves falls back to `blockchain.paymaster_private_key`, and that is
   the key ~20 modules under `runtime/blockchain/` sign and broadcast arbitrary
   value-moving transactions with. "gas-only" describes the CONTRACT's role for
   the key, not the key's scope in this codebase. It also printed READY on a
   `_filled()` check alone — the exact overclaim the module's own RUN-11 note
   introduced CONFIGURED for, and which `check_chain` already honours.

2. `check_push` read a top-level `apns`/`push` config key that NOTHING in the
   repository populates or sends from. The live sender reads
   `notifications.ios_push`. So a deployment with APNs fully configured and
   iOSPushChannel really posting to Apple was told "push fan-out is a no-op
   (never sent)" — and a hand-written top-level `apns` block got READY for a
   subtree no sender reads, which is the same drift pointing the other way.

3. The module's hard-guarantee block named `--write-routes` as "the one
   exception" to never writing a file. `main()`'s parser defines `--config` and
   `--json`; the flag exits 2 as an unrecognised argument.

4. The exit code is the only part of this tool CI reads, and the docstring said
   non-zero "only when a subsystem is HALF-configured". STUB is a fourth status
   and exited 0 — including "morpheus_security is INSTALLED but the live
   backend is noop", which is a misconfiguration by definition, and including a
   production deployment with no enforcement at all, which the check itself
   annotates FATAL. A go-live gate keyed on the exit code passed while
   enforcement was off: the tool meant to catch a misconfiguration agreeing
   with the misconfigured system.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import gateway.doctor as doctor

ROOT = Path(__file__).resolve().parent.parent

SIGNER_KEY = "0x" + "11" * 32

# The subtree the live sender actually reads (runtime/notifications/ios_push.py).
REAL_IOS_PUSH = {
    "notifications": {
        "ios_push": {
            "auth_key_p8": "-----BEGIN PRIVATE KEY-----\nMHc\n-----END PRIVATE KEY-----",
            "key_id": "ABC1234567",
            "team_id": "TEAM123456",
            "bundle_id": "com.themat.rix",
        }
    }
}


# ── 1. the paymaster signer ────────────────────────────────────────────────

def test_the_shared_platform_key_is_not_called_gas_only():
    _, status, detail = doctor.check_paymaster(
        {"blockchain": {"paymaster_private_key": SIGNER_KEY}})
    assert "platform key, gas-only" not in detail, (
        "doctor calls the platform's general signing key gas-only: the same "
        "value signs and broadcasts arbitrary transactions across "
        "runtime/blockchain/")
    assert "GENERAL signing key" in detail, detail
    assert status != doctor.READY, (
        "READY on a _filled() check alone — the RUN-11 overclaim check_chain "
        "already refuses to make")


def test_a_dedicated_signer_key_is_reported_as_the_dedicated_one():
    _, status, detail = doctor.check_paymaster(
        {"paymaster": {"signer_key": SIGNER_KEY}})
    assert status == doctor.CONFIGURED
    assert "paymaster.signer_key" in detail, detail


def test_an_unconfigured_paymaster_is_still_unconfigured():
    assert doctor.check_paymaster({})[1] == doctor.UNCONFIGURED


# ── 2. push ────────────────────────────────────────────────────────────────

def test_doctor_reads_the_subtree_the_sender_reads():
    _, status, detail = doctor.check_push(REAL_IOS_PUSH)
    assert status != doctor.UNCONFIGURED, (
        "APNs is fully configured where the sender reads it, and doctor says "
        f"the push fan-out never sends: {detail}")
    assert "no-op" not in detail and "never sent" not in detail, detail


def test_doctor_agrees_with_the_channel_it_is_reporting_on():
    from runtime.notifications.ios_push import iOSPushChannel

    for cfg in (REAL_IOS_PUSH, {}, {"notifications": {"ios_push": {
            "auth_key_p8": "YOUR_APNS_KEY_P8", "key_id": "YOUR_KEY_ID",
            "team_id": "YOUR_TEAM_ID", "bundle_id": "com.themat.rix"}}}):
        _, status, _ = doctor.check_push(cfg)
        assert (status != doctor.UNCONFIGURED) is iOSPushChannel(cfg).available, (
            "doctor and the sender disagree about whether this config sends")


def test_a_top_level_apns_block_no_sender_reads_is_not_ready():
    _, status, detail = doctor.check_push(
        {"apns": {"key_id": "ABC1234567", "key_path": "/etc/apns.p8"}})
    assert status == doctor.UNCONFIGURED, (
        "a top-level apns block is read by no sender in this repository, and "
        f"doctor reported it configured: {detail}")


# ── 3. the guarantee block ─────────────────────────────────────────────────

def test_every_option_the_module_docstring_names_is_a_real_option():
    """The guarantee block advertised a side effect the tool does not have.

    Any `--flag` the docstring names must either be accepted by the parser or
    be named in the same breath as not existing.
    """
    import re

    usage = subprocess.run(
        [sys.executable, "-m", "gateway.doctor", "--help"],
        cwd=str(ROOT), capture_output=True, text=True,
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
    ).stdout
    real = set(re.findall(r"--[a-z][a-z-]+", usage))
    assert "--config" in real and "--json" in real, usage

    head = doctor.__doc__ or ""
    for match in re.finditer(r"--[a-z][a-z-]+", head):
        flag = match.group(0)
        if flag in real:
            continue
        near = head[match.start():match.start() + 240]
        assert "no such option exists" in near, (
            f"the module docstring names {flag}, which the parser does not "
            f"define:\n{usage}")


# ── 4. the exit code, which is the part CI reads ───────────────────────────

def _stub_installed_but_dead(monkeypatch):
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: object() if name == "morpheus_security" else None)


def test_a_security_backend_that_failed_to_load_is_not_a_consistent_posture(
        monkeypatch, capsys):
    _stub_installed_but_dead(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["doctor", "--config", "does-not-exist.json"])
    rc = doctor.main()
    out = capsys.readouterr().out
    assert rc != 0, (
        "morpheus_security is installed and the live backend is noop — "
        "enforcement is OFF — and doctor exited 0")
    assert "Posture consistent" not in out, out


def test_production_without_enforcement_is_not_a_consistent_posture(
        monkeypatch, capsys):
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    monkeypatch.setenv("MATRIX_ENV", "production")
    monkeypatch.setattr(sys, "argv", ["doctor", "--config", "does-not-exist.json"])
    rc = doctor.main()
    assert rc != 0, (
        "doctor's own check calls this FATAL in production and the tool "
        "exited 0")


def test_the_public_posture_without_morpheus_still_exits_zero(monkeypatch):
    """The direction this must NOT move.

    morpheus_security is a private package; a development or public checkout
    runs OBSERVE by design, and that is the deliberate no-op the exit code is
    entitled to forgive. CI runs `python -m gateway.doctor` with no config.
    """
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    monkeypatch.setattr(sys, "argv", ["doctor", "--config", "does-not-exist.json"])
    assert doctor.main() == 0


def test_the_docstring_describes_the_exit_code_the_code_returns():
    head = doctor.__doc__ or ""
    assert "STUB" in head, (
        "the exit-code paragraph enumerates READY / UNCONFIGURED / "
        "HALF-CONFIGURED and never mentions the fourth status, which is the "
        "one that decides whether enforcement is on")


@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_doctor_still_runs(monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["doctor", "--config", "does-not-exist.json", *flag])
    assert doctor.main() in (0, 1)
