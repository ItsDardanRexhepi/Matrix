"""
Decentralized compute (Akash, Gensyn, Render) and DePIN device rentals.

This service wires three operations to their REAL provider integrations:

- ``submit_compute_job``   -> Akash Network REST API (deploy a workload).
- ``rent_device``          -> DePIN provider REST API (Render / Akash provider
                              lease), reserving a GPU/compute device.
- ``claim_compute_reward`` -> on-chain DePIN rental/reward contract claim
                              (platform-level, gas-sponsored) OR provider
                              payout API.

Integration model
------------------
Decentralized compute is PRIMARILY an off-chain protocol API: the provider
(Akash, Render, Gensyn) exposes a documented REST endpoint that the platform
calls with a provider API key. The service reads its own config block::

    config["services"]["compute"] = {
        "endpoint":          "https://api.akash.network",   # provider REST base
        "api_key":           "<provider API key>",
        "provider":          "akash" | "render" | "gensyn",
        "rental_contract":   "0x...",   # optional on-chain DePIN rental contract
    }

Credential gating
-----------------
Each method gates FIRST on the exact credential it needs (endpoint / api_key
for the REST path, or ``rental_contract`` + a live Web3 connection for the
on-chain path). When the credential is missing or a placeholder it returns the
canonical ``not_deployed_response`` naming the EXACT missing config key so
``CREDENTIALS_NEEDED.md`` can map it. Only when fully configured does it perform
the REAL protocol call.

Non-custodial
-------------
The REST calls submit/rent compute against the PLATFORM's provider account
(provider API key) — no user wallet funds are ever moved server-side. The
on-chain reward claim is signed ONLY with the platform paymaster account via
``Web3Manager.send_transaction`` (gas-sponsored, platform-level). User value is
never custodied or signed for here.
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

# Minimal ABI for a generic DePIN rental/reward contract claim. UNVERIFIED:
# the concrete DePIN rental contract (Render/Akash-on-Base, Gensyn) ABI is
# deployment-specific; this single-function signature is the canonical
# "claim(address)" shape and must be confirmed against the deployed contract.
_REWARD_CLAIM_ABI = [
    {
        "name": "claimRewards",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "recipient", "type": "address"}],
        "outputs": [{"name": "amount", "type": "uint256"}],
    }
]


class DecentralizedComputeService:
    """Decentralized compute (Akash, Gensyn, Render) and DePIN device rentals."""

    service_name = "compute"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── config helpers ───────────────────────────────────────────────

    def _cfg(self) -> dict:
        """Return this service's own config block (``services.compute``)."""
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    @staticmethod
    def _provider_name(cfg: dict) -> str:
        return str(cfg.get("provider", "akash") or "akash")

    # ── REST helper ──────────────────────────────────────────────────

    async def _provider_request(
        self,
        method: str,
        endpoint: str,
        api_key: str,
        path: str,
        json_body: dict | None = None,
    ) -> dict:
        """Call the provider's REST API. Imports httpx lazily.

        Returns a dict; on transport/parse failure returns an ``error`` dict so
        callers never raise from a network hiccup.
        """
        # The fault's kind travels with the error, so the caller can tell a
        # request that never left this process from one that was out when the
        # fault came. The classifier is creator_platforms' — the one place
        # that question is answered in this tree — rather than a second copy.
        from runtime.blockchain.services.creator_platforms._guards import (
            classify_transport_fault,
        )

        try:
            import httpx  # lazy — heavy/optional dependency
        except ImportError:
            return {
                "status": "error",
                "error": "httpx not installed — cannot reach provider REST API",
                "fault": "not_sent",
            }

        url = endpoint.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method, url, headers=headers, json=json_body
                )
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw": resp.text}
            return {
                "http_status": resp.status_code,
                "ok": resp.is_success,
                "response": payload,
            }
        except Exception as exc:  # noqa: BLE001 — surface, never raise
            logger.warning("compute provider request failed: %s", exc)
            return {"status": "error", "error": str(exc),
                    "fault": classify_transport_fault(exc)}

    def _provider_refused(
        self, reply: Any, *, method: str, endpoint: str, provider: str,
    ) -> dict | None:
        """What the provider's reply establishes when it did NOT accept the
        request, or None when it did.

        THE REPLY WAS NOT READ. Each of the three provider calls below answered
        with its word — "submitted", "reserved", "claim_submitted" — whatever
        `_provider_request` came back with, so a connection refused, a 401 for
        a bad key or a 503 was reported as a job submitted, with the provider's
        own error tucked under `provider_result`, which no reader looks
        through. The dispatcher recorded a broadcast for a request the provider
        had refused.

        Three answers, `classify_transport_fault`'s. The request never left
        this process, or the provider answered 4xx: a refusal, in the
        provider's words. The provider answered 5xx, or the fault came after
        the request was out: unknown — not a refusal and not a submission —
        and it is recorded the way the dispatcher records a transaction that
        went out unconfirmed, `broadcast: True` with `settled: False`, because
        that is the one record for "sent, and nobody knows"; there is no hash
        here, and the record says so. Accepted: None, and the caller says its
        word, which the gate reads as a broadcast, as it always did.
        """
        base = {
            "service": self.service_name, "method": method,
            "provider": provider, "endpoint": endpoint,
        }
        if not isinstance(reply, dict):
            return {**base, "status": "error", "provider_result": reply,
                    "error": f"provider reply was not an object: {reply!r}"[:300]}
        if reply.get("ok") is True:
            return None
        http = reply.get("http_status")
        if (isinstance(http, int) and http >= 500) or reply.get("fault") == "unknown":
            answered = f"HTTP {http}" if isinstance(http, int) else "a fault after the request was out"
            return {
                **base, "status": "pending", "settled": False, "value_moved": None,
                "broadcast": True, "tx_hash": None, "provider_result": reply,
                "disclosure": (
                    "The request reached the provider and its answer does not "
                    f"say whether it was accepted ({answered}). This is NOT a "
                    "refusal and NOT a submission; there is no transaction hash "
                    "to check, so ask the provider before retrying."
                ),
            }
        if isinstance(http, int):
            detail = f"provider answered HTTP {http}: {reply.get('response')!r}"[:300]
        else:
            detail = str(reply.get("error") or "provider request failed")
        return {**base, "status": "error", "error": detail, "provider_result": reply}

    # ── submit_compute_job ───────────────────────────────────────────

    async def submit_compute_job(self, **params: Any) -> dict:
        """Submit a compute job to the configured provider's REST API (Akash).

        Off-chain protocol API. Requires ``services.compute.endpoint`` and
        ``services.compute.api_key``. Operates on the PLATFORM provider account
        (no user funds moved).

        Params: ``manifest``/``sdl`` (deployment spec), ``image``, ``cpu``,
        ``memory``, ``gpu`` — passed through to the provider deployment body.
        """
        cfg = self._cfg()
        endpoint = cfg.get("endpoint", "")
        api_key = cfg.get("api_key", "")
        provider = self._provider_name(cfg)

        if is_placeholder_value(endpoint):
            return not_deployed_response(self.service_name, extra={
                "method": "submit_compute_job",
                "missing": "services.compute.endpoint",
                "protocol": f"{provider} (decentralized compute REST API)",
            })
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "submit_compute_job",
                "missing": "services.compute.api_key",
                "protocol": f"{provider} (decentralized compute REST API)",
            })

        # REAL provider deployment call.
        # UNVERIFIED: the exact deployments path/body is provider-specific.
        # Akash console-api uses POST /v1/deployments with an SDL/manifest body;
        # confirm the path for the configured provider before production.
        deployment_body = {
            "sdl": params.get("sdl") or params.get("manifest"),
            "image": params.get("image"),
            "resources": {
                "cpu": params.get("cpu"),
                "memory": params.get("memory"),
                "gpu": params.get("gpu"),
            },
        }
        result = await self._provider_request(
            "POST", endpoint, api_key,
            path="/v1/deployments",
            json_body=deployment_body,
        )
        refused = self._provider_refused(
            result, method="submit_compute_job", provider=provider,
            endpoint=endpoint.rstrip("/") + "/v1/deployments",
        )
        if refused is not None:
            return refused
        return {
            "status": "submitted",
            "service": self.service_name,
            "method": "submit_compute_job",
            "provider": provider,
            "endpoint": endpoint.rstrip("/") + "/v1/deployments",
            "verification": "UNVERIFIED — requires live provider account + testnet",
            "provider_result": result,
        }

    # ── rent_device ──────────────────────────────────────────────────

    async def rent_device(self, **params: Any) -> dict:
        """Rent a DePIN compute/GPU device via the provider REST API.

        Off-chain protocol API. Requires ``services.compute.endpoint`` and
        ``services.compute.api_key``. The lease is reserved against the PLATFORM
        provider account — no user wallet funds are moved server-side.

        Params: ``device_type``/``gpu_model``, ``duration_hours``, ``region``,
        ``max_price``.
        """
        cfg = self._cfg()
        endpoint = cfg.get("endpoint", "")
        api_key = cfg.get("api_key", "")
        provider = self._provider_name(cfg)

        if is_placeholder_value(endpoint):
            return not_deployed_response(self.service_name, extra={
                "method": "rent_device",
                "missing": "services.compute.endpoint",
                "protocol": f"{provider} (DePIN device rental REST API)",
            })
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "rent_device",
                "missing": "services.compute.api_key",
                "protocol": f"{provider} (DePIN device rental REST API)",
            })

        # REAL provider lease/reservation call.
        # UNVERIFIED: the exact lease path/body is provider-specific (Akash uses
        # /v1/leases on a bid; Render exposes a job/reservation endpoint).
        lease_body = {
            "device_type": params.get("device_type") or params.get("gpu_model"),
            "duration_hours": params.get("duration_hours"),
            "region": params.get("region"),
            "max_price": params.get("max_price"),
        }
        result = await self._provider_request(
            "POST", endpoint, api_key,
            path="/v1/leases",
            json_body=lease_body,
        )
        refused = self._provider_refused(
            result, method="rent_device", provider=provider,
            endpoint=endpoint.rstrip("/") + "/v1/leases",
        )
        if refused is not None:
            return refused
        return {
            "status": "reserved",
            "service": self.service_name,
            "method": "rent_device",
            "provider": provider,
            "endpoint": endpoint.rstrip("/") + "/v1/leases",
            "verification": "UNVERIFIED — requires live provider account + testnet",
            "provider_result": result,
        }

    # ── claim_compute_reward ─────────────────────────────────────────

    async def claim_compute_reward(self, **params: Any) -> dict:
        """Claim accrued compute/DePIN rewards.

        Two real paths, gated by config:

        1. On-chain DePIN rental/reward contract claim. Requires
           ``services.compute.rental_contract`` + a live Web3 connection. Signed
           ONLY with the platform paymaster account (gas-sponsored,
           platform-level) — never a user key.
        2. Off-chain provider payout API. Requires ``services.compute.endpoint``
           + ``services.compute.api_key``.

        If neither credential set is configured, returns CREDENTIAL-GATED naming
        the on-chain contract key (the canonical DePIN reward path).

        Params: ``recipient`` (the platform reward recipient address).
        """
        cfg = self._cfg()
        rental_contract = cfg.get("rental_contract", "")
        endpoint = cfg.get("endpoint", "")
        api_key = cfg.get("api_key", "")
        provider = self._provider_name(cfg)

        # ── Path 1: on-chain DePIN rental contract claim (platform-level) ──
        if not is_placeholder_value(rental_contract):
            if not self._web3.available:
                return not_deployed_response(self.service_name, extra={
                    "method": "claim_compute_reward",
                    "missing": "blockchain.rpc_url (RPC unreachable for on-chain claim)",
                    "protocol": f"{provider} DePIN rental/reward contract",
                })
            # Recipient defaults to the platform wallet; never a user key.
            recipient = params.get("recipient") or self._web3.platform_wallet
            if is_placeholder_value(recipient):
                return not_deployed_response(self.service_name, extra={
                    "method": "claim_compute_reward",
                    "missing": "blockchain.platform_wallet (reward recipient)",
                    "protocol": f"{provider} DePIN rental/reward contract",
                })
            try:
                contract = self._web3.load_contract(rental_contract, _REWARD_CLAIM_ABI)
                checksummed = self._web3.w3.to_checksum_address(recipient)
                tx = contract.functions.claimRewards(checksummed).build_transaction(
                    {"from": self._web3.platform_wallet or checksummed}
                )
                tx_hash = await self._web3.send_transaction(tx)
                return {
                    "status": "claim_submitted",
                    "service": self.service_name,
                    "method": "claim_compute_reward",
                    "provider": provider,
                    "path": "onchain",
                    "rental_contract": rental_contract,
                    "recipient": recipient,
                    "tx_hash": tx_hash,
                    "explorer_url": self._web3.explorer_url(tx_hash),
                    "signed_by": "platform paymaster (gas-sponsored, non-custodial)",
                    "verification": "UNVERIFIED — requires deployed rental contract + testnet",
                }
            except Exception as exc:  # noqa: BLE001
                logger.error("claim_compute_reward on-chain claim failed: %s", exc)
                return not_deployed_response(self.service_name, extra={
                    "method": "claim_compute_reward",
                    "missing": "services.compute.rental_contract (valid deployed reward contract)",
                    "protocol": f"{provider} DePIN rental/reward contract",
                    "error": str(exc),
                })

        # ── Path 2: off-chain provider payout API ──
        if not is_placeholder_value(endpoint) and not is_placeholder_value(api_key):
            result = await self._provider_request(
                "POST", endpoint, api_key,
                path="/v1/rewards/claim",
                json_body={"recipient": params.get("recipient")},
            )
            refused = self._provider_refused(
                result, method="claim_compute_reward", provider=provider,
                endpoint=endpoint.rstrip("/") + "/v1/rewards/claim",
            )
            if refused is not None:
                return refused
            return {
                "status": "claim_submitted",
                "service": self.service_name,
                "method": "claim_compute_reward",
                "provider": provider,
                "path": "provider_api",
                "endpoint": endpoint.rstrip("/") + "/v1/rewards/claim",
                "verification": "UNVERIFIED — requires live provider account + testnet",
                "provider_result": result,
            }

        # ── Neither credential set configured ──
        return not_deployed_response(self.service_name, extra={
            "method": "claim_compute_reward",
            "missing": "services.compute.rental_contract (on-chain) OR services.compute.endpoint + services.compute.api_key (provider payout API)",
            "protocol": f"{provider} DePIN rental/reward claim",
        })
