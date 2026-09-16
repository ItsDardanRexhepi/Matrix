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


async def test_an_inherited_internal_function_is_not_counted_as_implemented(service):
    """The inherited set is the compiled template's EXTERNALLY CALLABLE
    functions. ERC721's internal _safeMint is inherited, but it is not in the
    ABI, so a caller who declares it is told so (sdk/client.py says this)."""
    result = await _convert(service, ARTIST_PSEUDOCODE + "function _safeMint(to: address)\n")
    assert result["template_used"] == "erc721"
    assert result["unimplemented"] == ["_safeMint"], result["unimplemented"]
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
def forge_build(tmp_path_factory):
    """A forge project against the pinned OpenZeppelin (contracts/lib, or
    OPENZEPPELIN_CONTRACTS_DIR). Returns build(name, source) -> (abi, error).
    Skips when forge, solc 0.8.20 or the submodule is absent: the submodule is
    not checked out in every clone."""
    import json
    import shutil
    import subprocess

    oz = _openzeppelin_dir()
    forge = shutil.which("forge")
    if oz is None or forge is None:
        pytest.skip("forge or the OpenZeppelin submodule is not available")
    root = tmp_path_factory.mktemp("forge")
    (root / "src").mkdir()
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

    def build(name: str, source: str, *, stem: str | None = None, full: bool = False):
        # One build per contract: a single build fails as a whole, which would
        # make one broken source look like all of them. `stem` names the file
        # when `name` (the contract) is not a usable file name; `full` returns
        # the whole artifact, AST included, instead of the ABI.
        stem = stem or name
        (root / "src" / f"{stem}.sol").write_text(source)
        run = subprocess.run(
            [forge, "build", "--offline", "--ast", "--contracts", f"src/{stem}.sol"],
            cwd=root, capture_output=True, text=True, timeout=300)
        artifact = root / "out" / f"{stem}.sol" / f"{name}.json"
        if run.returncode == 0 and artifact.is_file():
            data = json.loads(artifact.read_text())
            return (data if full else data["abi"]), None
        return None, (run.stderr or run.stdout)[-1500:]

    return build


def _filled(name: str, text: str) -> str:
    return (text.replace("{{NAME}}", name).replace("{{SYMBOL}}", "TT")
                .replace("{{MAX_SUPPLY}}", "10000"))


@pytest.fixture(scope="module")
def compiled_templates(forge_build):
    from runtime.blockchain.services.contract_conversion.templates import TEMPLATES

    abis, errors = {}, {}
    for name, text in TEMPLATES.items():
        abi, err = forge_build(f"T_{name}", _filled(f"T_{name}", text))
        abis[name] = abi
        if err is not None:
            errors[name] = err
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


# ── what convert() returns when a fee recipient is configured ────────────
#
# Round-2 review: `conversion.inject_fees` defaults to True and takes effect as
# soon as `blockchain.platform_wallet` is set. RevenueEnforcer then adds
# `_collectERC20Fee`, which called `IERC20(token).transfer(...)` in templates
# that never import IERC20. convert() reported the result as status "success",
# audit passed, and forge rejected it: Error (7576) Undeclared identifier.
# Every control above ran with config {}, where fee injection is skipped, so the
# contract production returns was never compiled.

FEE_CONFIG = {"blockchain": {"platform_wallet": "0x000000000000000000000000000000000000bEEF"}}

MUSIC_PSEUDOCODE = """contract AlbumDrop
music album with songs and audio tracks, royalty for the artist
function mint(to: address, id: uint256, amount: uint256)
"""


def _reachable_templates():
    """Every template convert() can emit: the artist classifier's map, plus its
    erc721 default. Read from the classifier so a new mapping is covered."""
    from runtime.blockchain.services.contract_conversion import artist_classifier

    return sorted(set(artist_classifier._TEMPLATE_MAP.values()) | {"erc721"})


def test_every_reachable_template_compiles_after_fee_injection(forge_build):
    from runtime.blockchain.services.contract_conversion.revenue_enforcer import (
        RevenueEnforcer,
    )
    from runtime.blockchain.services.contract_conversion.templates import TEMPLATES

    failed = {}
    for name in _reachable_templates():
        contract = f"F_{name}"
        injected = RevenueEnforcer(FEE_CONFIG).inject_fee_logic(
            _filled(contract, TEMPLATES[name]))
        assert "_collectERC20Fee" in injected, "fee injection did not run"
        abi, err = forge_build(contract, injected)
        if abi is None:
            failed[name] = err
    assert not failed, f"fee-injected templates that do not compile: {sorted(failed)}\n{failed}"


@pytest.mark.parametrize("pseudocode,template", [
    (ARTIST_PSEUDOCODE, "erc721"),
    (MUSIC_PSEUDOCODE, "erc1155"),
])
async def test_the_fee_injected_contract_convert_returns_compiles(forge_build, pseudocode,
                                                                   template):
    result = await ContractConversionService(config=FEE_CONFIG).convert(
        pseudocode, "pseudocode")
    assert result.get("template_used") == template, (
        result.get("template_used"), result.get("artist_info"))
    source = result["generated_source"]
    assert "platformFeeRecipient" in source, "fee injection did not run"
    abi, err = forge_build(result["contract_name"], source)
    assert abi is not None, (
        f"convert() returned status {result['status']!r}, audit_passed "
        f"{result['audit_passed']!r} for a contract that does not compile:\n{err}")
    assert result["status"] == "success", (result["status"], result["unimplemented"])


# ── the contract name convert() pastes into the template ─────────────────
#
# Round-3 review: the template branch substituted the parsed pseudocode name
# into `contract {{NAME}} is ...` unchecked. The parser takes the first word
# after "contract", "class", "module" or "token", so ordinary prose ("... where
# every token is unique ...") names the contract `is`. convert() reported
# status "success", audit_passed True, and forge rejected the source: Error 2314
# for `is`, `2026Drop` and `Gällery`; Error 2333 (identifier already declared)
# for `ERC721`, `Strings`, `Context`, `IERC165`, and for `IMatrixFeeToken`
# once fees are injected; Error 5796 for `mint`, a function the template
# declares. The controls above compiled only ArtDrop and AlbumDrop.

PROSE_NAMING_THE_CONTRACT_IS = """An nft art gallery collection where every token is unique,
royalty for the creator, metadata on ipfs
function mint(to: address)
"""


def _art(name: str) -> str:
    return (f"contract {name}\n"
            "nft art gallery collection with royalty for the creator, metadata on ipfs\n"
            "function mint(to: address)\n")


UNUSABLE_NAMES = {
    "prose: is": (PROSE_NAMING_THE_CONTRACT_IS, "is"),
    "leading digit": (_art("2026Drop"), "2026Drop"),
    "non-ascii": (_art("G\u00e4llery"), "G\u00e4llery"),
    "imported contract": (_art("ERC721"), "ERC721"),
    "re-exported library": (_art("Strings"), "Strings"),
    "re-exported base": (_art("Context"), "Context"),
    "re-exported interface": (_art("IERC165"), "IERC165"),
    "injected fee interface": (_art("IMatrixFeeToken"), "IMatrixFeeToken"),
    "function the template declares": (_art("mint"), "mint"),
    "keyword": (_art("function"), "function"),
}

# Names that do NOT collide, including ones that look as if they might: an
# inherited function and an inherited internal the template text does not use,
# and an OpenZeppelin library its imports do not bring into scope.
USABLE_NAMES = ["ArtDrop", "Drop2026", "Gallery_1", "balanceOf", "_approve", "Math"]

_DECLARED = __import__("re").compile(r"^contract\s+(\S+)\s+is\b", __import__("re").M)


def _declared_contract(source: str) -> str:
    found = _DECLARED.findall(source)
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("case", sorted(UNUSABLE_NAMES))
@pytest.mark.parametrize("config", [{}, FEE_CONFIG], ids=["no-fee", "fee"])
async def test_an_unusable_name_is_not_pasted_into_the_template_and_the_change_is_said(
        case, config):
    source, requested = UNUSABLE_NAMES[case]
    result = await _convert(ContractConversionService(config=config), source)
    declared = _declared_contract(result["generated_source"])
    assert declared != requested, (
        f"{requested!r} was pasted into the template as the contract name; "
        f"convert() said status {result['status']!r}, audit_passed "
        f"{result['audit_passed']!r}")
    assert result["contract_name"] == declared, (result["contract_name"], declared)
    assert result.get("contract_name_substituted", {}).get("requested") == requested, (
        "the caller's name was replaced without saying so: "
        f"{result.get('contract_name_substituted')!r}")
    assert result["contract_name_substituted"]["used"] == declared
    assert result["contract_name_substituted"]["reason"]


@pytest.mark.parametrize("name", USABLE_NAMES)
async def test_a_usable_name_is_kept(name):
    result = await _convert(ContractConversionService(config=FEE_CONFIG), _art(name))
    assert _declared_contract(result["generated_source"]) == name
    assert result["contract_name"] == name
    assert "contract_name_substituted" not in result, result["contract_name_substituted"]


@pytest.mark.parametrize("name", sorted(UNUSABLE_NAMES) + USABLE_NAMES)
@pytest.mark.parametrize("config", [{}, FEE_CONFIG], ids=["no-fee", "fee"])
async def test_success_is_only_reported_for_a_template_contract_that_compiles(
        forge_build, name, config):
    source = UNUSABLE_NAMES[name][0] if name in UNUSABLE_NAMES else _art(name)
    result = await _convert(ContractConversionService(config=config), source)
    stem = "N_" + "".join(c if c.isalnum() and c.isascii() else "_" for c in name)
    abi, err = forge_build(result["contract_name"], result["generated_source"], stem=stem)
    assert abi is not None, (
        f"convert() returned status {result['status']!r}, audit_passed "
        f"{result['audit_passed']!r}, contract {result['contract_name']!r}, for a "
        f"contract that does not compile:\n{err}")
    assert result["status"] == "success", (result["status"], result["unimplemented"])


def test_the_recorded_template_scope_is_the_compilers(forge_build):
    """TEMPLATE_IMPORTED_SYMBOLS is what a contract name must not collide with:
    every name the template's `import` lines put in its file scope, which is
    more than the file names (ERC721.sol brings Context, Strings, IERC165 ...).
    Re-derived here from the AST's exportedSymbols."""
    from runtime.blockchain.services.contract_conversion.templates import (
        TEMPLATE_IMPORTED_SYMBOLS, TEMPLATES,
    )

    assert set(TEMPLATE_IMPORTED_SYMBOLS) == set(TEMPLATES)
    for name, text in TEMPLATES.items():
        contract = f"S_{name}"
        artifact, err = forge_build(contract, _filled(contract, text), full=True)
        assert artifact is not None, err
        exported = set(artifact["ast"]["exportedSymbols"]) - {contract}
        assert set(TEMPLATE_IMPORTED_SYMBOLS[name]) == exported, (
            name, sorted(exported ^ set(TEMPLATE_IMPORTED_SYMBOLS[name])))


# ── the fee recipient convert() pastes into the contract ─────────────────
#
# The other value convert() writes into a template is the operator's
# `blockchain.platform_wallet`, as an address literal. solc rejects an address
# literal that is not EIP-55 checksummed (Error 9429), and anything that is not
# 40 hex digits (Error 8936). A lower-case wallet, or the example config's
# "YOUR_PLATFORM_WALLET_ADDRESS" left in place, produced source that does not
# compile, reported as status "success" with the audit passed.

LOWERCASE_WALLET = "0x742d35cc6634c0532925a3b844bc454e4438f44e"
CHECKSUMMED_WALLET = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"


async def test_a_lower_case_fee_recipient_is_written_checksummed():
    result = await _convert(ContractConversionService(
        config={"blockchain": {"platform_wallet": LOWERCASE_WALLET}}), ARTIST_PSEUDOCODE)
    assert f"platformFeeRecipient = {CHECKSUMMED_WALLET};" in result["generated_source"], (
        "the fee recipient literal is not the checksummed address")
    assert LOWERCASE_WALLET not in result["generated_source"]


@pytest.mark.parametrize("wallet", ["YOUR_PLATFORM_WALLET_ADDRESS", "0x1234", "0x" + "ab" * 32])
async def test_a_fee_recipient_that_is_not_an_address_is_not_a_success(wallet):
    result = await ContractConversionService(
        config={"blockchain": {"platform_wallet": wallet}}).convert(
            ARTIST_PSEUDOCODE, "pseudocode")
    assert result["status"] == "error", (
        f"status {result['status']!r} for a contract whose fee recipient literal "
        f"is {wallet!r}")
    assert "generated_source" not in result
    assert wallet not in repr(result), "the configured value was echoed to the caller"
    assert "platform_wallet" in result["error"]


async def test_the_contract_with_a_lower_case_fee_recipient_compiles(forge_build):
    result = await _convert(ContractConversionService(
        config={"blockchain": {"platform_wallet": LOWERCASE_WALLET}}), ARTIST_PSEUDOCODE)
    abi, err = forge_build(result["contract_name"], result["generated_source"],
                           stem="W_lowercase")
    assert abi is not None, (
        f"convert() returned status {result['status']!r}, audit_passed "
        f"{result['audit_passed']!r} for a contract that does not compile:\n{err}")
    assert result["status"] == "success"


def test_the_fallback_contract_name_is_usable_in_every_template():
    from runtime.blockchain.services.contract_conversion.identifiers import (
        FALLBACK_CONTRACT_NAME, unusable_because,
    )
    from runtime.blockchain.services.contract_conversion.templates import TEMPLATES

    for name, text in TEMPLATES.items():
        assert unusable_because(FALLBACK_CONTRACT_NAME, name, text) is None, name
