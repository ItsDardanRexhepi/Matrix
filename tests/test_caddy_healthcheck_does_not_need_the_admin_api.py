"""The Caddy container's healthcheck asks something that is switched on.

docker-compose.prod.yml health-checked Caddy with
`wget http://localhost:2019/config/`, which is Caddy's admin API. The
Caddyfile's global options say `admin off`, which disables that endpoint (the
Caddy documentation: "If set to `off`, then the admin endpoint will be
disabled"), so nothing listened on 2019 and the container could never report
healthy. The comment above `admin off` called it a telemetry opt-out, which is
how the two came to disagree.

The fix keeps the admin API off and gives the healthcheck its own listener in
the Caddyfile: a port-only site (plain HTTP, no Host matcher, no automatic
HTTPS) bound to loopback and not published by compose. This reads both files;
docker and caddy are not run here.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOOPBACK = {"127.0.0.1", "::1", "[::1]", "localhost"}


def _caddy_blocks() -> list[tuple[str, list[str]]]:
    """Top-level Caddyfile blocks as (address, directive lines). The global
    options block has the address ''."""
    blocks: list[tuple[str, list[str]]] = []
    depth, current = 0, None
    for raw in (ROOT / "Caddyfile").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if depth == 0 and line.endswith("{"):
            current = (line[:-1].strip(), [])
            blocks.append(current)
        elif depth == 1 and current is not None:
            current[1].append(line)
        depth += line.count("{") - line.count("}")
    return blocks


def _compose() -> dict:
    class Loader(yaml.SafeLoader):
        pass

    # Compose's `!reset` tag (the prod file uses it on the gateway's ports).
    Loader.add_constructor("!reset", lambda loader, node: None)
    return yaml.load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"), Loader=Loader)


def _healthcheck_url() -> str:
    test = _compose()["services"]["caddy"]["healthcheck"]["test"]
    urls = [part for part in test if isinstance(part, str) and part.startswith("http")]
    assert len(urls) == 1, f"expected one URL in the caddy healthcheck, got {test}"
    return urls[0]


def _admin_address() -> str | None:
    """The admin endpoint the global options leave on, or None when off."""
    options = dict(_caddy_blocks())[""]
    for line in options:
        words = line.split()
        if words[0] == "admin":
            return None if words[1:2] == ["off"] else (words[1] if len(words) > 1 else "localhost:2019")
    return "localhost:2019"


def test_the_healthcheck_does_not_ask_an_admin_api_that_is_off():
    url = urlsplit(_healthcheck_url())
    if _admin_address() is None:
        assert url.port != 2019, (
            f"the caddy healthcheck asks {url.geturl()}, the admin API's port, "
            "but the Caddyfile sets `admin off`: nothing answers there, so the "
            "container can never report healthy"
        )


def test_the_healthcheck_port_is_a_loopback_site_the_caddyfile_serves():
    url = urlsplit(_healthcheck_url())
    sites = {}
    for address, body in _caddy_blocks():
        m = re.fullmatch(r"(?:http://)?:(\d+)", address)
        if m:
            sites[int(m.group(1))] = body
    assert url.port in sites, (
        f"the healthcheck asks port {url.port}, and no port-only site in the "
        f"Caddyfile serves it (port-only sites: {sorted(sites)})"
    )
    binds = [line.split()[1:] for line in sites[url.port] if line.split()[0] == "bind"]
    assert binds and all(h in LOOPBACK for b in binds for h in b), (
        f"the healthcheck site :{url.port} must bind loopback only, so it is "
        f"not reachable from outside the container; binds: {binds}"
    )
    assert url.hostname in {h.strip("[]") for b in binds for h in b}, (
        f"the healthcheck asks {url.hostname}, which the site's bind {binds} "
        "does not cover"
    )


def test_the_healthcheck_port_is_not_published():
    url = urlsplit(_healthcheck_url())
    published = [str(p) for p in _compose()["services"]["caddy"].get("ports", [])]
    assert not any(re.search(rf"(^|:){url.port}(/\w+)?$", p) for p in published), (
        f"port {url.port} is published by compose ({published}); the healthcheck "
        "listener is for the container itself"
    )
