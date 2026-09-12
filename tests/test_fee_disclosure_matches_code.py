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
}


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
]
_NOT_EDITABLE_HERE = ("web/terms.html", "web/privacy.html", "CHANGELOG.md")


# Prose a person reads, plus the one Python module whose strings are shipped to
# the app as product copy. Code comments elsewhere are not scanned: the DEX
# service's "zero fees to users" is scoped to swaps and is true (neither the
# contract nor the service takes a swap fee).
_USER_COPY_PY = ("gateway/bridge.py",)


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
