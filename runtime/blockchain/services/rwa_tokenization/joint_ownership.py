from __future__ import annotations

"""
JointOwnership — fractional ownership management for tokenized RWAs.

Allows multiple parties to own shares of a single asset token, transfer
shares between each other, and vote on collective actions.
"""

import logging
import math
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_SHARE_TOLERANCE = 0.001  # acceptable float rounding for 100 % check


class JointOwnership:
    """Manages fractional ownership structures for RWA tokens.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``rwa.min_share_pct`` (default 0.01)
        for the smallest permissible ownership share percentage.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        rwa_cfg = config.get("rwa", {})
        self._min_share_pct: float = rwa_cfg.get("min_share_pct", 0.01)
        # token_id -> ownership structure
        self._structures: dict[str, dict[str, Any]] = {}
        # token_id -> list of votes
        self._votes: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_joint(self, token_id: str, owners: list[dict]) -> dict:
        """Create a joint-ownership structure for *token_id*.

        Parameters
        ----------
        token_id : str
            The RWA token to apply fractional ownership to.
        owners : list[dict]
            Each dict must contain ``address`` (str) and ``percentage`` (float).
            Percentages must sum to 100.

        Returns
        -------
        dict
            The newly created ownership structure.
        """
        if not owners:
            raise ValueError("At least one owner is required")

        if token_id in self._structures:
            raise ValueError(f"Joint ownership already exists for token {token_id}")

        total_pct = sum(o.get("percentage", 0) for o in owners)
        if abs(total_pct - 100.0) > _SHARE_TOLERANCE:
            raise ValueError(
                f"Owner percentages must sum to 100, got {total_pct:.4f}"
            )

        addresses_seen: set[str] = set()
        normalised_owners: list[dict[str, Any]] = []
        for entry in owners:
            addr = entry.get("address")
            pct = entry.get("percentage", 0)
            if not addr:
                raise ValueError("Each owner must have an 'address'")
            if pct < self._min_share_pct:
                raise ValueError(
                    f"Share {pct}% for {addr} is below minimum {self._min_share_pct}%"
                )
            if addr in addresses_seen:
                raise ValueError(f"Duplicate owner address: {addr}")
            addresses_seen.add(addr)
            normalised_owners.append({"address": addr, "percentage": round(pct, 6)})

        structure = {
            "token_id": token_id,
            "owners": normalised_owners,
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": "active",
        }
        self._structures[token_id] = structure
        self._votes[token_id] = []
        logger.info("Joint ownership created for token %s with %d owners", token_id, len(normalised_owners))
        return structure

    async def transfer_share(
        self, token_id: str, from_addr: str, to_addr: str, percentage: float
    ) -> dict:
        """Transfer *percentage* of ownership from one party to another.

        If *to_addr* is not already an owner it is added; if *from_addr*'s
        remaining share drops to zero it is removed.
        """
        structure = self._get_structure(token_id)

        if percentage <= 0:
            raise ValueError("Transfer percentage must be positive")

        from_owner = self._find_owner(structure, from_addr)
        if from_owner is None:
            raise ValueError(f"{from_addr} is not an owner of token {token_id}")

        if from_owner["percentage"] < percentage - _SHARE_TOLERANCE:
            raise ValueError(
                f"{from_addr} owns {from_owner['percentage']:.4f}% but tried "
                f"to transfer {percentage:.4f}%"
            )

        from_owner["percentage"] = round(from_owner["percentage"] - percentage, 6)

        to_owner = self._find_owner(structure, to_addr)
        if to_owner is not None:
            to_owner["percentage"] = round(to_owner["percentage"] + percentage, 6)
        else:
            structure["owners"].append(
                {"address": to_addr, "percentage": round(percentage, 6)}
            )

        # Remove zero-share owners
        structure["owners"] = [
            o for o in structure["owners"] if o["percentage"] > _SHARE_TOLERANCE
        ]
        structure["updated_at"] = time.time()

        logger.info(
            "Transferred %.4f%% of token %s from %s to %s",
            percentage, token_id, from_addr, to_addr,
        )
        return structure

    async def get_ownership_structure(self, token_id: str) -> dict:
        """Return the current ownership structure for *token_id*."""
        return self._get_structure(token_id)

    async def vote_on_action(
        self, token_id: str, voter: str, action: str, support: bool
    ) -> dict:
        """Cast a vote on a proposed action for a jointly-owned asset.

        Voting power is proportional to ownership percentage.  An action
        passes when supporters hold > 50 % of total shares.

        Returns
        -------
        dict
            Vote record including current tally and pass/fail status.
        """
        structure = self._get_structure(token_id)
        owner = self._find_owner(structure, voter)
        if owner is None:
            raise ValueError(f"{voter} is not an owner of token {token_id}")

        votes = self._votes[token_id]

        # Prevent double-voting on the same action
        for v in votes:
            if v["voter"] == voter and v["action"] == action:
                raise ValueError(f"{voter} has already voted on action '{action}'")

        vote_record = {
            "vote_id": f"vote_{uuid.uuid4().hex[:12]}",
            "token_id": token_id,
            "voter": voter,
            "action": action,
            "support": support,
            "weight": owner["percentage"],
            "timestamp": time.time(),
        }
        votes.append(vote_record)

        # Tally
        action_votes = [v for v in votes if v["action"] == action]
        support_pct = sum(v["weight"] for v in action_votes if v["support"])
        oppose_pct = sum(v["weight"] for v in action_votes if not v["support"])
        total_voted = support_pct + oppose_pct

        passed = support_pct > 50.0
        rejected = oppose_pct >= 50.0

        result = {
            **vote_record,
            "tally": {
                "support_pct": round(support_pct, 4),
                "oppose_pct": round(oppose_pct, 4),
                "total_voted_pct": round(total_voted, 4),
                "total_votes": len(action_votes),
            },
            "status": "passed" if passed else ("rejected" if rejected else "pending"),
        }
        logger.info(
            "Vote on token %s action '%s' by %s: %s (support=%.2f%%)",
            token_id, action, voter, "for" if support else "against", support_pct,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_structure(self, token_id: str) -> dict:
        structure = self._structures.get(token_id)
        if structure is None:
            raise KeyError(f"No joint-ownership structure for token {token_id}")
        return structure

    @staticmethod
    def _find_owner(structure: dict, address: str) -> dict | None:
        for owner in structure["owners"]:
            if owner["address"] == address:
                return owner
        return None
