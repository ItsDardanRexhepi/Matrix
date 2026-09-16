"""The contract name the template branch pastes into ``contract {{NAME}} is ...``.

ContractConversionService.convert took the name the pseudocode parser found and
substituted it into the template unchecked. The parser takes the first word
after "contract", "class", "module" or "token", so ordinary prose ("... where
every token is unique ...") names the contract ``is``. The template branch then
reported status "success" with the audit passed, for source solc rejects:

    is, 2026Drop, Gällery         Error 2314  Expected identifier
    ERC721, Strings, Context,     Error 2333  Identifier already declared
    IERC165, IOpenMatrixFeeToken
    mint                          Error 5796  Functions are not allowed to have
                                              the same name as the contract

A name is used only if it is an ASCII Solidity identifier, is not a keyword,
reserved word or builtin, is not a name the template's imports put in its file
scope (templates.TEMPLATE_IMPORTED_SYMBOLS, recorded from the compiler's AST and
re-checked against it by the tests), and does not appear as an identifier in the
template or in the fee logic RevenueEnforcer adds. Otherwise the contract is
named FALLBACK_CONTRACT_NAME and the caller is told what was replaced and why.

The checks are deliberately wider than what solc strictly rejects: a name that
only shadows a builtin, or merely appears in the template text, is replaced too.
Replacing a usable name costs the caller a rename they are told about; pasting
an unusable one cost them a contract that does not compile, reported as a
success.
"""

from __future__ import annotations

import re

from runtime.blockchain.services.contract_conversion.revenue_enforcer import (
    INJECTED_SNIPPETS,
)
from runtime.blockchain.services.contract_conversion.templates import (
    TEMPLATE_IMPORTED_SYMBOLS,
)

FALLBACK_CONTRACT_NAME = "ArtContract"

# Keywords, reserved words, literals, units and non-elementary type names from
# the solc 0.8.20 grammar, plus contextual words (error, revert, global, from,
# transient, layout, at) that are identifiers in some positions only.
# Elementary sized types (uint256, bytes32, fixed128x18 ...) are matched by
# _ELEMENTARY_TYPE rather than listed.
_KEYWORDS = frozenset("""
    abstract address after alias anonymous apply as assembly at auto bool break
    byte bytes calldata case catch constant constructor continue contract copyof
    days default define delete do else emit enum error ether event external
    fallback false final finney fixed for from function global gwei hex hours if
    immutable implements import in indexed inline int interface internal is
    layout leave let library macro mapping match memory minutes modifier mutable
    new null of override partial payable pragma private promise public pure
    receive reference relocatable return returns revert sealed seconds sizeof
    static storage string struct super supports switch szabo this throw transient
    true try type typedef typeof ufixed uint unchecked unicode using var view
    virtual weeks wei while years
""".split())

# Global names solc defines. Naming the contract one of these shadows it in the
# template's file scope.
_BUILTINS = frozenset("""
    abi addmod assert block blobhash blockhash ecrecover gasleft keccak256 log0
    log1 log2 log3 log4 msg mulmod now require ripemd160 selfdestruct sha256 sha3
    suicide tx
""".split())

_ELEMENTARY_TYPE = re.compile(r"(?:u?int|bytes)\d+|u?fixed\d+x\d+")
# `$` is legal in Solidity, but RevenueEnforcer locates the contract with
# `contract\s+\w+`, so a name it cannot find is not accepted either.
_ASCII_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMMENT_OR_STRING = re.compile(
    r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_IDENTIFIER_TOKEN = re.compile(r"(?<![A-Za-z0-9_$])[A-Za-z_$][A-Za-z0-9_$]*")


def identifiers_in(source: str) -> frozenset[str]:
    """Every identifier-shaped token in Solidity *source*, outside comments and
    string literals. Template placeholders (``{{NAME}}``) are not identifiers."""
    code = _COMMENT_OR_STRING.sub(" ", source.replace("{{NAME}}", " "))
    return frozenset(_IDENTIFIER_TOKEN.findall(code))


_FEE_IDENTIFIERS = frozenset().union(*(identifiers_in(s) for s in INJECTED_SNIPPETS))


def unusable_because(name: str, template_name: str, template_source: str) -> str | None:
    """Why *name* cannot be the contract in *template_name*, or None if it can."""
    if not _ASCII_IDENTIFIER.fullmatch(name or ""):
        return ("not a Solidity identifier: ASCII letters, digits and _ only, "
                "not starting with a digit")
    if name in _KEYWORDS or _ELEMENTARY_TYPE.fullmatch(name):
        return "a Solidity keyword, reserved word or type name"
    if name in _BUILTINS:
        return "the name of a Solidity builtin"
    if name in TEMPLATE_IMPORTED_SYMBOLS.get(template_name, frozenset()):
        return f"already declared by the {template_name} template's imports"
    if name in identifiers_in(template_source) or name in _FEE_IDENTIFIERS:
        return f"already used in the {template_name} template or its fee logic"
    return None


def template_contract_name(
    requested: str, template_name: str, template_source: str,
) -> tuple[str, str | None]:
    """``(name to use, reason the requested one was replaced or None)``."""
    reason = unusable_because(requested, template_name, template_source)
    if reason is None:
        return requested, None
    return FALLBACK_CONTRACT_NAME, reason
