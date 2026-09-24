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
because no audit service is wired to them.

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

  * with nothing taking an order, no PDF writer, no gas check in the auditor
    and no test writer in the converter, none of those surfaces may list a
    deliverable nothing produces (a PDF report, gas optimisation, monitoring,
    a support channel, turnaround, a re-audit, test coverage, a client
    portfolio and the rest of the phrase list).

What this cannot see: a class list written outside the `vuln-item` markup or
the course table, and a review promise or a deliverable worded outside the
phrase lists.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

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


def _access_control_functions() -> list[str]:
    """The function names `_check_missing_access_control` inspects, read from
    its `sensitive` list."""
    tree = ast.parse(AUDIT.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_check_missing_access_control")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "sensitive"):
            return [e.elts[1].value for e in node.value.elts]
    raise AssertionError("_check_missing_access_control has no `sensitive` list")


_WIDER_THAN_THE_CHECK = re.compile(
    r"state-changing|\ball functions\b|\bany function\b|\badmin functions\b|\bprivileged\b", re.I)


def _access_control_row_problems(item: str) -> list[str]:
    problems = [f"{item!r} does not name {name}()" for name in _access_control_functions()
                if not re.search(rf"\b{name}\b", item)]
    if _WIDER_THAN_THE_CHECK.search(item):
        problems.append(f"{item!r} claims more than the functions the check reads")
    return problems


def test_the_access_control_row_names_the_functions_the_check_reads():
    """AC-001 reads seven named functions (mint, burn, pause, unpause, upgrade,
    setOwner, transferOwnership) and only their signatures. The pages and the
    course listed it as "Missing access control on state-changing functions",
    so a setPrice() or withdraw() with no access control, which the check never
    looks at, read as covered."""
    assert _access_control_functions()[:2] == ["mint", "burn"]
    assert _access_control_row_problems("Missing access control on state-changing functions")
    problems = []
    for rel in PAGES:
        problems += [f"{rel}: {p}" for item in _page_items(rel)
                     if _matches(item, "_check_missing_access_control")
                     for p in _access_control_row_problems(item)]
    problems += [f"{COURSE}: {p}" for category, _rule, _sev in _course_rows()
                 if _matches(category, "_check_missing_access_control")
                 for p in _access_control_row_problems(category)]
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


def _audit_service_is_never_wired() -> bool:
    """True when gateway/server.py assigns `self.audit_service` nothing but
    None, so both audit handlers answer 503 whatever the request carries."""
    tree = ast.parse((ROOT / "gateway" / "server.py").read_text(encoding="utf-8"))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "audit_service":
                    values.append(node.value)
        if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setattr"
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "audit_service"):
            values.append(None)
    return bool(values) and all(isinstance(v, ast.Constant) and v.value is None for v in values)


def test_no_audit_surface_offers_review_no_service_performs():
    assert _audit_service_is_never_wired(), (
        "an audit service is wired now; re-derive this check")
    offenders = []
    for rel in REVIEW_SURFACES:
        text = re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))
        flat = re.sub(r"\s+", " ", text).lower()
        for pattern in _REVIEW_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 20]}...")
    assert not offenders, "\n".join(offenders)


# ── Sibling axis: an offering lists deliverables nothing produces ───────────
#
# Under their "Not available to order" banners the audit tiers still listed,
# at prices, a PDF report delivered within 48 hours, gas optimisation analysis,
# code quality scoring, a best-practices compliance check, inline annotations,
# priority turnaround, a free re-audit, an executive summary, deployment
# readiness certification, ongoing contract monitoring and a dedicated support
# channel; the conversion page promised a "fully audited" contract with
# "comprehensive test coverage", a 30-day support window, SLA-backed
# turnaround, revision requests, a priority queue, custom template creation
# and direct engineering support, and showed six contracts "we have generated
# for clients" with line counts and quality grades. The audit is the twelve
# checks audit() runs, returned as a report; the converter writes no tests;
# no route takes an order for either, and nothing in the code produces the
# rest. A banner that says a tier cannot be ordered does not say its features
# do not exist. The list also names the tiers' own wording that its first
# patterns let through: "re-audit, and deployment certification", "priority
# re-audit after fixes", a price per audit and a badge included in one.

_DELIVERABLE_CLAIMS = [
    r"\bpdf\b",
    r"gas[- ]optimi[sz](?:ation|ed)",
    r"code quality scor",
    r"best[- ]practices? compliance",
    r"inline (?:code )?annotations?",
    r"executive summary",
    r"readiness certification",
    r"\bmonitoring\b",
    r"support (?:channel|window)",
    r"engineering support",
    r"\bsla\b|sla-backed",
    r"turnaround",
    r"delivered within",
    r"(?:free|priority) re-audit",
    r"re-audits? after fix",
    r"deployment (?:readiness )?certification",
    r"within \d+ (?:business )?(?:hours?|days?|weeks?)",
    r"dedicated support",
    r"\$\s?\d[\d,.]* per audit",
    r"badge included",
    r"revision requests?",
    r"priority (?:queue|processing)",
    r"custom template",
    r"test coverage",
    r"fully audited",
    r"generated for (?:our )?clients",
    r"\b[a-f][+-]? quality\b",
]
_PDF_WRITERS = ("reportlab", "fpdf", "weasyprint", "pdfkit", "xhtml2pdf", "pypdf")


def _nothing_produces_the_deliverables() -> list[str]:
    """The premises, measured: why none of the listed deliverables exists."""
    problems = []
    if not _audit_service_is_never_wired():
        problems.append("an audit service is wired now")
    for root in ("runtime", "gateway"):
        for path in (ROOT / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for lib in _PDF_WRITERS:
                if re.search(rf"^\s*(?:import|from)\s+{lib}\b", text, re.M):
                    problems.append(f"{path.relative_to(ROOT)} imports {lib}")
    if any("gas" in name for name, _r, _s in _auditor_checks()):
        problems.append("audit() runs a gas check now")
    conversion = "\n".join(p.read_text(encoding="utf-8") for p in sorted(
        (ROOT / "runtime" / "blockchain" / "services" / "contract_conversion").glob("*.py")))
    if re.search(r"\.t\.sol|function test|forge test", conversion):
        problems.append("the converter writes tests now")
    routes = "\n".join((ROOT / "gateway" / f).read_text(encoding="utf-8")
                       for f in ("server.py", "service_routes.py"))
    if re.search(r"add_(?:post|put)\(\s*[\"'][^\"']*(?:/services/conversion|/audit/order)", routes):
        problems.append("a conversion or audit order route is registered now")
    return problems


def _deliverable_offenders(rel: str, raw: str) -> list[str]:
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).lower()
    out = []
    for pattern in _DELIVERABLE_CLAIMS:
        for m in re.finditer(pattern, flat):
            out.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 30]}...")
    return out


def test_the_deliverable_scan_catches_the_old_copy():
    old = ("<li>PDF report delivered within 48 hours</li><li>Gas optimisation analysis</li>"
           "<li>Code quality scoring</li><li>Best practices compliance check</li>"
           "<li>Inline code annotations</li><li>Priority turnaround</li>"
           "<li>One free re-audit after fixes are applied</li><li>Executive summary</li>"
           "<li>Deployment readiness certification</li><li>Ongoing contract monitoring</li>"
           "<li>Dedicated support channel</li><li>30-day support window</li>"
           "<li>SLA-backed turnaround</li><li>Revision requests included</li>"
           "<li>Priority queue</li><li>Custom template creation</li>"
           "<li>Direct engineering support</li> a fully audited, gas-optimised contract with comprehensive "
           "test coverage. Types of contracts we have generated for clients: "
           "<strong>A+</strong> quality"
           # The tiers as web/audit.html and web/glasswing.html last listed them.
           "<li>PDF-ready structured output</li><div>$299 per audit</div>"
           "<p>Full audit with remediation, re-audit, and deployment certification</p>"
           "<li>Priority re-audit after fixes</li><li>Delivered within 1 week</li>"
           "<p>Automated 12-point scan with full PDF report</p>"
           "<li>First-year Glasswing Verified badge included</li>")
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", old)).lower()
    hits = {p for p in _DELIVERABLE_CLAIMS if re.search(p, flat)}
    assert hits == set(_DELIVERABLE_CLAIMS), set(_DELIVERABLE_CLAIMS) - hits
    # What the pages may still say: the scan, its report and a user re-running it.
    assert not _deliverable_offenders("x", "Glasswing runs 12 checks and returns a report; "
                                           "fix and re-audit after every change.")


def test_no_offering_lists_a_deliverable_nothing_produces():
    premises = _nothing_produces_the_deliverables()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    offenders = []
    for rel in REVIEW_SURFACES:
        offenders += _deliverable_offenders(rel, (ROOT / rel).read_text(encoding="utf-8"))
    assert not offenders, "\n".join(offenders)


_HERO_STAT = re.compile(
    r'<div class="hero-stat-num">([^<]*)</div>\s*<div class="hero-stat-label">([^<]*)</div>')
_CONVERSION = "runtime/blockchain/services/contract_conversion"


def _templates_the_converter_starts_from() -> set[str]:
    """The templates a conversion can start from: the artist classifier's
    recommendations (its category map and its fallback), the only thing the
    service passes to get_template()."""
    from runtime.blockchain.services.contract_conversion.artist_classifier import _TEMPLATE_MAP
    source = (ROOT / _CONVERSION / "artist_classifier.py").read_text(encoding="utf-8")
    fallbacks = re.findall(r'recommended_template = (?:_TEMPLATE_MAP\.get\([^,]+,\s*)?"(\w+)"', source)
    service = (ROOT / _CONVERSION / "service.py").read_text(encoding="utf-8")
    convert = next(n for n in ast.walk(ast.parse(service))
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "convert")
    body = ast.get_source_segment(service, convert)
    calls = re.findall(r"get_template\(([^)]*)\)", body)
    assert calls == ["template_name"], f"convert() picks a template some other way now: {calls}"
    assert 'template_name = artist_info["recommended_template"]' in body
    return set(_TEMPLATE_MAP.values()) | set(fallbacks)


def test_the_conversion_page_stats_are_measured_counts():
    """The conversion page's stats bar said "12 Contract Types", "100% Audit
    Included" and "<5min Generation Time", and then "8 Templates": templates.py
    holds eight, and a conversion can start from two of them. A stat must be
    one of the counts measured here."""
    from runtime.blockchain.services.contract_conversion.parser import SUPPORTED_LANGUAGES

    measured = {"source languages": len(SUPPORTED_LANGUAGES),
                "templates it starts from": len(_templates_the_converter_starts_from()),
                "automated checks": len(_auditor_checks())}
    stats = _HERO_STAT.findall((ROOT / "web" / "conversion-service.html").read_text(encoding="utf-8"))
    assert stats, "web/conversion-service.html has no stats bar"
    problems = []
    for number, label in stats:
        want = measured.get(label.strip().lower())
        if want is None:
            problems.append(f"{number} {label!r}: not a count this test measures")
        elif number.strip() != str(want):
            problems.append(f"{number} {label!r}: the code has {want}")
    assert not problems, "\n".join(problems)


def _cards(html: str, grid_id: str) -> list[str]:
    grid = re.search(rf'<div class="portfolio-grid" id="{grid_id}">(.*?)</div>\s*(?:</section>|<p)',
                     html, re.S)
    assert grid, f"no portfolio grid #{grid_id}"
    return re.findall(r'<div class="portfolio-name">([^<]+)</div>', grid.group(1))


def test_the_template_cards_are_the_ones_the_converter_starts_from():
    """The page listed all eight templates as "the contracts the converter can
    start from". The converter reaches get_template() only through the artist
    classifier, whose recommendations are erc721 and erc1155."""
    from runtime.blockchain.services.contract_conversion.templates import list_templates

    used = _templates_the_converter_starts_from()
    names = {t["name"] if isinstance(t, dict) else t for t in list_templates()}
    assert used < names, "precondition: the converter starts from some of the templates, not all"
    html = (ROOT / "web" / "conversion-service.html").read_text(encoding="utf-8")
    assert sorted(_cards(html, "templates-used")) == sorted(used)
    assert sorted(_cards(html, "templates-unused")) == sorted(names - used)
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).lower()
    assert "the contracts the converter can start from" not in flat


# ── Sibling axis: what a finding's description says ────────────────────────
#
# The audit pages said each finding carries "a description that says how to
# fix it", the audit page's hero "findings with remediation guidance", and
# course 01 "a description with a suggested fix". Three of the twelve checks
# state the problem and no fix: locked ether ("Funds will be locked"),
# unprotected selfdestruct ("Anyone can destroy this contract") and timestamp
# dependence.

_FIX_VERB = re.compile(r"(?:^|[.;]\s+)(?:Use|Add|Apply|Capture|Ensure|Consider|Pin|Replace|Remove|"
                       r"Require|Upgrade|Check|Move|Restrict|Emit)\b")
_EVERY_FINDING_HAS_A_FIX = [
    r"description that says how to fix",
    r"description with a suggested fix",
    r"findings? with remediation guidance",
    r"(?:each|every) finding[^.]{0,80}?(?:how to fix|suggested fix|remediation)",
]


def _check_descriptions() -> dict[str, list[str]]:
    """Each check's description strings, the constant text of every
    `description=` in its method."""
    source = AUDIT.read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(source).body
               if isinstance(n, ast.ClassDef) and n.name == "ContractAuditor")
    out: dict[str, list[str]] = {}
    for fn in cls.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("_check_")):
            continue
        texts = []
        for node in ast.walk(fn):
            if isinstance(node, ast.keyword) and node.arg == "description":
                parts = [c.value for c in ast.walk(node.value)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str)]
                texts.append("".join(parts))
        out[fn.name] = texts
    return out


def test_the_fix_claim_scan_catches_the_old_copy():
    old = ("for each finding its rule id, severity, title, a description that says how to fix it. "
           "returns its findings with remediation guidance. each finding also carries a "
           "description with a suggested fix and the code it points at.")
    assert {p for p in _EVERY_FINDING_HAS_A_FIX if re.search(p, old)} == set(_EVERY_FINDING_HAS_A_FIX)
    assert not any(re.search(p, "a one-line description of the problem; most checks also "
                                "suggest a fix") for p in _EVERY_FINDING_HAS_A_FIX)


def test_no_text_says_every_finding_says_how_to_fix_it():
    descriptions = _check_descriptions()
    assert set(descriptions) == {n for n, _r, _s in _auditor_checks()}
    without = sorted(n for n, texts in descriptions.items()
                     if texts and not all(_FIX_VERB.search(t) for t in texts))
    if not without:
        return  # every check suggests a fix now; the claim is not contradicted
    with_fix = len(descriptions) - len(without)
    assert with_fix * 2 > len(descriptions), (
        f"only {with_fix} of {len(descriptions)} checks suggest a fix; 'most' is no longer true")
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel in {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}:
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))).lower()
        for pattern in _EVERY_FINDING_HAS_A_FIX:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 30]}... "
                                 f"({', '.join(without)} give no fix)")
    assert not offenders, "\n".join(offenders)


# ── Sibling axis: the quoted conversion tiers a source can reach ────────────
#
# The conversion page quoted 0.01, 0.05 or 0.1 ETH, and docs/blockchain.md
# "0.05 ETH below 500; 0.1 ETH above". The complexity score starts at the
# non-blank line count, and a score of 200 (the default custom_threshold) makes
# the quote "negotiated", so with the default no source reaches the 0.1 ETH
# tier for 500 lines and more.

_QUOTE_SURFACES = {
    "web/conversion-service.html": re.compile(r'<section class="section" id="returns">(.*?)</section>', re.S),
    "docs/blockchain.md": re.compile(r"^\| Contract conversion tier.*$", re.M),
}


def _reachable_quotes() -> set[float]:
    from runtime.blockchain.services.contract_conversion.tier_manager import TierManager
    manager = TierManager({})
    return {manager.classify("\n".join(["uint256 a;"] * n))["fee_eth"] for n in range(1, 700)}


def test_every_quoted_tier_is_one_a_source_reaches_or_says_what_it_takes():
    from runtime.blockchain.services.contract_conversion.tier_manager import _TIERS

    reachable = _reachable_quotes()
    unreachable = sorted(fee for _n, _m, fee in _TIERS if fee not in reachable)
    assert unreachable == [0.1], f"precondition changed: unreachable by default = {unreachable}"
    problems = []
    for rel, section in _QUOTE_SURFACES.items():
        found = section.search((ROOT / rel).read_text(encoding="utf-8"))
        assert found, f"{rel}: the conversion quote text is not where this test reads it"
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", found.group(0))).lower()
        for fee in unreachable:
            if f"{fee:g} eth" in flat and "custom_threshold" not in flat:
                problems.append(f"{rel}: quotes {fee:g} ETH without saying it takes a raised "
                                "conversion.custom_threshold")
        if re.search(r"0\.1 eth above", flat):
            problems.append(f"{rel}: '0.1 ETH above' 500 lines is not reached with the default threshold")
    assert not problems, "\n".join(problems)


# ── Sibling axis: the badge widget and the key it needs ─────────────────────
#
# The Glasswing page said the widget "automatically displays your badge status".
# /badge/widget.js and /badge/{id}/status are not in the gateway's public set,
# so on a gateway with an API key set a visitor's browser is answered 401 on
# both and the widget does not load.

_WIDGET_CLAIM = re.compile(r"widget[^.]{0,80}?(?:displays|shows)[^.]{0,40}?badge(?:'s)? status")


def _badge_widget_paths_are_public() -> bool:
    import gateway.server as server
    source = Path(server.__file__).read_text(encoding="utf-8")
    block = source[source.index("self._public_paths"):]
    block = block[:block.index("}")]
    return "/badge/widget.js" in block


def test_the_widget_is_described_with_the_key_it_needs():
    if _badge_widget_paths_are_public():
        return  # the widget script is public now; the qualification is not needed
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel in {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}:
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))).lower()
        for m in _WIDGET_CLAIM.finditer(flat):
            around = flat[max(0, m.start() - 300):m.end() + 300]
            if "401" not in around:
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)


# ── Sibling axis: subscription tiers that promise what nothing performs ─────
#
# The phrase scan above read only the audit and conversion surfaces. The
# landing page's pricing listed, for Pro and Enterprise, a managed cloud
# gateway, priority API access, email support with a 24h SLA, a usage
# analytics dashboard, dedicated infrastructure, custom agent training, SSO and
# team management, priority support with a 4h SLA, a 99.9% SLA guarantee and an
# on-prem deployment option, behind a "Start Pro Trial" button; course 01's
# gateway module tied API keys to tiers with "priority processing", "dedicated
# support" and "custom plugins". Every capability in the catalog is free tier,
# and nothing in the gateway reads a subscription to decide anything. This
# scan reads every public page and document. The README's section on the MTRX
# app's hosted plans is the app's, which this repository cannot measure, and
# is not read.

_TIER_PROMISES = [
    r"\bsla\b",
    r"priority (?:support|api access|processing|queue)",
    r"dedicated (?:support|infrastructure)",
    r"custom (?:agent training|plugins)",
    r"on-prem(?:ise)? deployment option",
    r"managed cloud (?:gateway|hosting)",
    r"usage analytics dashboard",
    r"start (?:a |your )?pro trial",
    r"contact sales",
    r"premium tiers add",
    r"api keys are tied to subscription tiers",
]
_APP_PLANS_HEADING = re.compile(r"^## [^\n]*\(the hosted app\)[^\n]*$", re.M)


def _nothing_reads_a_subscription() -> list[str]:
    problems = []
    from runtime.capabilities.catalog import CAPABILITIES
    tiers = {c["min_tier"] for c in CAPABILITIES}
    if tiers != {"free"}:
        problems.append(f"the catalog has capabilities above free tier now: {sorted(tiers)}")
    out = subprocess.check_output(["git", "ls-files", "gateway/*.py", "runtime/*.py"], cwd=ROOT, text=True)
    for rel in out.splitlines():
        if rel == "runtime/monetization/entitlement_store.py" or not (ROOT / rel).is_file():
            continue
        if re.search(r"\.(?:active_tier_for|entitlements_for)\(", (ROOT / rel).read_text(encoding="utf-8")):
            problems.append(f"{rel} reads a subscription tier now")
    return problems


def _without_the_app_plans(rel: str, text: str) -> str:
    if rel != "README.md":
        return text
    m = _APP_PLANS_HEADING.search(text)
    if not m:
        return text
    end = text.find("\n## ", m.end())
    return text[:m.start()] + (text[end:] if end != -1 else "")


def test_the_tier_promise_scan_catches_the_old_copy():
    old = ("premium tiers add managed infrastructure and priority support. managed cloud hosting. "
           "priority api access. email support (24h sla). usage analytics dashboard. custom agent "
           "training. dedicated infrastructure. on-prem deployment option. start pro trial. contact "
           "sales. api keys are tied to subscription tiers: all services, priority processing; "
           "dedicated support, custom plugins")
    hits = {p for p in _TIER_PROMISES if re.search(p, old)}
    assert hits == set(_TIER_PROMISES), set(_TIER_PROMISES) - hits
    assert not any(re.search(p, "every capability in the catalog is free tier; pro and enterprise "
                                "are the app's subscription tiers, and nothing here changes with "
                                "the tier.") for p in _TIER_PROMISES)
    readme = "intro\n## Subscription Tiers (the hosted app)\n| Priority support |\n## Web\nsla here"
    assert "Priority support" not in _without_the_app_plans("README.md", readme)
    assert "sla here" in _without_the_app_plans("README.md", readme)


def test_no_public_text_promises_a_tier_nothing_performs():
    premises = _nothing_reads_a_subscription()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel in {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}:
            continue
        if not (ROOT / rel).is_file():
            continue
        text = _without_the_app_plans(rel, (ROOT / rel).read_text(encoding="utf-8"))
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()
        for pattern in _TIER_PROMISES:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)


# ── Sibling axis: a badge or a certificate is not an on-chain attestation ────
#
# The badge and certificate tables each carry an `eas_uid` column, and the
# README, the Glasswing page, the learn page, course-02 and the badges package
# said a badge (or a certificate) was "backed by" or "recorded as" an EAS
# attestation. Nothing writes that column: both INSERTs leave it out and no
# UPDATE sets it, so every record's `eas_uid` is NULL.

import subprocess  # noqa: E402

_EAS_WRITERS = [ROOT / "runtime" / "badges" / "badge_manager.py",
                ROOT / "runtime" / "certification" / "assessments.py"]
_ATTESTED_CLAIMS = [
    r"backed by (?:an )?on-chain (?:eas )?attestations?",
    r"backed by an eas \(ethereum attestation service\) attestation",
    r"recorded as an eas attestation",
    r"(?:badges?|certifications?) (?:are|is) backed by on-chain",
    r"verifiable by anyone using the attestation uid",
]


def _eas_uid_is_written() -> bool:
    for path in _EAS_WRITERS:
        text = path.read_text(encoding="utf-8")
        for stmt in re.findall(r"(?:INSERT INTO|UPDATE)\b.*?(?:VALUES|WHERE)", text, re.S | re.I):
            if "eas_uid" in stmt:
                return True
    return False


def test_the_attestation_claim_scan_catches_the_old_copy():
    old = ("Badges are backed by on-chain EAS attestations. Recorded as an EAS attestation "
           "on-chain. Professional certifications backed by on-chain attestations.")
    assert sum(bool(re.search(p, old.lower())) for p in _ATTESTED_CLAIMS) >= 3


def test_no_text_calls_a_badge_or_certificate_an_on_chain_attestation():
    if _eas_uid_is_written():
        return  # something attests now; the claim is not contradicted
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith("tests/") or rel == "CHANGELOG.md" or not (ROOT / rel).is_file():
            continue
        if not rel.endswith((".md", ".html", ".py")):
            continue
        text = re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))
        flat = re.sub(r"\s+", " ", text).lower()
        for pattern in _ATTESTED_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 20]}...")
    assert not offenders, "\n".join(offenders)
