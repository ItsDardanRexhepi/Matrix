"""
JurorPool — verifiable random juror selection for dispute resolution.

Uses Chainlink VRF (via Component 11 Oracle Gateway) to ensure juror
selection is provably fair and cannot be manipulated by either party.
Jurors must stake tokens to participate and are weighted by expertise
relevant to the dispute category.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Minimum stake (in platform tokens) required to join the juror pool.
DEFAULT_MIN_JUROR_STAKE: float = 50.0


class JurorPool:
    """Manages the pool of available jurors and handles selection."""

    def __init__(self, config: dict | None = None, oracle_gateway: Any | None = None) -> None:
        self.config = config or {}
        self._oracle_gateway = oracle_gateway
        self._min_stake = float(
            self.config.get("dispute_resolution", {}).get(
                "min_juror_stake", DEFAULT_MIN_JUROR_STAKE
            )
        )
        # address -> juror record
        self._jurors: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_juror(
        self, address: str, expertise: list[str], stake: float
    ) -> dict:
        """Register a new juror in the pool.

        Args:
            address: Wallet address of the juror.
            expertise: List of dispute categories the juror is qualified for.
            stake: Amount of tokens staked.

        Returns:
            Juror registration record.

        Raises:
            ValueError: If the stake is below the minimum or the address
                is already registered.
        """
        if address in self._jurors:
            raise ValueError(f"Juror already registered: {address}")

        if stake < self._min_stake:
            raise ValueError(
                f"Stake {stake} is below minimum {self._min_stake}"
            )

        valid_categories = {
            "transaction", "nft_ownership", "ip_rights",
            "contract_breach", "fraud", "service_quality",
        }
        invalid = set(expertise) - valid_categories
        if invalid:
            raise ValueError(f"Invalid expertise categories: {invalid}")

        record: dict[str, Any] = {
            "address": address,
            "expertise": expertise,
            "stake": stake,
            "registered_at": time.time(),
            "disputes_served": 0,
            "reputation_score": 1.0,
            "active": True,
        }
        self._jurors[address] = record
        logger.info("Juror registered — address=%s expertise=%s", address, expertise)
        return record

    async def remove_juror(self, address: str) -> dict:
        """Remove a juror from the pool.

        Raises:
            KeyError: If the address is not registered.
        """
        if address not in self._jurors:
            raise KeyError(f"Juror not found: {address}")

        record = self._jurors.pop(address)
        record["active"] = False
        record["removed_at"] = time.time()
        logger.info("Juror removed — address=%s", address)
        return record

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    async def select_jurors(
        self, dispute_id: str, count: int = 5, category: str | None = None
    ) -> list[dict]:
        """Select *count* jurors for a dispute using Chainlink VRF.

        Jurors with matching expertise for *category* are given higher
        weight so they are more likely to be selected, but any eligible
        juror may still be chosen to preserve decentralisation.

        Args:
            dispute_id: Identifier of the dispute requiring jurors.
            count: Number of jurors to select (default 5).
            category: Optional dispute category for expertise weighting.

        Returns:
            List of selected juror records.

        Raises:
            RuntimeError: If there are fewer eligible jurors than *count*.
        """
        eligible = [j for j in self._jurors.values() if j["active"]]
        if len(eligible) < count:
            raise RuntimeError(
                f"Not enough eligible jurors: need {count}, have {len(eligible)}"
            )

        # ---- Obtain randomness from VRF (Component 11) ----
        vrf_seed = await self._request_vrf_seed(dispute_id)

        # Build weighted pool: jurors with matching expertise get 3x weight.
        weighted_pool: list[dict] = []
        for juror in eligible:
            weight = 3 if category and category in juror["expertise"] else 1
            # Also boost by reputation
            weight = int(weight * juror["reputation_score"])
            weighted_pool.extend([juror] * max(weight, 1))

        # Deterministic shuffle using VRF seed
        selected: list[dict] = []
        seen_addresses: set[str] = set()
        idx = 0
        while len(selected) < count:
            # Derive a sub-seed per slot so each pick is independent
            slot_hash = hashlib.sha256(
                f"{vrf_seed}:{idx}".encode()
            ).hexdigest()
            position = int(slot_hash, 16) % len(weighted_pool)
            candidate = weighted_pool[position]

            if candidate["address"] not in seen_addresses:
                seen_addresses.add(candidate["address"])
                selected.append(candidate)

            idx += 1
            # Safety: prevent infinite loops if pool is exhausted
            if idx > len(weighted_pool) * 10:
                break

        if len(selected) < count:
            raise RuntimeError(
                f"Could not select {count} unique jurors from pool"
            )

        for juror in selected:
            juror["disputes_served"] += 1

        logger.info(
            "Selected %d jurors for dispute=%s (vrf_seed=%s)",
            count,
            dispute_id,
            vrf_seed[:16],
        )
        return selected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request_vrf_seed(self, dispute_id: str) -> str:
        """Request verifiable randomness from the Oracle Gateway.

        Falls back to a deterministic hash when the oracle is unavailable
        (e.g. in tests), but logs a warning since this is NOT
        cryptographically secure.
        """
        if self._oracle_gateway is not None:
            try:
                result = await self._oracle_gateway.execute(
                    action="request_random",
                    request_type="random_vrf",
                    dispute_id=dispute_id,
                )
                if isinstance(result, dict) and "random_value" in result:
                    return str(result["random_value"])
                if isinstance(result, str):
                    return result
            except Exception:
                logger.warning(
                    "VRF request failed for dispute=%s — falling back to hash",
                    dispute_id,
                    exc_info=True,
                )

        # Fallback: deterministic but not verifiable
        fallback = hashlib.sha256(
            f"{dispute_id}:{uuid.uuid4().hex}".encode()
        ).hexdigest()
        logger.warning("Using NON-VRF fallback seed for dispute=%s", dispute_id)
        return fallback
