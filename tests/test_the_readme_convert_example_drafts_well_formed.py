"""The README's convert example comes back as a draft that is well formed.

The README's "Convert a contract" example posts a rental contract written as
pseudocode, its functions indented under the `contract` line, to
POST /api/v1/contracts/convert. Without the parser's layout rules for that
indentation, the indented `constructor` takes `payRent` into its body,
`payable function payRent()` comes back not payable, and no statement has the
`;` Solidity needs, so the draft does not compile.

The service is built with no `blockchain.platform_wallet`, so no platform fee
is added to the draft. The first test reads the draft, so it needs no
compiler: for each function the README declares, the draft has the function
once, its statements in order and each ended with `;`, the constructor holds
no function, and `payable` is on exactly the functions the README writes it on.
The second compiles the draft with the newest solc from 0.8.20 on that is
already installed, and is skipped where none is; it downloads nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"


def _example_source() -> str:
    text = README.read_text(encoding="utf-8")
    m = re.search(r"/api/v1/contracts/convert.*?-d\s+'(\{.*?\})'\n", text, re.S)
    assert m, "the README no longer shows a convert request with a body"
    body = json.loads(m.group(1))
    assert body["source_lang"] == "pseudocode"
    return body["source_code"]


def _declared(source: str) -> dict[str, tuple[bool, list[str]]]:
    """name -> (written payable, statements): a function line, then the lines
    indented deeper than it."""
    out: dict[str, tuple[bool, list[str]]] = {}
    current, indent = None, 0
    for line in source.splitlines():
        if not line.strip():
            continue
        m = re.match(r"(\s*)(payable\s+)?function\s+(\w+)\(", line)
        if m:
            current, indent = out.setdefault(m.group(3), (bool(m.group(2)), [])), len(m.group(1))
        elif current is not None and len(line) - len(line.lstrip()) > indent:
            current[1].append(line.strip())
        else:
            current = None
    return out


def _blocks(draft: str) -> dict[str, tuple[str, list[str]]]:
    """name -> (header, body lines) for the constructor and each function."""
    out = {}
    for m in re.finditer(r"^[ \t]*(?:constructor|function\s+(\w+))\b([^{]*)\{", draft, re.M):
        depth, i = 1, m.end()
        while depth and i < len(draft):
            depth += {"{": 1, "}": -1}.get(draft[i], 0)
            i += 1
        out[m.group(1) or "constructor"] = (
            m.group(0), [ln.strip() for ln in draft[m.end():i - 1].splitlines() if ln.strip()])
    return out


def _draft(source: str) -> str:
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService

    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(ContractConversionService({"blockchain": {}}).convert(
            source, "pseudocode"))["generated_source"]
    finally:
        logging.disable(logging.NOTSET)


def test_the_readme_example_draft_has_each_function_once_ended_and_payable_where_written():
    source = _example_source()
    declared = _declared(source)
    assert set(declared) == {"constructor", "payRent"}, "precondition: the example's functions"
    draft = _draft(source)
    blocks = _blocks(draft)

    assert set(blocks) == set(declared), blocks.keys()
    assert len(re.findall(r"\bfunction\b", draft)) == len(declared) - 1, (
        "the draft declares a function the README does not, or declares one twice")
    assert not re.search(r"\bfunction\b", "\n".join(blocks["constructor"][1])), (
        "the constructor holds a function declaration")
    for name, (payable, statements) in declared.items():
        header, body = blocks[name]
        assert body == [s + ";" for s in statements], (name, body)
        assert bool(re.search(r"\bpayable\b", header)) == payable, (name, header)


def _installed_solc():
    try:
        import solcx

        versions = [v for v in solcx.get_installed_solc_versions()
                    if (v.major, v.minor) == (0, 8) and v.micro >= 20]
    except Exception:
        return None
    return max(versions) if versions else None


def test_the_readme_example_draft_compiles_where_a_solc_is_installed():
    version = _installed_solc()
    if version is None:
        pytest.skip("no solc 0.8.20 or later is installed, and nothing is downloaded")
    import solcx

    compiled = solcx.compile_source(_draft(_example_source()), solc_version=version)
    assert any(name.endswith(":Rental") for name in compiled), compiled.keys()
