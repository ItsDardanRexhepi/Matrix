"""What the public text says the capability surface holds is what the catalog holds.

The count of capabilities was corrected to the catalog's (195) on every surface
while the sentences beside it kept naming what the catalog does not have:
course-03 said "The DeFi and DeFi-advanced categories alone cover perps,
options, synthetics, ... liquid staking, restaking"; the README listed
"payments (streaming, escrow, channels)" and "security (MPC, social recovery,
session keys)", a category that holds nothing; docs/blockchain.md, under the
corrected heading, listed yield, LP, vaults, flash loans, perpetuals, options,
synthetics, streaming, escrow, payroll, stealth addresses, threshold
signatures, Arweave, Gensyn and Render; the landing page offered flash loans,
yield farming, conversion to Rust, Move and Cairo, token launches with
airdrops and vesting, and portfolio tracking. runtime/capabilities/catalog.py
records the removal of several of these as fabrications (flash_loan,
yield_optimize, vault_deposit, perp_trade, options_trade, synthetic_asset).

Two checks, both read from the catalog rather than typed in:

  * docs/blockchain.md's category list is rendered here from CATEGORIES and
    the capabilities each holds (with the ones flagged `available: false` said
    to be so) and must match it exactly;
  * on the capability surface — every paragraph that states a capability
    count, plus the category list, the landing page's feature cards and
    course-03's list of services — no term below may appear. Each term is
    first shown to match nothing in the catalog (ids, names, descriptions,
    protocols, subcategories), the conversion parser's languages or the
    generator's chains, so the check rests on a measured absence.

What this cannot see: a capability the catalog lacks named in words not on
the list below, outside the surfaces read.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BLOCKCHAIN_DOC = ROOT / "docs" / "blockchain.md"

# (label, pattern, case-sensitive)
TERMS = [
    ("perpetuals", r"\bperp(?:etual)?s?\b", False),
    ("options", r"\boptions\b", False),
    ("synthetics", r"\bsynthetics?\b", False),
    ("flash loans", r"\bflash[- ]?loans?\b", False),
    ("yield", r"\byield\b", False),
    ("vaults", r"\bvaults?\b", False),
    ("liquidity provision", r"\bliquidity provi\w*|\bLP\b", False),
    ("streaming payments", r"\bstreaming\b", False),
    ("escrow", r"(?<!vote )(?<!vote-)\bescrow\b", False),
    ("stealth addresses", r"\bstealth\b", False),
    ("threshold signatures", r"\bthreshold sig", False),
    ("private transfers", r"\bprivate transfers?\b|\bprivacy-preserving transfers?\b", False),
    ("payroll", r"\bpayroll\b", False),
    ("invoicing", r"\binvoic\w*", False),
    ("Arweave", r"\bArweave\b", True),
    ("Gensyn", r"\bGensyn\b", True),
    ("Render", r"\bRender\b", True),
    ("deployment", r"\bdeploy\w*", False),
    ("airdrops", r"\bairdrops?\b", False),
    ("vesting", r"\bvesting\b", False),
    ("tokenomics", r"\btokenomics\b", False),
    ("portfolio tracking", r"\bportfolio\b", False),
    ("conversion targets", r"\b(?:Rust|Move|Cairo|Solana|Aptos|Sui)\b", True),
]

# Public text; the changelog records history and legal copy is counsel's.
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_PUBLIC = ("README.md", "docs/", "web/", "education/", "sdk/", "agents/", "examples/")
_CAPABILITY_COUNT = re.compile(
    r"\b\d{2,4}\+?(?:-capability\b|\s+(?:discrete\s+)?(?:Web3\s+|blockchain\s+)?"
    r"capabilities\b(?!\s+(?:are|flagged|marked)\b))", re.I)
# A blank line, a list item, a heading, a table row or an HTML block tag ends a
# paragraph.
_BLOCK_BREAK = re.compile(
    r"\n[ \t]*\n|\n(?=[ \t]*(?:[-*|>]|#{1,6}\s|\d+\.\s|</?(?:li|p|div|h\d|tr|td|ul)\b))")


def _catalog_text() -> str:
    from runtime.capabilities.catalog import CAPABILITIES
    keys = ("id", "name", "description", "protocol", "subcategory", "service", "method", "action")
    return "\n".join(" ".join(str(c.get(k) or "") for k in keys) for c in CAPABILITIES)


def _conversion_text() -> str:
    from runtime.blockchain.services.contract_conversion.generator import _CHAIN_OPTIMISATIONS
    from runtime.blockchain.services.contract_conversion.parser import SUPPORTED_LANGUAGES
    return " ".join(sorted(SUPPORTED_LANGUAGES) + sorted(_CHAIN_OPTIMISATIONS))


def _hits(text: str) -> list[str]:
    out = []
    for label, pattern, case in TERMS:
        for m in re.finditer(pattern, text, 0 if case else re.I):
            out.append(f"{label}: {m.group(0)!r}")
    return out


def render_category_list() -> str:
    """The category list docs/blockchain.md carries, rendered from the catalog."""
    from runtime.capabilities.catalog import CAPABILITIES, CATEGORIES
    lines, empty = [], []
    for cat in CATEGORIES:
        caps = [c for c in CAPABILITIES if c["category"] == cat["id"]]
        if not caps:
            empty.append(cat["name"])
            continue
        available = [c["name"] for c in caps if c["available"]]
        flagged = [c["name"] for c in caps if not c["available"]]
        parts = [", ".join(available)] if available else []
        if flagged:
            lead = "catalogued with `available: false`: " if available else \
                "all catalogued with `available: false`: "
            parts.append(lead + ", ".join(flagged))
        lines.append(f"{len(lines) + 1}. **{cat['name']}** ({len(caps)}) — " + "; ".join(parts))
    out = "\n".join(lines)
    if empty:
        out += ("\n\nThe catalog also declares " + ", ".join(f"**{n}**" for n in empty)
                + (", which holds" if len(empty) == 1 else ", which hold") + " no capability.")
    return out


def _doc_category_list() -> str:
    text = BLOCKCHAIN_DOC.read_text(encoding="utf-8")
    m = re.search(r"all accessible through conversation:\n\n(.*?)\n\nState-changing capabilities",
                  text, re.S)
    assert m, "docs/blockchain.md has no category list where it is expected"
    return m.group(1)


def _section(text: str, start: str, end: str) -> str:
    m = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    assert m, f"section starting {start!r} not found"
    return m.group(1)


def _surfaces() -> list[tuple[str, str]]:
    """(where, text) for every piece of the capability surface."""
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    found = []
    for rel in out.splitlines():
        if rel in _NOT_READ or not rel.startswith(_PUBLIC) or not (ROOT / rel).is_file():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        for block in _BLOCK_BREAK.split(text):
            if _CAPABILITY_COUNT.search(re.sub(r"<[^>]+>", " ", block)):
                found.append((rel, block))
    found.append(("docs/blockchain.md category list", _doc_category_list()))
    landing = (ROOT / "web" / "landing.html").read_text(encoding="utf-8")
    found.append(("web/landing.html feature cards",
                  _section(landing, '<div class="feature-grid">', "<!-- Agents -->")))
    course = (ROOT / "education" / "course-03-defi-from-scratch"
              / "01-how-defi-actually-works.md").read_text(encoding="utf-8")
    found.append(("course-03 The Services", _section(course, "## The Services", "\n## ")))
    return found


def test_no_term_on_the_list_is_in_the_catalog():
    held = _catalog_text() + "\n" + _conversion_text()
    assert "Swap Tokens" in held and "solidity" in held, "the catalog text was not read"
    present = _hits(held)
    assert not present, f"the catalog holds these, so they cannot be refused: {present}"
    assert "perp_trade" in (ROOT / "runtime" / "capabilities" / "catalog.py").read_text(
        encoding="utf-8"), "the catalog's record of the removed perp_trade is gone"


def test_the_surface_scan_is_not_vacuous():
    old = ("The Matrix provides 195 capabilities across 21 categories. The DeFi and "
           "DeFi-advanced categories alone cover perps, options, synthetics, lending, swaps.")
    assert {h.split(":")[0] for h in _hits(old)} == {"perpetuals", "options", "synthetics"}
    assert not _hits("Vote-Escrow Lock and a Ceramic stream; quadratic voting")
    where = {w for w, _t in _surfaces()}
    assert {"README.md", "docs/blockchain.md category list",
            "web/landing.html feature cards", "course-03 The Services"} <= where


def test_the_category_list_is_rendered_from_the_catalog():
    assert _doc_category_list() == render_category_list(), (
        "docs/blockchain.md's category list is not the catalog's. It should read:\n\n"
        + render_category_list())


def test_the_capability_surface_names_only_what_the_catalog_holds():
    problems = []
    for where, text in _surfaces():
        problems += [f"{where}: {h}" for h in _hits(text)]
    assert not problems, "\n".join(problems)


def test_the_conversion_intent_names_only_what_the_converter_takes():
    """Trinity's convert_contract intent offered Rust and Move sources and Solana,
    Aptos and Sui targets, and its example converted a contract "to Solana".
    The parser takes solidity, vyper and pseudocode; the generator writes
    Solidity, tuned for the chains it has settings for (any other name gets
    Base's), so a "Solana" conversion came back as Solidity for Base."""
    from runtime.blockchain.services.contract_conversion.generator import _CHAIN_OPTIMISATIONS
    from runtime.blockchain.services.contract_conversion.parser import SUPPORTED_LANGUAGES
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    entry = INTENT_ACTION_MAP["convert_contract"]
    params = {p["name"]: p for p in entry["required_params"]}
    assert params["source_lang"]["example"] in SUPPORTED_LANGUAGES
    assert params["target_chain"]["example"] in _CHAIN_OPTIMISATIONS
    offered = " ".join([entry["description"], entry["follow_up"],
                        params["source_lang"]["description"],
                        params["target_chain"]["description"]])
    problems = re.findall(r"\b(?:rust|move|cairo|solana|aptos|sui)\b", offered, re.I)
    problems += re.findall(r"\b(?:Rust|Move|Cairo|Solana|Aptos|Sui)\b", entry["example_conversation"])
    problems += [c for c in re.findall(r"target_chain: '(\w+)'", entry["example_conversation"])
                 if c not in _CHAIN_OPTIMISATIONS]
    assert not problems, problems
