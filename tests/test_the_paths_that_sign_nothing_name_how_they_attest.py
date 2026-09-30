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

Where the primary schema is read from is scanned in every tracked text file.
The scan once read three files, and the bridge's own comment on its schema
constant still told the reader to supply the UID via
config["blockchain"]["schemas"]["primary"], which nothing reads; that comment is
now read against the bridge's code as well. The scan's patterns then matched
those wordings only, and schemas.py's own docstring and the comment on its
dict of schemas still said every UID, the primary's included, came from
blockchain.schemas: the patterns now read every such wording, and schemas.py's
texts are held to naming blockchain.eas_schema wherever they name
blockchain.schemas.

What this cannot see: a line whose code reference is not written as
(`file.py` `function`) or names the function outside the parentheses in another
form than `Class.method`, and a text that puts the primary schema in
blockchain.schemas in words outside the scan's patterns.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
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
#
# The patterns once matched those three wordings only. schemas.py kept "every
# UID must be supplied via config (blockchain.schemas.<component>)" in its
# docstring and "In production these are overridden via
# config["blockchain"]["schemas"]" above a dict whose first entry is the
# primary, and a planted "Put the core schema UID in blockchain.schemas.primary."
# passed.

_PRIMARY_FROM_SCHEMAS = re.compile(
    r"'primary' overrides blockchain\.eas_schema|into config blockchain\.schemas\.<component>\."
    # The primary entry named as a setting, dotted or subscripted.
    r"|\bblockchain\.schemas\.primary\b|\[[\"']schemas[\"']\]\s*\[[\"']primary[\"']\]"
    # The primary, core or platform schema said to be set in blockchain.schemas.
    r"|\b(?:primary|core|platform) schema(?: uid)?\b[^.]{0,40}\b(?:in|into|via|from|under)\s+(?:config\s+)?"
    r"[(`]*blockchain\.schemas\b"
    # Every UID said to come from blockchain.schemas, with no exception made for
    # the primary's.
    r"|\b(?:every|each|all)\b[^.]{0,60}?\buids?\b[^.]{0,80}?\bblockchain\.schemas"
    r"(?!(?:\.<?\w+>?)?[^.]{0,30}\b(?:except|the primary)\b)"
    # "These", the schemas of a dict that holds the primary, said to be overridden there.
    r"|\b(?:these|they|all of them) are overridden via config\[[\"']blockchain[\"']\]\[[\"']schemas[\"']\]",
    re.I)
_HERE = Path(__file__).resolve().relative_to(ROOT).as_posix()


def _tracked_texts() -> list[tuple[str, str]]:
    """(path, text) for every tracked file that reads as UTF-8 text, apart from
    this one, which quotes the old copy."""
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    texts = []
    for rel in out.splitlines():
        path = ROOT / rel
        if rel == _HERE or not path.is_file():
            continue
        try:
            texts.append((rel, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return texts


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
                '# "348"; a fabricated default attests against a nonexistent schema. Supply the\n'
                '# real registered UID via config["blockchain"]["schemas"]["primary"] and resolve',
                'print(f"# {n} schemas. After registering, paste each returned")\n'
                '    print(f"# bytes32 UID into config blockchain.schemas.<component>.\\n")',
                "and CANNOT be guessed or reused across chains. The defaults here are therefore\n"
                "intentionally EMPTY: every UID must be supplied via config\n"
                "(``blockchain.schemas.<component>``) as the real registered bytes32 for the",
                '# Platform schemas — maps component names to default schema UIDs.\n'
                '# In production these are overridden via config["blockchain"]["schemas"].',
                "Put the core schema UID in blockchain.schemas.primary.",
                "Set the primary schema via `blockchain.schemas`.",
                "config['blockchain']['schemas']['primary']",
                "All schema UIDs are read from blockchain.schemas."):
        assert _PRIMARY_FROM_SCHEMAS.search(old), old
    for text in ("Register with scripts/register_eas_schemas.py, then paste the resulting bytes32 UIDs into "
                 "config blockchain.schemas (the primary schema's into blockchain.eas_schema, where the code "
                 "reads it).",
                 'print("# bytes32 UID into config blockchain.schemas.<component>, except the")\n'
                 'print("# primary schema\'s, which goes in blockchain.eas_schema.\\n")',
                 "The core schema is read from blockchain.eas_schema, not from the 'primary' entry here, "
                 "which nothing reads.",
                 "set blockchain.eas_schema (or blockchain.schemas.<component>) to the registered bytes32 UID",
                 "A component's UID is supplied via config (``blockchain.schemas.<component>``)."):
        assert not _PRIMARY_FROM_SCHEMAS.search(text), (text, _PRIMARY_FROM_SCHEMAS.search(text))


def test_no_text_says_the_primary_schema_is_read_from_blockchain_schemas():
    assert _primary_is_read_from_eas_schema(), "the primary schema is read elsewhere now; re-derive this check"
    texts = _tracked_texts()
    read = {rel for rel, _ in texts}
    assert {"bridge/__init__.py", "matrix.config.json.example", "scripts/register_eas_schemas.py",
            "runtime/blockchain/services/attestation/schemas.py", "README.md"} <= read, "the scan reads less now"
    offenders = [f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)!r}" for rel, text in texts
                 for m in _PRIMARY_FROM_SCHEMAS.finditer(text)]
    assert not offenders, "\n".join(offenders)


def _schemas_module_texts() -> dict[str, str]:
    """schemas.py's module docstring and the comment directly above each of its
    module-level assignments, by the name assigned."""
    rel = "runtime/blockchain/services/attestation/schemas.py"
    source = (ROOT / rel).read_text(encoding="utf-8")
    tree, lines = ast.parse(source), source.splitlines()
    texts = {"the module docstring": ast.get_docstring(tree) or ""}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            start = node.lineno - 1
            while start and lines[start - 1].startswith("#"):
                start -= 1
            texts[getattr(target, "id", "?")] = " ".join(line.lstrip("# ") for line in lines[start:node.lineno - 1])
    return texts


def test_the_schema_module_says_its_primary_entry_is_not_read_from_blockchain_schemas():
    """PLATFORM_SCHEMAS holds a "primary" entry beside the component ones, and
    get_schema_uid reads blockchain.schemas for whatever name it is given, but
    no caller asks it for the primary: the attestation service resolves
    "primary" from blockchain.eas_schema before it looks there. So each text of
    the module that says a UID comes from blockchain.schemas also says where
    the primary's does."""
    from runtime.blockchain.services.attestation import schemas
    from runtime.blockchain.services.attestation.service import AttestationService

    assert "primary" in schemas.PLATFORM_SCHEMAS, "the primary entry moved; re-derive this check"
    assert _primary_is_read_from_eas_schema(), "the primary schema is read elsewhere now; re-derive this check"
    well_formed = "0x" + "cd" * 32
    config = {"blockchain": {"eas_schema": "", "schemas": {"payments": well_formed, "primary": well_formed}}}
    assert schemas.get_schema_uid("payments", config) == well_formed
    try:
        AttestationService(config)._resolve_schema("primary")
        raise AssertionError("the service resolved the primary from blockchain.schemas; re-derive this check")
    except ValueError:
        pass
    callers = [n for rel, text in _tracked_texts() if rel.endswith(".py") and not rel.startswith("tests/")
               for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call)
               and getattr(n.func, "id", getattr(n.func, "attr", None)) == "get_schema_uid"
               and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value in ("primary", "")]
    assert not callers, "a caller asks get_schema_uid for the primary now; re-derive this check"
    texts = _schemas_module_texts()
    assert {"the module docstring", "PRIMARY_SCHEMA_UID", "PLATFORM_SCHEMAS"} <= set(texts), sorted(texts)
    wrong = [f"{name}: {text!r}" for name, text in texts.items()
             if re.search(r"blockchain(?:\.|\W+)schemas\b", text)
             and not re.search(r"blockchain(?:\.|\W+)eas_schema\b", text)]
    assert not wrong, "\n".join(wrong)


# ── The bridge's schema constant ─────────────────────────────────────────────
#
# bridge/__init__.py's comment on EAS_SCHEMA_UID told the reader to "Supply the
# real registered UID via config["blockchain"]["schemas"]["primary"] and resolve
# it through ...get_schema_uid". Nothing in the bridge resolves a schema: the
# constant is the empty string, nothing assigns it, and bridge/deployer.py only
# copies it into the record it hashes for a deployment's UID; nothing in bridge/
# signs, sends or attests. The comment is read against that code.

_SIGNING_CALLS = {"attest", "batch_attest", "send_transaction", "send_raw_transaction",
                  "sign_transaction", "transact", "multi_attest"}
_SIGNING_MODULES = re.compile(r"^(?:web3|eth_account)\b|eas_client|eas_manager|attestation|web3_manager")


def _signs(tree: ast.AST) -> list[str]:
    """The signing or attesting calls and imports in *tree*."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _SIGNING_CALLS:
            found.append(f"calls .{node.func.attr}()")
        elif isinstance(node, ast.Import):
            found += [f"imports {a.name}" for a in node.names if _SIGNING_MODULES.search(a.name)]
        elif isinstance(node, ast.ImportFrom) and _SIGNING_MODULES.search(node.module or ""):
            found.append(f"imports from {node.module}")
    return found


def _assigns_the_schema(tree: ast.AST, definition: bool = False) -> list[int]:
    """Lines that bind EAS_SCHEMA_UID, as a name, an attribute or through
    setattr; with *definition*, one module-level annotated definition is not
    counted."""
    lines = []
    defined = [n for n in getattr(tree, "body", []) if isinstance(n, ast.AnnAssign)
               and getattr(n.target, "id", None) == "EAS_SCHEMA_UID"][:1] if definition else []
    for node in ast.walk(tree):
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
        for target in targets:
            if getattr(target, "id", getattr(target, "attr", None)) == "EAS_SCHEMA_UID" and node not in defined:
                lines.append(node.lineno)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setattr" \
                and any(isinstance(a, ast.Constant) and a.value == "EAS_SCHEMA_UID" for a in node.args):
            lines.append(node.lineno)
    return lines


def _the_bridge_schema_facts() -> list[str]:
    """What is wrong with the premises the comment is read against."""
    problems = []
    planted = ast.parse("from runtime.blockchain.eas_client import EASClient\n"
                        "w3.eth.send_raw_transaction(tx)\nbridge.EAS_SCHEMA_UID = 'x'\n")
    if len(_signs(planted)) != 2 or _assigns_the_schema(planted) != [3]:
        problems.append("the signing or assignment scan does not see a planted one")
    for rel, text in _tracked_texts():
        if not rel.endswith(".py") or rel.startswith("tests/"):
            continue
        tree = ast.parse(text)
        bound = _assigns_the_schema(tree, definition=rel == "bridge/__init__.py")
        if bound:
            problems.append(f"{rel} binds EAS_SCHEMA_UID at {bound}")
        if rel.startswith("bridge/") and _signs(tree):
            problems.append(f"{rel} {_signs(tree)}")
    constant = ast.parse((ROOT / "bridge" / "__init__.py").read_text(encoding="utf-8"))
    values = [n.value.value for n in ast.walk(constant) if isinstance(n, ast.AnnAssign)
              and getattr(n.target, "id", None) == "EAS_SCHEMA_UID" and isinstance(n.value, ast.Constant)]
    if values != [""]:
        problems.append(f"EAS_SCHEMA_UID is {values}")
    deployer = ast.parse((ROOT / "bridge" / "deployer.py").read_text(encoding="utf-8"))
    attest = next((n for n in ast.walk(deployer) if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == "_attest_deployment"), None)
    copies = attest is not None and any(
        isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "schema_uid"
                                        and getattr(v, "id", None) == "EAS_SCHEMA_UID"
                                        for k, v in zip(n.keys, n.values))
        for n in ast.walk(attest))
    hashes = attest is not None and any(isinstance(n, ast.Attribute) and n.attr == "sha256"
                                        for n in ast.walk(attest))
    if not (copies and hashes):
        problems.append("bridge/deployer.py _attest_deployment no longer hashes a record holding the schema")
    from runtime.blockchain.services.attestation.service import AttestationService
    for empty in ("", "YOUR_EAS_SCHEMA_UID", "0x1234"):
        try:
            AttestationService({"blockchain": {"eas_schema": empty}})._resolve_schema("primary")
            problems.append(f"the attestation service accepts eas_schema {empty!r}")
        except ValueError:
            pass
    return problems


def _the_bridge_schema_comment() -> str:
    lines = (ROOT / "bridge" / "__init__.py").read_text(encoding="utf-8").splitlines()
    end = next(i for i, line in enumerate(lines) if line.startswith("EAS_SCHEMA_UID"))
    start = end
    while start and lines[start - 1].startswith("#"):
        start -= 1
    return " ".join(line.lstrip("#").strip() for line in lines[start:end])


def test_the_bridges_schema_comment_says_what_the_bridge_does_with_it():
    problems = _the_bridge_schema_facts()
    assert _primary_is_read_from_eas_schema(), "the primary schema is read elsewhere now; re-derive this check"
    assert not problems, "re-derive this check: " + "; ".join(problems)
    comment = _the_bridge_schema_comment()
    wrong = []
    for needed, why in (
            (r"\bEMPTY\b[^.]*\bnothing sets it\b", "that the constant is empty and nothing sets it"),
            (r"\bThe bridge signs nothing with it\b", "that the bridge signs nothing with it"),
            (r"bridge/deployer\.py copies it into the record it hashes", "what the deployer does with it"),
            (r'reads its core schema from config\["blockchain"\]\["eas_schema"\]',
             "where the core schema is read from"),
            (r"refuses an empty or malformed one", "that an empty or malformed schema is refused")):
        if not re.search(needed, comment):
            wrong.append(f"the comment does not say {why}")
    if re.search(r"get_schema_uid|\bsupply\b", comment, re.I):
        wrong.append("the comment still tells the reader to supply or resolve the bridge's schema")
    assert not wrong, "\n".join(wrong) + "\n" + comment
