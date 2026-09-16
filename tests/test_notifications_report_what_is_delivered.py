"""What the gateway says about notifications is what it does with them.

daaef5f set out to make "configured channels actually fire at runtime". It
constructed the NotificationDispatcher, listed its channels at boot
("Notifications ready: telegram, slack") and later handed it the push-token
store — and nothing in the gateway ever called broadcast(). An operator who
configured an alerting channel was told it was ready, and no alert ever left
the process.

Which gateway events should reach which audience is not decided anywhere in the
repo, and broadcast() with no ``channels`` reaches ios_push (every registered
device) and web_chat (the shared events stream), so wiring an event without
that decision would send an operator message to every user. The startup report
is corrected to the truth instead, and tied to the code: the report may say
nothing sends only while no gateway or runtime module calls a notifier's
broadcast().

On the same axis, a configuration that claimed to reach a channel and did not:
the APNs key the deploy mounts (APNS_AUTH_KEY_P8_PATH) was read into
``notifications.channels.ios_push``; the channel reads
``notifications.ios_push``. The mount configured nothing.
"""

from __future__ import annotations

import ast
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, "tests")

from gateway.server import GatewayServer, _apply_env_overrides  # noqa: E402
from runtime.notifications import NotificationDispatcher  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOTHING_SENDS = "nothing in the gateway sends to them"


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


def _mount(tmp_path: Path) -> None:
    p8 = tmp_path / "apns_key.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\nCONTENTS\n-----END PRIVATE KEY-----\n")
    os.environ["APNS_AUTH_KEY_P8_PATH"] = str(p8)
    os.environ["APNS_KEY_ID"] = "K1"
    os.environ["APNS_TEAM_ID"] = "T1"
    os.environ["APNS_BUNDLE_ID"] = "com.opnmatrx.mtrx"


def test_a_mounted_apns_key_configures_the_channel_that_reads_it(clean_apns_env, tmp_path):
    _mount(tmp_path)
    dispatcher = NotificationDispatcher(_apply_env_overrides({}))
    assert dispatcher.get("ios_push").available, "the mounted key never reached the ios_push channel"
    assert "ios_push" in dispatcher.list_enabled_channels()


def test_the_mount_does_not_override_an_explicit_disable(clean_apns_env, tmp_path):
    """Like every other env overlay, the mount supplies credentials; an
    operator's `enabled: false` still wins."""
    _mount(tmp_path)
    cfg = _apply_env_overrides({"notifications": {"ios_push": {"enabled": False}}})
    dispatcher = NotificationDispatcher(cfg)
    assert "ios_push" not in dispatcher.list_enabled_channels()


def _notifier_broadcast_calls() -> list[str]:
    """Every call ``<something named *notifier*>.broadcast(...)`` in the code
    the gateway process runs (gateway/, runtime/ — not the dispatcher itself)."""
    found = []
    for base in ("gateway", "runtime"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if "notifications" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "broadcast"
                        and "notifier" in ast.unparse(node.func.value).lower()):
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def _bridge_notifier_users_imported() -> list[str]:
    """bridge.ApprovalGate and bridge.Deployer do call notifier.broadcast();
    they count only if the gateway process can construct them."""
    hits = []
    for base in ("gateway", "runtime"):
        for path in sorted((ROOT / base).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                if any(n == "bridge" or n.startswith("bridge.") for n in names):
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return hits


def test_the_startup_report_says_whether_anything_sends_to_the_configured_channels(caplog):
    scratch = tempfile.mkdtemp(prefix="the-matrix-notify-")
    config = {**SWEEP_CONFIG, "memory_dir": scratch, "database": {"path": f"{scratch}/n.db"},
              "notifications": {"webhook": {"url": "https://ops.example.invalid/hook"}}}
    with caplog.at_level(logging.INFO, logger="gateway.server"):
        server = GatewayServer(config)
    assert "webhook" in server.notifier.list_enabled_channels()
    report = [r.getMessage() for r in caplog.records if "webhook" in r.getMessage()]
    assert report, "the startup report does not name the configured channel"

    senders = _notifier_broadcast_calls() + _bridge_notifier_users_imported()
    says_nothing_sends = any(NOTHING_SENDS in line for line in report)
    if senders:
        assert not says_nothing_sends, (
            f"the report says nothing sends, but {senders} do — update the report")
    else:
        assert says_nothing_sends, (
            f"no gateway code sends to the notifier, and the report says: {report}")
