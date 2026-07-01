"""
Matrix-to-0pnMatrx Bridge — public-facing component pipeline.

Receives validated, owner-approved components from the Matrix private
runtime and deploys them into the 0pnMatrx open-source platform.

Pipeline stages:
    1. Exporter      — receives and unpacks exported component bundles
    2. Sanitizer     — re-validates that no private data leaked through
    3. ApprovalGate  — verifies the OTP-verified owner's approval before deploy
    4. Deployer      — installs the component into the live runtime
    5. MobileConverter — converts deployed components for MTRX iOS app
    6. Manifest      — tracks every component's lifecycle status

Owner approval is phone-OTP based (runtime/security/owner.py) — Telegram is gone.
All attestations are recorded on-chain via EAS (Ethereum Attestation Service).
"""

from __future__ import annotations

__all__ = [
    "ComponentExporter",
    "SanitizationValidator",
    "ApprovalGate",
    "ComponentDeployer",
    "MobileConverter",
    "ManifestManager",
]

# NeoSafe attester address (Base mainnet)
NEOSAFE_ADDRESS = "0x46fF491D7054A6F500026B3E81f358190f8d8Ec5"

# Owner approval is OTP-based (runtime/security/owner.py). The old Telegram owner
# ID is removed — Telegram is no longer in the approval/security path.

# EAS contract on Base (mainnet + sepolia share the OP-stack predeploy address).
# Verified against the official eas-contracts deployment artifacts. The previous
# value (0xA1207F3BBa224E2c9c3c6D5aF63D816e64D54892) was neither Base's EAS nor
# Ethereum-mainnet's EAS (0xA1207...0eb1582Ce587) — it was wrong.
EAS_CONTRACT = "0x4200000000000000000000000000000000000021"

# Schema UID for bridge attestations — EMPTY by default (P2-9). An EAS schema
# UID is a chain-specific keccak256 bytes32, NOT an easscan display number like
# "348"; a fabricated default attests against a nonexistent schema. Supply the
# real registered UID via config["blockchain"]["schemas"]["primary"] and resolve
# it through runtime.blockchain.services.attestation.schemas.get_schema_uid,
# which fails closed on an empty/malformed value.
EAS_SCHEMA_UID: str = ""

from bridge.exporter import ComponentExporter
from bridge.sanitizer import SanitizationValidator
from bridge.approval_gate import ApprovalGate
from bridge.deployer import ComponentDeployer
from bridge.mobile_converter import MobileConverter
from bridge.manifest import ManifestManager
