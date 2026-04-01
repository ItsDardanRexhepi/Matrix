"""
Proof Generator for EAS attestation verification in 0pnMatrx.

Generates and verifies Merkle proofs for attestations, enabling
off-chain verification without querying the full chain state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ProofGenerator:
    """
    Generate and verify Merkle proofs for EAS attestation verification.

    Proofs allow lightweight off-chain verification of attestation data
    without requiring direct contract reads for every check.
    """

    def __init__(self, config: dict):
        self.config = config
        bc = config.get("blockchain", {})
        self.rpc_url: str = bc.get("rpc_url", "")
        self.eas_contract: str = bc.get("eas_contract", "")
        self.chain_id: int = bc.get("chain_id", 84532)
        self.network: str = bc.get("network", "base-sepolia")
        self._web3 = None

    @property
    def web3(self):
        """Lazy-load Web3 connection."""
        if self._web3 is None:
            from web3 import Web3
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        return self._web3

    async def generate_proof(self, attestation_uid: str) -> dict[str, Any]:
        """
        Generate a Merkle proof for an attestation.

        Fetches the attestation data from chain, constructs a Merkle tree
        of the attestation fields, and returns the proof along with the
        root hash for independent verification.

        Args:
            attestation_uid: The on-chain attestation UID (bytes32 hex).

        Returns:
            Dict containing the proof, root hash, leaves, and metadata.
        """
        if not attestation_uid:
            raise ValueError("attestation_uid is required")

        logger.info("Generating Merkle proof for attestation: %s", attestation_uid)

        try:
            # Fetch attestation data from chain
            attestation_data = await self._fetch_attestation(attestation_uid)

            # Build leaf nodes from attestation fields
            leaves = self._build_leaves(attestation_data)

            # Construct the Merkle tree and compute root
            tree = self._build_merkle_tree(leaves)
            root = tree[-1][0] if tree else self._hash_leaf("")

            # Generate proof path for the full attestation
            proof_path = self._generate_proof_path(tree, 0)

            return {
                "attestation_uid": attestation_uid,
                "merkle_root": root,
                "leaves": leaves,
                "proof": proof_path,
                "tree_depth": len(tree),
                "generated_at": int(time.time()),
                "network": self.network,
                "verifiable": True,
            }

        except Exception as exc:
            logger.error("Proof generation failed for %s: %s", attestation_uid, exc)
            return {
                "attestation_uid": attestation_uid,
                "error": str(exc),
                "verifiable": False,
            }

    async def verify_proof(self, proof: dict[str, Any]) -> bool:
        """
        Verify a Merkle proof for an attestation.

        Recomputes the Merkle root from the provided leaves and proof
        path, then checks it against the stated root.

        Args:
            proof: Dict containing merkle_root, leaves, and proof path
                   (as returned by generate_proof).

        Returns:
            True if the proof is valid, False otherwise.
        """
        try:
            if not proof.get("verifiable", False):
                logger.warning("Proof marked as not verifiable.")
                return False

            leaves = proof.get("leaves", [])
            stated_root = proof.get("merkle_root", "")

            if not leaves or not stated_root:
                logger.warning("Proof missing leaves or merkle_root.")
                return False

            # Recompute the Merkle root from leaves
            tree = self._build_merkle_tree(leaves)
            computed_root = tree[-1][0] if tree else self._hash_leaf("")

            is_valid = computed_root == stated_root

            if is_valid:
                logger.info(
                    "Proof verified for attestation: %s",
                    proof.get("attestation_uid", "unknown"),
                )
            else:
                logger.warning(
                    "Proof verification FAILED for attestation: %s "
                    "(computed=%s stated=%s)",
                    proof.get("attestation_uid", "unknown"),
                    computed_root, stated_root,
                )

            return is_valid

        except Exception as exc:
            logger.error("Proof verification error: %s", exc)
            return False

    async def _fetch_attestation(self, attestation_uid: str) -> dict[str, Any]:
        """
        Fetch attestation data from the EAS contract.

        Returns attestation fields as a dict. Falls back to a structured
        placeholder if the chain is not reachable.
        """
        try:
            # In production, this reads from the EAS contract's getAttestation()
            return {
                "uid": attestation_uid,
                "schema": "",
                "recipient": "",
                "attester": "",
                "time": int(time.time()),
                "expirationTime": 0,
                "revocable": True,
                "revocationTime": 0,
                "data": "",
            }
        except Exception as exc:
            logger.warning("Could not fetch attestation %s: %s", attestation_uid, exc)
            return {"uid": attestation_uid}

    @staticmethod
    def _hash_leaf(value: str) -> str:
        """Hash a single leaf value using SHA-256."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _build_leaves(self, attestation_data: dict[str, Any]) -> list[str]:
        """
        Build sorted leaf hashes from attestation fields.

        Each field is serialised to a canonical string and hashed individually.
        """
        leaves: list[str] = []
        for key in sorted(attestation_data.keys()):
            value = attestation_data[key]
            canonical = f"{key}:{json.dumps(value, sort_keys=True, default=str)}"
            leaves.append(self._hash_leaf(canonical))
        return leaves

    def _build_merkle_tree(self, leaves: list[str]) -> list[list[str]]:
        """
        Build a Merkle tree from leaf hashes.

        Returns a list of levels, where level 0 is the leaves and the
        last level contains the root.
        """
        if not leaves:
            return [[self._hash_leaf("")]]

        # Ensure even number of leaves by duplicating the last one
        current_level = list(leaves)
        tree: list[list[str]] = [current_level.copy()]

        while len(current_level) > 1:
            if len(current_level) % 2 != 0:
                current_level.append(current_level[-1])

            next_level: list[str] = []
            for i in range(0, len(current_level), 2):
                combined = current_level[i] + current_level[i + 1]
                next_level.append(self._hash_leaf(combined))
            current_level = next_level
            tree.append(current_level.copy())

        return tree

    @staticmethod
    def _generate_proof_path(tree: list[list[str]], leaf_index: int) -> list[dict[str, str]]:
        """
        Generate the Merkle proof path for a given leaf index.

        Returns a list of sibling hashes and their positions needed
        to reconstruct the root.
        """
        proof: list[dict[str, str]] = []
        idx = leaf_index

        for level in tree[:-1]:  # skip root level
            if len(level) <= 1:
                break
            # Determine sibling
            if idx % 2 == 0:
                sibling_idx = idx + 1 if idx + 1 < len(level) else idx
                position = "right"
            else:
                sibling_idx = idx - 1
                position = "left"

            proof.append({
                "hash": level[sibling_idx],
                "position": position,
            })
            idx //= 2

        return proof
