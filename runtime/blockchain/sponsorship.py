"""D-045: the gas-sponsorship policy the platform already documents as enforced.

gateway/paymaster.py, the /api/v1/paymaster/sign docstring and the shipped
`matrix.config.json.example` all state that an action allowlist and a
per-identity daily USD cap are checked before the platform signs. Only the
allowlist was ever read, and only in one handler; `daily_cap_usd` had no reader
anywhere in the tree. Meanwhile 32 call sites across runtime/blockchain/ signed
transactions with the paymaster key directly, with no identity, cap or
allowlist in that whole layer.

This module is the enforcement the documents describe, and it is the only place
a platform signature is authorised. Two properties make it work rather than
merely exist:

DURABLE.  The spend ledger is a SQLite file, not a dict. A per-process bucket
          is refilled by every restart and is not shared between workers, so it
          would cap nothing in the posture that matters. The test for this runs
          two real interpreters against one file — an in-process assertion
          would make the object its own witness.

RESERVE-THEN-COMMIT.  `authorize_and_reserve` takes the budget inside one
          `BEGIN IMMEDIATE` transaction, so two concurrent requests cannot both
          see the same headroom. The caller commits once the signature is
          actually issued and releases it otherwise, so a signature that never
          happened does not consume the cap.

WHAT THIS DOES NOT DO, stated so nobody reads more into it: it does not price
the transaction. `est_usd` is supplied by the caller, which for the paymaster
route is computed from the userOp's own gas fields and a live ETH/USD quote.
If that quote is unavailable the caller must deny — a cap denominated in
dollars cannot be enforced against an unknown dollar amount, and this module
will not invent one.

WHAT THE ALLOWLIST IS CHECKED AGAINST.  For a UserOperation, the action is
          derived from the bytes being sponsored (`classify_user_operation`),
          never from a label the requester writes about its own request. An
          earlier route read `action_type` from the body and defaulted it to
          "transfer", so the allowlist was satisfied by whatever the caller
          said — §EE.

Posture: an operator who has configured no policy sees exactly the previous
behaviour. Denial happens only where a cap or an allowlist is configured.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from typing import Any, Optional, Sequence, Union

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 24 * 60 * 60

# A reservation this old was abandoned by a process that died between reserving
# and committing. Counting it forever would let one crash permanently shrink an
# identity's budget; the sweep on every write drops it.
RESERVATION_TTL_SECONDS = 300.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsorship_spend (
    id          TEXT PRIMARY KEY,
    identity    TEXT NOT NULL,
    action      TEXT NOT NULL,
    usd         REAL NOT NULL,
    state       TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spend_identity_time
    ON sponsorship_spend (identity, created_at);
"""


class SponsorshipDenied(Exception):
    """Raised where a denial must interrupt a signing path rather than be
    returned. Carries the decision so the caller can render an honest reason."""

    def __init__(self, decision: "SponsorshipDecision") -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class SponsorshipDecision:
    """A decision, never a bare bool — the reason and the numbers travel with
    it so a denial can be explained and an audit row can be written."""

    allowed: bool
    code: str
    reason: str
    identity: str = ""
    action: str = ""
    est_usd: float = 0.0
    spent_usd: float = 0.0
    cap_usd: Optional[float] = None
    reservation_id: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "action": self.action,
            "est_usd": round(self.est_usd, 6),
            "spent_usd": round(self.spent_usd, 6),
            "cap_usd": self.cap_usd,
        }


class SPEND_STATES:
    """What a sponsorship ledger row says has happened, and nothing more.

    RESERVED  budget taken, nothing signed. Ages out after RESERVATION_TTL.
    SIGNED    the platform issued a signature. NOT a spend: a signed
              transaction that is never broadcast, or that the node rejects,
              costs no gas at all. Still holds budget, because it may land.
    SPENT     a receipt confirmed it. This is when gas was paid.
    COMMITTED the pre-relabel name for SIGNED. Written by builds before this
              fix and still present in live ledgers, so it is still counted.
    """

    RESERVED = "reserved"
    SIGNED = "signed"
    SPENT = "spent"
    COMMITTED = "committed"


class SponsorshipPolicy:
    """Action allowlist + per-identity rolling-24h USD cap over a durable ledger."""

    def __init__(self, *, allowed_actions: Optional[list] = None,
                 daily_cap_usd: Optional[float] = None,
                 db_path: Optional[Path] = None) -> None:
        self.allowed_actions = (
            None if allowed_actions is None else {str(a) for a in allowed_actions})
        self.daily_cap_usd = None if daily_cap_usd is None else float(daily_cap_usd)
        self._db_path = Path(db_path) if db_path else None
        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(_SCHEMA)

    # ── construction ─────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "SponsorshipPolicy":
        cfg = config or {}
        bc = cfg.get("blockchain", {}) or {}
        # Resolve the paymaster block through the ONE resolver that knows its
        # two documented homes (top-level `paymaster` and `blockchain.paymaster`)
        # rather than re-deriving it here. An earlier draft of this method read
        # only the second, which silently dropped the allowlist for every
        # deployment using the first — caught by tests/test_paymaster_route.py.
        try:
            from gateway.paymaster import paymaster_config
            block = paymaster_config(cfg)
        except Exception:  # gateway unavailable (runtime imported standalone)
            block = (cfg.get("paymaster") or bc.get("paymaster") or {})
        policy = (block.get("policy", {}) or {}) if isinstance(block, dict) else {}

        allowed = policy.get("allowed_actions")
        if allowed is not None and not isinstance(allowed, (list, tuple, set)):
            logger.warning(
                "paymaster.policy.allowed_actions is %s, not a list — ignoring it "
                "rather than guessing an allowlist", type(allowed).__name__)
            allowed = None

        cap: Optional[float]
        raw_cap = policy.get("daily_cap_usd")
        if raw_cap in (None, ""):
            cap = None
        else:
            try:
                cap = float(raw_cap)
            except (TypeError, ValueError):
                # §DL: a malformed cap is not "no cap". Refusing to parse it into
                # unlimited spend is the only safe reading.
                logger.error(
                    "paymaster.policy.daily_cap_usd is %r, which is not a number. "
                    "Treating it as zero (deny) rather than as no cap.", raw_cap)
                cap = 0.0

        db_cfg = cfg.get("database", {}) or {}
        base = Path(str(db_cfg.get("path", "data/the-matrix.db"))).expanduser()
        if not base.is_absolute():
            base = Path.cwd() / base
        return cls(allowed_actions=list(allowed) if allowed is not None else None,
                   daily_cap_usd=cap,
                   db_path=base.with_name("sponsorship_spend.db"))

    @property
    def enforces_a_cap(self) -> bool:
        return self.daily_cap_usd is not None

    # ── storage ──────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0,
                               isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _spent(self, conn: sqlite3.Connection, identity: str, now: float) -> float:
        # `committed` is the pre-relabel name for `signed` and is still counted:
        # rows written by an earlier build are in live ledgers, and dropping them
        # from the sum would silently hand back budget that was already used.
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM sponsorship_spend "
            "WHERE identity = ? AND created_at >= ? AND ("
            "  state IN (?, ?, ?) OR (state = ? AND created_at >= ?))",
            (identity, now - WINDOW_SECONDS,
             SPEND_STATES.SPENT, SPEND_STATES.SIGNED, SPEND_STATES.COMMITTED,
             SPEND_STATES.RESERVED, now - RESERVATION_TTL_SECONDS),
        ).fetchone()
        return float(row[0] or 0.0)

    def _sweep(self, conn: sqlite3.Connection, now: float) -> None:
        """Bounded by construction: rows outside the window can never affect a
        decision again, so they are deleted rather than accumulated. (The
        wallet rate limiter's buckets were never swept; this one is.)"""
        conn.execute("DELETE FROM sponsorship_spend WHERE created_at < ?",
                     (now - WINDOW_SECONDS,))

    # ── the decision ─────────────────────────────────────────────────────

    def authorize_and_reserve(self, action: Union[str, Sequence[str]], *, identity: str,
                              est_usd: float = 0.0,
                              now: Optional[float] = None) -> SponsorshipDecision:
        """Authorise one platform signature and take its budget atomically.

        On an allow the caller MUST later call :meth:`commit` (the signature was
        issued) or :meth:`release` (it was not). An abandoned reservation stops
        counting after RESERVATION_TTL_SECONDS.
        """
        now = time.time() if now is None else now
        # One operation can do several things (an account `executeBatch`), so
        # the allowlist is checked against EVERY action in it: one allowed call
        # must not carry a disallowed one through. A bare string is one action.
        if action is None or isinstance(action, str):
            labels = [str(action or "")]
        else:
            labels = [str(a or "") for a in action]
        # Bounded: this string is stored in the ledger and echoed in a denial,
        # and the label list is as long as the caller's batch.
        action = summarize_labels(labels)
        identity = canonical_identity(identity)
        est_usd = max(0.0, float(est_usd or 0.0))

        if self.allowed_actions is not None:
            # An empty list of actions is not vacuously allowed.
            refused = [a for a in labels if a not in self.allowed_actions] or (
                [] if labels else ["<nothing>"])
            if refused:
                return SponsorshipDecision(
                    False, "action_not_allowed",
                    f"gas sponsorship not available for action '{summarize_labels(refused)}'",
                    identity=identity, action=action, est_usd=est_usd,
                    cap_usd=self.daily_cap_usd)

        if not self.enforces_a_cap:
            # No cap configured: previous behaviour exactly, allowlist aside.
            return SponsorshipDecision(
                True, "allowed_no_cap", "no daily cap configured",
                identity=identity, action=action, est_usd=est_usd)

        if not identity:
            return SponsorshipDecision(
                False, "identity_required",
                "gas sponsorship requires an identified caller: a per-identity "
                "daily cap cannot meter spend it cannot attribute",
                action=action, est_usd=est_usd, cap_usd=self.daily_cap_usd)

        cap = float(self.daily_cap_usd)
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._sweep(conn, now)
                spent = self._spent(conn, identity, now)
                if spent + est_usd > cap:
                    conn.execute("COMMIT")
                    return SponsorshipDecision(
                        False, "daily_cap_exceeded",
                        f"daily gas sponsorship cap reached: ${spent:.2f} of "
                        f"${cap:.2f} already sponsored for this identity in the "
                        f"last 24h; this request needs ${est_usd:.2f}",
                        identity=identity, action=action, est_usd=est_usd,
                        spent_usd=spent, cap_usd=cap)
                res_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO sponsorship_spend "
                    "(id, identity, action, usd, state, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (res_id, identity, action, est_usd,
                     SPEND_STATES.RESERVED, now))
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
        return SponsorshipDecision(
            True, "allowed", "within the daily sponsorship cap",
            identity=identity, action=action, est_usd=est_usd,
            spent_usd=spent, cap_usd=cap, reservation_id=res_id)

    def commit(self, reservation_id: str) -> None:
        """The signature was ISSUED. That is what this row now says.

        It used to say `committed`, documented as "the spend is real". A
        signature is not a spend. Gas is paid when a transaction is MINED, and
        between the two sit every outcome that costs nothing: a signed
        transaction that is never broadcast, one the node rejects, one that is
        replaced. This is the platform's own record of money it spent, and it
        was written on an event that does not spend money.

        THE ACCOUNTING IS DELIBERATELY UNCHANGED. A signature the platform
        issued may still land, so `signed` holds budget exactly as `committed`
        did — `_spent` counts it. This is a relabel, not a release: the row now
        says what is known, and :meth:`settle` and :meth:`abandon` say what
        happened next, for the callers that get to find out.
        """
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sponsorship_spend SET state = ? "
                "WHERE id = ? AND state = ?",
                (SPEND_STATES.SIGNED, reservation_id, SPEND_STATES.RESERVED))

    def settle(self, reservation_id: str) -> None:
        """The transaction was MINED — this is the point at which gas was paid."""
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sponsorship_spend SET state = ? WHERE id = ? AND state IN (?, ?, ?)",
                (SPEND_STATES.SPENT, reservation_id, SPEND_STATES.RESERVED,
                 SPEND_STATES.SIGNED, SPEND_STATES.COMMITTED))

    def abandon(self, reservation_id: str) -> None:
        """The signature was issued and never reached the chain — no gas was
        paid, so the budget goes back. An identity charged for gas nobody paid
        is capped out of sponsorship it is entitled to, which is the same defect
        as the over-claim, facing the other way and visible to nobody."""
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sponsorship_spend WHERE id = ? AND state IN (?, ?, ?)",
                (reservation_id, SPEND_STATES.RESERVED, SPEND_STATES.SIGNED,
                 SPEND_STATES.COMMITTED))

    def state_of(self, reservation_id: str) -> Optional[str]:
        """What this row says happened, or None if there is no such row."""
        if not reservation_id or self._db_path is None:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM sponsorship_spend WHERE id = ?",
                (reservation_id,)).fetchone()
        return None if row is None else str(row[0])

    def release(self, reservation_id: str) -> None:
        """The signature was NOT issued — give the budget back, so a failure
        downstream does not charge an identity for gas nobody sponsored."""
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sponsorship_spend WHERE id = ? AND state = ?",
                (reservation_id, SPEND_STATES.RESERVED))

    def spent_today(self, identity: str, *, now: Optional[float] = None) -> float:
        if self._db_path is None:
            return 0.0
        now = time.time() if now is None else now
        with self._connect() as conn:
            return self._spent(conn, canonical_identity(identity), now)


# ── what is being sponsored ──────────────────────────────────────────────
#
# §EE: the sponsorship allowlist used to be checked against `action_type`, a
# string the requester writes about its own request, defaulting to "transfer".
# The paymaster digest commits to keccak(callData) and keccak(initCode), so
# those bytes ARE what a signature sponsors — they are the only honest source for
# the action, and they are right there in the request.
#
# WHAT THIS DECODES. The smart-account wrapper (contracts/MatrixAccount.sol
# `execute(dest, value, func)` and `executeBatch(dest[], func[])`, plus the
# three-array `executeBatch` the MTRX client encodes), then the inner call's
# 4-byte selector.
#
# HOW IT DECODES. By walking the ABI head/tail words by hand, reading only
# lengths, address words, value words and each inner call's first four bytes.
# Nothing the caller sends is copied per element. An earlier version called
# eth_abi.decode, which accepts every bytes[] offset pointing at one shared blob
# and copies that blob once per element: a ~1 MiB request allocated gigabytes,
# on every sign request, before any policy check. Only the CANONICAL encoding —
# the one eth_abi, ethers and the MTRX client's ABIEncoder all produce — is
# described; any other offset layout, a dirty address word, or a length that
# runs past the data is `unrecognized_call_data`. Describing non-canonical
# layouts would mean agreeing with Solidity's decoder on each of them; refusing
# them is the reading that cannot disagree. A batch longer than MAX_BATCH_CALLS
# is the single label `oversized_batch`.
#
# WHAT IT CANNOT KNOW, stated so nobody reads more into it. The allowlist
# constrains which ABI function NAMES the call data invokes. It does not
# constrain what code runs, for three reasons, all of the same kind — each
# needs an address or codehash registry this repo does not have:
#
#   * the TARGET. `transfer(address,uint256)` on a contract someone wrote to look
#     like a token is still labelled "transfer", and runs whatever that contract
#     does;
#   * a VALUE TRANSFER. `execute(dest, value > 0, "")` is labelled "transfer"
#     whatever `dest` is. If `dest` has code, its receive/fallback function runs
#     on sponsored gas — the same property as the target above, since another
#     user's smart account (a legitimate recipient) is itself a contract;
#   * the SENDER. The wrapper decode assumes the sender IS an MatrixAccount,
#     whose execute/executeBatch mean what their ABI says. Nothing here checks
#     the sender's code, and without an authenticated session the route takes
#     the sender from the request. An account contract the caller wrote can give
#     `execute(x, 1, "")` any meaning it likes. MatrixVerifyingPaymaster
#     puts no restriction on the sender either.
#
# So `allowed_actions` is a statement about the shape of honest requests, not a
# security boundary against a caller who deploys contracts.
#
# Nor is the daily cap a boundary against such a caller. It is metered per
# IDENTITY, and the identity is an address the caller chooses. With no session,
# the route takes it from the X-Wallet-Address header or the body `sender`, both
# written by the caller; with a SIWE session it is an address whose key the
# caller holds, and keys cost nothing to make. Each new address starts with a
# fresh cap. (With an Apple session the identity is the wallet linked to that
# Apple user, or `apple:<sub>` when none is linked, not an address chosen per
# request; what rotating those costs a caller is not measured here.) The cap
# bounds sponsored spend per address, not per caller, and nothing in this repo
# bounds the total a caller who rotates addresses can draw except the
# EntryPoint deposit itself.

# Past this many calls in one batch the operation is one label, so neither the
# label list nor anything built from it grows with the caller's input.
MAX_BATCH_CALLS = 256

# How many distinct refused labels a denial names before summarising the rest.
_MAX_LABELS_ECHOED = 8

# Named inner calls. Each signature is hashed here rather than pasted as hex, so
# a typo is a different signature rather than a silently wrong selector.
_NAMED_SIGNATURES: dict[str, str] = {
    "transfer(address,uint256)": "transfer",        # ERC-20 transfer
    "approve(address,uint256)": "approve",          # ERC-20 approve
    "swap(uint256,address,uint256)": "swap",        # contracts/MatrixDEX.sol
    "mint(address,string,uint96)": "mint_nft",      # contracts/MatrixNFT.sol
}

_ACCOUNT_EXECUTE = "execute(address,uint256,bytes)"
_ACCOUNT_BATCH = "executeBatch(address[],bytes[])"                # MatrixAccount.sol
_ACCOUNT_BATCH_VALUES = "executeBatch(address[],uint256[],bytes[])"  # MTRX client encoding


@lru_cache(maxsize=None)
def _selectors() -> dict[str, bytes]:
    from eth_utils import keccak

    sigs = [_ACCOUNT_EXECUTE, _ACCOUNT_BATCH, _ACCOUNT_BATCH_VALUES, *_NAMED_SIGNATURES]
    return {sig: keccak(text=sig)[:4] for sig in sigs}


class _NotCanonical(Exception):
    """The bytes are not the canonical ABI encoding of the expected arguments."""


class _TooManyCalls(Exception):
    """A batch longer than MAX_BATCH_CALLS."""


def _pad32(n: int) -> int:
    return (n + 31) // 32 * 32


class _Args:
    """Read-only word access over the argument bytes. `memoryview` slices are
    views, so reading a word never copies the caller's buffer."""

    def __init__(self, data: bytes) -> None:
        self._view = memoryview(data)
        self.size = len(data)

    def word(self, at: int) -> int:
        if at < 0 or at + 32 > self.size:
            raise _NotCanonical
        return int.from_bytes(self._view[at:at + 32], "big")

    def address_word(self, at: int) -> None:
        if self.word(at) >> 160:
            # Solidity reverts on dirty upper bits; nothing to describe.
            raise _NotCanonical

    def head(self, at: int, length: int) -> bytes:
        if at < 0 or at + length > self.size:
            raise _NotCanonical
        return bytes(self._view[at:at + min(length, 4)])

    def bytes_at(self, at: int) -> tuple[int, bytes, int]:
        """A `bytes` value at `at`: (length, first four bytes, canonical end)."""
        length = self.word(at)
        end = at + 32 + _pad32(length)
        if end > self.size:
            raise _NotCanonical
        return length, self.head(at + 32, length), end

    def array_len(self, at: int) -> int:
        n = self.word(at)
        if n > MAX_BATCH_CALLS:
            raise _TooManyCalls
        return n


def _walk_execute(a: _Args) -> list[tuple[int, int, bytes]]:
    # execute(address, uint256, bytes): two static words, then one offset.
    a.address_word(0)
    value = a.word(32)
    if a.word(64) != 96:
        raise _NotCanonical
    length, head, _end = a.bytes_at(96)
    return [(value, length, head)]


def _walk_batch(a: _Args, with_values: bool) -> list[tuple[int, int, bytes]]:
    heads = 3 if with_values else 2
    cursor = 32 * heads

    # address[] dest
    if a.word(0) != cursor:
        raise _NotCanonical
    n = a.array_len(cursor)
    for i in range(n):
        a.address_word(cursor + 32 + 32 * i)
    cursor += 32 + 32 * n

    values = [0] * n
    if with_values:
        if a.word(32) != cursor:
            raise _NotCanonical
        if a.array_len(cursor) != n:
            raise _NotCanonical
        values = [a.word(cursor + 32 + 32 * i) for i in range(n)]
        cursor += 32 + 32 * n

    # bytes[] func: its offsets are relative to the word after its length, and
    # canonically each element starts exactly where the previous one ended — so
    # no two elements can share, overlap or skip bytes.
    if a.word(32 * (heads - 1)) != cursor:
        raise _NotCanonical
    if a.array_len(cursor) != n:
        raise _NotCanonical
    base = cursor + 32
    expected = 32 * n
    calls = []
    for i in range(n):
        if a.word(base + 32 * i) != expected:
            raise _NotCanonical
        length, head, end = a.bytes_at(base + expected)
        calls.append((values[i], length, head))
        expected = end - base
    return calls


def _inner_action(value: int, length: int, head: bytes) -> str:
    if length == 0:
        # Plain value transfer. With no value it moves nothing, so it is not a
        # transfer — it is a bare call into whatever `dest` is. With value, see
        # WHAT IT CANNOT KNOW above: `dest`'s receive/fallback code still runs.
        return "transfer" if value > 0 else "empty_call"
    if length < 4:
        return "unrecognized_call_data"
    for sig, label in _NAMED_SIGNATURES.items():
        if _selectors()[sig] == head:
            return label
    # Unnamed: report the selector itself, so an operator can allowlist one
    # exact function (`call:0x12345678`) rather than a whole category.
    return "call:0x" + head.hex()


def classify_user_operation(call_data: bytes, init_code: bytes = b"", *,
                            account_factory: Optional[str] = None) -> list[str]:
    """The actions a UserOperation performs, read from its own bytes.

    Returns one label per thing the platform would be paying gas for. A caller's
    declared action is deliberately not a parameter: nothing it says about its
    own request can change the answer.

    `init_code` is sponsored too — the EntryPoint runs it on the paymaster's
    gas. Deploying the platform's own account through the configured
    `account_factory` is part of every first operation and adds no label;
    initCode through any other factory (or with no factory configured to
    recognise it against) is labelled `init_code:<factory>`, which an
    allowlist then has to name explicitly.

    Time and memory are linear in the call data and the returned list has at
    most MAX_BATCH_CALLS + 1 entries; see HOW IT DECODES above.
    """
    call_data = bytes(call_data or b"")
    init_code = bytes(init_code or b"")
    labels: list[str] = []

    if init_code:
        factory = "0x" + init_code[:20].hex() if len(init_code) >= 20 else "malformed"
        if not (account_factory and factory == str(account_factory).lower()):
            labels.append(f"init_code:{factory}")

    if not call_data:
        return labels + ["empty_call_data"]

    sel = call_data[:4]
    table = _selectors()
    args = _Args(memoryview(call_data)[4:])
    try:
        if sel == table[_ACCOUNT_EXECUTE]:
            calls = _walk_execute(args)
        elif sel == table[_ACCOUNT_BATCH]:
            calls = _walk_batch(args, with_values=False)
        elif sel == table[_ACCOUNT_BATCH_VALUES]:
            calls = _walk_batch(args, with_values=True)
        else:
            return labels + ["unrecognized_call_data"]
    except _TooManyCalls:
        return labels + ["oversized_batch"]
    except _NotCanonical:
        # Bytes that carry an account selector but are not the canonical
        # encoding of its arguments are not a call anyone can describe.
        return labels + ["unrecognized_call_data"]

    if not calls:
        return labels + ["empty_batch"]
    return labels + [_inner_action(v, n, h) for v, n, h in calls]


def summarize_labels(labels: Sequence[str]) -> str:
    """A bounded, order-preserving rendering of a label list for a log line or a
    response body: distinct labels only, at most _MAX_LABELS_ECHOED of them."""
    distinct = list(dict.fromkeys(str(x) for x in labels))
    shown = ",".join(distinct[:_MAX_LABELS_ECHOED])
    if len(distinct) > _MAX_LABELS_ECHOED:
        shown += f",+{len(distinct) - _MAX_LABELS_ECHOED} more"
    return shown


# ── who is spending ──────────────────────────────────────────────────────
#
# A ContextVar rather than a parameter on 17 files' `execute(**kwargs)`: the
# identity has to reach a signing site several frames below the entry point,
# and threading it by hand is exactly the kind of change where one missed file
# becomes an unmetered path. Same idiom as gateway.security_gate's request
# context, and it propagates into everything awaited within the dispatch.

import contextvars  # noqa: E402  (kept beside the thing it exists for)

_caller_identity: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sponsorship_caller_identity", default="")


def canonical_identity(identity: Any) -> str:
    """One spelling per spender, decided in one place.

    An EVM address is case-insensitive — EIP-55 mixed case is a checksum, not an
    identity — so `0xCAFE…` and `0xcafe…` must draw on the same budget or the
    cap is trivially doubled by changing capitalisation. Anything that is NOT an
    address keeps its case: a generic user id may distinguish `A` from `a`, and
    folding those together would merge two spenders into one.
    """
    text = str(identity or "").strip()
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", text):
        return text.lower()
    return text


def set_caller_identity(identity: str):
    """Bind the caller identity for the current dispatch: whatever identity the
    entry point bound, which is authenticated only if that entry point derived
    it from a session. Returns the token to reset with — callers should reset in
    a `finally`."""
    return _caller_identity.set(canonical_identity(identity))


def reset_caller_identity(token) -> None:
    try:
        _caller_identity.reset(token)
    except (ValueError, LookupError):
        # A token from another context: nothing to reset, and raising here would
        # turn a bookkeeping detail into a failed user request.
        pass


def resolve_caller_identity() -> str:
    """The identity to meter this signature against.

    Two sources, in order: the tool dispatch that is running (set by the tool
    dispatcher), then the identity the security middleware bound for the HTTP
    request (a session's identity, else the caller-written X-Wallet-Address
    header or a body field). Empty when neither exists — which a configured cap
    treats as a denial rather than as a free pass.
    """
    who = _caller_identity.get()
    if who:
        return who
    try:
        from gateway.security_gate import current_request_security
        return canonical_identity((current_request_security() or {}).get("wallet"))
    except Exception:
        return ""


# ── the one signer ───────────────────────────────────────────────────────
#
# Every platform signature in runtime/blockchain/ is produced here, and
# tests/test_sponsorship_policy_is_enforced.py fails if a new one is not.
#
# The exemptions below sign with no policy check: no allowlist and no daily
# cap. They are listed rather than simply absent so the set is reviewable — an
# unlisted unmetered site fails the test.
#
# Three are EAS writes signed with the platform key, and their call data is not
# fixed. The catalog capabilities create_attestation and batch_attest reach
# eas.attest (when the batch queue submits) and eas.attest_time_critical with a
# recipient and payload fields the caller supplies, and revoke_attestation
# reaches eas.revoke with the attestation uid and schema the caller names. The
# service dispatcher's record of a completed action goes through the same
# queue. They are exempt so that one caller's daily cap is not charged for
# another's attestation and the audit trail does not stop at the cap; the cost
# is that whoever can call those capabilities spends the platform's gas with
# no cap. The fourth, gas_sponsor.sponsor, is GasSponsor.sponsor_transaction,
# which signs and sends whatever transaction it is handed; nothing in this tree
# calls it.
#
# AN EXEMPTION IS A CLAIM, AND ONE OF THEM WAS FALSE. `web3.platform_account`
# was listed as "shared account handle; every USE of it is a call site metered on
# its own". No use of it was. `Web3Manager.get_account()` returned the unmetered
# signer, `Web3Manager.send_transaction` signed with it, and that method is the
# ONLY signing path the 45 services in runtime/blockchain/services/** have — 35
# call sites across 16 services, every one of them a platform signature the
# D-045 cap never saw. The claim was the whole justification; nothing checked it.
#
# The exemption is gone. `Web3Manager.signer()` is metered like every other
# capability's `_platform_signer`, and `get_account()` hands back an address, not
# something that signs. A deployment that configures `allowed_actions` must list
# `web3.send_transaction` (or whatever `action=` its call sites pass) — an
# allowlist that silently excluded the platform's busiest signing path was
# exactly the failure this list exists to prevent.
UNMETERED_PLATFORM_OPERATIONS = {
    "eas.attest": "EAS attestation write (EASClient.attest), the batch queue's submissions included",
    "eas.attest_time_critical": "the same write on the time-critical path (create_attestation)",
    "eas.revoke": "revoking an attestation by the uid the caller names (revoke_attestation)",
    "gas_sponsor.sponsor": "GasSponsor.sponsor_transaction: signs and sends the transaction it "
                           "is handed; nothing in this tree calls it",
}


def unmetered_platform_signer(key: str, action: str):
    """The synchronous door for a listed exemption.

    `platform_signer` is async because pricing a capped request needs a live
    quote. An exempt operation is never priced, so it does not need to await
    anything — but it still goes through the list, so the exemption stays
    visible instead of being a bare `Account.from_key` somebody has to notice.
    """
    from eth_account import Account

    if action not in UNMETERED_PLATFORM_OPERATIONS:
        raise SponsorshipDenied(SponsorshipDecision(
            False, "unlisted_exemption",
            f"'{action}' asked to skip sponsorship metering but is not in "
            f"UNMETERED_PLATFORM_OPERATIONS"))
    return MeteredSigner(Account.from_key(key), None, action, "", None, metered=False)


class PlatformAddress:
    """The platform account as a HANDLE: its address, and nothing that signs.

    35 call sites read `get_account().address` to fill a transaction's `from`.
    One of them is not a read — it went on to sign, unmetered, with the account
    the handle carries. Handing back something that cannot sign makes the
    difference structural instead of a habit: a `from` address is free, and a
    signature goes through `Web3Manager.signer()`, which is metered.

    Only `sign_transaction` is refused — that is the gas-sponsored operation
    D-045 governs. Message signing is not a transaction and is not in its scope;
    it delegates like every other attribute.
    """

    def __init__(self, account) -> None:
        self._account = account

    @property
    def address(self) -> str:
        return self._account.address

    def sign_transaction(self, tx):
        raise SponsorshipDenied(SponsorshipDecision(
            False, "unmetered_signature",
            "the platform account handle does not sign: a transaction is signed "
            "through Web3Manager.signer()/send_transaction, which meters it "
            "against the D-045 sponsorship policy"))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._account, name)


def platform_address(key: str) -> PlatformAddress:
    """The platform account handle for *key* — built HERE, like every other
    account in this system.

    `test_f_no_blockchain_capability_constructs_a_platform_signer_directly`
    sweeps runtime/blockchain/ for `Account.from_key(` outside this module, and
    it is right to: a key loaded anywhere else is a signature the policy never
    saw. A handle that cannot sign is still an account built from the paymaster
    key, so it is built through this door and the sweep keeps its meaning.
    """
    from eth_account import Account

    return PlatformAddress(Account.from_key(key))


class MeteredSigner:
    """An eth_account signer that consults the sponsorship policy at the moment
    it signs — when the transaction's real gas numbers exist.

    Delegates every other attribute to the wrapped account, so it is a drop-in
    for the `Account.from_key(...)` it replaced.
    """

    def __init__(self, account, policy: Optional[SponsorshipPolicy], action: str,
                 identity: str, eth_usd: Optional[float], metered: bool = True) -> None:
        self._account = account
        self._policy = policy
        self._action = action
        self._identity = identity
        self._eth_usd = eth_usd
        self._metered = metered
        self._last_reservation_id: Optional[str] = None

    @property
    def last_reservation_id(self) -> Optional[str]:
        """The ledger row this signer last opened, or None.

        A caller that goes on to broadcast is the only party that ever learns
        whether the transaction landed, and it had no handle on the row — which
        is why the row could only ever be written at signing time. It can now
        call `policy.settle(...)` or `policy.abandon(...)` with this.
        """
        return self._last_reservation_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._account, name)

    def _estimate_usd(self, tx: dict) -> float:
        if not self._eth_usd:
            return 0.0
        try:
            gas = int(tx.get("gas", 0) or 0)
            price = int(tx.get("gasPrice", 0) or tx.get("maxFeePerGas", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
        return (gas * price / 1e18) * float(self._eth_usd)

    def sign_transaction(self, tx):
        if not self._metered or self._policy is None or not self._policy.enforces_a_cap:
            return self._account.sign_transaction(tx)

        decision = self._policy.authorize_and_reserve(
            self._action, identity=self._identity, est_usd=self._estimate_usd(tx))
        if not decision.allowed:
            logger.warning("platform signature denied (%s): %s",
                           self._action, decision.code)
            raise SponsorshipDenied(decision)
        try:
            signed = self._account.sign_transaction(tx)
        except Exception:
            self._policy.release(decision.reservation_id)
            raise
        # The signature now exists. It is recorded as a SIGNATURE — it holds the
        # budget, because it may land, and it does not claim gas has been paid.
        self._policy.commit(decision.reservation_id)
        self._last_reservation_id = decision.reservation_id
        return signed


async def platform_signer(config: dict, action: str, *, key: Optional[str] = None,
                          identity: Optional[str] = None,
                          metered: bool = True) -> MeteredSigner:
    """Build the platform signer for one operation.

    `action` is `<capability>.<method>` and is what the allowlist is checked
    against. A cap denominated in dollars needs a price; if one is configured
    and no quote can be had, this raises rather than sign something it cannot
    meter.
    """
    from eth_account import Account

    cfg = config or {}
    bc = cfg.get("blockchain", {}) or {}
    raw_key = key if key is not None else bc.get("paymaster_private_key", "")
    account = Account.from_key(raw_key)

    if not metered:
        if action not in UNMETERED_PLATFORM_OPERATIONS:
            raise SponsorshipDenied(SponsorshipDecision(
                False, "unlisted_exemption",
                f"'{action}' asked to skip sponsorship metering but is not in "
                f"UNMETERED_PLATFORM_OPERATIONS"))
        return MeteredSigner(account, None, action, "", None, metered=False)

    policy = SponsorshipPolicy.from_config(cfg)
    if not policy.enforces_a_cap:
        return MeteredSigner(account, policy, action,
                             resolve_caller_identity(), None)

    from runtime.blockchain.price_feed import PriceFeed
    quote = await PriceFeed(cfg).eth_usd()
    who = (canonical_identity(identity) if identity is not None
           else resolve_caller_identity())
    return MeteredSigner(account, policy, action, who, float(quote["price"]))
