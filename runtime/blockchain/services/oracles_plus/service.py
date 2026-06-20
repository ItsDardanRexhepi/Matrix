"""
Pyth, RedStone, API3 data feeds and Chainlink Keepers automation.

Each method gates on the EXACT credential it needs (CREDENTIAL-GATED) and,
when that credential is present, performs the protocol's REAL operation:

- ``pyth_pull``        — Hermes REST API (off-chain price + binary VAA update
                         data) and optionally an on-chain read of the canonical
                         Pyth pull contract on Base.
- ``redstone_request`` — RedStone Oracle Gateway REST API (off-chain signed
                         data packages).
- ``api3_query``       — on-chain read of an API3 dAPI proxy contract
                         (``read()`` → (value, timestamp)).
- ``register_keeper_job`` — platform-level on-chain write to the Chainlink
                         Automation registry (paymaster-signed).

Honesty rules:
- Default network is Base Sepolia (chain 84532). No mainnet assumptions.
- No secrets are hardcoded — every credential is read from config.
- NON-CUSTODIAL: the only key that ever signs is the platform paymaster
  account (via ``Web3Manager.send_transaction``). No user wallet is ever
  signed for or custodied server-side. ``register_keeper_job`` funds/registers
  an upkeep on the PLATFORM account only.
- Heavy deps (web3, httpx) are imported lazily so module import / test
  collection never breaks when they are absent.
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


# ─────────────────────────────────────────────────────────────────────────
# Real, canonical protocol interfaces (verified where noted).
# ─────────────────────────────────────────────────────────────────────────

# Pyth pull oracle (IPyth) — canonical address on Base (mainnet & Sepolia
# share this deployment). Verified: https://docs.pyth.network/price-feeds/contract-addresses/evm
PYTH_CONTRACT_BASE = "0x8250f4aF4B972684F7b336503E2D6dFeDeB1487a"

# Pyth Hermes price-service REST base URL (documented, public, no key required).
# https://hermes.pyth.network/docs/
PYTH_HERMES_BASE = "https://hermes.pyth.network"

# RedStone Oracle Gateway REST base URL (documented, public).
# Verified live: returns signed data packages per data-feed id at
# /data-packages/latest/<data-service-id>. https://docs.redstone.finance/
REDSTONE_API_BASE = "https://oracle-gateway-1.a.redstone.finance"

# Chainlink Automation (Keepers) Registry — address is network-specific and
# must be supplied in config. The function selector below is from the public
# AutomationRegistrar interface. UNVERIFIED for the operator's specific
# registrar version — the registrar ABI varies by Automation version (2.0/2.1).

# Minimal Pyth IPyth ABI — only the read functions this service calls.
# Verified against the public IPyth interface (pyth-sdk-solidity).
_PYTH_ABI = [
    {
        "name": "getPriceUnsafe",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "bytes32"}],
        "outputs": [
            {
                "name": "price",
                "type": "tuple",
                "components": [
                    {"name": "price", "type": "int64"},
                    {"name": "conf", "type": "uint64"},
                    {"name": "expo", "type": "int32"},
                    {"name": "publishTime", "type": "uint256"},
                ],
            }
        ],
    },
    {
        "name": "getUpdateFee",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "updateData", "type": "bytes[]"}],
        "outputs": [{"name": "feeAmount", "type": "uint256"}],
    },
]

# Minimal API3 dAPI proxy ABI — IProxy.read() returns (value int224, timestamp uint32).
# Verified against the public API3 IProxy interface.
_API3_PROXY_ABI = [
    {
        "name": "read",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "value", "type": "int224"},
            {"name": "timestamp", "type": "uint32"},
        ],
    }
]

# Minimal Chainlink Automation registrar ABI — registerUpkeep(RegistrationParams).
# UNVERIFIED: the registrar struct/selector differs across Automation versions
# (2.0 vs 2.1+). The operator must supply the registrar that matches their
# deployment; this minimal ABI targets the 2.1 AutomationRegistrar2_1 shape.
_KEEPER_REGISTRAR_ABI = [
    {
        "name": "registerUpkeep",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "requestParams",
                "type": "tuple",
                "components": [
                    {"name": "name", "type": "string"},
                    {"name": "encryptedEmail", "type": "bytes"},
                    {"name": "upkeepContract", "type": "address"},
                    {"name": "gasLimit", "type": "uint32"},
                    {"name": "adminAddress", "type": "address"},
                    {"name": "triggerType", "type": "uint8"},
                    {"name": "checkData", "type": "bytes"},
                    {"name": "triggerConfig", "type": "bytes"},
                    {"name": "offchainConfig", "type": "bytes"},
                    {"name": "amount", "type": "uint96"},
                ],
            }
        ],
        "outputs": [{"name": "upkeepId", "type": "uint256"}],
    }
]


class OraclesPlusService:
    """Pyth, RedStone, API3 data feeds and Chainlink Keepers automation."""

    service_name = "oracles_plus"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict."""
        return self._config.get("services", {}).get(self.service_name, {})

    @staticmethod
    def _load_httpx():
        """Lazily import httpx; return module or None if unavailable."""
        try:
            import httpx  # noqa: WPS433 — intentional lazy import
            return httpx
        except ImportError:
            return None

    # ── Pyth (Hermes REST + on-chain pull contract) ──────────────────

    async def pyth_pull(self, **params: Any) -> dict:
        """Pull a Pyth price update via the Hermes REST API (real, off-chain).

        Params
        ------
        price_id / feed_id : str
            The Pyth price-feed id (bytes32 hex, e.g. the ETH/USD feed id).
        with_onchain : bool, optional
            If True and the Pyth contract is reachable, also read the latest
            cached price from the canonical Pyth pull contract on Base.

        Off-chain Hermes is public (no API key). The CREDENTIAL-GATE here is
        the price feed id — without it there is nothing real to fetch.
        """
        feed_id = params.get("price_id") or params.get("feed_id") or params.get("id")
        if is_placeholder_value(feed_id):
            return not_deployed_response(self.service_name, extra={
                "method": "pyth_pull",
                "missing": "price_id (Pyth bytes32 price-feed id, params)",
                "protocol": "pyth",
            })

        httpx = self._load_httpx()
        if httpx is None:
            return not_deployed_response(self.service_name, extra={
                "method": "pyth_pull",
                "missing": "httpx (python package) — required for Hermes REST",
                "protocol": "pyth",
            })

        cfg = self._cfg()
        # Operator may override the Hermes endpoint (e.g. a private Hermes).
        hermes_base = cfg.get("hermes_endpoint") or PYTH_HERMES_BASE
        feed_hex = feed_id[2:] if str(feed_id).startswith("0x") else str(feed_id)

        # Hermes v2 latest-updates endpoint (real, documented).
        url = f"{hermes_base}/v2/updates/price/latest"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params={"ids[]": feed_hex})
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pyth_pull Hermes request failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "pyth_pull",
                "missing": "reachable Hermes endpoint / valid price_id",
                "protocol": "pyth",
                "error": str(exc),
            })

        parsed = (data or {}).get("parsed") or []
        result: dict[str, Any] = {
            "status": "ok",
            "protocol": "pyth",
            "source": "hermes",
            "endpoint": url,
            "feed_id": feed_id,
            # binary VAA update data — the bytes a consumer would submit on-chain
            "update_data": (data or {}).get("binary", {}).get("data", []),
            "feeds": parsed,
        }

        # Optional on-chain read of the cached price from the canonical Pyth
        # pull contract. Address override via config; defaults to canonical Base.
        if params.get("with_onchain"):
            pyth_addr = cfg.get("pyth_contract_address") or PYTH_CONTRACT_BASE
            if not self._web3.available or is_placeholder_value(pyth_addr):
                result["onchain"] = {
                    "status": "not_deployed",
                    "missing": "blockchain.rpc_url / services.oracles_plus.pyth_contract_address",
                }
            else:
                try:
                    contract = self._web3.load_contract(pyth_addr, _PYTH_ABI)
                    feed_bytes = bytes.fromhex(feed_hex)
                    price = contract.functions.getPriceUnsafe(feed_bytes).call()
                    result["onchain"] = {
                        "contract": pyth_addr,
                        "price": int(price[0]),
                        "conf": int(price[1]),
                        "expo": int(price[2]),
                        "publish_time": int(price[3]),
                    }
                except Exception as exc:  # noqa: BLE001
                    logger.warning("pyth_pull on-chain read failed: %s", exc)
                    result["onchain"] = {"status": "error", "error": str(exc)}

        return result

    # ── RedStone (Oracle Gateway REST) ───────────────────────────────

    async def redstone_request(self, **params: Any) -> dict:
        """Fetch a signed RedStone data package via the RedStone REST API (real).

        Params
        ------
        data_feed / symbol : str
            The RedStone data-feed id (e.g. "ETH", "BTC").
        data_service_id : str, optional
            RedStone data-service id (defaults to the public primary-prod
            service, also overridable in config).
        unique_signers / unique_signers_count : int, optional
            Number of unique signers required.

        The public RedStone gateway needs no API key, so the CREDENTIAL-GATE
        is the data-feed id (no feed → nothing real to fetch).
        """
        feed = params.get("data_feed") or params.get("symbol") or params.get("feed_id")
        if is_placeholder_value(feed):
            return not_deployed_response(self.service_name, extra={
                "method": "redstone_request",
                "missing": "data_feed (RedStone data-feed symbol, params)",
                "protocol": "redstone",
            })

        httpx = self._load_httpx()
        if httpx is None:
            return not_deployed_response(self.service_name, extra={
                "method": "redstone_request",
                "missing": "httpx (python package) — required for RedStone REST",
                "protocol": "redstone",
            })

        cfg = self._cfg()
        api_base = cfg.get("redstone_endpoint") or REDSTONE_API_BASE
        data_service = (
            params.get("data_service_id")
            or cfg.get("redstone_data_service_id")
            or "redstone-primary-prod"
        )
        unique_signers = int(
            params.get("unique_signers")
            or params.get("unique_signers_count")
            or 1
        )

        # RedStone gateway "data-packages/latest" endpoint (real, documented).
        url = f"{api_base}/data-packages/latest/{data_service}"
        query: dict[str, Any] = {
            "dataFeedId": feed,
            "uniqueSignersCount": unique_signers,
        }
        # An operator API key, when configured, is passed as documented.
        headers: dict[str, str] = {}
        api_key = cfg.get("redstone_api_key")
        if not is_placeholder_value(api_key):
            headers["X-Api-Key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=query, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("redstone_request failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "redstone_request",
                "missing": "reachable RedStone gateway / valid data_feed",
                "protocol": "redstone",
                "error": str(exc),
            })

        return {
            "status": "ok",
            "protocol": "redstone",
            "source": "redstone-gateway",
            "endpoint": url,
            "data_feed": feed,
            "data_service_id": data_service,
            "unique_signers": unique_signers,
            "data_packages": data,
        }

    # ── API3 (dAPI proxy contract on-chain read) ─────────────────────

    async def api3_query(self, **params: Any) -> dict:
        """Read an API3 dAPI value from its on-chain proxy contract (real read).

        Params
        ------
        proxy_address : str
            The API3 dAPI proxy contract address (network-specific; operator
            supplies it per dAPI). May also be set as
            ``services.oracles_plus.api3_proxy_address`` in config.

        API3 reads are pull-style on-chain: ``IProxy.read()`` returns
        ``(value int224, timestamp uint32)``. The CREDENTIAL-GATE is the proxy
        address plus a reachable RPC.
        """
        cfg = self._cfg()
        proxy = (
            params.get("proxy_address")
            or params.get("dapi_proxy")
            or cfg.get("api3_proxy_address")
        )

        if is_placeholder_value(proxy):
            return not_deployed_response(self.service_name, extra={
                "method": "api3_query",
                "missing": "services.oracles_plus.api3_proxy_address (or proxy_address param)",
                "protocol": "api3",
            })
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "api3_query",
                "missing": "blockchain.rpc_url (Base Sepolia RPC, chain 84532)",
                "protocol": "api3",
            })

        try:
            contract = self._web3.load_contract(proxy, _API3_PROXY_ABI)
            value, timestamp = contract.functions.read().call()
        except Exception as exc:  # noqa: BLE001
            logger.warning("api3_query on-chain read failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "api3_query",
                "missing": "valid API3 dAPI proxy_address / reachable RPC",
                "protocol": "api3",
                "error": str(exc),
            })

        return {
            "status": "ok",
            "protocol": "api3",
            "source": "api3-dapi-proxy",
            "proxy_address": proxy,
            "value": int(value),         # int224, raw 18-decimal fixed point
            "timestamp": int(timestamp),  # uint32 unix seconds
        }

    # ── Chainlink Keepers / Automation (platform-level on-chain write) ─

    async def register_keeper_job(self, **params: Any) -> dict:
        """Register a Chainlink Automation upkeep (platform-level on-chain write).

        Params
        ------
        upkeep_contract : str
            The address of the contract implementing checkUpkeep/performUpkeep.
        name : str, optional
        gas_limit : int, optional
        check_data : str (hex), optional
        amount : int, optional
            LINK (juels) to fund the upkeep with.
        trigger_type : int, optional  (0 = conditional, 1 = log)

        NON-CUSTODIAL: this signs ONLY with the platform paymaster account via
        ``Web3Manager.send_transaction`` and registers the upkeep under the
        PLATFORM admin address. No user wallet is signed for or custodied.
        Requires both the registrar address (config) and a reachable RPC +
        paymaster key.
        """
        cfg = self._cfg()
        registrar = cfg.get("keeper_registrar_address") or cfg.get("registrar_address")
        upkeep_contract = params.get("upkeep_contract") or params.get("target")

        # CREDENTIAL-GATE: registrar address.
        if is_placeholder_value(registrar):
            return not_deployed_response(self.service_name, extra={
                "method": "register_keeper_job",
                "missing": "services.oracles_plus.keeper_registrar_address (Chainlink Automation registrar)",
                "protocol": "chainlink_keepers",
            })
        # CREDENTIAL-GATE: target upkeep contract.
        if is_placeholder_value(upkeep_contract):
            return not_deployed_response(self.service_name, extra={
                "method": "register_keeper_job",
                "missing": "upkeep_contract (address of the contract to automate, params)",
                "protocol": "chainlink_keepers",
            })
        # CREDENTIAL-GATE: RPC reachable.
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "register_keeper_job",
                "missing": "blockchain.rpc_url (Base Sepolia RPC, chain 84532)",
                "protocol": "chainlink_keepers",
            })
        # CREDENTIAL-GATE: paymaster key (the only signer; platform-level).
        if is_placeholder_value(self._web3.paymaster_key):
            return not_deployed_response(self.service_name, extra={
                "method": "register_keeper_job",
                "missing": "blockchain.paymaster_private_key (platform signer)",
                "protocol": "chainlink_keepers",
            })

        try:
            account = self._web3.get_account()
            admin_address = account.address  # platform account — non-custodial
            name = params.get("name") or "0pnMatrx upkeep"
            gas_limit = int(params.get("gas_limit") or 500_000)
            amount = int(params.get("amount") or 0)  # LINK juels to fund
            trigger_type = int(params.get("trigger_type") or 0)
            check_data_hex = params.get("check_data") or "0x"
            check_data = bytes.fromhex(
                check_data_hex[2:] if check_data_hex.startswith("0x") else check_data_hex
            )

            registrar_contract = self._web3.load_contract(registrar, _KEEPER_REGISTRAR_ABI)
            checksum_upkeep = registrar_contract.w3.to_checksum_address(upkeep_contract)

            # RegistrationParams tuple (AutomationRegistrar2_1 shape — UNVERIFIED
            # for the operator's specific registrar version).
            registration_params = (
                name,                 # name
                b"",                  # encryptedEmail
                checksum_upkeep,      # upkeepContract
                gas_limit,            # gasLimit
                admin_address,        # adminAddress (PLATFORM account)
                trigger_type,         # triggerType
                check_data,           # checkData
                b"",                  # triggerConfig
                b"",                  # offchainConfig
                amount,               # amount (LINK juels)
            )

            tx = registrar_contract.functions.registerUpkeep(
                registration_params
            ).build_transaction({
                "from": admin_address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
        except Exception as exc:  # noqa: BLE001
            logger.error("register_keeper_job failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "register_keeper_job",
                "missing": "valid registrar ABI/version + funded LINK allowance",
                "protocol": "chainlink_keepers",
                "error": str(exc),
            })

        return {
            "status": "submitted",
            "protocol": "chainlink_keepers",
            "tx_hash": tx_hash,
            "explorer_url": self._web3.explorer_url(tx_hash),
            "registrar": registrar,
            "upkeep_contract": upkeep_contract,
            "admin_address": admin_address,
            "gas_paid_by": "platform (0pnMatrx paymaster)",
            "non_custodial": True,
        }
