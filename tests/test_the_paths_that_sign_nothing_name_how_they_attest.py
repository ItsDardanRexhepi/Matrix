"""Each path docs/blockchain.md lists as signing nothing today is described by
the call it makes.

The list was introduced with "These call the same code and sign nothing today.
Each goes through `AttestationService.attest`, which resolves its schema first
and, when `blockchain.eas_schema` is not a well-formed bytes32 UID, refuses the
attestation and queues nothing". Three of its lines do not fit that:
`GasSponsor.sponsor_transaction` is not an attestation at all;
`NeoSafeRouter.route_revenue` attests through `EASClient.attest`, not the
attestation service; and the x402 limit change attests under the `payments`
component's schema, which `blockchain.schemas.payments` sets, so the shipped
example config (whose `eas_schema` is a placeholder and whose `payments` schema
is well formed) does not refuse it.

The premise is measured with the shipped example config: the primary schema is
refused and the `payments` component's schema resolves. Each line's code is then
read by AST: which attest call its function makes and under which schema, and
the line has to say so.

What this cannot see: a line whose code reference is not written as
(`file.py` `function`) or names the function outside the parentheses in another
form than `Class.method`.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_OPENING = "These call the same code and sign nothing today"


def _the_list() -> tuple[str, list[str]]:
    text = (ROOT / "docs" / "blockchain.md").read_text(encoding="utf-8")
    start = text.index(_OPENING)
    block = text[start:].split("\n\n", 2)
    preamble, bullets = block[0], [b for b in block[1].splitlines() if b.startswith("- ")]
    return preamble, bullets


def _functions(tree: ast.Module) -> dict[str, ast.AST]:
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{item.name}"] = item
                    out.setdefault(item.name, item)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _attest_calls(fn: ast.AST) -> list[tuple[str, str | None]]:
    """(route, schema) for each `.attest(...)` call in *fn*: route is
    "EASClient.attest" when the receiver is an EASClient built in the function,
    else "AttestationService.attest"; schema is the schema_uid literal."""
    eas_names = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                 and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "EASClient"
                 for t in n.targets if isinstance(t, ast.Name)}
    calls = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "attest"):
            continue
        receiver = node.func.value
        is_eas = (isinstance(receiver, ast.Name) and receiver.id in eas_names) or (
            isinstance(receiver, ast.Call) and getattr(receiver.func, "id", "") == "EASClient")
        schema = next((kw.value.value for kw in node.keywords
                       if kw.arg == "schema_uid" and isinstance(kw.value, ast.Constant)), None)
        calls.append(("EASClient.attest" if is_eas else "AttestationService.attest", schema))
    return calls


def _paths(bullet: str) -> list[tuple[str, str, list[tuple[str, str | None]]]]:
    """(file, function, attest calls) for each code reference in *bullet*."""
    out = []
    for m in re.finditer(r"\(`([\w/.]+\.py)`((?:[ ,]*`\w+`)*)\)", bullet):
        rel, names = m.group(1), re.findall(r"`(\w+)`", m.group(2))
        functions = _functions(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
        if not names:
            names = [t for t in re.findall(r"`(\w+\.\w+)`", bullet) if t in functions]
        assert names, f"no function named for {rel} in: {bullet[:80]}"
        for name in names:
            assert name in functions, f"{rel} has no {name}"
            out.append((rel, name, _attest_calls(functions[name])))
    return out


def _schemas_resolve() -> tuple[bool, bool]:
    from runtime.blockchain.services.attestation.service import AttestationService
    config = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    svc = AttestationService(config)
    answers = []
    for schema in ("primary", "payments"):
        try:
            svc._resolve_schema(schema)
            answers.append(True)
        except ValueError:
            answers.append(False)
    return answers[0], answers[1]


def _wrong(preamble: str, bullets: list[str]) -> list[str]:
    wrong = []
    routes = set()
    for bullet in bullets:
        paths = _paths(bullet)
        assert paths, f"a line with no code reference: {bullet[:80]}"
        for rel, name, calls in paths:
            if not calls:
                if not re.search(r"\bnot an attestation\b", bullet):
                    wrong.append(f"{name} makes no attest call; its line does not say it is not an attestation")
                routes.add("none")
                continue
            for route, schema in calls:
                routes.add(route)
                if route == "EASClient.attest" and "`EASClient.attest`" not in bullet:
                    wrong.append(f"{name} attests through EASClient.attest; its line does not say so")
                if route == "AttestationService.attest":
                    if schema in (None, "", "primary"):
                        if "`primary`" not in bullet:
                            wrong.append(f"{name} attests under the primary schema; its line does not say so")
                    elif f"`blockchain.schemas.{schema}`" not in bullet:
                        wrong.append(f"{name} attests under the {schema!r} component schema; "
                                     f"its line does not name blockchain.schemas.{schema}")
    if routes != {"AttestationService.attest"} and re.search(
            r"\beach (?:one )?goes through `?AttestationService\.attest", preamble, re.I):
        wrong.append(f"the opening says each goes through AttestationService.attest; the lines use {sorted(routes)}")
    if "AttestationService.attest" in routes and not (
            "`blockchain.eas_schema`" in preamble and "`blockchain.schemas.<component>`" in preamble):
        wrong.append("the opening does not say which setting each kind of schema name is resolved from")
    return wrong


def test_the_check_reads_the_old_opening_as_wrong():
    preamble, bullets = _the_list()
    old = ("These call the same code and sign nothing today. Each goes through `AttestationService.attest`, "
           "which resolves its schema first and, when `blockchain.eas_schema` is not a well-formed bytes32 "
           "UID, refuses the attestation and queues nothing:")
    assert any("the opening says each goes through" in w for w in _wrong(old, bullets))


def test_the_example_config_refuses_the_primary_schema_and_resolves_the_payments_one():
    primary, payments = _schemas_resolve()
    assert (primary, payments) == (False, True), (
        "the shipped example config's schemas resolve differently now; re-derive this check")


def test_each_path_that_signs_nothing_is_described_by_the_call_it_makes():
    assert _schemas_resolve() == (False, True), "re-derive this check"
    preamble, bullets = _the_list()
    assert len(bullets) >= 5, bullets
    wrong = _wrong(preamble, bullets)
    assert not wrong, "\n".join(wrong)


# ── Where the primary schema is read from ────────────────────────────────────
#
# The example config's schemas comment said "'primary' overrides
# blockchain.eas_schema for the core schema", schemas.py said to supply the
# primary UID via blockchain.schemas.primary, and the registration script told
# the operator to paste every UID, the primary's included, into
# blockchain.schemas.<component>. AttestationService resolves `primary` (and an
# empty name) from blockchain.eas_schema and never looks the name up in
# blockchain.schemas, and EASClient reads blockchain.eas_schema; the shipped
# example config, whose schemas.primary is well formed and whose eas_schema is a
# placeholder, has its primary schema refused.

_PRIMARY_FROM_SCHEMAS = re.compile(
    r"'primary' overrides blockchain\.eas_schema|\(blockchain\.schemas\.primary\)"
    r"|\[\"schemas\"\]\[\"primary\"\]|into config blockchain\.schemas\.<component>\.", re.I)
_PRIMARY_TEXTS = ("matrix.config.json.example", "runtime/blockchain/services/attestation/schemas.py",
                  "scripts/register_eas_schemas.py")


def _primary_is_read_from_eas_schema() -> bool:
    from runtime.blockchain.eas_client import EASClient
    from runtime.blockchain.services.attestation.service import AttestationService
    well_formed = "0x" + "ab" * 32
    config = {"blockchain": {"eas_schema": "YOUR_EAS_SCHEMA_UID", "schemas": {"primary": well_formed}}}
    try:
        AttestationService(config)._resolve_schema("primary")
        return False
    except ValueError:
        pass
    config["blockchain"]["eas_schema"] = well_formed
    return (AttestationService(config)._resolve_schema("primary") == well_formed
            and EASClient(config).eas_schema == well_formed)


def test_the_primary_scan_catches_the_old_copy():
    for old in ("Empty/malformed values fail closed. 'primary' overrides blockchain.eas_schema for the "
                "core schema.",
                'PRIMARY_SCHEMA_UID: str = ""  # config-required (blockchain.schemas.primary)',
                '# registered bytes32 via config["blockchain"]["schemas"]["primary"].',
                'print(f"# {n} schemas. After registering, paste each returned")\n'
                '    print(f"# bytes32 UID into config blockchain.schemas.<component>.\\n")'):
        assert _PRIMARY_FROM_SCHEMAS.search(old), old


def test_no_text_says_the_primary_schema_is_read_from_blockchain_schemas():
    assert _primary_is_read_from_eas_schema(), "the primary schema is read elsewhere now; re-derive this check"
    offenders = [f"{rel}: {m.group(0)!r}" for rel in _PRIMARY_TEXTS
                 for m in _PRIMARY_FROM_SCHEMAS.finditer((ROOT / rel).read_text(encoding="utf-8"))]
    assert not offenders, "\n".join(offenders)
