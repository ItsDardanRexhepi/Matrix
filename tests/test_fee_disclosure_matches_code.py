"""The published fee disclosure is the fees the code takes — no fewer, and no
"there are none".

docs/what-makes-0pnmatrx-different.md promised "No hidden fees. No gas fees ...
for every capability, forever"; docs/blockchain.md's Fees section read, in full,
"There are none ... No exceptions. No conditions. Ever."; README offered to
"send money anywhere in the world instantly with zero fees". Meanwhile three
contracts take a cut on-chain (Marketplace 5% of every sale, Staking 5% of
rewards, DAO treasury withdrawals 1% / 0.5% / 0.25%), the NFT contract forwards
the whole mint price to the platform, the stablecoin transfer those docs
advertise deducts a tiered fee, and seven platform services compute a platform
fee on the operation they perform.

The rates are DERIVED from the code that charges them — Solidity constants and
function bodies, Python default schedules — never typed into this test. For
each source, docs/blockchain.md's Fees table must carry a row that names the
source file in backticks and states every derived rate. Change a rate in code
without changing the disclosure (or vice versa) and this fails.

It also checks the complement: no public document may say there are no fees
while any source above takes one. The fee-taking is established first, from
the code, so that check rests on a measured fact, not on the doc's own words.

The first version of FEE_SOURCES was a hand-picked list, so the test named
"every fee the code takes is disclosed" could not see a fee nobody had listed,
and four were missing from the table that claimed completeness: the cross-border
payment fee (0.5%, on the flagship send-money path), the service-level staking
commission, the DAO treasury tiers, and the insurance cancellation withholding —
plus the DEX pools' 0.3% input fee, which the DEX service reported as
`user_fee: 0.0  # ZERO FEES`. So the list is now checked against a SWEEP:
every tracked file under runtime/, gateway/ and contracts/ that defines a
fee-named constant or default with a nonzero value, a fee tier table, a literal
fraction withheld under a fee comment, or a Solidity transfer to the platform
fee recipient, must be in FEE_SOURCES or in NOT_CHARGED with a reason that is
itself checked. The sweep is a pattern match: a fee computed under a name that
says neither "fee" nor "commission" would not be found, and the disclosure says
exactly that.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISCLOSURE = ROOT / "docs" / "blockchain.md"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _bps_constant(rel: str, name: str) -> list[float]:
    m = re.search(rf"\b{name}\s*=\s*(\d+)", _src(rel))
    assert m, f"{name} not found in {rel}"
    return [int(m.group(1)) / 10_000]


def _dao_tiers() -> list[float]:
    body = re.search(r"function _tieredFeeBps\(.*?\{(.*?)\n    \}", _src("contracts/OpenMatrixDAO.sol"), re.S)
    assert body, "_tieredFeeBps not found"
    return [int(x) / 10_000 for x in re.findall(r"return\s+(\d+)\s*;", body.group(1))]


def _py_default(rel: str, key: str, scale: float) -> list[float]:
    m = re.search(rf'["\']{key}["\']\s*[:,]\s*([\d.]+)', _src(rel))
    assert m, f"default for {key} not found in {rel}"
    return [float(m.group(1)) * scale]


def _stablecoin_tiers() -> list[float]:
    from runtime.blockchain.services.stablecoin.service import DEFAULT_FEE_TIERS
    return [rate for _, rate in DEFAULT_FEE_TIERS]


def _gaming_default() -> list[float]:
    m = re.search(r"_DEFAULT_PLATFORM_PCT\s*=\s*([\d.]+)",
                  _src("runtime/blockchain/services/gaming/revenue_share.py"))
    return [float(m.group(1)) / 100]


def _cross_border_default() -> list[float]:
    from runtime.blockchain.services.cross_border.service import CrossBorderService
    return [CrossBorderService({}).fee_for(100.0)["fee_pct"] / 100]


def _dex_pool_default() -> list[float]:
    m = re.search(r'default_fee_tier["\']\s*,\s*(\d+)', _src("runtime/blockchain/services/dex/pools.py"))
    assert m, "default_fee_tier default not found"
    assert "fee_tier / 1_000_000" in _src("runtime/blockchain/services/dex/pools.py")
    return [int(m.group(1)) / 1_000_000]


def _dao_treasury_tiers() -> list[float]:
    from runtime.blockchain.services.dao_management.treasury import _FEE_TIERS
    return [pct / 100 for _, pct in _FEE_TIERS]


def _insurance_cancellation() -> list[float]:
    src = _src("runtime/blockchain/services/insurance/service.py")
    fn = re.search(r"async def cancel_policy\(.*?\n    async def |async def cancel_policy\(.*\Z", src, re.S).group(0)
    m = re.search(r"premium_paid\"\]\s*\*\s*remaining_ratio\s*\*\s*(0\.\d+)", fn)
    assert m, "cancel_policy refund multiplier not found"
    return [round(1 - float(m.group(1)), 10)]


def _staking_service_default() -> list[float]:
    m = re.search(r"_COMMISSION_PCT\s*=\s*([\d.]+)", _src("runtime/blockchain/services/staking/service.py"))
    return [float(m.group(1)) / 100]


def _nft_mint_forwards_to_platform() -> list[float]:
    src = _src("contracts/OpenMatrixNFT.sol")
    mint = re.search(r"function mint\(.*?\n    \}", src, re.S).group(0)
    assert "platformFeeRecipient.call{value: msg.value}" in mint
    return []  # the whole mint price; there is no rate to state


def _insurance_excess_to_platform() -> list[float]:
    src = _src("contracts/OpenMatrixInsurance.sol")
    fn = re.search(r"function withdrawExcess\(.*?\n    \}", src, re.S).group(0)
    assert "platformFeeRecipient.call" in fn
    return []


# (source file cited in the disclosure, rates derived from that file)
FEE_SOURCES = {
    "contracts/OpenMatrixMarketplace.sol": lambda: _bps_constant("contracts/OpenMatrixMarketplace.sol", "PLATFORM_FEE_BPS"),
    "contracts/OpenMatrixStaking.sol": lambda: _bps_constant("contracts/OpenMatrixStaking.sol", "COMMISSION_BPS"),
    "contracts/OpenMatrixDAO.sol": _dao_tiers,
    "contracts/OpenMatrixNFT.sol": _nft_mint_forwards_to_platform,
    "contracts/OpenMatrixInsurance.sol": _insurance_excess_to_platform,
    "runtime/blockchain/services/stablecoin/service.py": _stablecoin_tiers,
    "runtime/blockchain/services/marketplace/service.py": lambda: _py_default("runtime/blockchain/services/marketplace/service.py", "platform_fee_pct", 1 / 100),
    "runtime/blockchain/services/subscriptions/service.py": lambda: _py_default("runtime/blockchain/services/subscriptions/service.py", "platform_fee_pct", 1 / 100),
    "runtime/blockchain/services/gaming/revenue_share.py": _gaming_default,
    "runtime/blockchain/services/rwa_tokenization/pooled_purchase.py": lambda: _py_default("runtime/blockchain/services/rwa_tokenization/pooled_purchase.py", "platform_fee_pct", 1 / 100),
    "runtime/blockchain/services/nft_services/royalty_enforcement.py": lambda: _py_default("runtime/blockchain/services/nft_services/royalty_enforcement.py", "platform_fee_bps", 1 / 10_000),
    "runtime/blockchain/services/defi/p2p_lending.py": lambda: _py_default("runtime/blockchain/services/defi/p2p_lending.py", "platform_fee_bps", 1 / 10_000),
    "runtime/blockchain/services/contract_conversion/revenue_enforcer.py": lambda: _py_default("runtime/blockchain/services/contract_conversion/revenue_enforcer.py", "platform_fee_bps", 1 / 10_000),
    "runtime/blockchain/services/nft_services/service.py": lambda: _py_default("runtime/blockchain/services/nft_services/service.py", "platform_fee_bps", 1 / 10_000),
    "runtime/blockchain/services/cross_border/service.py": _cross_border_default,
    "runtime/blockchain/services/staking/service.py": _staking_service_default,
    "runtime/blockchain/services/dao_management/treasury.py": _dao_treasury_tiers,
    "runtime/blockchain/services/insurance/service.py": _insurance_cancellation,
    "runtime/blockchain/services/dex/pools.py": _dex_pool_default,
}


def _no_caller_outside(rel: str, *names: str) -> bool:
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    for other in out.splitlines():
        if other == rel or other.startswith("tests/") or not (ROOT / other).is_file():
            continue
        text = (ROOT / other).read_text(encoding="utf-8")
        if any(f"{n}(" in text for n in names):
            return False
    return True


# Files the sweep finds that define a fee-looking number the platform does NOT
# take. Each reason is checked, so an exemption cannot outlive its premise.
NOT_CHARGED = {
    "runtime/blockchain/protocol_abstraction/cross_chain_router.py": (
        "third-party bridge fees (Stargate, Hop, Across) quoted in a route estimate; "
        "paid to the bridge, not the platform",
        lambda: "SUPPORTED_BRIDGES" in _src("runtime/blockchain/protocol_abstraction/cross_chain_router.py")
        and "platform" not in "".join(ln for ln in _src(
            "runtime/blockchain/protocol_abstraction/cross_chain_router.py").splitlines()
            if "fee_bps" in ln).lower()),
    "runtime/blockchain/protocol_referrals.py": (
        "Uniswap interface fee / Aave / 1inch referral parameters: nothing in the "
        "tree calls the helpers that would put them on a transaction",
        lambda: _no_caller_outside("runtime/blockchain/protocol_referrals.py",
                                   "get_uniswap_fee_params", "get_aave_referral_code",
                                   "get_1inch_referrer")),
    "runtime/blockchain/services/gaming/service.py": (
        "`platform_fee_pct` is read and only logged; game revenue fees are "
        "computed in gaming/revenue_share.py, which is listed",
        lambda: len(re.findall(r"self\._platform_fee\b", _src(
            "runtime/blockchain/services/gaming/service.py"))) <= 2
        and "runtime/blockchain/services/gaming/revenue_share.py" in FEE_SOURCES),
    "runtime/blockchain/services/dispute_resolution/appeals.py": (
        "APPEAL_TIERS holds juror counts and stake multipliers for an appeal; "
        "no entry carries a fee",
        lambda: "fee" not in re.search(r"APPEAL_TIERS[^=]*=\s*\[(.*?)\n\]", _src(
            "runtime/blockchain/services/dispute_resolution/appeals.py"), re.S).group(1).lower()),
    "runtime/blockchain/services/insurance/fee_engine.py": (
        "`_TIERS` is the premium schedule, the price of the cover a policy buys, "
        "not a fee on an operation; the insurance service's platform take is the "
        "cancellation withholding, which is listed",
        lambda: "calculate_premium" in _src("runtime/blockchain/services/insurance/fee_engine.py")
        and "platform_fee" not in _src("runtime/blockchain/services/insurance/fee_engine.py")
        and "runtime/blockchain/services/insurance/service.py" in FEE_SOURCES),
    "runtime/blockchain/services/rwa_tokenization/service.py": (
        "a docstring example of the pooled-purchase config; the fee is taken in "
        "rwa_tokenization/pooled_purchase.py, which is listed",
        lambda: "runtime/blockchain/services/rwa_tokenization/pooled_purchase.py" in FEE_SOURCES
        and "platform_fee_pct" not in re.sub(r'""".*?"""', "", _src(
            "runtime/blockchain/services/rwa_tokenization/service.py"), flags=re.S)),
}

def _conversion_tier_quotes() -> list[float]:
    from runtime.blockchain.services.contract_conversion.tier_manager import _TIERS
    return [fee for _name, _max, fee in _TIERS]


def _conversion_quote_is_not_collected() -> bool:
    """Nothing outside the quoting code reads the quoted amount: no payment,
    transfer or ledger path takes `fee_eth`."""
    out = subprocess.check_output(["git", "ls-files", "runtime/*.py", "gateway/*.py"],
                                  cwd=ROOT, text=True)
    quoting = {"runtime/blockchain/services/contract_conversion/tier_manager.py",
               "runtime/blockchain/services/contract_conversion/service.py"}
    for rel in out.splitlines():
        if rel in quoting or not (ROOT / rel).is_file():
            continue
        # a read of the quoted amount out of a result: ["fee_eth"] or .get("fee_eth")
        if re.search(r"""(?:\[|\.get\()\s*["']fee_eth["']""", (ROOT / rel).read_text(encoding="utf-8")):
            return False
    service = _src("runtime/blockchain/services/contract_conversion/service.py")
    return not re.search(r"fee_eth\b[^\n]*(?:transfer|send|charge|collect|pay)", service, re.I)


# Files that quote a fee the platform does not collect. Each is disclosed under
# "Quoted, not collected" at its derived amounts, and its reason is checked.
QUOTED_NOT_COLLECTED = {
    "runtime/blockchain/services/contract_conversion/tier_manager.py": (
        _conversion_tier_quotes, _conversion_quote_is_not_collected),
}


_FEE_NAME = r"(?:[A-Za-z]+_)*_?(?:fee|fees|commission)(?:_[A-Za-z]+)*"
_NONZERO = r"(?!0(?:\.0+)?(?![\d.]))(\d+(?:\.\d+)?)"
_SWEEP_PY = [
    re.compile(rf"\b{_FEE_NAME}\b\s*(?::[^=\n]*)?=\s*\(?\s*(?:float|int)?\(?\s*{_NONZERO}", re.I),
    re.compile(rf"""\.get\(\s*["']{_FEE_NAME}["']\s*,\s*{_NONZERO}""", re.I),
    re.compile(rf"""["']{_FEE_NAME}["']\s*:\s*{_NONZERO}""", re.I),
    re.compile(r"\b[A-Z_]*FEE_TIERS\s*(?::[^=\n]*)?="),
    # A tier table whose entries carry a fee but whose name does not say so
    # (contract_conversion's `_TIERS`, one `fee_eth` per tier) passed the sweep.
    re.compile(r"\b_?[A-Z]*_?TIERS\s*(?::[^=\n]*)?=\s*\["),
    re.compile(r"\*\s*0\.\d+\s*#.*\b(?:fee|commission)\b", re.I),
    re.compile(r"\b_COMMISSION_PCT\s*="),
]
_SWEEP_SOL = [
    re.compile(r"constant\s+[A-Z_]*(?:FEE|COMMISSION)[A-Z_]*\s*=\s*[1-9]"),
    re.compile(r"platformFeeRecipient\.call\{value"),
]
# A number named like a fee that is not a charge to anyone.
_SWEEP_IGNORE = re.compile(r"gas|max_?fee|priority|base_?fee|late_?fee|network_?fee|entry_fee", re.I)


def _sweep_fee_files(files: dict[str, str]) -> set[str]:
    found = set()
    for rel, text in files.items():
        patterns = _SWEEP_SOL if rel.endswith(".sol") else _SWEEP_PY
        for line in text.splitlines():
            if _SWEEP_IGNORE.search(line):
                continue
            if any(p.search(line) for p in patterns):
                found.add(rel)
                break
    return found


def test_the_fee_sweep_is_not_vacuous():
    planted = {
        "h.py": '_TIERS: list[tuple[str, int | None, float]] = [',
        "a.py": 'self._fee_pct: float = float(cfg.get("fee_pct", 0.5))',
        "b.py": 'refund = paid * ratio * 0.9  # 10% cancellation fee',
        "c.py": '_FEE_TIERS: list = [(1, 2)]',
        "d.sol": "uint256 public constant PLATFORM_FEE_BPS = 500;",
        "e.py": '"default_feed_limit": 50,',
        "f.py": 'fee = 0',
        "g.py": 'max_fee_per_gas = 30',
    }
    assert _sweep_fee_files(planted) == {"a.py", "b.py", "c.py", "d.sol", "h.py"}


def test_every_file_that_defines_a_fee_is_disclosed_or_classified():
    out = subprocess.check_output(["git", "ls-files", "runtime/*.py", "gateway/*.py",
                                   "contracts/*.sol"], cwd=ROOT, text=True)
    files = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in out.splitlines()
             if not rel.startswith("contracts/test/") and (ROOT / rel).is_file()}
    found = _sweep_fee_files(files)
    unclassified = sorted(found - set(FEE_SOURCES) - set(NOT_CHARGED)
                          - set(QUOTED_NOT_COLLECTED))
    assert not unclassified, (
        "files define a fee the disclosure neither lists nor classifies as not charged:\n"
        + "\n".join(unclassified))
    unclassified = sorted(found - set(FEE_SOURCES) - set(NOT_CHARGED) - set(QUOTED_NOT_COLLECTED))
    assert not unclassified, unclassified
    stale = sorted(set(NOT_CHARGED) - found)
    assert not stale, f"NOT_CHARGED lists files the sweep no longer finds: {stale}"
    broken = sorted(rel for rel, (_why, holds) in NOT_CHARGED.items() if not holds())
    assert not broken, f"NOT_CHARGED reasons no longer hold for: {broken}"


async def test_dex_quote_reports_the_pool_fee_it_deducts():
    """DEXService returned `user_fee: 0.0  # ZERO FEES` while every pool hop
    deducts its fee tier from the input. The quote must report the fee the
    route computed, and that the platform takes none of it."""
    from runtime.blockchain.services.dex.service import DEXService

    dex = DEXService({})
    await dex.add_liquidity("0xlp", "AAA", "BBB", 1_000_000.0, 1_000_000.0)
    quote = await dex.get_quote("AAA", "BBB", 1_000.0)
    route = await dex.router.find_best_route("AAA", "BBB", 1_000.0)
    assert route["total_fees"] > 0
    assert quote["user_fee"] == route["total_fees"], quote
    assert quote["platform_fee"] == 0.0, quote


def _pct(rate: float) -> str:
    return f"{rate * 100:.4f}".rstrip("0").rstrip(".") + "%"


def _fees_rows() -> list[str]:
    text = DISCLOSURE.read_text(encoding="utf-8")
    m = re.search(r"^## Fees\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, "docs/blockchain.md has no Fees section"
    return [ln for ln in m.group(1).splitlines() if ln.startswith("|")]


def test_rate_extraction_is_not_vacuous():
    derived = {src: fn() for src, fn in FEE_SOURCES.items()}
    assert derived["contracts/OpenMatrixMarketplace.sol"] == [0.05]
    assert len(derived["contracts/OpenMatrixDAO.sol"]) == 3
    assert len(derived["runtime/blockchain/services/stablecoin/service.py"]) == 4
    assert any(rates for rates in derived.values())


def test_every_fee_the_code_takes_is_disclosed_at_its_rate():
    rows = _fees_rows()
    problems = []
    for source, derive in FEE_SOURCES.items():
        cited = [r for r in rows if f"`{source}`" in r]
        if not cited:
            problems.append(f"no Fees row cites `{source}`")
            continue
        row = " ".join(cited)
        for rate in derive():
            if not re.search(rf"(?<![\d.]){re.escape(_pct(rate))}", row):
                problems.append(f"`{source}` takes {_pct(rate)}; its Fees row does not say so")
    assert not problems, "\n".join(problems)


_NO_FEE_CLAIMS = [
    r"there are none",
    r"no hidden fees",
    r"\bno gas fees\b",
    r"\bzero fees\b",
    r"everything is free",
    r"every capability on 0pnmatrx is free",
    r"no exceptions\. no conditions",
    r"\bno platform fee\b",
    r"\bzero[- ]fee\b",
]
_NOT_EDITABLE_HERE = ("web/terms.html", "web/privacy.html", "CHANGELOG.md")


# Prose a person reads, plus the Python modules whose strings are shipped to a
# user as product copy or tool output. Code comments elsewhere are not scanned
# by this phrase list; the DEX service's old "ZERO FEES to users" comment was
# false (its pools deduct 0.3% of the input) and is covered by the DEX quote
# test above instead.
_USER_COPY_PY = ("gateway/bridge.py", "runtime/blockchain/services/dex/service.py")


def test_no_public_surface_says_there_are_no_fees():
    derived = {src: fn() for src, fn in FEE_SOURCES.items()}  # measured premise
    assert any(derived.values()), "no fee found in code; this check would be vacuous"
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", *_USER_COPY_PY],
                                  cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel.startswith(("tests/", "contracts/")) or rel in _NOT_EDITABLE_HERE:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if any(re.search(p, low) for p in _NO_FEE_CLAIMS):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:110]}")
    assert not offenders, "\n".join(offenders)


def _eth(amount: float) -> str:
    return f"{amount:g} ETH"


def test_every_quoted_fee_is_disclosed_as_not_collected():
    text = DISCLOSURE.read_text(encoding="utf-8")
    section = re.search(r"^### Quoted, not collected\s*$(.*?)(?=^#{2,3} |\Z)", text, re.M | re.S)
    assert section, "docs/blockchain.md has no 'Quoted, not collected' section"
    rows = [ln for ln in section.group(1).splitlines() if ln.startswith("|")]
    problems = []
    for source, (derive, not_collected) in QUOTED_NOT_COLLECTED.items():
        assert not_collected(), f"{source}: its quote is read by a collection path now"
        row = " ".join(r for r in rows if f"`{source}`" in r)
        if not row:
            problems.append(f"no 'Quoted, not collected' row cites `{source}`")
            continue
        for amount in derive():
            if _eth(amount) not in row:
                problems.append(f"`{source}` quotes {_eth(amount)}; its row does not say so")
        if "collect" not in row.lower():
            problems.append(f"`{source}` row does not say the quote is not collected")
    assert not problems, "\n".join(problems)


# ── where fees go ────────────────────────────────────────────────────────────
#
# Two false claims about NeoSafe, in opposite directions, each replaced the
# other. The old copy said every fee routes to NeoSafe automatically through
# NeoSafeRouter; the router has no caller. The correction said nothing routes
# fees to NeoSafe; but scripts/deploy_all.py — the command CREDENTIALS_NEEDED.md
# gives — deploys each platform contract with the configured NeoSafe address
# (`OPENMATRIX_NEOSAFE_ADDRESS`) as its `platformFeeRecipient`, and five of
# those contracts pay their fee to that address. Both premises are measured
# here, from the deploy script's AST and the Solidity, and the copy is held to
# both: it may not say the router moves fees, and it may not say no fee reaches
# NeoSafe.

import ast  # noqa: E402

_DEPLOY_ALL = ROOT / "scripts" / "deploy_all.py"


def _contracts_paying_platform_fee_recipient() -> set[str]:
    """Contracts whose Solidity pays `platformFeeRecipient` (a call{value} or
    a token transfer to it)."""
    out = set()
    for path in sorted((ROOT / "contracts").glob("OpenMatrix*.sol")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"platformFeeRecipient\.call\{value|safeTransfer(?:From)?\([^)]*platformFeeRecipient", text):
            out.add(path.stem)
    return out


def _deployed_with_neosafe_as_fee_recipient() -> set[str]:
    """Contracts scripts/deploy_all.py deploys with cfg["neosafe_address"] as
    the first constructor argument (the `_platformFeeRecipient` parameter)."""
    tree = ast.parse(_DEPLOY_ALL.read_text(encoding="utf-8"))
    contracts = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if getattr(target, "id", "") == "CONTRACTS":
                contracts = node.value
    assert contracts is not None, "scripts/deploy_all.py has no CONTRACTS table"
    out = set()
    for entry in contracts.elts:
        fields = {k.value: v for k, v in zip(entry.keys, entry.values)}
        args = fields.get("constructor_args")
        first = (args.body.elts[0] if isinstance(args, ast.Lambda)
                 and isinstance(args.body, ast.List) and args.body.elts else None)
        if (isinstance(first, ast.Subscript) and getattr(first.value, "id", "") == "cfg"
                and isinstance(first.slice, ast.Constant) and first.slice.value == "neosafe_address"):
            out.add(fields["name"].value)
    return out


def _contracts_whose_fee_reaches_neosafe() -> set[str]:
    return _contracts_paying_platform_fee_recipient() & _deployed_with_neosafe_as_fee_recipient()


def test_the_deploy_wiring_measurement_is_not_vacuous():
    paying = _contracts_paying_platform_fee_recipient()
    deployed = _deployed_with_neosafe_as_fee_recipient()
    assert "OpenMatrixMarketplace" in paying and "OpenMatrixDEX" not in paying, paying
    assert {"OpenMatrixMarketplace", "OpenMatrixDEX"} <= deployed, deployed
    assert "OpenMatrixMarketplace" in _contracts_whose_fee_reaches_neosafe()
    # Every contract the Fees table lists as taking an on-chain fee is one the
    # deploy script points at NeoSafe, so "paid to platformFeeRecipient" and
    # "paid to the configured NeoSafe address" describe the same deployment.
    on_chain = {Path(src).stem for src in FEE_SOURCES if src.endswith(".sol")}
    assert on_chain <= deployed, on_chain - deployed


# The router moves nothing: claims that it does.
_NEOSAFE_ROUTING_CLAIMS = [
    r"(?:fees?|revenue)\b(?:(?!\bnot\b)[^.|]){0,60}\brout(?:es?|ed) to (?:the )?neosafe(?! [^.]*\bno\b)",
    r"all platform fees (?:go|flow|route|automatically route) to (?:the )?neosafe",
    r"fee-generating action[^.]{0,60}calls\s+:?(?:meth:)?`?route_fee",
    r"queues fees in-memory until live",
    r"activates[^.]{0,200}neosafe eth transfer",
    r"single point of revenue collection",
    r"collects these referral fees automatically",
]

# The deploy script points the contracts' fees at NeoSafe: claims that no fee
# reaches it.
_NEOSAFE_UNDER_CLAIMS = [
    r"nothing routes (?:platform )?fees to (?:the )?neosafe",
    r"fees? (?:are|is) not routed to (?:the )?neosafe",
    r"rout(?:es|ing) nothing to (?:the )?neosafe",
    r"fees do not reach neosafe",
]


def _calls_the_neosafe_router(text: str) -> bool:
    return bool(re.search(r"\.route_(?:fee|revenue)\(", text))


def _neosafe_router_has_no_caller() -> bool:
    out = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True)
    for rel in out.splitlines():
        if (rel.startswith(("tests/", "examples/")) or rel == "runtime/blockchain/services/neosafe.py"
                or not (ROOT / rel).is_file()):
            continue
        if _calls_the_neosafe_router((ROOT / rel).read_text(encoding="utf-8")):
            return False
    return True


def test_the_neosafe_claim_scans_catch_both_old_copies():
    over = ("Revenue from all fee-generating actions routes to NeoSafe automatically. "
            "All platform fees automatically route to the NeoSafe multisig via RevenueEnforcer. "
            "Every fee-generating action across the 44 services calls :meth:`route_fee` to record. "
            "0pnMatrx collects these referral fees automatically; the fees are routed to the NeoSafe multisig.")
    low = over.lower()
    assert sum(bool(re.search(p, low)) for p in _NEOSAFE_ROUTING_CLAIMS) >= 4
    under = ("Nothing routes platform fees to the NeoSafe multisig today. Fees are not routed to "
             "NeoSafe automatically. RevenueEnforcer routes nothing to NeoSafe, so platform fees do "
             "not reach NeoSafe through this module.")
    low = under.lower()
    assert sum(bool(re.search(p, low)) for p in _NEOSAFE_UNDER_CLAIMS) == 4
    fixed = ("Each contract pays its fee to platformFeeRecipient, which scripts/deploy_all.py sets to "
             "the configured NeoSafe address; NeoSafeRouter has no caller.").lower()
    assert not any(re.search(p, fixed) for p in _NEOSAFE_ROUTING_CLAIMS + _NEOSAFE_UNDER_CLAIMS)


def _public_surfaces() -> list[tuple[str, str]]:
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.py"], cwd=ROOT, text=True)
    surfaces = []
    for rel in out.splitlines():
        if rel.startswith(("tests/", "contracts/")) or rel in _NOT_EDITABLE_HERE:
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        surfaces.append((rel, path.read_text(encoding="utf-8")))
    return surfaces


def _flat(raw: str) -> str:
    return re.sub(r"\s*\n\s*(?:#+\s*|//\s*|\*\s*)?", " ", raw).lower()


def test_no_public_surface_says_the_router_moves_fees_to_neosafe():
    if not _neosafe_router_has_no_caller():
        return  # something routes fees now; the claim is not contradicted
    offenders = []
    for rel, raw in _public_surfaces():
        if _calls_the_neosafe_router(raw):
            continue  # a file that calls the router is demonstrating what it does
        flat = _flat(raw)
        for pattern in _NEOSAFE_ROUTING_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 20]}...")
    assert not offenders, "\n".join(offenders)


def test_no_public_surface_says_no_fee_reaches_neosafe():
    reach = _contracts_whose_fee_reaches_neosafe()
    if not reach:
        return  # the deploy script no longer points contract fees at NeoSafe
    offenders = []
    for rel, raw in _public_surfaces():
        flat = _flat(raw)
        for pattern in _NEOSAFE_UNDER_CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 40):m.end() + 20]}...")
    assert not offenders, (
        f"{sorted(reach)} pay their fee to platformFeeRecipient, which scripts/deploy_all.py "
        "sets to the configured NeoSafe address, so these sentences are false:\n" + "\n".join(offenders))


_MUST_SAY_WHERE_CONTRACT_FEES_GO = ["docs/blockchain.md", "README.md", "examples/README.md"]


def test_the_fee_documents_say_where_the_contract_fee_recipient_points():
    if not _contracts_whose_fee_reaches_neosafe():
        return
    offenders = []
    for rel in _MUST_SAY_WHERE_CONTRACT_FEES_GO:
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        sentences = re.split(r"(?<=[.!?])\s+", flat)
        if not any("platformfeerecipient" in s and "deploy_all.py" in s and "neosafe" in s
                   for s in sentences):
            offenders.append(rel)
    assert not offenders, (
        "these documents do not say, in one sentence, that the contracts pay platformFeeRecipient "
        "and that scripts/deploy_all.py sets it to the NeoSafe address: " + ", ".join(offenders))
