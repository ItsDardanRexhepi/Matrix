"""
ConversionWizard — converts traditional organisations to DAOs.

Analyses an organisation's structure, recommends an appropriate DAO
governance model, performs the conversion, and migrates existing members
into DAO roles.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Mapping of traditional roles to DAO equivalents
ROLE_MAPPING: dict[str, str] = {
    "ceo": "admin",
    "cto": "admin",
    "cfo": "treasurer",
    "coo": "admin",
    "president": "admin",
    "vice_president": "moderator",
    "director": "moderator",
    "manager": "moderator",
    "board_member": "council",
    "treasurer": "treasurer",
    "secretary": "council",
    "employee": "member",
    "contractor": "contributor",
    "advisor": "council",
    "intern": "member",
    "volunteer": "contributor",
    "shareholder": "token_holder",
    "partner": "council",
    "member": "member",
}

# Governance type recommendation weights
_GOV_WEIGHTS = {
    "has_shares": {"token_weighted": 3, "quadratic": 2, "one_member_one_vote": 0},
    "equal_voting": {"one_member_one_vote": 3, "quadratic": 1, "token_weighted": 0},
    "large_member_count": {"quadratic": 2, "token_weighted": 1, "one_member_one_vote": 1},
    "small_member_count": {"one_member_one_vote": 2, "token_weighted": 1, "quadratic": 0},
    "hierarchical": {"token_weighted": 2, "quadratic": 1, "one_member_one_vote": 0},
    "flat": {"one_member_one_vote": 3, "quadratic": 2, "token_weighted": 0},
}


class ConversionWizard:
    """Wizard for converting traditional organisations into DAOs.

    Parameters
    ----------
    config : dict
        Platform configuration.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        # conversion_id -> conversion record
        self._conversions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze_org(self, org_structure: dict) -> dict:
        """Analyse an organisation structure and recommend a DAO type.

        Parameters
        ----------
        org_structure : dict
            Must contain:

            - ``name`` (str): organisation name
            - ``members`` (list[dict]): each with ``name``, ``role``, and
              optionally ``shares`` (float)
            - ``type`` (str, optional): e.g. ``"corporation"``, ``"nonprofit"``
            - ``voting_style`` (str, optional): ``"equal"`` or ``"weighted"``

        Returns
        -------
        dict
            Analysis with recommended governance type and rationale.
        """
        name = org_structure.get("name")
        if not name:
            raise ValueError("Organisation must have a 'name'")

        members = org_structure.get("members", [])
        if not members:
            raise ValueError("Organisation must have at least one member")

        org_type = org_structure.get("type", "unknown")
        voting_style = org_structure.get("voting_style", "unknown")

        # Determine characteristics
        has_shares = any(m.get("shares", 0) > 0 for m in members)
        member_count = len(members)
        unique_roles = {m.get("role", "member").lower() for m in members}
        is_hierarchical = len(unique_roles) >= 3
        is_flat = len(unique_roles) <= 2
        equal_voting = voting_style == "equal"

        # Score governance types
        scores: dict[str, int] = {"token_weighted": 0, "one_member_one_vote": 0, "quadratic": 0}

        traits: list[str] = []
        if has_shares:
            traits.append("has_shares")
        if equal_voting:
            traits.append("equal_voting")
        if member_count > 50:
            traits.append("large_member_count")
        else:
            traits.append("small_member_count")
        if is_hierarchical:
            traits.append("hierarchical")
        if is_flat:
            traits.append("flat")

        for trait in traits:
            weights = _GOV_WEIGHTS.get(trait, {})
            for gov_type, weight in weights.items():
                scores[gov_type] += weight

        recommended = max(scores, key=lambda k: scores[k])

        # Map roles
        role_analysis = []
        for m in members:
            trad_role = m.get("role", "member").lower()
            dao_role = ROLE_MAPPING.get(trad_role, "member")
            role_analysis.append({
                "name": m.get("name", "unknown"),
                "traditional_role": trad_role,
                "dao_role": dao_role,
                "shares": m.get("shares", 0),
            })

        rationale_parts = []
        if has_shares:
            rationale_parts.append("Organisation has share-based ownership")
        if equal_voting:
            rationale_parts.append("Organisation prefers equal voting")
        if member_count > 50:
            rationale_parts.append(f"Large member count ({member_count}) favours quadratic voting")
        if is_hierarchical:
            rationale_parts.append("Multiple role tiers detected")
        if is_flat:
            rationale_parts.append("Flat structure detected")

        analysis = {
            "org_name": name,
            "org_type": org_type,
            "member_count": member_count,
            "unique_roles": sorted(unique_roles),
            "traits": traits,
            "governance_scores": scores,
            "recommended_governance": recommended,
            "rationale": "; ".join(rationale_parts) if rationale_parts else "Default recommendation",
            "role_mapping": role_analysis,
            "analyzed_at": time.time(),
        }

        logger.info(
            "Org analysis for '%s': recommended=%s (scores=%s)",
            name, recommended, scores,
        )
        return analysis

    async def convert(self, org_structure: dict, dao_config: dict) -> dict:
        """Convert an organisation to a DAO.

        Parameters
        ----------
        org_structure : dict
            Same format as ``analyze_org``.
        dao_config : dict
            Must contain:

            - ``governance_type`` (str)
            - ``dao_name`` (str, optional — defaults to org name)
            - ``token_symbol`` (str, optional)
            - ``initial_treasury`` (float, optional)

        Returns
        -------
        dict
            Conversion record with DAO details and member migration plan.
        """
        name = org_structure.get("name")
        if not name:
            raise ValueError("Organisation must have a 'name'")

        members = org_structure.get("members", [])
        if not members:
            raise ValueError("Organisation must have at least one member")

        governance_type = dao_config.get("governance_type")
        if not governance_type:
            # Auto-analyse
            analysis = await self.analyze_org(org_structure)
            governance_type = analysis["recommended_governance"]

        dao_name = dao_config.get("dao_name", name)
        token_symbol = dao_config.get("token_symbol", dao_name[:4].upper())

        conversion_id = f"conv_{uuid.uuid4().hex[:12]}"
        now = time.time()

        # Build member migration plan
        migration_plan: list[dict] = []
        total_shares = sum(m.get("shares", 1) for m in members)
        for m in members:
            trad_role = m.get("role", "member").lower()
            dao_role = ROLE_MAPPING.get(trad_role, "member")
            shares = m.get("shares", 1)
            voting_power = self._calculate_voting_power(
                shares, total_shares, governance_type
            )
            migration_plan.append({
                "name": m.get("name", "unknown"),
                "address": m.get("address", ""),
                "traditional_role": trad_role,
                "dao_role": dao_role,
                "token_allocation": shares,
                "voting_power": voting_power,
            })

        conversion = {
            "conversion_id": conversion_id,
            "org_name": name,
            "dao_name": dao_name,
            "governance_type": governance_type,
            "token_symbol": token_symbol,
            "member_count": len(members),
            "total_shares": total_shares,
            "migration_plan": migration_plan,
            "initial_treasury": dao_config.get("initial_treasury", 0.0),
            "status": "converted",
            "created_at": now,
        }
        self._conversions[conversion_id] = conversion

        logger.info(
            "Organisation '%s' converted to DAO '%s' (type=%s, members=%d)",
            name, dao_name, governance_type, len(members),
        )
        return conversion

    # ── CLUSTER B: `migrate_members` REMOVED.
    #
    # It reported `"migrated": N` with a per-member `migrated_at` timestamp for
    # a `dao_id` it never located, looping the caller's own list and appending
    # to a LOCAL list that was returned and discarded. It wrote no store,
    # awaited nothing, and never touched `DAOService._daos` — the only
    # membership truth in the system. Strip the claim and a ROLE_MAPPING
    # lookup remains, which `analyze_org` and `convert` already return.
    #
    # REMOVED RATHER THAN REFUSED, because unlike the multisig case there is no
    # substrate here to build on and no caller to serve: `migrate_members`
    # appears exactly once in the repo — its own definition. `DAOService.join_dao`
    # is the real operation, with five validations and three store writes.
    #
    # AND IT WAS THE CHEAPEST OF THE FOUR TO ARM. Not in ACTION_MAP, not in the
    # catalog, no route — inert only because nobody wired it. ONE ACTION_MAP
    # LINE would have made it live, with no config change and no gate to
    # notice. An inert fabrication one line from live is not safe, it is
    # unattended, and leaving dead fabricating code in place is leaving a
    # loaded surface for whoever next goes looking for a batch-membership API.

    # RESTORED. The `migrate_members` deletion hunk ended on this decorator and
    # took it with the removed method, so `convert()`'s `self._calculate_voting_power(
    # shares, total, governance_type)` began passing FOUR arguments to a
    # three-parameter function and raised TypeError on every call. Working code,
    # killed by a deletion that looked local — and the suite stayed green because
    # nothing exercised `convert()`. Both halves are now covered:
    # tests/test_conversion_wizard_convert.py drives the method, and
    # tests/test_bound_call_arity.py catches the SHAPE for every class in the
    # tree, so the next lost decorator fails a test rather than a caller.
    @staticmethod
    def _calculate_voting_power(
        shares: float, total_shares: float, governance_type: str
    ) -> float:
        """Calculate voting power based on governance type."""
        if total_shares <= 0:
            return 0.0

        if governance_type == "token_weighted":
            return round((shares / total_shares) * 100, 4)
        elif governance_type == "one_member_one_vote":
            return 1.0
        elif governance_type == "quadratic":
            import math
            raw = math.sqrt(shares)
            total_sqrt = sum(
                math.sqrt(s) for s in [shares]  # normalised per-member
            )
            # Relative quadratic weight (percentage of sqrt total)
            # In practice, total_sqrt would sum all members; here we
            # return the raw sqrt for the caller to normalise across
            # the full membership.
            return round(raw, 4)
        else:
            return round((shares / total_shares) * 100, 4)
