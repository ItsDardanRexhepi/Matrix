"""
Schema definitions for EAS attestations across the 0pnMatrx platform.

Each component type maps to a schema UID registered on-chain. EAS schema UIDs
are keccak256 hashes produced by the SchemaRegistry — they are chain-specific
and CANNOT be guessed or reused across chains. The defaults here are therefore
intentionally EMPTY: every UID must be supplied via config
(``blockchain.schemas.<component>``) as the real registered bytes32 for the
target chain. ``get_schema_uid`` FAILS CLOSED on an empty/malformed UID rather
than attesting against a placeholder. Register with
``scripts/register_eas_schemas.py`` and paste the resulting UIDs into config.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Primary platform schema UID — EMPTY by default; supply the real
# registered bytes32 via config["blockchain"]["schemas"]["primary"].
PRIMARY_SCHEMA_UID: str = ""  # config-required (blockchain.schemas.primary); no fabricated default

# Platform schemas — maps component names to default schema UIDs.
# In production these are overridden via config["blockchain"]["schemas"].
PLATFORM_SCHEMAS: dict[str, str] = {
    # Core platform schema — config-required (no fabricated default).
    "primary": PRIMARY_SCHEMA_UID,
    # Component-specific schemas
    "identity": "",
    "payments": "",
    "governance": "",
    "ip_royalties": "",
    "disputes": "",
    "nfts": "",
    "defi": "",
    "staking": "",
    "insurance": "",
    "gaming": "",
    "supply_chain": "",
    "crossborder": "",
    "securities": "",
    "tokenization": "",
    "agent_identity": "",
    "ban_record": "",
    "rights_reversion": "",
    "emergency_freeze": "",
    "document_verification": "",
}

# Schema field definitions for each component type
SCHEMA_DEFINITIONS: dict[str, str] = {
    "primary": "string platform, string action, string agent, uint256 timestamp, bytes data",
    "identity": "address subject, string identityType, bytes32 identityHash, uint256 timestamp",
    "payments": "address sender, address recipient, uint256 amount, string currency, uint256 timestamp",
    "governance": "address voter, bytes32 proposalId, bool support, uint256 weight, uint256 timestamp",
    "ip_royalties": "address creator, bytes32 contentHash, uint256 royaltyBps, address[] recipients, uint256 timestamp",
    "disputes": "address claimant, address respondent, bytes32 disputeId, string category, uint256 timestamp",
    "nfts": "address owner, address collection, uint256 tokenId, string action, uint256 timestamp",
    "defi": "address user, string protocol, string action, uint256 amount, uint256 timestamp",
    "staking": "address staker, uint256 amount, uint256 duration, string pool, uint256 timestamp",
    "insurance": "address policyholder, bytes32 policyId, uint256 coverage, uint256 premium, uint256 timestamp",
    "gaming": "address player, bytes32 gameId, string event, bytes data, uint256 timestamp",
    "supply_chain": "address entity, bytes32 itemId, string stage, bytes32 prevHash, uint256 timestamp",
    "crossborder": "address sender, address recipient, uint256 amount, string fromCurrency, string toCurrency, uint256 timestamp",
    "securities": "address issuer, bytes32 securityId, string securityType, uint256 amount, uint256 timestamp",
    "tokenization": "address owner, bytes32 assetId, string assetType, uint256 totalSupply, uint256 timestamp",
    "agent_identity": "address agent, bytes32 agentHash, string agentType, uint256 registeredAt",
    "ban_record": "address subject, string reason, uint256 duration, address issuedBy, uint256 timestamp",
    "rights_reversion": "address rightsHolder, bytes32 contentId, string reason, uint256 effectiveAt, uint256 timestamp",
    "emergency_freeze": "address target, string reason, address frozenBy, uint256 timestamp",
    "document_verification": "address subject, bytes32 documentHash, string docType, string propertyId, uint256 timestamp",
}


_UID_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def get_schema_uid(component: str, config: dict | None = None) -> str:
    """
    Resolve a schema UID for a component, checking config overrides first.

    FAILS CLOSED (P2-9): if the resolved UID is empty or not a 66-char
    ``0x``+64-hex bytes32, raises ValueError instead of returning a placeholder
    that would attest against a nonexistent schema.

    Args:
        component: Component name (e.g. "payments", "disputes").
        config: Optional config dict with blockchain.schemas overrides.

    Returns:
        A validated bytes32 schema UID string.
    """
    uid = ""
    if config:
        overrides = config.get("blockchain", {}).get("schemas", {})
        if component in overrides:
            uid = overrides[component]
    if not uid:
        uid = PLATFORM_SCHEMAS.get(component, PRIMARY_SCHEMA_UID)
    if not _UID_RE.match(str(uid or "")):
        raise ValueError(
            f"EAS schema '{component}' is not configured — set "
            f"blockchain.schemas.{component} to the registered bytes32 UID for "
            f"your target chain (see scripts/register_eas_schemas.py)."
        )
    return uid


def get_schema_definition(component: str) -> str:
    """
    Get the Solidity-style schema field definition for a component.

    Args:
        component: Component name.

    Returns:
        Schema definition string (e.g. "string action, uint256 timestamp").
    """
    return SCHEMA_DEFINITIONS.get(component, SCHEMA_DEFINITIONS["primary"])


def build_schema_registration_data(component: str, resolver: str = "", revocable: bool = True) -> dict[str, Any]:
    """
    Build the data needed to register a new schema on the EAS SchemaRegistry.

    Args:
        component: Component name whose definition to use.
        resolver: Optional resolver contract address.
        revocable: Whether attestations under this schema can be revoked.

    Returns:
        Dict with schema, resolver, and revocable fields.
    """
    return {
        "schema": get_schema_definition(component),
        "resolver": resolver or "0x0000000000000000000000000000000000000000",
        "revocable": revocable,
        "component": component,
    }
