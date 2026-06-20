"""
Cross-chain messaging and bridging via CCIP, Hyperlane, Wormhole, Axelar, Stargate.

This service wires the major cross-chain interoperability protocols to the
platform. Every method follows the same shape:

1. CREDENTIAL-GATED gate FIRST — if the specific router/gateway/mailbox
   address (or the RPC) this method needs is missing or a placeholder, the
   method returns the canonical ``not_deployed_response`` naming the EXACT
   missing config key so ``CREDENTIALS_NEEDED.md`` can map it.
2. REAL path — once the operator has populated the relevant
   ``services.ccip.*`` config keys, the method performs the protocol's REAL
   on-chain call (router.ccipSend / mailbox.dispatch / core.publishMessage /
   gateway.callContract / stargate router) signed by the **platform
   paymaster account** via ``Web3Manager.send_transaction`` (gas-sponsored).

Non-custodial: all on-chain WRITES are signed by the platform paymaster
account only. Bridging a TOKEN moves value, so token bridges operate on the
PLATFORM account's own balance (platform-treasury bridging) — this service
NEVER signs with, or moves funds from, a user's wallet. When a caller asks to
bridge a *user's* funds, the honest answer is a prepared/unsigned op for the
user's own wallet to sign; that is surfaced via the ``non_custodial`` field
rather than custodied server-side.

Config keys (read from ``services.ccip``):
    - ``ccip_router_address``      — Chainlink CCIP Router (defaults to the
                                     known Base-Sepolia router, marked
                                     UNVERIFIED until confirmed on-chain)
    - ``hyperlane_mailbox``        — Hyperlane Mailbox address (REQUIRED)
    - ``wormhole_core``            — Wormhole core bridge address (REQUIRED)
    - ``axelar_gateway``           — Axelar gateway address (REQUIRED)
    - ``stargate_router``          — Stargate router address (REQUIRED)
    - ``link_token``               — LINK token addr for CCIP fee (optional;
                                     when unset the fee is paid in native gas)
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)

# Chainlink CCIP Router on Base Sepolia (chain 84532).
# Supplied by the integration spec; treat as UNVERIFIED until confirmed
# against the live Chainlink CCIP directory before any mainnet use.
# https://docs.chain.link/ccip/directory/testnet
_CCIP_ROUTER_BASE_SEPOLIA = "0xD3b06cEbF099CE7DA4AcCf578aaebFDBd6e88a93"

# bytes32 / bytes empty defaults.
_ZERO_BYTES32 = "0x" + "00" * 32

# ── Minimal ABIs — only the single function each method invokes. ──────────

# Chainlink CCIP Router. EVM2AnyMessage is the canonical struct from
# IRouterClient (Client.EVM2AnyMessage). ccipSend returns the bytes32
# messageId. getFee is a view call used to size the native fee.
# Verified against chainlink/contracts ccip IRouterClient + Client.sol.
_CCIP_ROUTER_ABI: list[dict] = [
    {
        "type": "function",
        "name": "ccipSend",
        "stateMutability": "payable",
        "inputs": [
            {"name": "destinationChainSelector", "type": "uint64"},
            {
                "name": "message",
                "type": "tuple",
                "components": [
                    {"name": "receiver", "type": "bytes"},
                    {"name": "data", "type": "bytes"},
                    {
                        "name": "tokenAmounts",
                        "type": "tuple[]",
                        "components": [
                            {"name": "token", "type": "address"},
                            {"name": "amount", "type": "uint256"},
                        ],
                    },
                    {"name": "feeToken", "type": "address"},
                    {"name": "extraArgs", "type": "bytes"},
                ],
            },
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "type": "function",
        "name": "getFee",
        "stateMutability": "view",
        "inputs": [
            {"name": "destinationChainSelector", "type": "uint64"},
            {
                "name": "message",
                "type": "tuple",
                "components": [
                    {"name": "receiver", "type": "bytes"},
                    {"name": "data", "type": "bytes"},
                    {
                        "name": "tokenAmounts",
                        "type": "tuple[]",
                        "components": [
                            {"name": "token", "type": "address"},
                            {"name": "amount", "type": "uint256"},
                        ],
                    },
                    {"name": "feeToken", "type": "address"},
                    {"name": "extraArgs", "type": "bytes"},
                ],
            },
        ],
        "outputs": [{"name": "fee", "type": "uint256"}],
    },
]

# Hyperlane Mailbox.dispatch — recipient is bytes32 (left-padded address).
# Verified against hyperlane-xyz/hyperlane-monorepo IMailbox.
_HYPERLANE_MAILBOX_ABI: list[dict] = [
    {
        "type": "function",
        "name": "dispatch",
        "stateMutability": "payable",
        "inputs": [
            {"name": "destinationDomain", "type": "uint32"},
            {"name": "recipientAddress", "type": "bytes32"},
            {"name": "messageBody", "type": "bytes"},
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
]

# Wormhole core bridge publishMessage — emits a VAA-eligible LogMessagePublished.
# Verified against wormhole-foundation IWormhole.
_WORMHOLE_CORE_ABI: list[dict] = [
    {
        "type": "function",
        "name": "publishMessage",
        "stateMutability": "payable",
        "inputs": [
            {"name": "nonce", "type": "uint32"},
            {"name": "payload", "type": "bytes"},
            {"name": "consistencyLevel", "type": "uint8"},
        ],
        "outputs": [{"name": "sequence", "type": "uint64"}],
    },
]

# Axelar gateway callContract — general-message-passing entrypoint.
# Verified against axelarnetwork/axelar-cgp-solidity IAxelarGateway.
_AXELAR_GATEWAY_ABI: list[dict] = [
    {
        "type": "function",
        "name": "callContract",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "destinationChain", "type": "string"},
            {"name": "destinationContractAddress", "type": "string"},
            {"name": "payload", "type": "bytes"},
        ],
        "outputs": [],
    },
]

# Stargate router send. UNVERIFIED — Stargate has two live generations
# (V1 ``swap(...)`` and V2 ``sendToken(...)``) whose signatures differ; the
# operator must confirm which router generation ``stargate_router`` points at
# before production use. This minimal V2-style ``send`` is a best-effort
# placeholder and is gated behind the configured address regardless.
_STARGATE_ROUTER_ABI: list[dict] = [
    {
        "type": "function",
        "name": "swap",
        "stateMutability": "payable",
        "inputs": [
            {"name": "dstChainId", "type": "uint16"},
            {"name": "srcPoolId", "type": "uint256"},
            {"name": "dstPoolId", "type": "uint256"},
            {"name": "refundAddress", "type": "address"},
            {"name": "amountLD", "type": "uint256"},
            {"name": "minAmountLD", "type": "uint256"},
            {
                "name": "lzTxParams",
                "type": "tuple",
                "components": [
                    {"name": "dstGasForCall", "type": "uint256"},
                    {"name": "dstNativeAmount", "type": "uint256"},
                    {"name": "dstNativeAddr", "type": "bytes"},
                ],
            },
            {"name": "to", "type": "bytes"},
            {"name": "payload", "type": "bytes"},
        ],
        "outputs": [],
    },
]


class CrossChainMessagingService:
    """Cross-chain messaging and bridging via CCIP, Hyperlane, Wormhole, Axelar, Stargate."""

    service_name = "ccip"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── Helpers ───────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict (``services.ccip``)."""
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    def _ccip_router(self) -> str:
        """CCIP router — known Base-Sepolia router unless overridden (UNVERIFIED)."""
        addr = self._cfg().get("ccip_router_address", "")
        if is_placeholder_value(addr):
            return _CCIP_ROUTER_BASE_SEPOLIA
        return addr

    @staticmethod
    def _to_bytes(value: Any) -> bytes:
        """Coerce a hex string / bytes / None into ``bytes`` (empty by default)."""
        if value is None or value == "":
            return b""
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if isinstance(value, str):
            s = value[2:] if value.startswith("0x") else value
            try:
                return bytes.fromhex(s)
            except ValueError:
                # Treat as a UTF-8 message body when not valid hex.
                return value.encode("utf-8")
        return bytes(value)

    def _addr_to_bytes32(self, address: str) -> bytes:
        """Left-pad a 20-byte address into a bytes32 (Hyperlane recipient form)."""
        w3 = self._web3.w3
        raw = bytes.fromhex(w3.to_checksum_address(address)[2:])
        return raw.rjust(32, b"\x00")

    def _platform_unsigned_note(self) -> dict:
        """Standard non-custodial note attached to every value-moving op."""
        return {
            "signer": "platform_paymaster",
            "note": (
                "On-chain write signed by the platform paymaster account only. "
                "This bridges the PLATFORM account's own balance; a user's wallet "
                "funds are never custodied or moved server-side. To bridge a "
                "user's funds, the user's own wallet must sign."
            ),
        }

    # ── Chainlink CCIP ────────────────────────────────────────────────

    async def bridge_token_ccip(self, **params: Any) -> dict:
        """Bridge a token cross-chain via Chainlink CCIP ``Router.ccipSend``.

        Params: ``destination_chain_selector`` (uint64 CCIP selector),
        ``receiver`` (dest address), ``token`` (ERC-20 on this chain),
        ``amount`` (uint, base units), optional ``data`` (hex), optional
        ``fee_token`` (LINK addr; native gas when unset).

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        """
        selector = params.get("destination_chain_selector") or params.get("dest_selector")
        receiver = params.get("receiver") or params.get("to")
        token = params.get("token")
        amount = params.get("amount")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_token_ccip",
                "missing": "blockchain.rpc_url",
                "protocol": "Chainlink CCIP",
            })
        router_addr = self._ccip_router()
        if is_placeholder_value(router_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_token_ccip",
                "missing": "services.ccip.ccip_router_address",
                "protocol": "Chainlink CCIP",
            })
        if selector is None or is_placeholder_value(receiver) or is_placeholder_value(token) or amount is None:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_token_ccip",
                "missing": "destination_chain_selector / receiver / token / amount (call params)",
                "protocol": "Chainlink CCIP",
            })

        # ── REAL path: Router.ccipSend(selector, EVM2AnyMessage) ──────
        try:
            w3 = self._web3.w3
            router = self._web3.load_contract(router_addr, _CCIP_ROUTER_ABI)

            fee_token_cfg = self._cfg().get("link_token", "")
            fee_token = (
                w3.to_checksum_address(fee_token_cfg)
                if not is_placeholder_value(fee_token_cfg)
                else "0x0000000000000000000000000000000000000000"  # native fee
            )
            receiver_bytes = self._addr_to_bytes32(receiver)
            message = (
                receiver_bytes,                          # receiver (abi-encoded address)
                self._to_bytes(params.get("data")),      # data
                [(w3.to_checksum_address(token), int(amount))],  # tokenAmounts
                fee_token,                               # feeToken
                self._to_bytes(params.get("extra_args")),  # extraArgs
            )

            # Size the fee so we can attach native value when paying in gas.
            try:
                fee = router.functions.getFee(int(selector), message).call()
            except Exception as fee_exc:  # noqa: BLE001
                logger.warning("CCIP getFee failed, defaulting to 0: %s", fee_exc)
                fee = 0
            native_value = int(fee) if fee_token == "0x0000000000000000000000000000000000000000" else 0

            tx = router.functions.ccipSend(int(selector), message).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "value": native_value,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "bridge_token_ccip",
                "protocol": "Chainlink CCIP",
                "router": router_addr,
                "destination_chain_selector": int(selector),
                "token": w3.to_checksum_address(token),
                "amount": int(amount),
                "fee_paid": int(fee),
                "fee_token": fee_token,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "non_custodial": self._platform_unsigned_note(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("bridge_token_ccip on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "bridge_token_ccip",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    async def send_cross_chain_message(self, **params: Any) -> dict:
        """Send an arbitrary cross-chain message via Chainlink CCIP ``ccipSend``.

        Like ``bridge_token_ccip`` but with no token transfer — a pure
        ``EVM2AnyMessage`` data payload. Params: ``destination_chain_selector``,
        ``receiver``, ``data`` (hex or utf-8), optional ``fee_token``.

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        """
        selector = params.get("destination_chain_selector") or params.get("dest_selector")
        receiver = params.get("receiver") or params.get("to")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "send_cross_chain_message",
                "missing": "blockchain.rpc_url",
                "protocol": "Chainlink CCIP",
            })
        router_addr = self._ccip_router()
        if is_placeholder_value(router_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "send_cross_chain_message",
                "missing": "services.ccip.ccip_router_address",
                "protocol": "Chainlink CCIP",
            })
        if selector is None or is_placeholder_value(receiver):
            return not_deployed_response(self.service_name, extra={
                "method": "send_cross_chain_message",
                "missing": "destination_chain_selector / receiver (call params)",
                "protocol": "Chainlink CCIP",
            })

        # ── REAL path: Router.ccipSend with empty tokenAmounts ────────
        try:
            w3 = self._web3.w3
            router = self._web3.load_contract(router_addr, _CCIP_ROUTER_ABI)

            fee_token_cfg = self._cfg().get("link_token", "")
            fee_token = (
                w3.to_checksum_address(fee_token_cfg)
                if not is_placeholder_value(fee_token_cfg)
                else "0x0000000000000000000000000000000000000000"
            )
            message = (
                self._addr_to_bytes32(receiver),
                self._to_bytes(params.get("data")),
                [],  # no token transfer — message only
                fee_token,
                self._to_bytes(params.get("extra_args")),
            )

            try:
                fee = router.functions.getFee(int(selector), message).call()
            except Exception as fee_exc:  # noqa: BLE001
                logger.warning("CCIP getFee failed, defaulting to 0: %s", fee_exc)
                fee = 0
            native_value = int(fee) if fee_token == "0x0000000000000000000000000000000000000000" else 0

            tx = router.functions.ccipSend(int(selector), message).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "value": native_value,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "send_cross_chain_message",
                "protocol": "Chainlink CCIP",
                "router": router_addr,
                "destination_chain_selector": int(selector),
                "receiver": w3.to_checksum_address(receiver),
                "fee_paid": int(fee),
                "fee_token": fee_token,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("send_cross_chain_message on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "send_cross_chain_message",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ── Hyperlane ─────────────────────────────────────────────────────

    async def bridge_hyperlane(self, **params: Any) -> dict:
        """Dispatch a cross-chain message via Hyperlane ``Mailbox.dispatch``.

        Params: ``destination_domain`` (uint32 Hyperlane domain id),
        ``recipient`` (dest address — padded to bytes32), ``message`` /
        ``data`` (body, hex or utf-8).

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        Requires ``services.ccip.hyperlane_mailbox`` (no canonical default —
        the Mailbox address is chain-specific).
        """
        domain = params.get("destination_domain") or params.get("dest_domain")
        recipient = params.get("recipient") or params.get("to")
        mailbox_addr = self._cfg().get("hyperlane_mailbox", "")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_hyperlane",
                "missing": "blockchain.rpc_url",
                "protocol": "Hyperlane",
            })
        if is_placeholder_value(mailbox_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_hyperlane",
                "missing": "services.ccip.hyperlane_mailbox",
                "protocol": "Hyperlane",
            })
        if domain is None or is_placeholder_value(recipient):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_hyperlane",
                "missing": "destination_domain / recipient (call params)",
                "protocol": "Hyperlane",
            })

        # ── REAL path: Mailbox.dispatch(domain, recipient32, body) ────
        try:
            w3 = self._web3.w3
            mailbox = self._web3.load_contract(mailbox_addr, _HYPERLANE_MAILBOX_ABI)
            recipient32 = self._addr_to_bytes32(recipient)
            body = self._to_bytes(params.get("message") or params.get("data"))

            tx = mailbox.functions.dispatch(
                int(domain), recipient32, body
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "bridge_hyperlane",
                "protocol": "Hyperlane",
                "mailbox": w3.to_checksum_address(mailbox_addr),
                "destination_domain": int(domain),
                "recipient": w3.to_checksum_address(recipient),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("bridge_hyperlane on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "bridge_hyperlane",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ── Wormhole ──────────────────────────────────────────────────────

    async def bridge_wormhole(self, **params: Any) -> dict:
        """Publish a cross-chain message via Wormhole core ``publishMessage``.

        Params: ``payload`` (bytes, hex or utf-8), optional ``nonce`` (uint32,
        default 0), optional ``consistency_level`` (uint8, default 1 ==
        finalized). This emits the ``LogMessagePublished`` event a Guardian set
        signs into a VAA off-chain.

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        Requires ``services.ccip.wormhole_core``.
        """
        core_addr = self._cfg().get("wormhole_core", "")
        payload = params.get("payload") or params.get("data")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_wormhole",
                "missing": "blockchain.rpc_url",
                "protocol": "Wormhole",
            })
        if is_placeholder_value(core_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_wormhole",
                "missing": "services.ccip.wormhole_core",
                "protocol": "Wormhole",
            })
        if is_placeholder_value(payload):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_wormhole",
                "missing": "payload (call params)",
                "protocol": "Wormhole",
            })

        # ── REAL path: core.publishMessage(nonce, payload, consistency) ─
        try:
            w3 = self._web3.w3
            core = self._web3.load_contract(core_addr, _WORMHOLE_CORE_ABI)
            nonce = int(params.get("nonce") or 0)
            consistency = int(params.get("consistency_level") or 1)
            payload_bytes = self._to_bytes(payload)

            tx = core.functions.publishMessage(
                nonce, payload_bytes, consistency
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "bridge_wormhole",
                "protocol": "Wormhole",
                "core_bridge": w3.to_checksum_address(core_addr),
                "nonce": nonce,
                "consistency_level": consistency,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("bridge_wormhole on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "bridge_wormhole",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ── Axelar ────────────────────────────────────────────────────────

    async def bridge_axelar(self, **params: Any) -> dict:
        """Call a contract cross-chain via Axelar ``gateway.callContract``.

        Params: ``destination_chain`` (Axelar chain name, e.g. "ethereum"),
        ``destination_contract`` (dest contract address as a string),
        ``payload`` (bytes, hex or utf-8).

        On-chain WRITE signed by the platform paymaster (gas-sponsored).
        Requires ``services.ccip.axelar_gateway``. Note: Axelar gas for
        execution on the destination chain is normally paid to the Axelar Gas
        Service separately; this method emits the GMP call only.
        """
        gateway_addr = self._cfg().get("axelar_gateway", "")
        dest_chain = params.get("destination_chain") or params.get("dest_chain")
        dest_contract = params.get("destination_contract") or params.get("dest_contract")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_axelar",
                "missing": "blockchain.rpc_url",
                "protocol": "Axelar",
            })
        if is_placeholder_value(gateway_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_axelar",
                "missing": "services.ccip.axelar_gateway",
                "protocol": "Axelar",
            })
        if is_placeholder_value(dest_chain) or is_placeholder_value(dest_contract):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_axelar",
                "missing": "destination_chain / destination_contract (call params)",
                "protocol": "Axelar",
            })

        # ── REAL path: gateway.callContract(chain, contract, payload) ─
        try:
            w3 = self._web3.w3
            gateway = self._web3.load_contract(gateway_addr, _AXELAR_GATEWAY_ABI)
            payload_bytes = self._to_bytes(params.get("payload") or params.get("data"))

            tx = gateway.functions.callContract(
                str(dest_chain), str(dest_contract), payload_bytes
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "bridge_axelar",
                "protocol": "Axelar",
                "gateway": w3.to_checksum_address(gateway_addr),
                "destination_chain": str(dest_chain),
                "destination_contract": str(dest_contract),
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("bridge_axelar on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "bridge_axelar",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ── Stargate ──────────────────────────────────────────────────────

    async def bridge_stargate(self, **params: Any) -> dict:
        """Bridge a token via the Stargate (LayerZero) router ``swap``.

        Params: ``dst_chain_id`` (uint16 LayerZero/Stargate chain id),
        ``src_pool_id``, ``dst_pool_id`` (Stargate pool ids), ``amount``
        (uint, local decimals), optional ``min_amount`` (slippage floor,
        defaults to ``amount``), ``to`` (dest recipient address).

        On-chain WRITE signed by the platform paymaster (gas-sponsored) —
        bridges the PLATFORM account's own balance only (see ``non_custodial``).

        UNVERIFIED: Stargate has two router generations (V1 ``swap`` / V2
        ``sendToken``) with different signatures; ``stargate_router`` must point
        at the matching generation for this ABI. Confirm before production use.
        """
        router_addr = self._cfg().get("stargate_router", "")
        dst_chain_id = params.get("dst_chain_id") or params.get("dst_chain")
        src_pool_id = params.get("src_pool_id")
        dst_pool_id = params.get("dst_pool_id")
        amount = params.get("amount")
        to = params.get("to") or params.get("recipient")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_stargate",
                "missing": "blockchain.rpc_url",
                "protocol": "Stargate (LayerZero)",
            })
        if is_placeholder_value(router_addr):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_stargate",
                "missing": "services.ccip.stargate_router",
                "protocol": "Stargate (LayerZero)",
            })
        if (
            dst_chain_id is None
            or src_pool_id is None
            or dst_pool_id is None
            or amount is None
            or is_placeholder_value(to)
        ):
            return not_deployed_response(self.service_name, extra={
                "method": "bridge_stargate",
                "missing": "dst_chain_id / src_pool_id / dst_pool_id / amount / to (call params)",
                "protocol": "Stargate (LayerZero)",
            })

        # ── REAL path: Stargate router.swap(...) ──────────────────────
        try:
            w3 = self._web3.w3
            router = self._web3.load_contract(router_addr, _STARGATE_ROUTER_ABI)
            platform_addr = self._web3.get_account().address
            amount_ld = int(amount)
            min_amount_ld = int(params.get("min_amount") or amount_ld)
            # lzTxParams: no extra dest-gas / native airdrop by default.
            lz_tx_params = (0, 0, b"")
            to_bytes = bytes.fromhex(w3.to_checksum_address(to)[2:])

            # LayerZero message fee is paid in native value; size it from
            # config when provided (router.quoteLayerZeroFee is generation
            # specific and intentionally not assumed here).
            native_value = int(params.get("native_fee") or self._cfg().get("stargate_native_fee", 0) or 0)

            tx = router.functions.swap(
                int(dst_chain_id),
                int(src_pool_id),
                int(dst_pool_id),
                platform_addr,        # refund address = platform
                amount_ld,
                min_amount_ld,
                lz_tx_params,
                to_bytes,
                b"",                  # payload
            ).build_transaction({
                "from": platform_addr,
                "chainId": self._web3.chain_id,
                "value": native_value,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "bridge_stargate",
                "protocol": "Stargate (LayerZero)",
                "router": w3.to_checksum_address(router_addr),
                "dst_chain_id": int(dst_chain_id),
                "src_pool_id": int(src_pool_id),
                "dst_pool_id": int(dst_pool_id),
                "amount": amount_ld,
                "min_amount": min_amount_ld,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
                "abi_status": "UNVERIFIED (confirm Stargate router generation)",
                "non_custodial": self._platform_unsigned_note(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("bridge_stargate on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "bridge_stargate",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    # ── Remote-chain query (off-chain protocol API) ───────────────────

    async def query_remote_chain(self, **params: Any) -> dict:
        """Query the delivery/attestation status of a cross-chain message.

        Off-chain READ against a cross-chain tracking API. Params:
        ``message_id`` / ``tx_hash`` (the source message id or tx hash),
        optional ``protocol`` (ccip|hyperlane|wormhole|axelar|stargate).

        Requires a configured tracker endpoint (``services.ccip.tracker_url``,
        optionally ``services.ccip.tracker_api_key``). httpx is imported lazily;
        if unavailable the method is CREDENTIAL-GATED.
        """
        message_id = params.get("message_id") or params.get("tx_hash") or params.get("id")
        tracker_url = self._cfg().get("tracker_url", "")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if is_placeholder_value(tracker_url):
            return not_deployed_response(self.service_name, extra={
                "method": "query_remote_chain",
                "missing": "services.ccip.tracker_url",
                "protocol": "cross-chain message tracker API",
            })
        if is_placeholder_value(message_id):
            return not_deployed_response(self.service_name, extra={
                "method": "query_remote_chain",
                "missing": "message_id / tx_hash (call params)",
                "protocol": "cross-chain message tracker API",
            })

        try:
            import httpx  # lazy heavy import — keep module import-safe
        except ImportError:
            return not_deployed_response(self.service_name, extra={
                "method": "query_remote_chain",
                "missing": "httpx (Python package)",
                "protocol": "cross-chain message tracker API",
            })

        # ── REAL path: GET the tracker for this message id ────────────
        # UNVERIFIED: exact tracker route/shape depends on the configured
        # provider (e.g. CCIP explorer API, Wormholescan, Axelarscan). The
        # base URL + optional api_key come entirely from config.
        try:
            api_key = self._cfg().get("tracker_api_key", "")
            headers = {}
            if not is_placeholder_value(api_key):
                headers["Authorization"] = f"Bearer {api_key}"
            query = {"messageId": str(message_id)}
            protocol = params.get("protocol")
            if protocol:
                query["protocol"] = str(protocol)

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(tracker_url, params=query, headers=headers)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception:  # noqa: BLE001 — non-JSON tracker response
                    data = {"raw": resp.text}

            return {
                "status": "ok",
                "service": self.service_name,
                "method": "query_remote_chain",
                "protocol": str(protocol) if protocol else "cross-chain tracker",
                "tracker_url": tracker_url,
                "message_id": str(message_id),
                "result": data,
                "result_status": "UNVERIFIED (tracker response shape is provider-specific)",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("query_remote_chain API call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "query_remote_chain",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
