"""The texts about who signs on their own, and who reads a node's refusal, say
what the code does.

Three service paths sign and broadcast a transaction themselves rather than
through `Web3Manager.send_transaction`: the conversion pipeline's deploy, the
attestation service's revocation and its time-critical write. Three texts
said the revocation and the time-critical write signed under listed
exemptions. The revocation is metered, as `attestation.revoke`, and there is
no `eas.revoke` exemption; the time-critical write is metered when a caller
asks for it, and only the platform's own record of it is the listed
`eas.attest_time_critical`. The README said a node refusal is read on the
shared manager's send "which the services send through", with no word on
those three, which do not read one, and it left out the one answer other than
a listed refusal that can give budget back: a node with no send method.

Each test derives what it checks from the code, so a new self-broadcasting
service, a new exemption or a change to what counts as a refusal moves the
test with it.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVICES = REPO / "runtime" / "blockchain" / "services"

#: How the README names each service path that broadcasts on its own.
_NAMED_IN_THE_README = {
    "contract_conversion/service.py": "conversion pipeline's deploy",
    "attestation/service.py": "revocation",
    "attestation/time_critical.py": "time-critical attestation",
}


def _self_broadcasting_service_modules() -> set[str]:
    found = set()
    for path in SERVICES.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "send_raw_transaction"):
                found.add(path.relative_to(SERVICES).as_posix())
    return found


def _sponsorship_bullet() -> str:
    readme = (REPO / "README.md").read_text()
    start = readme.index("- **Gas sponsorship is metered against what the EntryPoint can charge.**")
    end = readme.index("\n- **", start + 1)
    return " ".join(readme[start:end].split())


def test_the_readme_names_each_service_path_that_does_not_read_a_refusal():
    modules = _self_broadcasting_service_modules()
    assert modules == set(_NAMED_IN_THE_README), (
        f"the service modules that broadcast on their own are {sorted(modules)}; "
        f"the README is held to {sorted(_NAMED_IN_THE_README)}")
    bullet = _sponsorship_bullet()
    missing = [phrase for phrase in _NAMED_IN_THE_README.values() if phrase not in bullet]
    assert not missing, (
        f"the README's sponsorship paragraph says a refusal is read where the "
        f"services send, and does not name {missing}, which sign and broadcast "
        f"on their own and do not read one")


def test_the_readme_names_every_answer_that_gives_budget_back():
    from web3.exceptions import MethodUnavailable

    from runtime.blockchain.sponsorship import node_refused

    error = {"code": -32601, "message": "the method eth_sendRawTransaction does not exist"}
    if not node_refused(MethodUnavailable(repr(error), rpc_response={"error": error})):
        return
    assert "no method for sending" in _sponsorship_bullet(), (
        "a node with no send method gives budget back (subject to the lookup), "
        "and the README's list of what gives it back leaves that out")


def _prose(path: pathlib.Path) -> str:
    text = path.read_text()
    if path.suffix == ".py":
        text = "\n".join(re.sub(r"^\s*#:?\s?", "", line) for line in text.splitlines())
    return " ".join(text.split())


_CALLED_AN_EXEMPTION = re.compile(
    r"revoke[^.;]{0,160}?(?:listed|unmetered)[^.;]{0,40}?exemption", re.IGNORECASE)


def test_no_text_says_the_revocation_signs_under_an_exemption():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    if any("revoke" in op for op in UNMETERED_PLATFORM_OPERATIONS):
        return
    texts = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md")),
             *sorted((REPO / "runtime").rglob("*.py")), *sorted((REPO / "gateway").rglob("*.py"))]
    saying_so = []
    for path in texts:
        for match in _CALLED_AN_EXEMPTION.finditer(_prose(path)):
            saying_so.append(f"{path.relative_to(REPO)}: ...{match.group(0)}...")
    assert not saying_so, (
        "no revocation is a listed exemption (the attestation service's revoke "
        "is metered as attestation.revoke), and these say it is:\n  "
        + "\n  ".join(saying_so))
