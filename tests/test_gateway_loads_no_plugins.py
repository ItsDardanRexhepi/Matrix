"""Nothing in the gateway loads a plugin, and nothing public says it does.

After the marketplace stopped claiming to install plugins, the copy that
replaced it said "a plugin runs when its package is placed in
`plugins/installed/`, where the plugin loader finds it" (README, the plugin
guide, the API reference, the marketplace page and its live purchase answer,
the marketplace package docstrings, course-01), and course-01's tutorial told
readers to "Restart the gateway to load your plugin" and watch for
"[INFO] Plugin loaded". runtime/plugins/loader.py can import such a package,
but no production code constructs PluginLoader or PluginRegistry.

Measured, not read from the copy:

  1. a probe plugin package is placed in `plugins/installed/` of an empty
     directory; in a fresh interpreter started there, the gateway app is built
     and its startup hooks run, and a ToolDispatcher is built. The probe writes
     a marker when it is imported and another when `on_load` runs. Neither
     appears. The same interpreter then runs `PluginLoader().load_all()` and
     both markers appear, so the probe is not inert;
  2. with (1) measured, no tracked text outside tests and the changelog may
     say a placed plugin runs, is found and loaded by the gateway, or is loaded
     when the gateway starts; and the documents a plugin author follows must
     say that nothing in the gateway loads it.

Wiring the loader into gateway startup was not done here: plugin tools reach
the agents, so it adds a public surface that needs its own security review.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROBE = textwrap.dedent('''
    from pathlib import Path
    Path("imported.marker").write_text("1")
    from runtime.plugins.base import OpenMatrixPlugin


    class ProbePlugin(OpenMatrixPlugin):
        @property
        def name(self):
            return "probe"

        @property
        def version(self):
            return "0.0.1"

        async def on_load(self, config):
            Path("loaded.marker").write_text("1")
''')

_SCRIPT = textwrap.dedent('''
    import asyncio, sys
    from pathlib import Path
    from aiohttp.test_utils import TestServer
    from gateway.server import GatewayServer

    async def main():
        server = GatewayServer({})
        app = server.create_app()
        ts = TestServer(app)
        await ts.start_server()
        from runtime.tools.dispatcher import ToolDispatcher
        ToolDispatcher({})
        import runtime.react_loop  # noqa: F401
        await ts.close()
        print("GATEWAY", Path("imported.marker").exists(), Path("loaded.marker").exists())
        from runtime.plugins.loader import PluginLoader
        loaded = await PluginLoader().load_all({})
        print("LOADER", Path("imported.marker").exists(), Path("loaded.marker").exists(),
              [p.name for p in loaded])

    asyncio.run(main())
''')


def _gateway_and_loader_markers(tmp_path: Path) -> tuple[tuple[bool, bool], tuple[bool, bool]]:
    pkg = tmp_path / "plugins" / "installed" / "probe_plugin"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(_PROBE, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("OPNMATRX_ENV", None)
    proc = subprocess.run([sys.executable, "-c", _SCRIPT], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=300)
    gateway = re.search(r"^GATEWAY (True|False) (True|False)$", proc.stdout, re.M)
    loader = re.search(r"^LOADER (True|False) (True|False) (.*)$", proc.stdout, re.M)
    assert proc.returncode == 0 and gateway and loader, (
        "the measurement did not run to the end; re-derive this check",
        proc.returncode, proc.stdout[-2000:], proc.stderr[-4000:])
    return ((gateway.group(1) == "True", gateway.group(2) == "True"),
            (loader.group(1) == "True", loader.group(2) == "True"))


_RUNS_CLAIMS = [
    r"plugin runs (?:only )?when its package is (?:placed|put)",
    r"(?:plugin loader|pluginloader|loader\.py`?) finds it",
    r"runs your plugin by placing",
    r"restart (?:the )?gateway (?:to load|and verify the plugin loads)",
    r"\[info\] plugin loaded",
    r"plugin loads without errors on gateway startup",
    r"called (?:once )?when the gateway starts",
    r"when the gateway loads a plugin",
    r"on_unload\(\)`? is called on platform shutdown",
    r"the `?pluginloader`? scans `?plugins/installed/",
    r"called when the plugin is loaded during platform startup",
    r"the gateway and react loop query this registry",
    r"the platform calls these methods at specific points",
    r"runs in an isolated sandbox",
]

# Documents a plugin author follows: each must say nothing in the gateway loads it.
_MUST_SAY_NOT_LOADED = [
    "README.md", "docs/PLUGIN_DEVELOPMENT.md", "docs/api-reference.md",
    "education/course-01-intro-to-0pnmatrx/04-your-first-plugin.md",
    "web/marketplace.html", "runtime/marketplace/plugin_store.py",
]
_NOT_LOADED = re.compile(r"nothing in (?:the|this) gateway (?:loads|calls)", re.I)


def test_the_claim_scan_catches_the_old_copy():
    old = ("Build plugins for 0pnMatrx. A plugin runs when its package is placed in "
           "`plugins/installed/`, where the plugin loader finds it. Restart the gateway to "
           "load your plugin: [INFO] Plugin loaded: my-plugin v1.0.0")
    low = old.lower()
    assert sum(bool(re.search(p, low)) for p in _RUNS_CLAIMS) >= 4
    assert not _NOT_LOADED.search(old)


def test_the_gateway_loads_no_plugin_and_no_text_says_it_does(tmp_path):
    gateway, loader = _gateway_and_loader_markers(tmp_path)
    assert loader == (True, True), "the probe plugin did not load even through the loader"
    if gateway != (False, False):
        return  # the gateway loads plugins now; the copy is not contradicted
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
        for pattern in _RUNS_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 30]}...")
    for rel in _MUST_SAY_NOT_LOADED:
        flat = re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8"))
        if not _NOT_LOADED.search(flat):
            offenders.append(f"{rel}: does not say that nothing in the gateway loads a plugin")
    assert not offenders, "\n".join(offenders)
