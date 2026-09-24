"""What the text says the contract converter takes and returns is what it does.

The README's examples table and examples/README.md called example 01 "Plain
English to audited Solidity"; the capability map said Convert Contract takes
"plain-English or pseudocode"; example 01 said it "Takes a plain English
rental agreement description" (it takes pseudocode). The converter's parser
reads structured pseudocode: a `contract` line, `state name: type` lines and
`function name(params)` lines. Given a paragraph of prose it finds no state and
no function, and the answer is an empty contract marked `partial`. The
README's pipeline line ended in "compile artifacts"; a conversion compiles
nothing unless an operator turns on `conversion.auto_deploy`.

Both premises are measured here by running the converter, then the public
text is read.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PROSE = ('Create a token called "MatrixCoin" with the symbol "MTRX". Total supply should be '
          "1,000,000 tokens. The deployer receives the full initial supply. Include a burn "
          "function that lets any holder destroy their own tokens.")
_CLAIMS = [
    r"plain[- ]english (?:to|->|→|into) (?:audited )?solidity",
    r"convert plain[- ]english (?:or pseudocode |descriptions? )?into (?:audited )?solidity",
    r"plain[- ]english rental agreement description",
    r"glasswing security audit → compile artifacts",
]
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}


def _convert(source: str) -> dict:
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(ContractConversionService({"blockchain": {}}).convert(source, "pseudocode"))
    finally:
        logging.disable(logging.NOTSET)


def test_the_claim_scan_catches_the_old_text():
    old = ("| `01_contract_conversion.py` | Plain English to audited Solidity, ready for you | "
           "Plain English -> Solidity -> audit | Convert plain-English descriptions into "
           "audited Solidity | 1. Takes a plain English rental agreement description | "
           "pseudocode/Solidity/Vyper → optimised Solidity → Glasswing security audit → "
           "compile artifacts")
    flat = old.lower()
    assert {p for p in _CLAIMS if re.search(p, flat)} == set(_CLAIMS)
    assert not any(re.search(p, "a rental agreement written as pseudocode, converted to "
                                "audited solidity") for p in _CLAIMS)


def test_no_text_says_the_converter_reads_prose_or_compiles_what_it_converts():
    prose = _convert(_PROSE)
    assert prose["status"] == "partial" and not prose["ir"]["functions"], (
        "the converter now reads prose; re-derive this check")
    structured = _convert("contract C\nstate owner: address\n\nfunction pause()\n"
                          "    require(msg.sender == owner);\n")
    assert structured["ir"]["functions"], "precondition: structured pseudocode is read"
    assert not {"abi", "bytecode", "compiled"} & set(structured), (
        "a conversion now returns compile artifacts without auto_deploy; re-derive this check")

    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.py"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8")).lower()
        for pattern in _CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)



# ── The same claim in the demo, the chat intents, the A2A listings and the
# certification bank, and the "optimised" claim beside it ─────────────────
#
# demo.py said "Describe a contract in plain English. We compile & deploy it."
# and asked for "plain English / pseudocode"; for pseudocode it then deployed a
# hand-written SimpleVault or ERC-20 in place of the generated source, which it
# did not try to compile. The conversion page's heading and footer said "Plain
# Language to Solidity", Trinity's conversion follow-up asked for "a plain
# description", the A2A listing offered to "Convert plain English requirements",
# course 01 said "you describe what you want in plain English", the landing
# page "Just describe what you need in plain English", and the certification
# bank asked which endpoint "converts a natural-language contract description"
# (naming a route that is not registered). The README, demo and example 01
# called the output "optimised Solidity" from a "gas-optimisation pass": the
# generator declares a custom error for each require message and leaves the
# require statements as they are.

_WIDER_CLAIMS = [
    r"describe (?:a |your |the )?contract in plain english",
    r"plain[- ](?:english|language) to solidity",
    r"(?:convert|turn)s? (?:a )?(?:plain[- ]english|natural[- ]language)[^.]{0,60}(?:contract|solidity|specification)",
    r"natural[- ]language contract description",
    r"(?:describe|say) what you (?:want|need) in plain english",
    r"instead of writing solidity[^.]{0,40}plain english",
    r"\bor a plain description\b",
    r"gas[- ]optimi[sz]ation pass",
    r"gas[- ]optimi[sz]ed solidity",
    r"\boptimi[sz]ed solidity\b",
    r"apply gas optimi[sz]ations during conversion",
    r"(?:scan|audit)[^.]{0,120}gas optimi[sz]ation issues",
]


def test_the_wider_scan_catches_the_old_text():
    old = ("describe a contract in plain english. we compile & deploy it. | plain language to "
           "solidity | convert plain english requirements into structured smart contract "
           "specifications | which endpoint converts a natural-language contract description into "
           "audited solidity | just describe what you need in plain english | instead of writing "
           "solidity code, you describe what you want in plain english | whether it's solidity, "
           "vyper or a plain description | with an automatic security scan and gas-optimisation "
           "pass | generates gas-optimised solidity for base l2 | → optimised solidity → | apply "
           "gas optimizations during conversion. | performs a 12-point vulnerability scan covering "
           "swc registry patterns, access control, front-running, and gas optimization issues.")
    hits = {p for p in _WIDER_CLAIMS if re.search(p, old)}
    assert hits == set(_WIDER_CLAIMS), set(_WIDER_CLAIMS) - hits
    assert not any(re.search(p, "the converter reads structured pseudocode, solidity or vyper, "
                                "not prose; ask in chat, in your own words.") for p in _WIDER_CLAIMS)


def _require_messages_survive_generation() -> bool:
    from runtime.blockchain.services.contract_conversion.generator import ContractGenerator
    from runtime.blockchain.services.contract_conversion.parser import SourceParser
    ir = SourceParser({}).parse(
        'contract C\nstate owner: address\n\nfunction pause()\n'
        '    require(msg.sender == owner, "not owner");\n', "pseudocode")
    out = ContractGenerator({}).generate(ir, "base")
    return "error notowner();" in out and '"not owner"' in out


def test_no_text_says_the_converter_reads_prose_or_optimises_what_it_writes():
    prose = _convert(_PROSE)
    assert prose["status"] == "partial" and not prose["ir"]["functions"], (
        "the converter now reads prose; re-derive this check")
    assert _require_messages_survive_generation(), (
        "the generator now replaces require strings with its custom errors; re-derive this check")
    from runtime.security.audit import ContractAuditor
    assert not [m for m in dir(ContractAuditor) if m.startswith("_check_") and "gas" in m], (
        "the auditor has a gas check now; re-derive this check")
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.py"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))).lower()
        for pattern in _WIDER_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)


def test_the_conversion_intent_offers_only_parameters_the_service_takes():
    """Trinity's convert_contract entry offered an `optimize` flag ("Apply gas
    optimizations during conversion"). convert() takes no such parameter, so a
    call that sent it was refused by the dispatcher as invalid parameters."""
    import inspect
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    takes = set(inspect.signature(ContractConversionService.convert).parameters) - {"self"}
    entry = INTENT_ACTION_MAP["convert_contract"]
    offered = {p["name"] for p in entry.get("required_params", []) + entry.get("optional_params", [])}
    assert offered <= takes, f"offered but not taken: {sorted(offered - takes)}"


def test_the_demo_deploys_the_converted_source_or_says_it_is_a_stand_in():
    """demo.py replaced the generated source with a hand-written contract for
    every pseudocode run, printed "CONTRACT DEPLOYED SUCCESSFULLY" and signed it
    "Powered by The Matrix — Smart Contract Conversion Engine"."""
    import ast
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("demo_under_test", ROOT / "demo.py")
    demo = importlib.util.module_from_spec(spec)
    sys.modules["demo_under_test"] = demo
    try:
        spec.loader.exec_module(demo)
    finally:
        sys.modules.pop("demo_under_test", None)

    def refuse_generated(source):
        if source.startswith("contract C { broken") or "@openzeppelin" in source:
            raise RuntimeError("stderr:\nExpected ';' but got identifier")
        return {"<stdin>:X": {"abi": [], "bin": "00"}}

    vault_ir = {"functions": [{"name": "deposit"}, {"name": "withdraw"}]}
    compiled_ok = demo._source_to_deploy("contract C {}", lambda s: {"C": {"abi": [], "bin": "00"}},
                                         "C", ir=vault_ir)
    assert compiled_ok["source"] == "contract C {}" and compiled_ok["stand_in"] is False

    stand_in = demo._source_to_deploy("contract C { broken", refuse_generated, "C", ir=vault_ir)
    assert stand_in["stand_in"] is True and stand_in["source"] != "contract C { broken"
    assert "not the contract the converter generated" in stand_in["note"]
    assert "Expected ';'" in stand_in["compile_error"]

    template = demo._source_to_deploy("import \"@openzeppelin/x.sol\";", refuse_generated,
                                      "ERC721Demo", template_name="erc721")
    assert template["source"] is None and "Nothing was deployed" in template["note"]

    assert "STAND-IN" in demo._deployment_headline(True)
    assert "not the converted contract" in demo._deployment_headline(True)
    assert "STAND-IN" not in demo._deployment_headline(False)

    run_demo = next(n for n in ast.parse((ROOT / "demo.py").read_text(encoding="utf-8")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "run_demo")
    direct = [n for n in ast.walk(run_demo) if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "_make_standalone_contract"]
    assert not direct, "run_demo builds a stand-in without going through _source_to_deploy"
