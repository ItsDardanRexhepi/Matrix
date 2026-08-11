"""D7 — the FAKE-DELIVERY detector. A method that says value arrived, when it
mutated no store that would make that true.

WHY THIS EXISTS SEPARATELY FROM D6.

D6 (`test_uuid_mint_fabrication_shape.py`) detects `uuid4 + store-write +
hardcoded status + NO await`. `CrossBorderService.send_payment` — the largest
fabrication on the money path — slips it entirely, because it DOES await:
compliance, FX conversion, attestation. Every one of those awaits resolves to
in-process computation. The largest instance of the class was invisible to the
detector built to find the class.

The instinct was to widen D6 by dropping the `not awaits` clause. That was
tried and measured, and it is wrong in BOTH directions:

    9 newly caught, 5 KNOWN fabrications dropped, and 1 false positive —
    `InsuranceService.file_claim`, the method NEW-78 had just made genuinely
    real.

A detector that flags a correct fix is worse than one with a known blind spot:
it teaches the next reader to un-fix it. There is no one-line token swap that
separates these, and shipping one would have been false precision.

SO D7 DETECTS ON A DIFFERENT AXIS. D6 catches a method by what it LACKS (an
await) — an implementation accident. D7 catches it by what it CLAIMS — the
defect itself:

    1. it returns a hardcoded status literal from the DELIVERY vocabulary
       ("sent" / "completed" / "transferred" / "bridging" / …), AND
    2. it contains no transfer primitive and no honest-refusal gate, so it
       cannot have delivered anything, AND
    3. it carries no RECORDED_UNSETTLED disclosure, so nothing tells the
       caller otherwise, AND
    4. **it writes no store keyed by the SUBJECT of the claim** — it only
       appends a record under a freshly minted id, or writes nothing at all.

CLAUSE 4 IS WHAT MAKES THIS PRECISE, and it was learned by getting it wrong.
Without it the detector fires on two honest methods:

    StablecoinService.transfer   debits `self._balances[from_addr][token]` and
                                 credits the recipient. It genuinely moves the
                                 balance it claims to move. (An earlier grep of
                                 mine missed this because the code goes through
                                 `.setdefault(from_addr, {})[token]` — recorded
                                 because the near-miss is the point.)
    SupplyChainService.transfer_custody
                                 validates the current holder, refuses on
                                 mismatch, appends a hash-chained provenance
                                 event, and sets `self._custody[product_id]`.
                                 For custody, the record IS the asset.

Both move the thing they claim to move. `remit` writes `_payments[remit_id]` —
a record OF the claim, not the asset. `GamingService.trade_item` writes
`_assets[trade_id]`, keyed by the TRADE, so the item's owner never changes.
That distinction is the whole finding.

RATCHET: this inventory may only SHRINK. Frozen by NAME, not by count, so a
fix and a new instance cannot cancel out.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "runtime/blockchain"

# Status literals that assert value reached someone.
DELIVERY_VOCABULARY = frozenset({
    "sent", "completed", "paid", "settled", "delivered",
    "transferred", "bridged", "disbursed", "remitted", "bridging",
})

# Tokens meaning the method can really move value, or honestly refuses to.
_REAL_OR_REFUSES = (
    "send_transaction", "send_raw_transaction", "sign_transaction", "to_wei",
    "build_transaction", "get_transaction_receipt",
    "not_deployed_response", "is_placeholder", "_require_config",
)

# The honest idiom (x402 / fundraising / attestation already use it).
_DISCLOSES = ("value_moved", "disclosure", "RECORDED_UNSETTLED")


def _delivery_claims(fn: ast.AST) -> set[str]:
    """Hardcoded ``"status": "<delivery word>"`` literals in the body."""
    found = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant) and key.value == "status"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value in DELIVERY_VOCABULARY
            ):
                found.add(value.value)
    return found


def _writes_a_subject_store(fn: ast.AST) -> bool:
    """True if the method mutates a store keyed by one of its own parameters.

    That is the signature of a real move: the ledger that DEFINES the thing
    changes. A fabrication only appends a record under a fresh id.
    """
    params = {a.arg for a in fn.args.args}
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            # self._store[<param>] = ...
            if (
                isinstance(target.value, ast.Attribute)
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "self"
            ):
                key_src = ast.unparse(target.slice)
                if any(p in key_src for p in params):
                    return True
            # self._store.setdefault(<k>, {})[<k2>] = ...  (nested ledger)
            if isinstance(target.value, ast.Call):
                return True
    return False


def find_fake_delivery() -> set[str]:
    """Every method claiming delivery it cannot have performed."""
    found: set[str] = set()
    paths = sorted(
        set(ROOT.rglob("services/**/*.py")) | set(ROOT.glob("*.py"))
    )
    for path in paths:
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        rel = str(path.relative_to(ROOT))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _delivery_claims(fn):
                    continue
                body = ast.unparse(fn)
                if any(t in body for t in _REAL_OR_REFUSES):
                    continue
                if any(d in body for d in _DISCLOSES):
                    continue
                if _writes_a_subject_store(fn):
                    continue
                found.add(f"{rel}::{cls.name}.{fn.name}")
    return found


# ── The frozen inventory (measured 2026-08-11; ratchet: may only shrink) ──
#
# Six instances across five services — a cross-domain control from day one.
# Every one of these was read by hand before freezing.

KNOWN_FAKE_DELIVERY = {
    # Domain 8. remit skips every guard its sibling send_payment applies —
    # sanctions, KYC, travel rule, the _max_payment cap, negative amounts —
    # and never converts currency, reporting net_amount in the SOURCE currency
    # while declaring the remittance sent.
    "services/cross_border/service.py::CrossBorderService.remit",
    # Says "bridging"; ACTION_TO_FEED_EVENT publishes it as "bridge_completed".
    # Its honest twin CCIPService.bridge_token_ccip is catalogued available=False
    # while this is catalogued available=True.
    "services/cross_border/service.py::CrossBorderService.bridge_transfer",
    # THE ONE D6 MISSES. Real compliance, real FX, real fee maths, then
    # "completed" over money that never moved. Category 6, not 4: strip the
    # claim and a genuine engine remains — so the fix is vocabulary.
    "services/cross_border/service.py::CrossBorderService.send_payment",
    # Writes _assets[trade_id] — keyed by the TRADE, so the item's owner is
    # never changed. Buyer and seller both keep what they had.
    "services/gaming/service.py::GamingService.trade_item",
    # No store write at all, and the content_hash is a second uuid4 — not a
    # hash of the content. No XMTP client is contacted.
    "services/social/service.py::SocialService.send_encrypted_message",
    # No store write at all: rights are declared transferred and nothing
    # records who holds them.
    "services/nft_services/rights.py::RightsManagement.transfer_rights",
}


def test_the_inventory_only_shrinks():
    """The ratchet. Frozen by NAME so a fix and a regression cannot cancel."""
    current = find_fake_delivery()

    new = current - KNOWN_FAKE_DELIVERY
    assert not new, (
        "new fake-delivery methods — each claims value reached someone while "
        f"mutating no store that would make it true: {sorted(new)}"
    )

    fixed = KNOWN_FAKE_DELIVERY - current
    assert not fixed, (
        "these no longer match — remove them from KNOWN_FAKE_DELIVERY to "
        f"tighten the ratchet: {sorted(fixed)}"
    )


def test_the_measured_count_is_recorded():
    """BURN-DOWN: 6 at introduction (2026-08-11)."""
    assert len(KNOWN_FAKE_DELIVERY) == 6
    assert len(find_fake_delivery()) == 6


def test_it_catches_the_one_d6_misses():
    """The reason D7 exists, asserted rather than asserted-in-a-comment.

    send_payment awaits compliance, conversion and attestation — all local —
    so D6's `not awaits` clause excludes it. If this ever stops holding,
    the two detectors have converged and one of them is redundant.
    """
    from tests.test_uuid_mint_fabrication_shape import find_fabrication_shape

    target = "services/cross_border/service.py::CrossBorderService.send_payment"
    d6_name = "cross_border/service.py::CrossBorderService.send_payment"

    assert target in find_fake_delivery(), "D7 no longer catches send_payment"
    assert d6_name not in find_fabrication_shape(), (
        "D6 now catches send_payment too — the detectors have converged; "
        "re-read whether D7 still earns its place"
    )


# ── The clause-4 controls: why the two honest methods are NOT here ────────


def test_a_real_balance_move_is_not_flagged():
    """StablecoinService.transfer says "completed" and MEANS it.

    It debits `self._balances[from_addr][token]` and credits the recipient,
    after a balance check and a rate-limit check. Without clause 4 the
    detector fires on it. This is the false positive that shaped the design —
    and my own earlier grep missed the debit because it goes through
    `.setdefault(from_addr, {})[token]`.
    """
    assert not any(
        "StablecoinService.transfer" in k for k in find_fake_delivery()
    ), "D7 is flagging a method that genuinely moves the balance it claims"


def test_a_real_custody_move_is_not_flagged():
    """SupplyChainService.transfer_custody says "transferred" and means it.

    It validates the current holder, refuses on mismatch, appends a
    hash-chained provenance event, and sets `self._custody[product_id]`. For
    custody, the record IS the asset — so mutating the record IS the transfer.
    """
    assert not any(
        "transfer_custody" in k for k in find_fake_delivery()
    ), "D7 is flagging a method whose record write IS the custody change"


def test_the_disclosure_idiom_exempts_a_method():
    """A method that says "recorded, not settled" is honest and must not fire.

    This is the fix shape for every entry above, so the detector has to
    recognise it — otherwise fixing an instance would not clear it.
    """
    src = (
        "class S:\n"
        "    async def pay(self, sender, amount):\n"
        "        pid = uuid.uuid4().hex\n"
        "        rec = {'id': pid, 'status': 'completed',\n"
        "               'value_moved': False,\n"
        "               'disclosure': 'RECORDED ONLY — no value moved.'}\n"
        "        self._payments[pid] = rec\n"
        "        return rec\n"
    )
    fn = ast.parse(src).body[0].body[0]
    assert _delivery_claims(fn) == {"completed"}
    body = ast.unparse(fn)
    assert any(d in body for d in _DISCLOSES), (
        "the disclosure idiom is not recognised — fixing an instance would "
        "not clear the ratchet"
    )


def test_the_vocabulary_is_about_delivery_not_lifecycle():
    """`pending`, `created`, `submitted` are NOT delivery claims.

    "submitted" is the honest CCIP literal for a broadcast-but-unconfirmed
    transaction. Including it would flag the correct implementation and push
    people toward the fabrication.
    """
    for word in ("pending", "created", "submitted", "queued", "recorded"):
        assert word not in DELIVERY_VOCABULARY
