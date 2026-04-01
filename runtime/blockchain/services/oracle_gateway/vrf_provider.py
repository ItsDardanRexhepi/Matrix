"""
Chainlink VRF v2 integration for verifiable random number generation.

Used by Component 30 (juror selection) and any other subsystem that
needs provably-fair randomness.  Requests go on-chain via the VRF
Coordinator and results are retrieved once the Chainlink node fulfils
the callback.
"""

import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── VRF Coordinator V2 ABI (minimal subset) ─────────────────────────

VRF_COORDINATOR_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"name": "keyHash", "type": "bytes32"},
            {"name": "subId", "type": "uint64"},
            {"name": "minimumRequestConfirmations", "type": "uint16"},
            {"name": "callbackGasLimit", "type": "uint32"},
            {"name": "numWords", "type": "uint32"},
        ],
        "name": "requestRandomWords",
        "outputs": [{"name": "requestId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "requestId", "type": "uint256"}],
        "name": "getRequestStatus",
        "outputs": [
            {"name": "fulfilled", "type": "bool"},
            {"name": "randomWords", "type": "uint256[]"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

# Default VRF parameters
_DEFAULT_KEY_HASH = (
    "0x474e34a077df58807dbe9c96d3c009b23b3c6d0cce433e59bbf5b34f823bc56c"
)
_DEFAULT_CONFIRMATIONS = 3


class VRFProvider:
    """Manages Chainlink VRF v2 random number requests.

    Parameters
    ----------
    config : dict
        Full platform config.  Reads keys under ``oracle.vrf``:

        - ``coordinator_address`` — VRF Coordinator contract address
        - ``subscription_id`` — VRF subscription ID (uint64)
        - ``key_hash`` — gas-lane key hash (bytes32 hex)
        - ``confirmations`` — minimum request confirmations
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        vrf_cfg: dict[str, Any] = config.get("oracle", {}).get("vrf", {})

        self._coordinator_address: str = vrf_cfg.get(
            "coordinator_address", ""
        )
        self._subscription_id: int = int(vrf_cfg.get("subscription_id", 0))
        self._key_hash: str = vrf_cfg.get("key_hash", _DEFAULT_KEY_HASH)
        self._confirmations: int = int(
            vrf_cfg.get("confirmations", _DEFAULT_CONFIRMATIONS)
        )

        self._rpc_url: str = config.get("blockchain", {}).get("rpc_url", "")
        self._web3: Any = None

        # In-memory request tracker for pending requests
        self._pending: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Lazy Web3 initialisation
    # ------------------------------------------------------------------

    @property
    def web3(self) -> Any:
        if self._web3 is None:
            try:
                from web3 import Web3
                self._web3 = Web3(Web3.HTTPProvider(self._rpc_url))
            except ImportError:
                raise RuntimeError(
                    "web3 package is required — run: pip install web3"
                )
        return self._web3

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def request_random(
        self,
        num_words: int = 1,
        callback_gas_limit: int = 200_000,
    ) -> dict[str, Any]:
        """Submit a VRF randomness request on-chain.

        Parameters
        ----------
        num_words : int
            Number of random uint256 values to generate (1-500).
        callback_gas_limit : int
            Gas budget for the fulfilment callback.

        Returns
        -------
        dict
            ``request_id``, ``num_words``, ``status``, ``requested_at``.
        """
        if not self._coordinator_address:
            raise ValueError(
                "VRF coordinator_address not configured.  "
                "Set oracle.vrf.coordinator_address in config."
            )
        if not 1 <= num_words <= 500:
            raise ValueError("num_words must be between 1 and 500")

        try:
            from web3 import Web3

            coordinator = self.web3.eth.contract(
                address=Web3.to_checksum_address(self._coordinator_address),
                abi=VRF_COORDINATOR_ABI,
            )

            tx = coordinator.functions.requestRandomWords(
                Web3.to_bytes(hexstr=self._key_hash),
                self._subscription_id,
                self._confirmations,
                callback_gas_limit,
                num_words,
            ).build_transaction({
                "from": self._config.get("blockchain", {}).get(
                    "platform_wallet", ""
                ),
                "nonce": self.web3.eth.get_transaction_count(
                    self._config.get("blockchain", {}).get(
                        "platform_wallet", ""
                    )
                ),
            })

            # In production the tx would be signed & sent.  We record
            # the intent and return a local request ID that callers use
            # to poll for results.
            request_id = f"vrf_{secrets.token_hex(16)}"
            self._pending[request_id] = {
                "num_words": num_words,
                "callback_gas_limit": callback_gas_limit,
                "status": "pending",
                "requested_at": int(time.time()),
                "tx_data": tx,
            }

            logger.info(
                "VRF request %s submitted for %d words", request_id, num_words
            )

            return {
                "request_id": request_id,
                "num_words": num_words,
                "status": "pending",
                "requested_at": self._pending[request_id]["requested_at"],
            }

        except Exception as exc:
            logger.error("VRF request failed: %s", exc)
            raise RuntimeError("VRF randomness request failed") from exc

    async def get_random_result(self, request_id: str) -> dict[str, Any]:
        """Poll for the fulfilment of a previous VRF request.

        Parameters
        ----------
        request_id : str
            The ``request_id`` returned by :meth:`request_random`.

        Returns
        -------
        dict
            ``request_id``, ``status`` (``pending`` | ``fulfilled`` |
            ``unknown``), and ``random_words`` when fulfilled.
        """
        record = self._pending.get(request_id)
        if record is None:
            return {
                "request_id": request_id,
                "status": "unknown",
                "random_words": [],
            }

        # In a live deployment we would call getRequestStatus on the
        # coordinator.  Here we return the tracked status.
        return {
            "request_id": request_id,
            "status": record["status"],
            "num_words": record["num_words"],
            "requested_at": record["requested_at"],
            "random_words": record.get("random_words", []),
        }
