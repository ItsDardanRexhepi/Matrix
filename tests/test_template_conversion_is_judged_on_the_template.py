"""RUN-3 on the template branch: judge the contract that was produced.

When the artist classifier recommends a template (source_lang "pseudocode", tier
"simple"), ContractConversionService.convert emits the TEMPLATE — a complete
OpenZeppelin contract with real function bodies — as `generated_source`. The
honesty check that follows still measured the parsed pseudocode IR, whose bodies
are empty for a one-line declaration, so the service reported:

    status: "partial", unimplemented: ["mint"],
    audit: {"verdict": "not_applicable", "reason": "every function body is empty"}

about a contract whose `mint` is fully implemented — and threw away the real
audit it had just computed over that template (which, for the erc721 template,
flags SWC-103 floating pragma). The caller was shown neither what they got nor
what the auditor found in it.

The property asserted: the audit a caller receives is the audit of the source
the caller receives, re-derived here by auditing `generated_source` directly —
not a comparison against any string the service writes about itself.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.contract_conversion.service import (
    ContractConversionService,
)
from runtime.security.audit import ContractAuditor

ARTIST_PSEUDOCODE = """contract ArtDrop
nft art gallery collection with royalty for the creator, metadata on ipfs
function mint(to: address)
"""

# Declares a function the erc721 template does not have.
ARTIST_WITH_AN_EXTRA = """contract ArtDrop
nft art gallery collection with royalty for the creator, metadata on ipfs
function mint(to: address)
function airdrop(to: address)
"""


@pytest.fixture
def service():
    return ContractConversionService(config={})


async def _convert(service, src):
    result = await service.convert(src, "pseudocode")
    assert result.get("template_used"), (
        "fixture no longer reaches the template branch — the test would prove "
        f"nothing: {result.get('artist_info')!r} {result.get('tier')!r}")
    return result


async def test_the_reported_audit_is_the_audit_of_the_generated_source(service):
    result = await _convert(service, ARTIST_PSEUDOCODE)
    independent = ContractAuditor({}).audit(
        result["generated_source"], result["contract_name"]).to_dict()
    assert result["audit"] == independent, (
        "the audit returned is not the audit of the contract returned:\n"
        f"returned: {result['audit']!r}\nactual:   {independent!r}")
    assert result["audit_passed"] is ContractAuditor({}).audit(
        result["generated_source"], result["contract_name"]).passed


async def test_a_function_the_template_implements_is_not_unimplemented(service):
    result = await _convert(service, ARTIST_PSEUDOCODE)
    assert "mint" not in result["unimplemented"], result["unimplemented"]
    assert result["status"] == "success", (result["status"], result["unimplemented"])


async def test_a_declared_function_the_template_lacks_is_still_named(service):
    """The other direction: the template does not carry `airdrop`, so the
    caller's declared function is genuinely absent from what they got. That must
    stay visible — the fix is to measure the output, not to stop measuring."""
    result = await _convert(service, ARTIST_WITH_AN_EXTRA)
    assert "airdrop" not in result["generated_source"]
    assert result["unimplemented"] == ["airdrop"], result["unimplemented"]
    assert result["status"] == "partial"
    # The audit is still the real one: there IS executable logic to judge.
    assert result["audit"].get("verdict") != "not_applicable"


async def test_a_partial_conversion_is_not_auto_deployed(monkeypatch):
    """Measuring the template makes its audit pass, which is what the deploy
    gate reads. A contract missing a function the caller declared must not reach
    deployment on the strength of that pass."""
    svc = ContractConversionService(config={"conversion": {"auto_deploy": True}})
    attempted = []

    async def fake_deploy(source, name):
        attempted.append(name)
        return {"status": "skipped", "reason": "test"}

    monkeypatch.setattr(svc, "_compile_and_deploy", fake_deploy)
    result = await _convert(svc, ARTIST_WITH_AN_EXTRA)
    assert attempted == [], "a partial conversion was sent to deployment"
    assert result["deployment"]["status"] == "blocked"
