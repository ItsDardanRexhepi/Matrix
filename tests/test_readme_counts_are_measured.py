"""Every count the README gives for the service registry and the capability
catalog is the one the code has.

The README said "50+ blockchain services" in three places, the architecture
diagram among them, while runtime/blockchain/services/registry.py has 45. It
said "221 capabilities" while runtime/capabilities/catalog.py has 195. A number written by hand goes stale
without anyone touching it, so each one is compared with the code here.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
README = (REPO / "README.md").read_text()


def _measured() -> dict[str, int]:
    from runtime.blockchain.services.registry import _SERVICE_MAP
    from runtime.capabilities.catalog import CAPABILITIES, CATEGORIES

    return {
        "services": len(_SERVICE_MAP),
        "capabilities": len(CAPABILITIES),
        "categories": len(CATEGORIES),
        "backing": len({c["service"] for c in CAPABILITIES}),
    }


def test_every_service_count_is_the_registry():
    n = _measured()["services"]
    claimed = re.findall(r"(\d[\d,]*\+?)\s+[Bb]lockchain\s+[Ss]ervices", README)
    claimed += re.findall(r"of the (\d+) services in the service registry", README)
    assert claimed, "the README no longer counts the blockchain services"
    wrong = sorted({c for c in claimed if c != str(n)})
    assert not wrong, (
        f"the README counts the blockchain services as {wrong}; "
        f"the service registry has {n}")


def test_every_capability_and_category_count_is_the_catalog():
    m = _measured()
    headline = re.findall(r"\*\*(\d[\d,]*) capabilities across (\d+) categories\*\*", README)
    assert headline, "the README no longer states the catalog's size"
    for caps, cats in headline:
        assert int(caps.replace(",", "")) == m["capabilities"], (
            f"the README says {caps} capabilities; the catalog has {m['capabilities']}")
        assert int(cats) == m["categories"], (
            f"the README says {cats} categories; the catalog defines {m['categories']}")

    served = re.search(r"The (\d+)\s+are served by (\d+) of the (\d+) services", README)
    assert served, "the README no longer says how many services back the catalog"
    caps, backing, services = (int(g) for g in served.groups())
    assert (caps, backing, services) == (m["capabilities"], m["backing"], m["services"]), (
        f"the README says {caps} capabilities served by {backing} of {services} services; "
        f"the code has {m['capabilities']}, {m['backing']} and {m['services']}")

    buckets = re.search(r"/api/v1/capabilities/categories\s+#\s+(\d+) buckets", README)
    if buckets:
        assert int(buckets.group(1)) == m["categories"]
