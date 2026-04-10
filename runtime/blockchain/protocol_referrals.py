"""Protocol Referral Fees -- automated DeFi integrator revenue collection.

Many DeFi protocols (Uniswap, Aave, 1inch, etc.) pay a percentage of
transaction fees to integrators who route volume through them.  This is
a standard incentive mechanism: protocols want distribution, and
integrators earn a cut for delivering users.

0pnMatrx collects these referral fees automatically whenever a user
executes a DeFi transaction through the platform.  The fees are routed
to the NeoSafe multisig so they accrue to the protocol treasury without
any manual intervention.

Supported programmes
--------------------
- **Uniswap V3 interface fee** -- up to 25 bps on swaps, paid in the
  output token to a designated fee recipient.
- **Aave V3 referral rewards** -- a referral code passed in
  ``supply`` / ``borrow`` / ``flashLoan`` calls earns a share of the
  protocol's interest revenue.
- **1inch referral programme** -- a referrer address appended to API
  swap requests earns a share of the positive-slippage surplus.

All revenue parameters live in ``PROTOCOL_REFERRAL_CONFIGS`` so they
can be tuned or extended without touching call-site code.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NeoSafe multisig — all referral fees route here
# ---------------------------------------------------------------------------

NEOSAFE_ADDRESS = "0x46fF491D7054A6F500026B3E81f358190f8d8Ec5"

# ---------------------------------------------------------------------------
# Per-protocol configuration
# ---------------------------------------------------------------------------

PROTOCOL_REFERRAL_CONFIGS: dict[str, dict[str, Any]] = {
    "uniswap_v3": {
        "fee_recipient": NEOSAFE_ADDRESS,
        "fee_bps": 25,  # 0.25% — Uniswap's max interface fee
        "enabled": True,
        "description": "Uniswap V3 interface fee on swaps",
    },
    "aave_v3": {
        "referral_code": 0,  # Set to your Aave referral code once registered
        "enabled": True,
        "description": "Aave V3 referral rewards on loans",
    },
    "1inch": {
        "referrer_address": NEOSAFE_ADDRESS,
        "enabled": True,
        "description": "1inch referral program on swaps",
    },
}


class ProtocolReferralCollector:
    """Collect and track DeFi protocol referral fees.

    Provides helper methods that return the correct fee parameters
    for each supported protocol, and persists referral events to
    SQLite for accounting and dashboard display.
    """

    def __init__(
        self,
        db=None,
        config: dict | None = None,
    ) -> None:
        """Initialise the collector.

        Parameters
        ----------
        db : runtime.db.database.Database, optional
            The platform's shared async SQLite wrapper.  When provided,
            referral events are persisted to a local table.
        config : dict, optional
            Override ``PROTOCOL_REFERRAL_CONFIGS``.  Useful for tests
            or per-environment tuning.
        """
        self.db = db
        self.config: dict[str, dict[str, Any]] = (
            config if config is not None else PROTOCOL_REFERRAL_CONFIGS
        )
        # Resolve NeoSafe address: prefer the Uniswap fee_recipient in
        # the active config (it is canonical), fall back to the module
        # constant.
        uniswap_cfg = self.config.get("uniswap_v3", {})
        self.neosafe_address: str = uniswap_cfg.get(
            "fee_recipient", NEOSAFE_ADDRESS
        )

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the ``protocol_referral_events`` table if it does not exist."""
        if self.db is None:
            logger.warning(
                "ProtocolReferralCollector.initialize called without a db — "
                "event recording will be unavailable"
            )
            return

        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocol_referral_events (
                id                  TEXT PRIMARY KEY,
                protocol            TEXT NOT NULL,
                tx_hash             TEXT,
                estimated_fee_eth   REAL,
                estimated_fee_usd   REAL,
                recorded_at         REAL NOT NULL
            )
            """,
            commit=True,
        )
        logger.info("protocol_referral_events table ready")

    # ------------------------------------------------------------------
    # Protocol-specific parameter helpers
    # ------------------------------------------------------------------

    def get_uniswap_fee_params(self) -> dict:
        """Return fee parameters for Uniswap V3 ``ExactInputSingle`` / ``ExactInputMultihop``.

        Returns a dict with ``feeRecipient`` and ``fee`` (in basis
        points) ready to be merged into the swap call parameters.
        If the Uniswap V3 referral is disabled in the config, returns
        an empty dict so callers can safely ``**unpack`` the result.
        """
        cfg = self.config.get("uniswap_v3", {})
        if not cfg.get("enabled", False):
            return {}

        return {
            "feeRecipient": cfg.get("fee_recipient", self.neosafe_address),
            "fee": cfg.get("fee_bps", 25),
        }

    def get_aave_referral_code(self) -> int:
        """Return the Aave V3 referral code for ``supply`` / ``borrow`` / ``flashLoan``.

        Returns ``0`` (no referral) when the Aave programme is
        disabled.
        """
        cfg = self.config.get("aave_v3", {})
        if not cfg.get("enabled", False):
            return 0

        return int(cfg.get("referral_code", 0))

    def get_1inch_referrer(self) -> str:
        """Return the referrer address to pass in 1inch API swap requests.

        Returns an empty string when the 1inch programme is disabled.
        """
        cfg = self.config.get("1inch", {})
        if not cfg.get("enabled", False):
            return ""

        return cfg.get("referrer_address", self.neosafe_address)

    # ------------------------------------------------------------------
    # Revenue estimation
    # ------------------------------------------------------------------

    async def estimate_monthly_referral_revenue(
        self,
        swap_volume_usd: float,
        loan_volume_usd: float,
    ) -> dict:
        """Estimate monthly referral income across all protocols.

        Parameters
        ----------
        swap_volume_usd : float
            Expected monthly swap volume routed through the platform
            (applies to Uniswap and 1inch).
        loan_volume_usd : float
            Expected monthly lending / borrowing volume routed through
            the platform (applies to Aave).

        Returns
        -------
        dict
            Per-protocol estimates and aggregate total.
        """
        uniswap_revenue = swap_volume_usd * 0.0025  # 25 bps
        aave_revenue = loan_volume_usd * 0.001  # ~10 bps (varies)
        oneinch_revenue = swap_volume_usd * 0.001  # ~10 bps

        total = uniswap_revenue + aave_revenue + oneinch_revenue

        logger.debug(
            "Estimated monthly referral revenue: $%.2f "
            "(uni=$%.2f aave=$%.2f 1inch=$%.2f)",
            total,
            uniswap_revenue,
            aave_revenue,
            oneinch_revenue,
        )

        return {
            "uniswap_v3": uniswap_revenue,
            "aave_v3": aave_revenue,
            "1inch": oneinch_revenue,
            "total_estimated_usd": total,
            "swap_volume_usd": swap_volume_usd,
            "loan_volume_usd": loan_volume_usd,
        }

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    async def record_referral_event(
        self,
        protocol: str,
        tx_hash: str,
        estimated_fee_eth: float,
        eth_price_usd: float = 2500.0,
    ) -> None:
        """Persist a referral event to SQLite.

        Parameters
        ----------
        protocol : str
            Protocol identifier (e.g. ``uniswap_v3``, ``aave_v3``,
            ``1inch``).
        tx_hash : str
            On-chain transaction hash that triggered the referral.
        estimated_fee_eth : float
            Estimated fee amount denominated in ETH.
        eth_price_usd : float
            Spot ETH price used to derive the USD estimate.  Defaults
            to 2500 when a live feed is unavailable.
        """
        if self.db is None:
            logger.warning(
                "Cannot record referral event — no database configured"
            )
            return

        event_id = str(uuid.uuid4())
        estimated_fee_usd = estimated_fee_eth * eth_price_usd
        now = time.time()

        await self.db.execute(
            """
            INSERT INTO protocol_referral_events
                (id, protocol, tx_hash, estimated_fee_eth, estimated_fee_usd, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                protocol,
                tx_hash,
                estimated_fee_eth,
                estimated_fee_usd,
                now,
            ),
            commit=True,
        )

        logger.info(
            "Recorded referral event %s: protocol=%s tx=%s "
            "fee_eth=%.6f fee_usd=%.2f",
            event_id,
            protocol,
            tx_hash,
            estimated_fee_eth,
            estimated_fee_usd,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    async def get_referral_summary(self, days: int = 30) -> dict:
        """Summarise referral events over the last *days* days.

        Parameters
        ----------
        days : int
            Look-back window in days (default 30).

        Returns
        -------
        dict
            ``total_events``, ``total_estimated_eth``,
            ``total_estimated_usd``, ``by_protocol`` breakdown, and
            the ``days`` parameter echoed back.
        """
        empty_summary: dict[str, Any] = {
            "total_events": 0,
            "total_estimated_eth": 0.0,
            "total_estimated_usd": 0.0,
            "by_protocol": {},
            "days": days,
        }

        if self.db is None:
            logger.warning(
                "Cannot query referral summary — no database configured"
            )
            return empty_summary

        cutoff = time.time() - (days * 86400)

        # Aggregate totals
        totals_row = await self.db.fetchone(
            """
            SELECT
                COUNT(*)                       AS total_events,
                COALESCE(SUM(estimated_fee_eth), 0) AS total_eth,
                COALESCE(SUM(estimated_fee_usd), 0) AS total_usd
            FROM protocol_referral_events
            WHERE recorded_at >= ?
            """,
            (cutoff,),
        )

        if not totals_row or totals_row["total_events"] == 0:
            return empty_summary

        # Per-protocol breakdown
        protocol_rows = await self.db.fetchall(
            """
            SELECT
                protocol,
                COUNT(*)                       AS events,
                COALESCE(SUM(estimated_fee_eth), 0) AS total_eth,
                COALESCE(SUM(estimated_fee_usd), 0) AS total_usd
            FROM protocol_referral_events
            WHERE recorded_at >= ?
            GROUP BY protocol
            """,
            (cutoff,),
        )

        by_protocol: dict[str, dict[str, Any]] = {}
        for row in protocol_rows:
            by_protocol[row["protocol"]] = {
                "events": row["events"],
                "total_estimated_eth": row["total_eth"],
                "total_estimated_usd": row["total_usd"],
            }

        return {
            "total_events": totals_row["total_events"],
            "total_estimated_eth": totals_row["total_eth"],
            "total_estimated_usd": totals_row["total_usd"],
            "by_protocol": by_protocol,
            "days": days,
        }

    # ------------------------------------------------------------------
    # Dashboard helpers
    # ------------------------------------------------------------------

    def get_supported_protocols(self) -> list[dict]:
        """Return metadata for every configured protocol.

        Intended for dashboard / admin-panel display.  Each entry
        contains the protocol key, its config fields, and whether
        it is currently enabled.
        """
        protocols: list[dict] = []
        for key, cfg in self.config.items():
            protocols.append(
                {
                    "protocol": key,
                    "enabled": cfg.get("enabled", False),
                    "description": cfg.get("description", ""),
                    "config": {
                        k: v
                        for k, v in cfg.items()
                        if k not in ("description",)
                    },
                }
            )
        return protocols
