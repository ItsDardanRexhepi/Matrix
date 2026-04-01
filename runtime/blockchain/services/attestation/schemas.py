"""
Schema definitions for EAS attestations across the 0pnMatrx platform.

Each component type maps to a schema UID registered on-chain. Schema 348
is the primary platform schema. All schema UIDs are config-driven but
defaults are provided for Base Sepolia testnet.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default primary schema UID (Schema 348)
PRIMARY_SCHEMA_UID: str = "0x0000000000000000000000000000000000000000000000000000000000000348"

# Platform schemas — maps component names to default schema UIDs.
# In production these are overridden via config["blockchain"]["schemas"].
PLATFORM_SCHEMAS: dict[str, str] = {
    # Core platform schema (Schema 348)
    "primary": PRIMARY_SCHEMA_UID,
    # Component-specific schemas
    "identity": "0x0000000000000000000000000000000000000000000000000000000000000001",
    "payments": "0x0000000000000000000000000000000000000000000000000000000000000002",
    "governance": "0x0000000000000000000000000000000000000000000000000000000000000003",
    "ip_royalties": "0x0000000000000000000000000000000000000000000000000000000000000004",
    "disputes": "0x0000000000000000000000000000000000000000000000000000000000000005",
    "nfts": "0x0000000000000000000000000000000000000000000000000000000000000006",
    "defi": "0x0000000000000000000000000000000000000000000000000000000000000007",
    "staking": "0x0000000000000000000000000000000000000000000000000000000000000008",
    "insurance": "0x0000000000000000000000000000000000000000000000000000000000000009",
    "gaming": "0x000000000000000000000000000000000000000000000000000000000000000a",
    "supply_chain": "0x000000000000000000000000000000000000000000000000000000000000000b",
    "crossborder": "0x000000000000000000000000000000000000000000000000000000000000000c",
    "securities": "0x000000000000000000000000000000000000000000000000000000000000000d",
    "tokenization": "0x000000000000000000000000000000000000000000000000000000000000000e",
    "agent_identity": "0x000000000000000000000000000000000000000000000000000000000000000f",
    "ban_record": "0x0000000000000000000000000000000000000000000000000000000000000010",
    "rights_reversion": "0x0000000000000000000000000000000000000000000000000000000000000011",
    "emergency_freeze": "0x0000000000000000000000000000000000000000000000000000000000000012",
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
}


def get_schema_uid(component: str, config: dict | None = None) -> str:
    """
    Resolve a schema UID for a component, checking config overrides first.

    Args:
        component: Component name (e.g. "payments", "disputes").
        config: Optional config dict with blockchain.schemas overrides.

    Returns:
        The schema UID string.
    """
    if config:
        overrides = config.get("blockchain", {}).get("schemas", {})
        if component in overrides:
            return overrides[component]
    return PLATFORM_SCHEMAS.get(component, PRIMARY_SCHEMA_UID)


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
