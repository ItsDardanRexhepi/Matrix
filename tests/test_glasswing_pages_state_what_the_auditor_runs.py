"""What the Glasswing pages and course say the audit checks is what the auditor runs.

web/glasswing.html and web/audit.html each listed twelve "vulnerability
classes" — two different lists — and course-02 module 04 a third, with SWC ids
and severities. `ContractAuditor.audit` (runtime/security/audit.py) runs a fixed
list of pattern checks, and none of the three lists was it: the pages promised
oracle-manipulation, flash-loan, MEV, upgrade-proxy, uninitialized-storage and
missing-event checks the auditor does not have, and left out the tx.origin,
selfdestruct, unbounded-loop and locked-ether checks it does. The same pages
offered "manual expert code review", "manual review checklists" and a
"professional security audit" (and web/conversion-service.html "full audit +
manual review") on a gateway whose audit routes answer 503
because no audit service exists (tests/test_documented_endpoints_are_registered.py).

Everything here is derived from `audit.py`, never typed in:

  * the check list is read from the `checks = [...]` literal in `audit()`, and
    each check's rule id and severity from its method body;
  * each listed class on a page or in the course must name exactly one check
    (every word of the check's name appears in the item), each check must be
    named by exactly one item, and the list is exactly as long as the checks;
  * every "N-point" / "N vulnerability classes" / "N attack classes" count on
    those surfaces must equal the measured number of checks;
  * the course table's rule id and severity columns must be the check's own;
  * with the audit routes measured as always unavailable, none of the surfaces
    may offer manual, expert or professional review, or a standalone audit
    submission.

What this cannot see: a class list written outside the `vuln-item` markup or
the course table, and a review promise worded outside the phrase list.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.test_documented_endpoints_are_registered import _always_unavailable_handlers

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "runtime" / "security" / "audit.py"
PAGES = ["web/glasswing.html", "web/audit.html"]
COURSE = "education/course-02-smart-contract-security/04-using-glasswing.md"
# Every served page or course module that describes an audit offering.
REVIEW_SURFACES = PAGES + [COURSE, "web/conversion-service.html"]
COUNT_SURFACES = PAGES + [COURSE, "education/course-02-smart-contract-security/README.md",
                          "education/course-02-smart-contract-security/01-why-contracts-get-hacked.md"]

_ITEM = re.compile(r'<div class="vuln-item"><div class="vuln-num">\d+</div>(.*?)</div>')
_COURSE_ROW = re.compile(r"^\|\s*\d+\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", re.M)
_COUNT = re.compile(r"\b(\d+)(?:-point| (?:vulnerability|attack) class(?:es)?)", re.I)


def _auditor_checks() -> list[tuple[str, str, str]]:
    """(method name, rule id, severity) for each check `audit()` runs, in order."""
    source = AUDIT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ContractAuditor")
    audit = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "audit")
    names: list[str] = []
    for node in ast.walk(audit):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "checks"):
            names = [e.attr for e in node.value.elts]
    assert names, "audit() has no `checks = [...]` list"
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    out = []
    for name in names:
        body = ast.get_source_segment(source, methods[name])
        rule = re.search(r'rule_id="([^"]+)"', body)
        sev = re.search(r"severity=Severity\.([A-Z]+)", body)
        assert rule and sev, name
        out.append((name, rule.group(1), sev.group(1).lower()))
    return out


def _words(check: str) -> list[str]:
    return check[len("_check_"):].split("_")


def _matches(item: str, check: str) -> bool:
    low = item.lower()
    return all(w in low for w in _words(check))


def _page_items(rel: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", m.group(1)).strip()
            for m in _ITEM.finditer((ROOT / rel).read_text(encoding="utf-8"))]


def _course_rows() -> list[tuple[str, str, str]]:
    text = (ROOT / COURSE).read_text(encoding="utf-8")
    section = re.search(r"^## The .*?Scan\s*$(.*?)(?=^## )", text, re.M | re.S)
    assert section, "course-02 module 04 has no scan section"
    return _COURSE_ROW.findall(section.group(1))


def _bijection_problems(items: list[str], checks: list[str]) -> list[str]:
    problems = []
    if len(items) != len(checks):
        problems.append(f"{len(items)} classes listed, the auditor runs {len(checks)} checks")
    for item in items:
        hit = [c for c in checks if _matches(item, c)]
        if len(hit) != 1:
            problems.append(f"{item!r} names {len(hit)} of the auditor's checks: {hit}")
    for check in checks:
        hit = [i for i in items if _matches(i, check)]
        if len(hit) != 1:
            problems.append(f"{check} is named by {len(hit)} listed classes: {hit}")
    return problems


def test_the_check_list_is_read_from_the_auditor():
    checks = _auditor_checks()
    from runtime.security.audit import ContractAuditor
    assert {n for n, _r, _s in checks} == {
        m for m in dir(ContractAuditor) if m.startswith("_check_")}, "audit() skips a check"
    assert {"_check_reentrancy", "_check_tx_origin"} <= {n for n, *_ in checks}
    assert all(s in {"critical", "high", "medium", "low", "info"} for _n, _r, s in checks)


def test_the_matcher_is_not_vacuous():
    checks = ["_check_reentrancy", "_check_tx_origin", "_check_unbounded_loop"]
    assert not _bijection_problems(["Reentrancy", "tx.origin authorization", "Unbounded loops"], checks)
    old_page = ["Reentrancy detection", "Oracle manipulation risks", "Flash loan attack vectors"]
    assert _bijection_problems(old_page, checks)
    assert _bijection_problems(["Reentrancy", "Reentrancy again", "Unbounded loops"], checks)


def test_each_page_lists_exactly_the_checks_the_auditor_runs():
    checks = [n for n, _r, _s in _auditor_checks()]
    problems = []
    for rel in PAGES:
        problems.extend(f"{rel}: {p}" for p in _bijection_problems(_page_items(rel), checks))
    assert not problems, "\n".join(problems)


def test_the_course_table_is_the_auditor_with_its_own_rule_ids_and_severities():
    checks = _auditor_checks()
    rows = _course_rows()
    problems = _bijection_problems([r[0] for r in rows], [n for n, *_ in checks])
    for category, rule, severity in rows:
        for name, rule_id, sev in checks:
            if _matches(category, name):
                if rule != rule_id:
                    problems.append(f"{category!r}: rule id {rule!r}, the auditor emits {rule_id!r}")
                if severity.strip().lower() != sev:
                    problems.append(f"{category!r}: severity {severity!r}, the auditor emits {sev!r}")
    assert not problems, "\n".join(f"{COURSE}: {p}" for p in problems)


def test_every_stated_count_is_the_number_of_checks():
    count = len(_auditor_checks())
    problems = []
    for rel in COUNT_SURFACES:
        for lineno, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            for m in _COUNT.finditer(line):
                if int(m.group(1)) != count:
                    problems.append(f"{rel}:{lineno}: {m.group(0)!r} (the auditor runs {count})")
    assert not problems, "\n".join(problems)


_REVIEW_CLAIMS = [
    r"manual (?:expert )?(?:code )?review",
    r"expert (?:code )?review",
    r"professional(?:ly)?(?: \S+){0,4} audit",
    r"submit existing contracts for standalone audits",
]


def test_the_review_scan_catches_the_old_copy():
    old = ("Manual expert code review. Get your contracts audited with manual review checklists. "
           "Verifiable proof your contract passed a professional security audit; your protocol "
           "has been professionally audited. You can also submit existing contracts for standalone audits.")
    assert sum(bool(re.search(p, old.lower())) for p in _REVIEW_CLAIMS) == 4
    # The heading form the first pattern list could not see: the adjective and
    # "audit" separated by the product words.
    heading = "Professional Smart Contract Security Auditing, powered by Glasswing."
    assert re.search(_REVIEW_CLAIMS[2], heading.lower())
    assert not re.search(_REVIEW_CLAIMS[2], "Automated Smart Contract Security Scanning")


def test_no_audit_surface_offers_review_no_service_performs():
    assert {"handle_audit_request", "handle_audit_report"} <= _always_unavailable_handlers(), (
        "an audit service is wired now; re-derive this check")
    offenders = []
    for rel in REVIEW_SURFACES:
        text = re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))
        flat = re.sub(r"\s+", " ", text).lower()
        for pattern in _REVIEW_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 20]}...")
    assert not offenders, "\n".join(offenders)
