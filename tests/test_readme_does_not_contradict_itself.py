"""The README may not contradict itself, or the code it describes.

It is the first thing a reader trusts, and it had eight places where one part
said something another part denied:

  * a stale five-provider table sitting directly under the seventeen-provider
    one that replaced it;
  * "All transactions are sponsored — users never pay gas", against the same
    file's "gas sponsored within the policy the operator configures" and
    "gas sponsorship is metered";
  * an examples table promising "plain English to deployed smart contract",
    against "it does not deploy contracts for you";
  * "all free", against Subscription Tiers, $299 services, $49 courses and
    $149 certifications;
  * a paid audit service advertised as available while the gateway hardcodes
    `audit_service = None` and the endpoint answers 503;
  * `/pricing` listed as a page the gateway serves, with no such route;
  * courses and certifications repeating the deployment claim;
  * a test count naming a number the tree no longer runs.

These tests assert the properties, so a new contradiction of the same shape
fails here rather than being read by a stranger.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
README = (REPO / "README.md").read_text()


def _tables_with(header_word: str) -> list[str]:
    return [b for b in README.split("\n\n") if header_word in b and b.lstrip().startswith("|")]


def test_only_one_provider_table():
    """The Model Support rewrite left the old table's rows behind once."""
    tables = [t for t in README.split("\n\n") if "| `ollama` |" in t or "| `ollama`" in t]
    assert len(tables) == 1, (
        f"{len(tables)} provider tables in the README — a stale one contradicts the current one")


def test_the_provider_table_is_not_followed_by_orphaned_rows():
    after = README.split("runtime/models/providers.py`, so they cannot drift apart")[-1]
    orphan = re.search(r"^\|\s*(Ollama|OpenAI|Anthropic|NVIDIA|Gemini)\b", after, re.M)
    assert orphan is None, f"orphaned provider row after the table: {orphan.group(0)!r}"


def test_gas_is_never_described_as_always_free():
    for claim in ("users never\npay gas", "users never pay gas",
                  "All transactions are sponsored by the platform paymaster"):
        assert claim not in README, (
            f"README says {claim!r}, but sponsorship is capped and allowlisted "
            "elsewhere in the same file")
    assert "within the policy the operator configures" in README


def test_the_readme_never_says_the_platform_deploys_for_you():
    """It says plainly that it does not; nothing else may promise otherwise."""
    assert "does not deploy it for you" in README or "It does not deploy contracts for you" in README
    for contradiction in ("to deployed smart contract",
                          "plain English to deployed"):
        assert contradiction not in README, f"README promises a deployment it refuses: {contradiction!r}"


def test_free_and_paid_are_distinguished_rather_than_both_asserted():
    """'all free' and a $299 service can coexist only if the file says which is
    which."""
    if "$" in README:
        assert "What is free, and what is paid" in README, (
            "the README names prices but never separates the free platform from the paid services")
        section = README.split("What is free, and what is paid")[1][:900]
        assert "free, open source, and unlimited" in section
        assert "hosted" in section


def test_no_page_is_listed_that_the_gateway_does_not_serve():
    """Every http://localhost:18790/<page> in the README must be a real route."""
    # Routes are registered in both files, and an API path has several
    # segments — matching only the first one reports /api as missing.
    registered = ((REPO / "gateway/server.py").read_text()
                  + (REPO / "gateway/service_routes.py").read_text())
    listed = set(re.findall(r"http://localhost:18790(/[A-Za-z0-9/_\-]*)", README))
    missing = []
    for path in listed:
        if path in ("", "/"):
            continue
        # exact registration, or a registered prefix (…/capabilities/categories
        # is served by the capabilities router)
        if any(f'"{path}"' in registered or f'"{path}/' in registered for _ in (0,)):
            continue
        parent = "/".join(path.split("/")[:-1])
        if parent and f'"{parent}"' in registered:
            continue
        missing.append(path)
    assert not missing, f"the README lists pages the gateway does not serve: {missing}"


def test_a_service_the_gateway_refuses_is_not_advertised_as_available():
    server = (REPO / "gateway/server.py").read_text()
    if "self.audit_service = None" in server:
        assert "not live" in README, (
            "the gateway hardcodes audit_service = None (POST /audit/request answers 503), "
            "so the README must not present the paid audit as something you can buy")


def test_the_test_count_is_not_a_number_the_tree_stopped_running():
    """A count in prose goes stale silently; this at least pins its shape and
    keeps it plausible against the files that exist."""
    m = re.search(r"automated suite of ([\d,]+) tests", README)
    assert m, "the README no longer states how many tests back it"
    claimed = int(m.group(1).replace(",", ""))
    test_files = list((REPO / "tests").glob("test_*.py"))
    assert claimed > 100 * 0 + len(test_files), "the claimed count is below the number of test files"
    assert claimed < 100_000, "implausible test count"
