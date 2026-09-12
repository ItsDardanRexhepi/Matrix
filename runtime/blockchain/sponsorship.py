"""D-045: the gas-sponsorship policy the platform already documents as enforced.

gateway/paymaster.py, the /api/v1/paymaster/sign docstring and the shipped
`openmatrix.config.json.example` all state that an action allowlist and a
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
        base = Path(str(db_cfg.get("path", "data/0pnmatrx.db"))).expanduser()
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
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0) FROM sponsorship_spend "
            "WHERE identity = ? AND created_at >= ? AND ("
            "  state = 'committed' OR (state = 'reserved' AND created_at >= ?))",
            (identity, now - WINDOW_SECONDS, now - RESERVATION_TTL_SECONDS),
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
        action = ",".join(labels)
        identity = canonical_identity(identity)
        est_usd = max(0.0, float(est_usd or 0.0))

        if self.allowed_actions is not None:
            # An empty list of actions is not vacuously allowed.
            refused = [a for a in labels if a not in self.allowed_actions] or (
                [] if labels else ["<nothing>"])
            if refused:
                return SponsorshipDecision(
                    False, "action_not_allowed",
                    f"gas sponsorship not available for action '{','.join(refused)}'",
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
                    "VALUES (?, ?, ?, ?, 'reserved', ?)",
                    (res_id, identity, action, est_usd, now))
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
        return SponsorshipDecision(
            True, "allowed", "within the daily sponsorship cap",
            identity=identity, action=action, est_usd=est_usd,
            spent_usd=spent, cap_usd=cap, reservation_id=res_id)

    def commit(self, reservation_id: str) -> None:
        """The signature was issued — the spend is real."""
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE sponsorship_spend SET state = 'committed' "
                "WHERE id = ? AND state = 'reserved'", (reservation_id,))

    def release(self, reservation_id: str) -> None:
        """The signature was NOT issued — give the budget back, so a failure
        downstream does not charge an identity for gas nobody sponsored."""
        if not reservation_id or self._db_path is None:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM sponsorship_spend WHERE id = ? AND state = 'reserved'",
                         (reservation_id,))

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
# WHAT THIS DECODES. The smart-account wrapper (contracts/OpenMatrixAccount.sol
# `execute(dest, value, func)` and `executeBatch(dest[], func[])`, plus the
# three-array `executeBatch` the MTRX client encodes), then the inner call's
# 4-byte selector.
#
# WHAT IT CANNOT KNOW, stated so nobody reads more into it: a selector names an
# ABI function, not what the target contract does with it. `transfer(address,
# uint256)` on a contract someone wrote to look like a token is still labelled a
# transfer. Binding labels to known token or DEX addresses would need an address
# registry this repo does not have; the daily cap is what bounds the spend
# either way.

# Named inner calls. Each signature is hashed here rather than pasted as hex, so
# a typo is a different signature rather than a silently wrong selector.
_NAMED_SIGNATURES: dict[str, str] = {
    "transfer(address,uint256)": "transfer",        # ERC-20 transfer
    "approve(address,uint256)": "approve",          # ERC-20 approve
    "swap(uint256,address,uint256)": "swap",        # contracts/OpenMatrixDEX.sol
    "mint(address,string,uint96)": "mint_nft",      # contracts/OpenMatrixNFT.sol
}

_ACCOUNT_EXECUTE = "execute(address,uint256,bytes)"
_ACCOUNT_BATCH = "executeBatch(address[],bytes[])"                # OpenMatrixAccount.sol
_ACCOUNT_BATCH_VALUES = "executeBatch(address[],uint256[],bytes[])"  # MTRX client encoding


@lru_cache(maxsize=None)
def _selectors() -> dict[str, bytes]:
    from eth_utils import keccak

    sigs = [_ACCOUNT_EXECUTE, _ACCOUNT_BATCH, _ACCOUNT_BATCH_VALUES, *_NAMED_SIGNATURES]
    return {sig: keccak(text=sig)[:4] for sig in sigs}


def _inner_action(value: int, func: bytes) -> str:
    if not func:
        # Plain value transfer. With no value it moves nothing, so it is not a
        # transfer — it is a bare call into whatever `dest` is.
        return "transfer" if value > 0 else "empty_call"
    if len(func) < 4:
        return "unrecognized_call_data"
    sel = func[:4]
    for sig, label in _NAMED_SIGNATURES.items():
        if _selectors()[sig] == sel:
            return label
    # Unnamed: report the selector itself, so an operator can allowlist one
    # exact function (`call:0x12345678`) rather than a whole category.
    return "call:0x" + sel.hex()


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
    """
    from eth_abi import decode

    call_data = bytes(call_data or b"")
    init_code = bytes(init_code or b"")
    labels: list[str] = []

    if init_code:
        factory = "0x" + init_code[:20].hex() if len(init_code) >= 20 else "malformed"
        if not (account_factory and factory == str(account_factory).lower()):
            labels.append(f"init_code:{factory}")

    if not call_data:
        return labels + ["empty_call_data"]

    sel, args = call_data[:4], call_data[4:]
    table = _selectors()
    try:
        if sel == table[_ACCOUNT_EXECUTE]:
            _dest, value, func = decode(["address", "uint256", "bytes"], args)
            return labels + [_inner_action(int(value), bytes(func))]
        if sel == table[_ACCOUNT_BATCH]:
            dests, funcs = decode(["address[]", "bytes[]"], args)
            values = [0] * len(dests)
        elif sel == table[_ACCOUNT_BATCH_VALUES]:
            dests, values, funcs = decode(["address[]", "uint256[]", "bytes[]"], args)
        else:
            return labels + ["unrecognized_call_data"]
    except Exception:
        # Bytes that carry an account selector but do not decode as its
        # arguments are not a call anyone can describe.
        return labels + ["unrecognized_call_data"]

    if len(dests) != len(funcs) or len(values) != len(dests):
        return labels + ["unrecognized_call_data"]
    if not dests:
        return labels + ["empty_batch"]
    return labels + [_inner_action(int(v), bytes(f)) for v, f in zip(values, funcs)]


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
    """Bind the authenticated caller for the current dispatch. Returns the token
    to reset with — callers should reset in a `finally`."""
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
    dispatcher), then the authenticated HTTP request (set by the security
    middleware). Empty when neither exists — which a configured cap treats as a
    denial rather than as a free pass.
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
# The exemptions below are platform-initiated record-keeping, not sponsorship of
# a caller's operation: fixed call data the model never composes, written on the
# platform's own behalf. Metering them against a per-CALLER daily cap would
# charge one user's budget for another's attestation and would stop the audit
# trail at $50 a day. They are listed rather than simply absent so the set is
# reviewable — an unlisted unmetered site fails the test.
UNMETERED_PLATFORM_OPERATIONS = {
    "eas.attest": "EAS attestation write — fixed schema, the platform's own record",
    "eas.attest_time_critical": "the same write on the time-critical path",
    "eas.revoke": "revoking an attestation the platform itself issued",
    "gas_sponsor.sponsor": "the gas-sponsorship accounting path itself",
    "web3.platform_account": "shared account handle; every USE of it is a call "
                             "site metered on its own",
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
        # The signature now exists; only now is the budget actually spent.
        self._policy.commit(decision.reservation_id)
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
