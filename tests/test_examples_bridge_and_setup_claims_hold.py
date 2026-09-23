"""The examples, the bridge, the setup wizard and the scripts, held to the code.

Built true:
  * a marketplace purchase says what it is — a record, `recorded_unsettled`,
    nothing moved — so it is not attested or announced as a purchase;
  * the bridge manifest refuses to record an unapproved component as
    `attested`, which it counts as deployed, and refuses an unknown status;
  * the bridge deployer no longer reports `attested: True` over a locally
    computed sha256 it presented as an EAS UID;
  * the hive-mind's shared context subscribes under its lock and calls its
    subscribers outside it;
  * the setup wizard's channel test never raises, including from the
    dispatcher's constructor and with an event loop already running.

Corrected: the example narratives (an insurance payout, an atomic escrow, an
attestation for every action — none of which happen), the platform-wide "users
never pay gas", the approval gate's "AND a fresh OTP", the deployer's third
guard, the iOS packager's "deployed", the CLI's "only errors", the directed
event bus, the route generator's "read-only", the EAS schema UIDs' "cannot be
guessed", the wizard's "only writer" and "verifies by sending a test message".
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _prose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text or ""))


def _run(path: Path, monkeypatch, capsys) -> str:
    from tests.test_examples_are_honest import _run_example

    _run_example(path, monkeypatch)
    return capsys.readouterr().out


# ── the examples, run ──────────────────────────────────────────────────────

def test_the_insurance_example_prints_no_payout(monkeypatch, capsys):
    out = _run(ROOT / "examples" / "04_parametric_insurance.py", monkeypatch, capsys)
    for phrase in ("Payout to farmer", "Net payout", "automatic payout to policyholder",
                   "Claim paid: True", "Oracle verified: yes"):
        assert phrase not in out, f"the example still prints {phrase!r}"


def test_the_marketplace_example_narrates_no_escrow(monkeypatch, capsys):
    out = _run(ROOT / "examples" / "05_marketplace_flow.py", monkeypatch, capsys)
    for phrase in ("Released atomically", "Buyer now owns template",
                   "atomic escrow", "Purchase completed!", "payment and transfer in one tx"):
        assert phrase not in out, f"the example still prints {phrase!r}"
    assert "not performed" in out


def test_the_attestation_example_does_not_promise_every_action():
    src = (ROOT / "examples" / "06_eas_attestation_chain.py").read_text()
    assert "Every Action Creates a Verifiable Record" not in src
    assert "every state-modifying capability is attested on-chain automatically" not in src
    readmes = (ROOT / "README.md").read_text() + (ROOT / "examples" / "README.md").read_text()
    assert "Every action creates a verifiable on-chain attestation record" not in readmes
    assert "Every state-modifying action in The Matrix creates an on-chain EAS" not in readmes
    assert "Atomic escrow" not in readmes and "atomic escrow" not in readmes


# ── the marketplace service ────────────────────────────────────────────────

async def test_a_marketplace_purchase_is_a_record_that_moved_nothing():
    from runtime.blockchain.services.marketplace.service import MarketplaceService
    from runtime.blockchain.services.service_dispatcher import _record_verdict, RECORD_REFUSED

    svc = MarketplaceService({})
    listing = await svc.list_item("0xSELLER", "digital", {"title": "t"}, 1.0)
    sale = await svc.buy_item(listing["listing_id"], "0xBUYER")
    assert sale["status"] == "recorded_unsettled"
    assert sale["settled"] is False and sale["value_moved"] is False
    assert _record_verdict(sale) == RECORD_REFUSED, (
        "a recorded sale that moved nothing would be attested as a purchase")


# ── the bridge ─────────────────────────────────────────────────────────────

def _manifest(tmp_path):
    from bridge.manifest import ManifestManager

    return ManifestManager(str(tmp_path / "manifest.json"))


def test_an_unapproved_component_cannot_be_recorded_as_attested(tmp_path):
    from bridge.manifest import ManifestEntry

    m = _manifest(tmp_path)
    m.entries.append(ManifestEntry(component_name="c", version="1", content_hash="h"))
    assert m.update_deployment("c", "attested", attestation_uid="0x1") is None
    assert m.get_summary()["deployed"] == 0
    assert m.update_deployment("c", "installed-somehow") is None


async def test_the_deployer_does_not_report_an_attestation_it_did_not_make(tmp_path):
    from bridge.approval_gate import ApprovalDecision, ApprovalStatus
    from bridge.deployer import ComponentDeployer
    from bridge.exporter import ExportBundle
    from bridge.sanitizer import SanitizationResult

    bundle = ExportBundle(component_name="widget", version="1.0",
                          source_files={"a.py": "x = 1\n"}, metadata={},
                          content_hash="abc")
    clean = SanitizationResult(component_name="widget", is_clean=True, violations=[])
    approved = ApprovalDecision(component_name="widget", version="1.0",
                                status=ApprovalStatus.APPROVED, request_id="r")
    result = await ComponentDeployer(runtime_dir=str(tmp_path)).deploy(
        bundle, clean, approved)
    assert result.success is True
    assert result.attested is False and result.attestation_uid == "", (
        "a sha256 computed here was reported as an EAS attestation")


def test_the_bridge_docstrings_say_what_is_checked():
    import bridge.approval_gate as gate
    import bridge.deployer as deployer
    from bridge.mobile_converter import MobileConverter

    assert "AND a fresh OTP. Rejecting" not in _prose(gate.__doc__)
    doc = _prose(deployer.__doc__)
    assert "3. A valid manifest entry" not in doc
    assert "records an EAS attestation on-chain" not in doc
    assert "Will only proceed if all required components are deployed" not in _prose(
        MobileConverter.package_all.__doc__)


# ── hive-mind ──────────────────────────────────────────────────────────────

def test_a_subscriber_may_read_the_context_it_is_notified_from():
    """A callback that calls get() used to run while set() held the lock in
    one version of this class; the notify runs outside it now, on a snapshot."""
    from hivemind.orchestrator import SharedContextLayer

    ctx = SharedContextLayer()
    seen = []
    ctx.subscribe("k", lambda key, value: seen.append(ctx.get(key)))
    ctx.set("k", 1)
    assert seen == [1]


def test_concurrent_subscriptions_are_not_lost():
    import threading

    from hivemind.orchestrator import SharedContextLayer

    ctx = SharedContextLayer()
    calls = []
    threads = [threading.Thread(target=ctx.subscribe,
                                args=("k", lambda k, v, i=i: calls.append(i)))
               for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ctx.set("k", 1)
    assert len(calls) == 50


def test_the_event_bus_docstring_matches_directed_delivery():
    from hivemind.events import EventBus

    assert "only handlers for target_agent + type fire" not in _prose(EventBus.__doc__)


# ── the setup wizard ───────────────────────────────────────────────────────

def test_the_channel_test_never_raises_from_the_dispatchers_constructor(monkeypatch):
    import runtime.notifications as notifications
    from setup import _shared

    class _Boom:
        def __init__(self, config):
            raise RuntimeError("bad notifications config")

    monkeypatch.setattr(notifications, "NotificationDispatcher", _Boom)
    out = _shared.test_channel_via_dispatcher({}, "discord")
    assert out["status"] == "error"


async def test_the_channel_test_never_raises_inside_a_running_loop(monkeypatch):
    import runtime.notifications as notifications
    from setup import _shared

    class _Stub:
        def __init__(self, config):
            pass

        async def test_channel(self, name):
            return {"status": "ok", "channel": name}

    monkeypatch.setattr(notifications, "NotificationDispatcher", _Stub)
    out = _shared.test_channel_via_dispatcher({}, "discord")
    assert out == {"status": "ok", "channel": "discord"}


def test_the_wizard_docstrings_say_what_the_wizard_does():
    import setup as setup_pkg

    assert "verifies the channel by sending a test message" not in _prose(setup_pkg.__doc__)
    wizard = (ROOT / "setup.py").read_text()
    assert "The ONLY writer in the wizard" not in wizard


# ── scripts, the CLI, the SDK, the gas sentence ────────────────────────────

def test_the_scripts_and_cli_say_what_they_do():
    gen = (ROOT / "scripts" / "generate_route_table.py").read_text()
    assert "Read-only and import-free" not in gen
    eas = _prose((ROOT / "scripts" / "register_eas_schemas.py").read_text())
    assert "They cannot be guessed or reused across chains" not in eas
    cli = (ROOT / "cli" / "gateway.py").read_text()
    assert "forward only errors to terminal" not in cli


def test_no_platform_wide_users_never_pay_gas():
    offenders = []
    for top in ("runtime", "gateway", "sdk", "docs", "examples"):
        for path in (ROOT / top).rglob("*"):
            if path.suffix not in (".py", ".md") or not path.is_file():
                continue
            for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if re.search(r"users never pay|Users never pay", line):
                    offenders.append(f"{path.relative_to(ROOT)}:{i}")
    assert not offenders, (
        "a transaction prepared for the user's own wallet is paid by that "
        "wallet; these still say users never pay:\n  " + "\n  ".join(offenders))
