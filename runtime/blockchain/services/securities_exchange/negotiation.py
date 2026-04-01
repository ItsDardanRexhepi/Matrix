"""
TermsNegotiation — private placement negotiation engine for the
tokenized securities exchange.

Supports multi-round offer/counter-offer workflows for private placements.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_VALID_STATUSES = ("pending", "countered", "accepted", "rejected", "expired")


class TermsNegotiation:
    """Private placement negotiation engine.

    Config keys (under ``config["securities"]``):
        offer_expiry_seconds (int): Default offer TTL (default 7 days).
        max_counter_rounds (int): Max counter-offer rounds (default 10).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg: dict[str, Any] = config.get("securities", {})

        self._offer_expiry: int = int(
            s_cfg.get("offer_expiry_seconds", 7 * 86400)
        )
        self._max_rounds: int = int(s_cfg.get("max_counter_rounds", 10))

        # offer_id -> offer record
        self._offers: dict[str, dict[str, Any]] = {}
        # security_id -> [offer_ids]
        self._security_offers: dict[str, list[str]] = {}

        logger.info(
            "TermsNegotiation initialised (expiry=%ds, max_rounds=%d).",
            self._offer_expiry, self._max_rounds,
        )

    async def create_offer(
        self, issuer: str, security_id: str, terms: dict
    ) -> dict:
        """Create a new private placement offer.

        Args:
            issuer: Issuer wallet address.
            security_id: Security being offered.
            terms: Dict with keys like 'price_per_unit', 'min_investment',
                   'max_investment', 'lockup_period', 'discount_pct',
                   'vesting_schedule'.

        Returns:
            Offer record.
        """
        if not issuer or not security_id:
            raise ValueError("issuer and security_id are required")
        if not terms:
            raise ValueError("Terms cannot be empty")

        offer_id = str(uuid.uuid4())
        now = int(time.time())

        offer = {
            "offer_id": offer_id,
            "security_id": security_id,
            "issuer": issuer,
            "current_terms": dict(terms),
            "original_terms": dict(terms),
            "status": "pending",
            "round": 1,
            "history": [
                {
                    "round": 1,
                    "party": issuer,
                    "action": "create",
                    "terms": dict(terms),
                    "timestamp": now,
                }
            ],
            "created_at": now,
            "expires_at": now + self._offer_expiry,
            "updated_at": now,
            "accepted_by": None,
        }

        self._offers[offer_id] = offer
        self._security_offers.setdefault(security_id, []).append(offer_id)

        logger.info(
            "Offer created: id=%s security=%s issuer=%s",
            offer_id, security_id, issuer,
        )
        return dict(offer)

    async def counter_offer(
        self, offer_id: str, investor: str, counter_terms: dict
    ) -> dict:
        """Submit a counter-offer to an existing offer.

        Args:
            offer_id: The offer to counter.
            investor: Investor submitting the counter.
            counter_terms: Modified terms.

        Returns:
            Updated offer record.
        """
        offer = self._offers.get(offer_id)
        if not offer:
            raise ValueError(f"Offer {offer_id} not found")

        if offer["status"] not in ("pending", "countered"):
            raise ValueError(
                f"Offer {offer_id} is {offer['status']}, cannot counter"
            )

        now = int(time.time())
        if now > offer["expires_at"]:
            offer["status"] = "expired"
            offer["updated_at"] = now
            raise ValueError(f"Offer {offer_id} has expired")

        if offer["round"] >= self._max_rounds:
            raise ValueError(
                f"Maximum negotiation rounds ({self._max_rounds}) reached"
            )

        offer["round"] += 1
        offer["status"] = "countered"
        offer["current_terms"] = dict(counter_terms)
        offer["updated_at"] = now
        offer["expires_at"] = now + self._offer_expiry  # Reset expiry

        offer["history"].append({
            "round": offer["round"],
            "party": investor,
            "action": "counter",
            "terms": dict(counter_terms),
            "timestamp": now,
        })

        logger.info(
            "Counter-offer submitted: offer=%s round=%d investor=%s",
            offer_id, offer["round"], investor,
        )
        return dict(offer)

    async def accept_offer(self, offer_id: str, party: str) -> dict:
        """Accept the current terms of an offer.

        Args:
            offer_id: The offer to accept.
            party: The accepting party's address.

        Returns:
            Finalised offer record.
        """
        offer = self._offers.get(offer_id)
        if not offer:
            raise ValueError(f"Offer {offer_id} not found")

        if offer["status"] not in ("pending", "countered"):
            raise ValueError(
                f"Offer {offer_id} is {offer['status']}, cannot accept"
            )

        now = int(time.time())
        if now > offer["expires_at"]:
            offer["status"] = "expired"
            offer["updated_at"] = now
            raise ValueError(f"Offer {offer_id} has expired")

        offer["status"] = "accepted"
        offer["accepted_by"] = party
        offer["updated_at"] = now

        offer["history"].append({
            "round": offer["round"],
            "party": party,
            "action": "accept",
            "terms": dict(offer["current_terms"]),
            "timestamp": now,
        })

        logger.info(
            "Offer accepted: offer=%s party=%s final_terms=%s",
            offer_id, party, offer["current_terms"],
        )
        return dict(offer)

    async def get_negotiations(self, security_id: str) -> list:
        """Get all negotiation offers for a security.

        Returns:
            List of offer records.
        """
        offer_ids = self._security_offers.get(security_id, [])
        results = []
        now = int(time.time())

        for oid in offer_ids:
            offer = self._offers.get(oid)
            if not offer:
                continue
            # Auto-expire stale offers
            if offer["status"] in ("pending", "countered") and now > offer["expires_at"]:
                offer["status"] = "expired"
                offer["updated_at"] = now
            results.append(dict(offer))

        return results
