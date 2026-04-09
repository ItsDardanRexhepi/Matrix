"""
DAOService — main entry point for DAO Conversion & Management.

Provides create, join, leave, and query operations for Decentralized
Autonomous Organizations, backed by the DAOFactory, TreasuryManager,
and ConversionWizard sub-components.
"""

import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

from .conversion_wizard import ConversionWizard
from .factory import DAOFactory
from .treasury import TreasuryManager

logger = logging.getLogger(__name__)


class DAOService:
    """Unified DAO management service.

    Parameters
    ----------
    config : dict
        Full platform configuration.  Reads:

        - ``blockchain.chain_id``
        - ``blockchain.platform_wallet``
        - ``dao.*`` — sub-keys for factory, treasury, conversion

    Example config snippet::

        {
            "blockchain": {
                "chain_id": 8453,
                "platform_wallet": "0xPlatform..."
            },
            "dao": {
                "factory": {
                    "voting_period_blocks": 50400,
                    "quorum_pct": 4
                },
                "treasury": {
                    "approval_threshold_pct": 50.0
                },
                "default_governance": "token_weighted",
                "max_members": 10000
            }
        }
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        dao_cfg = config.get("dao", {})
        self._default_governance: str = dao_cfg.get(
            "default_governance", "token_weighted"
        )
        self._max_members: int = dao_cfg.get("max_members", 10_000)
        self._dao_factory_address: str = (
            dao_cfg.get("factory_address", "")
            or config.get("blockchain", {}).get("dao_factory_address", "")
            or ""
        )
        self._web3 = Web3Manager.get_shared(config)

        # Sub-components
        self.factory = DAOFactory(config)
        self.treasury = TreasuryManager(config)
        self.conversion_wizard = ConversionWizard(config)

        # dao_id -> DAO record
        self._daos: dict[str, dict[str, Any]] = {}

        logger.info("DAOService initialised")

    # ------------------------------------------------------------------
    # Core DAO operations
    # ------------------------------------------------------------------

    async def create_dao(self, creator: str, name: str, config: dict) -> dict:
        """Create a new DAO.

        Parameters
        ----------
        creator : str
            Wallet address of the creator.
        name : str
            Human-readable DAO name.
        config : dict
            DAO-specific settings.  Keys:

            - ``governance_type`` (str, optional) — defaults to platform default
            - ``token_address`` (str, optional) — existing governance token
            - ``description`` (str, optional)
            - ``initial_deposit`` (float, optional) — seed treasury

        Returns
        -------
        dict
            The DAO record including deployment details.
        """
        if not creator:
            raise ValueError("Creator address is required")
        if not name:
            raise ValueError("DAO name is required")

        if (
            not self._web3.available
            or self._web3.is_placeholder(self._dao_factory_address)
        ):
            logger.warning(
                "Service %s called but contract not deployed",
                self.__class__.__name__,
            )
            return not_deployed_response("dao_management", {
                "operation": "create_dao",
                "requested": {"creator": creator, "name": name},
            })

        governance_type = config.get("governance_type", self._default_governance)
        token_address = config.get("token_address")

        # Deploy contracts via factory
        deployment = await self.factory.deploy(
            creator=creator,
            name=name,
            governance_type=governance_type,
            token_address=token_address,
        )

        dao_id = deployment["dao_id"]
        now = time.time()

        dao = {
            "dao_id": dao_id,
            "name": name,
            "description": config.get("description", ""),
            "creator": creator,
            "governance_type": governance_type,
            "deployment": deployment,
            "members": [
                {
                    "address": creator,
                    "role": "admin",
                    "stake": 0.0,
                    "joined_at": now,
                }
            ],
            "member_count": 1,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self._daos[dao_id] = dao

        # Seed treasury if requested
        initial_deposit = config.get("initial_deposit", 0.0)
        if initial_deposit > 0:
            await self.treasury.deposit(
                dao_id=dao_id,
                depositor=creator,
                token="native",
                amount=initial_deposit,
            )

        logger.info(
            "DAO created: %s '%s' by %s (governance=%s)",
            dao_id, name, creator, governance_type,
        )
        return dao

    async def get_dao(self, dao_id: str) -> dict:
        """Retrieve a DAO by its ID."""
        dao = self._daos.get(dao_id)
        if dao is None:
            raise KeyError(f"DAO {dao_id} not found")
        return dao

    async def join_dao(self, dao_id: str, member: str, stake: float) -> dict:
        """Add a member to a DAO.

        Parameters
        ----------
        dao_id : str
            The DAO to join.
        member : str
            Wallet address of the new member.
        stake : float
            Amount staked to join (can be 0 for free membership).
        """
        dao = await self.get_dao(dao_id)

        if dao["status"] != "active":
            raise ValueError(f"DAO {dao_id} is not active (status={dao['status']})")

        if dao["member_count"] >= self._max_members:
            raise ValueError(
                f"DAO {dao_id} has reached maximum membership ({self._max_members})"
            )

        # Check for duplicate membership
        for m in dao["members"]:
            if m["address"] == member:
                raise ValueError(f"{member} is already a member of DAO {dao_id}")

        if stake < 0:
            raise ValueError("Stake must be non-negative")

        now = time.time()
        member_record = {
            "address": member,
            "role": "member",
            "stake": stake,
            "joined_at": now,
        }
        dao["members"].append(member_record)
        dao["member_count"] = len(dao["members"])
        dao["updated_at"] = now

        # If stake > 0, deposit to treasury
        if stake > 0:
            await self.treasury.deposit(
                dao_id=dao_id,
                depositor=member,
                token="native",
                amount=stake,
            )

        logger.info(
            "Member %s joined DAO %s (stake=%.4f)", member, dao_id, stake,
        )
        return {
            "dao_id": dao_id,
            "member": member_record,
            "member_count": dao["member_count"],
        }

    async def leave_dao(self, dao_id: str, member: str) -> dict:
        """Remove a member from a DAO.

        The DAO creator (admin) cannot leave unless they transfer
        admin role first.
        """
        dao = await self.get_dao(dao_id)

        member_record = None
        member_index = None
        for i, m in enumerate(dao["members"]):
            if m["address"] == member:
                member_record = m
                member_index = i
                break

        if member_record is None:
            raise ValueError(f"{member} is not a member of DAO {dao_id}")

        # Prevent sole admin from leaving
        if member_record["role"] == "admin":
            admin_count = sum(
                1 for m in dao["members"] if m["role"] == "admin"
            )
            if admin_count <= 1:
                raise ValueError(
                    f"Cannot remove sole admin {member} from DAO {dao_id}. "
                    "Transfer admin role first."
                )

        dao["members"].pop(member_index)
        dao["member_count"] = len(dao["members"])
        dao["updated_at"] = time.time()

        logger.info("Member %s left DAO %s", member, dao_id)
        return {
            "dao_id": dao_id,
            "removed_member": member,
            "stake_returned": member_record.get("stake", 0.0),
            "member_count": dao["member_count"],
        }
