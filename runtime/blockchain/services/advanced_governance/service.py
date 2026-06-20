"""
veToken locks, quadratic voting, RetroPGF, gauge bribes, voting delegation.

Real protocol wiring (CREDENTIAL-GATED until the operator configures keys):

- ``vote_escrow``    → Curve-style VotingEscrow ``create_lock`` (platform veToken
                       position, on-chain WRITE via the paymaster account).
- ``quadratic_vote`` → Snapshot hub (snapshot.org) off-chain vote. Snapshot votes
                       are EIP-712 signed by the *voter*; we NEVER sign a user's
                       vote server-side, so we return the prepared unsigned typed
                       data for the user's wallet (non-custodial).
- ``submit_retropgf``→ EAS attestation registry (RetroPGF round application).
- ``place_bribe``    → gauge bribe-market ``deposit_bribe`` (platform-funded
                       incentive, on-chain WRITE via paymaster).
- ``delegate_voting``→ Snapshot Delegate Registry ``setDelegate`` for the platform
                       account, OR a prepared op for a user's wallet.

Config (read from ``services.advanced_governance`` unless noted):
    ve_token_address        — Curve VotingEscrow contract (vote_escrow)
    snapshot_hub            — Snapshot hub base URL (quadratic_vote)
    snapshot_space          — Snapshot space id, e.g. "myspace.eth"
    eas_address / eas_schema — EAS contract + schema uid (submit_retropgf)
                               (falls back to blockchain.eas_contract/eas_schema)
    bribe_market_address    — gauge bribe market contract (place_bribe)
    delegate_registry_address — Snapshot Delegate Registry (delegate_voting)

NON-CUSTODIAL: state-changing on-chain ops use ONLY the platform paymaster
account (``Web3Manager.send_transaction``) and operate on the PLATFORM's own
governance position. Any operation that would move a *user's* tokens or cast a
*user's* vote is returned as a prepared/unsigned payload for the user's wallet —
the server never custodies user funds or signs on a user's behalf.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)


# ── Minimal, real ABIs (only the function we actually invoke) ──────────

# Curve VotingEscrow (ve-token). Canonical signatures used by Curve & forks.
_VOTING_ESCROW_ABI = [
    {
        "name": "create_lock",
        "stateMutability": "nonpayable",
        "type": "function",
        "inputs": [
            {"name": "_value", "type": "uint256"},
            {"name": "_unlock_time", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "name": "balanceOf",
        "stateMutability": "view",
        "type": "function",
        "inputs": [{"name": "addr", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "locked",
        "stateMutability": "view",
        "type": "function",
        "inputs": [{"name": "addr", "type": "address"}],
        "outputs": [
            {"name": "amount", "type": "int128"},
            {"name": "end", "type": "uint256"},
        ],
    },
]

# Convex/Votium-style gauge bribe market. ``depositBribe`` is the canonical
# entrypoint on Votium-style bribe markets. UNVERIFIED: exact selector varies
# by deployment (Votium v1/v2, Hidden Hand, Curve-native); operator must point
# bribe_market_address at a deployment matching this minimal interface.
_BRIBE_MARKET_ABI = [
    {
        "name": "depositBribe",
        "stateMutability": "nonpayable",
        "type": "function",
        "inputs": [
            {"name": "_proposal", "type": "bytes32"},
            {"name": "_token", "type": "address"},
            {"name": "_amount", "type": "uint256"},
            {"name": "_choiceIndex", "type": "uint256"},
        ],
        "outputs": [],
    },
]

# Snapshot Delegate Registry — same address across most chains:
# 0x469788fE6E9E9681C6ebF3bF78e7Fd26Fc015446. setDelegate(id, delegate).
_DELEGATE_REGISTRY_ADDRESS = "0x469788fE6E9E9681C6ebF3bF78e7Fd26Fc015446"
_DELEGATE_REGISTRY_ABI = [
    {
        "name": "setDelegate",
        "stateMutability": "nonpayable",
        "type": "function",
        "inputs": [
            {"name": "id", "type": "bytes32"},
            {"name": "delegate", "type": "address"},
        ],
        "outputs": [],
    },
]

# Snapshot public hub (off-chain vote sequencer). Real, documented base URL.
_SNAPSHOT_HUB_DEFAULT = "https://hub.snapshot.org"


class AdvancedGovernanceService:
    """veToken locks, quadratic voting, RetroPGF, gauge bribes, voting delegation."""

    service_name = "advanced_governance"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── helpers ────────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        return self._config.get("services", {}).get(self.service_name, {})

    def _gate(self, method: str, missing: str, protocol: str, extra: dict | None = None) -> dict:
        payload = {"method": method, "missing": missing, "protocol": protocol}
        if extra:
            payload.update(extra)
        return not_deployed_response(self.service_name, extra=payload)

    # ── vote_escrow — Curve VotingEscrow create_lock (on-chain WRITE) ───

    async def vote_escrow(self, **params: Any) -> dict:
        """Create a veToken lock on a Curve-style VotingEscrow contract.

        Platform-level: locks the PLATFORM's tokens into its own ve position via
        the paymaster account. To lock a *user's* tokens, that user's wallet must
        sign — pass ``on_behalf_of`` to get a prepared unsigned tx instead.

        params: amount (token units, float/int), lock_duration_seconds (int),
                on_behalf_of (optional user address → prepared, unsigned tx).
        """
        ve_addr = self._cfg().get("ve_token_address", "")

        if is_placeholder_value(ve_addr):
            return self._gate("vote_escrow", "services.advanced_governance.ve_token_address",
                              "Curve VotingEscrow (veToken)")
        if not self._web3.available:
            return self._gate("vote_escrow", "blockchain.rpc_url",
                              "Curve VotingEscrow (veToken)")

        amount = params.get("amount")
        lock_duration = params.get("lock_duration_seconds") or params.get("lock_duration")
        if amount is None or lock_duration is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "vote_escrow",
                "error": "amount and lock_duration_seconds are required",
            }

        try:
            value_wei = int(float(amount) * 1e18)  # assume 18-decimal lock token
            unlock_time = int(time.time()) + int(lock_duration)
            contract = self._web3.load_contract(ve_addr, _VOTING_ESCROW_ABI)
            fn = contract.functions.create_lock(value_wei, unlock_time)

            # NON-CUSTODIAL: a user lock must be signed by the user's wallet.
            on_behalf_of = params.get("on_behalf_of")
            if on_behalf_of:
                tx = fn.build_transaction({"from": self._web3.w3.to_checksum_address(on_behalf_of)})
                return {
                    "status": "prepared_unsigned",
                    "service": self.service_name,
                    "method": "vote_escrow",
                    "note": "User-owned lock: sign this with the user's wallet (non-custodial).",
                    "unsigned_tx": {k: (v.hex() if isinstance(v, bytes) else v) for k, v in tx.items()},
                    "ve_token_address": ve_addr,
                    "unlock_time": unlock_time,
                }

            # Platform-level lock: paymaster account signs + sponsors gas.
            tx = fn.build_transaction({"from": self._web3.get_account().address})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "vote_escrow",
                "protocol": "Curve VotingEscrow",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "ve_token_address": ve_addr,
                "locked_amount_wei": str(value_wei),
                "unlock_time": unlock_time,
                "signer": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("vote_escrow failed: %s", exc)
            return {"status": "error", "service": self.service_name, "method": "vote_escrow", "error": str(exc)}

    # ── quadratic_vote — Snapshot hub (off-chain, user-signed) ──────────

    async def quadratic_vote(self, **params: Any) -> dict:
        """Cast a Snapshot vote (off-chain, quadratic voting strategy).

        Snapshot votes are EIP-712 typed-data signed by the VOTER's wallet. The
        server is non-custodial and never signs a user's vote, so this returns
        the prepared EIP-712 ``Vote`` payload for the user's wallet to sign and
        relay to the Snapshot hub. If a pre-signed envelope is supplied, it is
        relayed to the real hub.

        params: proposal (id), choice, voter (address), space (override),
                signed_envelope (optional dict → relayed to the hub as-is).
        """
        cfg = self._cfg()
        space = params.get("space") or cfg.get("snapshot_space", "")
        hub = cfg.get("snapshot_hub") or _SNAPSHOT_HUB_DEFAULT

        if is_placeholder_value(space):
            return self._gate("quadratic_vote", "services.advanced_governance.snapshot_space",
                              "Snapshot (snapshot.org hub)")

        proposal = params.get("proposal") or params.get("proposal_id")
        choice = params.get("choice")
        voter = params.get("voter")
        if not proposal or choice is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "quadratic_vote",
                "error": "proposal and choice are required",
            }

        # If the user already signed the EIP-712 envelope, relay it to the hub.
        signed_envelope = params.get("signed_envelope")
        if signed_envelope:
            try:
                import httpx  # lazy
            except ImportError:
                return self._gate("quadratic_vote", "httpx (pip install httpx)",
                                  "Snapshot (snapshot.org hub)")
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.post(f"{hub.rstrip('/')}/api/msg", json=signed_envelope)
                return {
                    "status": "submitted" if resp.status_code < 400 else "error",
                    "service": self.service_name,
                    "method": "quadratic_vote",
                    "protocol": "Snapshot",
                    "hub": hub,
                    "http_status": resp.status_code,
                    "response": _safe_json(resp),
                }
            except Exception as exc:  # noqa: BLE001
                logger.error("quadratic_vote relay failed: %s", exc)
                return {"status": "error", "service": self.service_name,
                        "method": "quadratic_vote", "error": str(exc)}

        # NON-CUSTODIAL default: return the unsigned EIP-712 payload to be signed
        # by the voter's wallet. Snapshot domain/types are the documented schema.
        message = {
            "space": space,
            "proposal": proposal,
            "type": "quadratic",
            "choice": choice,
            "app": "0pnmatrx",
            "from": voter or "",
            "timestamp": int(time.time()),
        }
        typed_data = {
            "domain": {"name": "snapshot", "version": "0.1.4"},
            "types": {
                "Vote": [
                    {"name": "from", "type": "address"},
                    {"name": "space", "type": "string"},
                    {"name": "timestamp", "type": "uint64"},
                    {"name": "proposal", "type": "bytes32"},
                    {"name": "choice", "type": "uint32"},
                    {"name": "app", "type": "string"},
                ]
            },
            "primaryType": "Vote",
            "message": message,
        }
        return {
            "status": "prepared_unsigned",
            "service": self.service_name,
            "method": "quadratic_vote",
            "protocol": "Snapshot",
            "note": "Sign this EIP-712 payload with the voter's wallet, then POST to the hub /api/msg (non-custodial).",
            "hub": hub,
            "typed_data": typed_data,
        }

    # ── submit_retropgf — EAS attestation registry ─────────────────────

    async def submit_retropgf(self, **params: Any) -> dict:
        """Register a RetroPGF application via an EAS attestation (on-chain WRITE).

        Platform-level: the platform account attests the application reference
        on the Ethereum Attestation Service. Uses cfg.eas_address (falling back
        to blockchain.eas_contract) + cfg.eas_schema (blockchain.eas_schema).

        params: project_id, recipient (address), metadata_uri.
        """
        cfg = self._cfg()
        bc = self._config.get("blockchain", {})
        eas_addr = cfg.get("eas_address") or bc.get("eas_contract", "")
        eas_schema = cfg.get("eas_schema") or bc.get("eas_schema", "")

        if is_placeholder_value(eas_addr):
            return self._gate("submit_retropgf", "services.advanced_governance.eas_address (or blockchain.eas_contract)",
                              "RetroPGF via EAS (Ethereum Attestation Service)")
        if is_placeholder_value(eas_schema):
            return self._gate("submit_retropgf", "services.advanced_governance.eas_schema (or blockchain.eas_schema)",
                              "RetroPGF via EAS (Ethereum Attestation Service)")
        if not self._web3.available:
            return self._gate("submit_retropgf", "blockchain.rpc_url",
                              "RetroPGF via EAS (Ethereum Attestation Service)")

        project_id = params.get("project_id")
        recipient = params.get("recipient")
        metadata_uri = params.get("metadata_uri", "")
        if not project_id or not recipient:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "submit_retropgf",
                "error": "project_id and recipient are required",
            }

        # Real EAS ``attest`` ABI (canonical IEAS.attest with AttestationRequest).
        eas_abi = [{
            "name": "attest",
            "stateMutability": "payable",
            "type": "function",
            "inputs": [{
                "name": "request", "type": "tuple",
                "components": [
                    {"name": "schema", "type": "bytes32"},
                    {"name": "data", "type": "tuple", "components": [
                        {"name": "recipient", "type": "address"},
                        {"name": "expirationTime", "type": "uint64"},
                        {"name": "revocable", "type": "bool"},
                        {"name": "refUID", "type": "bytes32"},
                        {"name": "data", "type": "bytes"},
                        {"name": "value", "type": "uint256"},
                    ]},
                ],
            }],
            "outputs": [{"name": "", "type": "bytes32"}],
        }]
        try:
            w3 = self._web3.w3
            schema_b32 = _to_bytes32(eas_schema)
            # Encoded application payload (project ref + metadata URI) as bytes.
            data_bytes = f"{project_id}|{metadata_uri}".encode("utf-8")
            request = (
                schema_b32,
                (
                    w3.to_checksum_address(recipient),
                    0,           # expirationTime: no expiry
                    True,        # revocable
                    b"\x00" * 32,  # refUID
                    data_bytes,
                    0,           # value
                ),
            )
            contract = self._web3.load_contract(eas_addr, eas_abi)
            tx = contract.functions.attest(request).build_transaction(
                {"from": self._web3.get_account().address}
            )
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "submit_retropgf",
                "protocol": "EAS (RetroPGF application attestation)",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "eas_address": eas_addr,
                "schema": eas_schema,
                "project_id": project_id,
                "signer": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("submit_retropgf failed: %s", exc)
            return {"status": "error", "service": self.service_name, "method": "submit_retropgf", "error": str(exc)}

    # ── place_bribe — gauge bribe market depositBribe (on-chain WRITE) ──

    async def place_bribe(self, **params: Any) -> dict:
        """Deposit a gauge-vote bribe/incentive into a bribe market (on-chain WRITE).

        Platform-level: incentives are funded from the PLATFORM account via the
        paymaster. This never moves a user's tokens.

        params: proposal (bytes32/hex), reward_token (address), amount (float),
                choice_index (int, default 0).
        """
        cfg = self._cfg()
        bribe_addr = cfg.get("bribe_market_address", "")

        if is_placeholder_value(bribe_addr):
            return self._gate("place_bribe", "services.advanced_governance.bribe_market_address",
                              "gauge bribe market (Votium/Convex-style)")
        if not self._web3.available:
            return self._gate("place_bribe", "blockchain.rpc_url",
                              "gauge bribe market (Votium/Convex-style)")

        proposal = params.get("proposal") or params.get("proposal_id")
        reward_token = params.get("reward_token") or params.get("token")
        amount = params.get("amount")
        choice_index = int(params.get("choice_index", 0))
        if not proposal or not reward_token or amount is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "place_bribe",
                "error": "proposal, reward_token and amount are required",
            }

        try:
            w3 = self._web3.w3
            amount_wei = int(float(amount) * 1e18)  # assume 18-decimal reward token
            proposal_b32 = _to_bytes32(proposal)
            contract = self._web3.load_contract(bribe_addr, _BRIBE_MARKET_ABI)
            tx = contract.functions.depositBribe(
                proposal_b32,
                w3.to_checksum_address(reward_token),
                amount_wei,
                choice_index,
            ).build_transaction({"from": self._web3.get_account().address})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "place_bribe",
                "protocol": "gauge bribe market",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "bribe_market_address": bribe_addr,
                "reward_token": reward_token,
                "amount_wei": str(amount_wei),
                "choice_index": choice_index,
                "signer": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("place_bribe failed: %s", exc)
            return {"status": "error", "service": self.service_name, "method": "place_bribe", "error": str(exc)}

    # ── delegate_voting — Snapshot Delegate Registry setDelegate ────────

    async def delegate_voting(self, **params: Any) -> dict:
        """Delegate voting power via the Snapshot Delegate Registry (on-chain WRITE).

        Platform-level: delegates the PLATFORM account's voting power. To delegate
        a *user's* voting power, pass ``on_behalf_of`` to receive a prepared
        unsigned tx for the user's wallet (non-custodial — the server never
        delegates a user's power without their signature).

        params: delegate (address), space (Snapshot space id, default ""=global),
                on_behalf_of (optional user address → prepared, unsigned tx).
        """
        cfg = self._cfg()
        # Delegate Registry is the canonical cross-chain address; allow override.
        registry_addr = cfg.get("delegate_registry_address") or _DELEGATE_REGISTRY_ADDRESS

        if not self._web3.available:
            return self._gate("delegate_voting", "blockchain.rpc_url",
                              "Snapshot Delegate Registry")

        delegate = params.get("delegate")
        if not delegate:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "delegate_voting",
                "error": "delegate (address) is required",
            }
        space = params.get("space") or cfg.get("snapshot_space", "") or ""

        try:
            w3 = self._web3.w3
            id_b32 = _to_bytes32(space) if space else (b"\x00" * 32)
            contract = self._web3.load_contract(registry_addr, _DELEGATE_REGISTRY_ABI)
            fn = contract.functions.setDelegate(id_b32, w3.to_checksum_address(delegate))

            on_behalf_of = params.get("on_behalf_of")
            if on_behalf_of:
                tx = fn.build_transaction({"from": w3.to_checksum_address(on_behalf_of)})
                return {
                    "status": "prepared_unsigned",
                    "service": self.service_name,
                    "method": "delegate_voting",
                    "note": "User delegation: sign this with the user's wallet (non-custodial).",
                    "unsigned_tx": {k: (v.hex() if isinstance(v, bytes) else v) for k, v in tx.items()},
                    "delegate_registry_address": registry_addr,
                    "delegate": delegate,
                    "space": space,
                }

            tx = fn.build_transaction({"from": self._web3.get_account().address})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "delegate_voting",
                "protocol": "Snapshot Delegate Registry",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "delegate_registry_address": registry_addr,
                "delegate": delegate,
                "space": space,
                "signer": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("delegate_voting failed: %s", exc)
            return {"status": "error", "service": self.service_name, "method": "delegate_voting", "error": str(exc)}


# ── module-level helpers ────────────────────────────────────────────────

def _to_bytes32(value: Any) -> bytes:
    """Coerce a hex string / id into a 32-byte value (right-padded if short)."""
    if isinstance(value, bytes):
        return value[:32].ljust(32, b"\x00")
    s = str(value)
    if s.startswith("0x"):
        hexpart = s[2:]
        if len(hexpart) % 2:  # tolerate odd-length hex
            hexpart = "0" + hexpart
        raw = bytes.fromhex(hexpart)
        return raw[:32].ljust(32, b"\x00")
    raw = s.encode("utf-8")
    return raw[:32].ljust(32, b"\x00")


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return getattr(resp, "text", "")
