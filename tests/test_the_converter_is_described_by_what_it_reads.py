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
