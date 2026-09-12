"""The plugin marketplace installs nothing, and nothing public says it does.

After the commission fix the copy said "Free plugins install today" (README,
docs/PLUGIN_DEVELOPMENT.md, the marketplace page, course-01 twice, the package
docstrings), the page told visitors "Installing is an authenticated call: POST
/marketplace/plugins/{plugin_id}/purchase", and course-01 said the marketplace
"handles distribution and installation of free plugins". Measured:

  * `PluginMarketplace.purchase` on each seeded free listing returned
    `{"status": "already_purchased"}`. `has_purchased` counts every free listing
    as owned, so the free "instant purchase" branch after it could not run, and
    no code in the marketplace fetches, writes or loads plugin code.
    runtime/plugins/loader.py scans `plugins/installed/`, which nothing in the
    marketplace touches.
  * two of the three seeded listings (a portfolio tracker and gas price alerts)
    had no implementation anywhere in the tree, and the page rendered them as
    plugins on the gateway.

The properties, each measured rather than read from the copy:
  1. a purchase of a free listing reports `installed: False`, records nothing,
     and creates nothing under `plugins/installed/`;
  2. every seeded example listing names a plugin class that exists in
     runtime/plugins/;
  3. with (1) measured, no tracked text outside tests and the changelog says
     the marketplace installs, distributes or sells plugins, or that a free
     plugin installs. Wrapped lines are joined before matching.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


async def _free_purchases(tmp_path) -> tuple[bool, list[dict]]:
    """Buy every seeded free listing from inside an empty directory, then ask
    the plugin loader what it can find there. Measured on the filesystem and
    the loader, not on any field the purchase response writes about itself."""
    from runtime.marketplace.plugin_store import PluginMarketplace
    from runtime.plugins.loader import PluginLoader

    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        market = PluginMarketplace(config={})
        await market.initialize()
        free = [pid for pid, l in market.listings.items() if l.price_usd <= 0]
        assert free, "no free listing seeded; re-derive this check"
        results = [await market.purchase("0xbuyer", pid) for pid in free]
        discovered = await PluginLoader().discover()
        nothing = (not discovered and not (tmp_path / "plugins").exists()
                   and not market.purchases)
        return nothing, results
    finally:
        os.chdir(old)


async def _free_purchase_installs_nothing(tmp_path) -> bool:
    return (await _free_purchases(tmp_path))[0]


async def test_a_free_listing_purchase_installs_and_records_nothing(tmp_path):
    nothing, results = await _free_purchases(tmp_path)
    assert nothing, "a free purchase installed or recorded something"
    # and the response says so, rather than implying an install
    for result in results:
        assert result.get("installed") is False, result
        assert result.get("status") != "ok", result


def _plugin_names_in_tree() -> set[str]:
    import runtime.plugins as pkg
    from runtime.plugins.base import OpenMatrixPlugin

    names = set()
    for info in pkgutil.iter_modules(pkg.__path__):
        module = importlib.import_module(f"runtime.plugins.{info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, OpenMatrixPlugin) and obj is not OpenMatrixPlugin \
                    and not inspect.isabstract(obj):
                names.add(_norm(obj.name.fget(obj.__new__(obj))))
    return names


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("plugin", ""))


def test_every_seeded_example_listing_names_a_plugin_in_this_tree():
    from runtime.marketplace.plugin_store import EXAMPLE_PLUGINS

    implemented = _plugin_names_in_tree()
    assert "helloworld" in implemented  # the matcher sees the one that exists
    missing = [p["name"] for p in EXAMPLE_PLUGINS if _norm(p["name"]) not in implemented]
    assert not missing, f"seeded listings with no plugin in runtime/plugins/: {missing}"


_INSTALL_CLAIMS = [
    r"free plugins? (?:install|are installed)",
    r"installs? free (?:ones|plugins?)",
    r"install(?:ation|ing)? (?:of )?free plugins?",
    r"installing is an authenticated call",
    r"purchase or install",
    r"(?:want|get) (?:it|them) installed",
    r"sell plugins",
    r"marketplace handles (?:the )?(?:distribution|installation)",
    r"publish them to the marketplace",
    r"once approved, your plugin",
    r"submit(?:s|ted)? a (?:new )?plugin (?:listing )?for review",
    r"plugin listing for review",
]


def test_the_install_claim_scan_catches_the_old_copy():
    old = ("Build plugins for 0pnMatrx. Free plugins install today; paid plugin\n"
           "sales are not live yet. The 0pnMatrx plugin marketplace handles "
           "distribution and\ninstallation of free plugins.")
    flat = re.sub(r"\s+", " ", old).lower()
    assert sum(bool(re.search(p, flat)) for p in _INSTALL_CLAIMS) >= 2


async def test_no_tracked_text_says_the_marketplace_installs_plugins(tmp_path):
    if not await _free_purchase_installs_nothing(tmp_path):
        return  # the marketplace installs something; the claim is not contradicted
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel == "CHANGELOG.md" or not (ROOT / rel).is_file():
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        flat = re.sub(r"\s*\n\s*(?:#\s*|//\s*|\*\s*)?", " ", text).lower()
        flat = re.sub(r"[ \t]+", " ", flat)
        for pattern in _INSTALL_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)
