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


# ── functions the template INHERITS are implemented too ──────────────────
#
# Round-1 review: implemented_functions reads function bodies written in the
# template text. The erc721 template is `ERC721, ERC721Enumerable,
# ERC721URIStorage, ERC2981, Ownable`, so a caller who declared balanceOf,
# safeTransferFrom, transferFrom or royaltyInfo — all implemented by the contract
# they got — was told those were unimplemented and got status "partial".

ARTIST_DECLARING_INHERITED = """contract ArtDrop
nft art gallery collection with royalty for the creator, metadata on ipfs
function mint(to: address)
function balanceOf(owner: address)
function safeTransferFrom(from: address, to: address, id: uint256)
function transferFrom(from: address, to: address, id: uint256)
function royaltyInfo(id: uint256, price: uint256)
"""

MUSIC_DECLARING_INHERITED = """contract AlbumDrop
music album with songs and audio tracks, royalty for the artist
function mint(to: address, id: uint256, amount: uint256)
function balanceOfBatch(owners: address, ids: uint256)
function safeBatchTransferFrom(from: address, to: address, ids: uint256)
function royaltyInfo(id: uint256, price: uint256)
function remix(id: uint256)
"""


async def test_a_declared_inherited_erc721_function_is_implemented(service):
    result = await _convert(service, ARTIST_DECLARING_INHERITED)
    assert result["template_used"] == "erc721"
    for inherited in ("balanceOf", "safeTransferFrom", "transferFrom", "royaltyInfo"):
        assert f"function {inherited}" not in result["generated_source"], (
            f"{inherited} is written in the template text; this would not test inheritance")
    assert result["unimplemented"] == [], result["unimplemented"]
    assert result["status"] == "success"


async def test_a_declared_inherited_erc1155_function_is_implemented_and_a_missing_one_named(
        service):
    result = await _convert(service, MUSIC_DECLARING_INHERITED)
    assert result["template_used"] == "erc1155"
    assert result["unimplemented"] == ["remix"], result["unimplemented"]
    assert result["status"] == "partial"


def test_every_template_has_a_recorded_external_function_list():
    from runtime.blockchain.services.contract_conversion.templates import (
        TEMPLATE_EXTERNAL_FUNCTIONS, TEMPLATES,
    )

    assert set(TEMPLATE_EXTERNAL_FUNCTIONS) == set(TEMPLATES)


# ── the recorded lists are the compiler's, not a hand-typed guess ────────

def _openzeppelin_dir():
    import os
    from pathlib import Path

    candidates = [os.environ.get("OPENZEPPELIN_CONTRACTS_DIR", ""),
                  str(Path(__file__).resolve().parents[1]
                      / "contracts" / "lib" / "openzeppelin-contracts" / "contracts")]
    for c in candidates:
        if c and (Path(c) / "token" / "ERC721" / "ERC721.sol").is_file():
            return Path(c)
    return None


@pytest.fixture(scope="module")
def compiled_templates(tmp_path_factory):
    """Compile every template with forge against the pinned OpenZeppelin
    (contracts/lib, or OPENZEPPELIN_CONTRACTS_DIR). Skips when either is absent:
    the submodule is not checked out in every clone."""
    import json
    import shutil
    import subprocess

    from runtime.blockchain.services.contract_conversion.templates import TEMPLATES

    oz = _openzeppelin_dir()
    forge = shutil.which("forge")
    if oz is None or forge is None:
        pytest.skip("forge or the OpenZeppelin submodule is not available")
    root = tmp_path_factory.mktemp("templates")
    (root / "src").mkdir()
    for name, text in TEMPLATES.items():
        (root / "src" / f"T_{name}.sol").write_text(
            text.replace("{{NAME}}", f"T_{name}").replace("{{SYMBOL}}", "TT")
                .replace("{{MAX_SUPPLY}}", "10000"))
    (root / "foundry.toml").write_text(
        '[profile.default]\nsrc = "src"\nout = "out"\ncache_path = "cache"\nlibs = []\n'
        'solc_version = "0.8.20"\noffline = true\n'
        f'remappings = ["@openzeppelin/contracts/={oz}/"]\n'
        f'allow_paths = ["{oz.parent}"]\n')
    (root / "src" / "Probe.sol").write_text(
        "// SPDX-License-Identifier: MIT\npragma solidity 0.8.20;\ncontract Probe {}\n")
    probe = subprocess.run([forge, "build", "--offline", "--contracts", "src/Probe.sol"],
                           cwd=root, capture_output=True, text=True, timeout=300)
    if probe.returncode != 0:
        pytest.skip(f"forge cannot compile offline with solc 0.8.20: {probe.stderr[-300:]}")
    # One build per template: a single build fails as a whole, which would make
    # one broken template look like all of them.
    abis, errors = {}, {}
    for name in TEMPLATES:
        run = subprocess.run(
            [forge, "build", "--offline", "--contracts", f"src/T_{name}.sol"],
            cwd=root, capture_output=True, text=True, timeout=300)
        artifact = root / "out" / f"T_{name}.sol" / f"T_{name}.json"
        if run.returncode == 0 and artifact.is_file():
            abis[name] = json.loads(artifact.read_text())["abi"]
        else:
            abis[name] = None
            errors[name] = (run.stderr or run.stdout)[-1500:]
    return errors, abis


def test_every_template_compiles_against_the_pinned_openzeppelin(compiled_templates):
    errors, abis = compiled_templates
    failed = sorted(name for name, abi in abis.items() if abi is None)
    assert not failed, f"templates that do not compile: {failed}\n{errors}"


def test_the_recorded_external_functions_are_the_compiled_abi(compiled_templates):
    from runtime.blockchain.services.contract_conversion.templates import (
        TEMPLATE_EXTERNAL_FUNCTIONS,
    )

    _run, abis = compiled_templates
    for name, abi in abis.items():
        if abi is None:
            continue  # reported by the compile test
        compiled = {e["name"] for e in abi if e.get("type") == "function"}
        assert set(TEMPLATE_EXTERNAL_FUNCTIONS[name]) == compiled, (
            name, sorted(compiled ^ set(TEMPLATE_EXTERNAL_FUNCTIONS[name])))
