"""The capability map says which capabilities write a record and move nothing.

These service methods answer `recorded_unsettled` whenever they act: they write
a record on the platform and call no contract, or refuse (`not_deployed` with
no chain or contract configured). The capability map described each as the
action itself — "Buy or sell an AI model NFT", "Enter an on-chain tournament",
"Rent an NFT for a specified duration", "Claim accrued staking rewards" — while
its Payments rows, held by tests/test_money_is_described_as_it_moves.py,
already said "recorded, not settled". The methods became records in the
attest-money passes, the README says so of the trades among them, and the rows
stayed as they were.

The set is found from the code: every method of a service class with a return
that is a `recorded_unsettled_response`, whose every other return is a
`not_deployed_response` or an error. Staking's claim is adjudicated by hand
below. Each method's row, named here, must say what it does the way the
Payments rows do: recorded, not settled.

SIBLING AXIS, named and not changed: the chat intents' descriptions in
runtime/chat/intent_actions.py still describe some of the same actions as
done ("Split an NFT into tradeable fractions", "Trade game items with other
players").
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVICES = ROOT / "runtime" / "blockchain" / "services"

#: Each method that only records, and the name of its row in the map (None
#: where the map has no row for it).
_ROW_OF = {
    "agent_identity/service.py::AgentIdentityService.trade_model_access": "Trade AI Model",
    "dex/service.py::DEXService.swap": "Token Swap",
    "agent_identity/service.py::AgentIdentityService.sell_training_data": "Sell Training Data",
    "gaming/service.py::GamingService.enter_tournament": "Tournament Enter",
    "gaming/service.py::GamingService.trade_item": "Game Item Trade",
    "gaming/service.py::GamingService.attest_achievement": "Achievement Attest",
    "gaming/service.py::GamingService.place_prediction_bet": "Place Prediction Bet",
    "marketplace/service.py::MarketplaceService.buy_item": "Buy Marketplace Item",
    "nft_services/service.py::NFTService.fractionalize": "Fractionalize NFT",
    "nft_services/service.py::NFTService.rent": "Rent NFT",
    "nft_services/service.py::NFTService.dynamic_update": "Dynamic Update",
    "nft_services/service.py::NFTService.batch_mint": "Batch Mint",
    "nft_services/service.py::NFTService.royalty_claim": "Royalty Claim",
    "nft_services/service.py::NFTService.bridge_nft": "Bridge NFT",
    "nft_services/service.py::NFTService.mint_soulbound": "Soulbound Mint",
    "rwa_tokenization/service.py::RWAService.fractional_buy": "Fractional Buy",
    "rwa_tokenization/service.py::RWAService.claim_income": "RWA Income Claim",
    "rwa_tokenization/service.py::RWAService.verify_provenance": None,
}

#: Methods the derivation below cannot settle on its own, adjudicated by reading
#: them. Staking's claim also answers "no_rewards" when nothing has accrued and
#: refuses through `staking_not_deployed`; when it acts it zeroes the pending
#: rewards and records the commission split, and transfers nothing to anyone.
_ADJUDICATED = {
    "staking/service.py::StakingService.claim_rewards": "Claim Staking Rewards",
}


def _kind(node: ast.AST, recorded_names: set[str]) -> str:
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return {"recorded_unsettled_response": "recorded",
                "not_deployed_response": "refusal"}.get(name, "other")
    if isinstance(node, ast.Name):
        return "recorded" if node.id in recorded_names else "other"
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "status" and isinstance(value, ast.Constant):
                return {"recorded_unsettled": "recorded", "error": "refusal"}.get(value.value, "other")
    return "other"


def _methods_that_only_record() -> set[str]:
    found = set()
    for path in sorted(SERVICES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            for fn in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                recorded = set()
                for node in ast.walk(fn):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None \
                            and _kind(node.value, set()) == "recorded":
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        recorded |= {t.id for t in targets if isinstance(t, ast.Name)}
                kinds = [_kind(r.value, recorded) for r in ast.walk(fn)
                         if isinstance(r, ast.Return) and r.value is not None]
                if "recorded" in kinds and set(kinds) <= {"recorded", "refusal"}:
                    found.add(f"{path.relative_to(SERVICES).as_posix()}::{cls.name}.{fn.name}")
    return found


def _rows_named(name: str) -> list[str]:
    text = (ROOT / "docs" / "COMPLETE_CAPABILITY_MAP.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines()
            if line.startswith("| ") and line.split("|")[1].strip() == name]


def test_the_set_of_methods_that_only_record_is_the_one_named_here():
    found = _methods_that_only_record()
    assert found == set(_ROW_OF), (
        f"methods that only record, not named here: {sorted(found - set(_ROW_OF))}; "
        f"named here and no longer only recording: {sorted(set(_ROW_OF) - found)}")


def test_the_capability_map_says_each_one_records_and_moves_nothing():
    wrong = []
    for method, name in {**_ROW_OF, **_ADJUDICATED}.items():
        if name is None:
            continue
        rows = _rows_named(name)
        if not rows:
            wrong.append(f"{method}: the map has no row named {name!r}")
        wrong += [f"{method}: {row}" for row in rows
                  if not re.search(r"\brecorded, not settled\b", row)]
    assert not wrong, "rows that do not say the capability only records:\n" + "\n".join(wrong)
