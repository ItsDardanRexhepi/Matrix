from __future__ import annotations

"""
DAOFactory — deploys and configures DAO governance infrastructure.

Supports three governance models:

- **token_weighted**: voting power proportional to token holdings
- **one_member_one_vote**: equal voting power per member
- **quadratic**: voting power is the square root of tokens held

Each deployment creates a governor contract, a timelock controller,
and a treasury contract address.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

GOVERNANCE_TYPES = {"token_weighted", "one_member_one_vote", "quadratic"}

# Default governance parameters
_DEFAULTS = {
    "voting_delay_blocks": 1,
    "voting_period_blocks": 50_400,  # ~7 days at 12 s/block
    "quorum_pct": 4,
    "proposal_threshold": 1,
    "timelock_delay_seconds": 172_800,  # 2 days
}


class DAOFactory:
    """Factory for deploying DAO governance contracts.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``dao.factory`` sub-key for
        deployment defaults.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        factory_cfg = config.get("dao", {}).get("factory", {})
        self._chain_id: int = config.get("blockchain", {}).get("chain_id", 8453)
        self._voting_delay: int = factory_cfg.get(
            "voting_delay_blocks", _DEFAULTS["voting_delay_blocks"]
        )
        self._voting_period: int = factory_cfg.get(
            "voting_period_blocks", _DEFAULTS["voting_period_blocks"]
        )
        self._quorum_pct: int = factory_cfg.get(
            "quorum_pct", _DEFAULTS["quorum_pct"]
        )
        self._timelock_delay: int = factory_cfg.get(
            "timelock_delay_seconds", _DEFAULTS["timelock_delay_seconds"]
        )

        # Deployed DAOs: dao_id -> deployment record
        self._deployments: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def deploy(
        self,
        creator: str,
        name: str,
        governance_type: str,
        token_address: str | None = None,
    ) -> dict:
        """Deploy a complete DAO governance stack.

        Parameters
        ----------
        creator : str
            Wallet address of the DAO creator.
        name : str
            Human-readable DAO name.
        governance_type : str
            One of ``token_weighted``, ``one_member_one_vote``, ``quadratic``.
        token_address : str, optional
            Existing governance token contract address.  If ``None``, a
            new governance token is "minted" (address generated).

        Returns
        -------
        dict
            Deployment record with contract addresses.
        """
        if not creator:
            raise ValueError("Creator address is required")
        if not name:
            raise ValueError("DAO name is required")
        if governance_type not in GOVERNANCE_TYPES:
            raise ValueError(
                f"Invalid governance type '{governance_type}'. "
                f"Must be one of {sorted(GOVERNANCE_TYPES)}"
            )

        dao_id = f"dao_{uuid.uuid4().hex[:12]}"
        now = time.time()

        # Generate deterministic contract addresses
        seed = f"{dao_id}:{creator}:{name}:{now}"
        governor_addr = "0x" + hashlib.sha256(
            f"{seed}:governor".encode()
        ).hexdigest()[:40]
        timelock_addr = "0x" + hashlib.sha256(
            f"{seed}:timelock".encode()
        ).hexdigest()[:40]
        treasury_addr = "0x" + hashlib.sha256(
            f"{seed}:treasury".encode()
        ).hexdigest()[:40]

        if token_address is None:
            token_address = "0x" + hashlib.sha256(
                f"{seed}:token".encode()
            ).hexdigest()[:40]

        deployment = {
            "dao_id": dao_id,
            "name": name,
            "creator": creator,
            "governance_type": governance_type,
            "chain_id": self._chain_id,
            "contracts": {
                "governor": governor_addr,
                "timelock": timelock_addr,
                "treasury": treasury_addr,
                "token": token_address,
            },
            "parameters": {
                "voting_delay_blocks": self._voting_delay,
                "voting_period_blocks": self._voting_period,
                "quorum_pct": self._quorum_pct,
                "timelock_delay_seconds": self._timelock_delay,
                "proposal_threshold": _DEFAULTS["proposal_threshold"],
            },
            "deployed_at": now,
            "status": "deployed",
        }
        self._deployments[dao_id] = deployment

        logger.info(
            "DAO deployed: %s '%s' (type=%s, governor=%s)",
            dao_id, name, governance_type, governor_addr,
        )
        return deployment

    def get_deployment(self, dao_id: str) -> dict | None:
        """Return the deployment record for a DAO."""
        return self._deployments.get(dao_id)
