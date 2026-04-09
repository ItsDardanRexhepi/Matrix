"""
ContractConversionService — orchestrate the full contract conversion
pipeline: parse source, classify complexity, detect creative patterns,
generate optimised Solidity, and inject platform fees.

This is the single entry point for all contract conversions on 0pnMatrx.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.services.contract_conversion.artist_classifier import ArtistClassifier
from runtime.blockchain.services.contract_conversion.generator import ContractGenerator
from runtime.blockchain.services.contract_conversion.parser import SourceParser
from runtime.blockchain.services.contract_conversion.revenue_enforcer import RevenueEnforcer
from runtime.blockchain.services.contract_conversion.templates import get_template, list_templates
from runtime.blockchain.services.contract_conversion.tier_manager import TierManager
from runtime.blockchain.web3_manager import Web3Manager
from runtime.security.audit import ContractAuditor

logger = logging.getLogger(__name__)

_SOLC_VERSION = "0.8.20"
_SOLC_INSTALLED = False


class ContractConversionService:
    """Orchestrate the full smart-contract conversion pipeline.

    Config keys used:
        - ``blockchain.platform_wallet`` — fee recipient
        - ``blockchain.platform_fee_bps`` — platform fee basis points
        - ``conversion.tier_overrides`` — per-tier fee overrides
        - ``conversion.custom_threshold`` — custom-tier boundary
        - ``conversion.creative_threshold`` — artist detection threshold
        - ``conversion.default_license`` — SPDX license identifier
        - ``conversion.inject_fees`` — whether to auto-inject fees (default True)

    Parameters
    ----------
    config : dict
        Full platform configuration dictionary.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        conv_cfg = config.get("conversion", {})
        self._inject_fees: bool = conv_cfg.get("inject_fees", True)
        self._auto_deploy: bool = conv_cfg.get("auto_deploy", False)

        self._parser = SourceParser(config)
        self._generator = ContractGenerator(config)
        self._tier_manager = TierManager(config)
        self._artist_classifier = ArtistClassifier(config)
        self._revenue_enforcer = RevenueEnforcer(config)
        self._auditor = ContractAuditor(config)
        self._web3 = Web3Manager.get_shared(config)

        logger.info("ContractConversionService initialised.")

    def _ensure_solc(self) -> bool:
        """Make sure solc is installed for the configured version. Returns True on success."""
        global _SOLC_INSTALLED
        if _SOLC_INSTALLED:
            return True
        try:
            import solcx  # type: ignore
        except ImportError:
            logger.warning("py-solc-x not installed; on-chain deployment unavailable")
            return False
        try:
            installed = [str(v) for v in solcx.get_installed_solc_versions()]
            if _SOLC_VERSION not in installed:
                logger.info("Installing solc %s ...", _SOLC_VERSION)
                solcx.install_solc(_SOLC_VERSION)
            solcx.set_solc_version(_SOLC_VERSION)
            _SOLC_INSTALLED = True
            return True
        except Exception as exc:
            logger.warning("Failed to prepare solc %s: %s", _SOLC_VERSION, exc)
            return False

    async def _compile_and_deploy(
        self, solidity_source: str, contract_name: str
    ) -> dict[str, Any]:
        """Compile *solidity_source* via solcx and deploy via Web3Manager.

        Returns a dict describing the on-chain deployment, or
        ``{"status": "error", ...}`` on failure. Never raises.
        """
        if not self._web3.available:
            return {
                "status": "skipped",
                "reason": "Web3Manager not available — set blockchain.rpc_url",
            }
        if not self._ensure_solc():
            return {
                "status": "skipped",
                "reason": "py-solc-x not installed or solc unavailable",
            }
        try:
            import solcx  # type: ignore
            compiled = solcx.compile_source(
                solidity_source,
                output_values=["abi", "bin"],
                solc_version=_SOLC_VERSION,
            )
        except Exception as exc:
            logger.error("solc compilation failed: %s", exc)
            return {"status": "error", "stage": "compile", "error": str(exc)}

        # Pick the requested contract or the last compiled artifact
        artifact_key = None
        for key in compiled.keys():
            if key.endswith(f":{contract_name}"):
                artifact_key = key
                break
        if artifact_key is None:
            artifact_key = next(iter(compiled.keys()))
        artifact = compiled[artifact_key]
        abi = artifact.get("abi", [])
        bytecode = artifact.get("bin", "")
        if not bytecode:
            return {"status": "error", "stage": "compile", "error": "empty bytecode"}

        try:
            account = self._web3.get_account()
            w3 = self._web3.w3
            contract = w3.eth.contract(abi=abi, bytecode=bytecode)
            tx = contract.constructor().build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": self._web3.chain_id,
                "gasPrice": w3.eth.gas_price,
            })
            tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
            tx_hash = w3.eth.send_raw_transaction(raw)
            tx_hash_hex = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            return {
                "status": "deployed",
                "contract_address": getattr(receipt, "contractAddress", None),
                "tx_hash": tx_hash_hex,
                "block_number": getattr(receipt, "blockNumber", None),
                "explorer": self._web3.explorer_url(tx_hash_hex),
            }
        except Exception as exc:
            logger.error("On-chain deployment failed: %s", exc)
            return {"status": "error", "stage": "deploy", "error": str(exc)}

    async def convert(
        self,
        source_code: str,
        source_lang: str,
        target_chain: str = "base",
    ) -> dict[str, Any]:
        """Convert source code into optimised Solidity for *target_chain*.

        Pipeline steps:
        1. Parse source into intermediate representation.
        2. Classify complexity tier and compute fee.
        3. Detect artist/creative patterns.
        4. Generate optimised Solidity.
        5. Inject platform fee logic (if configured).

        Parameters
        ----------
        source_code : str
            The smart-contract source code in *source_lang*.
        source_lang : str
            Source language: ``solidity``, ``vyper``, or ``pseudocode``.
        target_chain : str
            Target chain for optimisation (default ``base``).

        Returns
        -------
        dict
            Keys: ``status``, ``generated_source``, ``contract_name``,
            ``target_chain``, ``tier``, ``artist_info``, ``ir``,
            ``conversion_time_ms``, ``template_used``.
        """
        start = time.monotonic()

        try:
            # 1. Parse
            ir = self._parser.parse(source_code, source_lang)

            # 2. Classify
            tier_info = self._tier_manager.classify(source_code)

            # 3. Artist detection
            artist_info = self._artist_classifier.classify(source_code)

            # 4. If artist contract with a recommended template, consider
            #    using the template as a base (only for pseudocode or when
            #    the source is very simple)
            template_used: str | None = None
            if (
                artist_info.get("is_artist")
                and artist_info.get("recommended_template")
                and source_lang == "pseudocode"
                and tier_info["tier"] == "simple"
            ):
                template_name = artist_info["recommended_template"]
                template_source = get_template(template_name)
                if template_source:
                    # Fill template placeholders with IR data
                    contract_name = ir.get("contract_name", "ArtContract")
                    generated = template_source.replace("{{NAME}}", contract_name)
                    generated = generated.replace("{{SYMBOL}}", contract_name[:5].upper())
                    generated = generated.replace("{{MAX_SUPPLY}}", "10000")
                    template_used = template_name
                    logger.info(
                        "Used template '%s' for artist contract '%s'",
                        template_name, contract_name,
                    )
                else:
                    generated = self._generator.generate(ir, target_chain)
            else:
                # 4b. Generate from IR
                generated = self._generator.generate(ir, target_chain)

            # 5. Inject fees
            if self._inject_fees:
                try:
                    generated = self._revenue_enforcer.inject_fee_logic(generated)
                except ValueError as exc:
                    logger.warning(
                        "Fee injection skipped: %s", exc,
                    )

            # 6. Security audit
            audit_report = self._auditor.audit(generated, ir.get("contract_name", ""))

            elapsed_ms = round((time.monotonic() - start) * 1000, 2)

            result: dict[str, Any] = {
                "status": "success",
                "generated_source": generated,
                "contract_name": ir.get("contract_name", ""),
                "target_chain": target_chain,
                "tier": tier_info,
                "artist_info": artist_info,
                "audit": audit_report.to_dict(),
                "audit_passed": audit_report.passed,
                "ir": {
                    "functions": len(ir.get("functions", [])),
                    "state_variables": len(ir.get("state_variables", [])),
                    "events": len(ir.get("events", [])),
                    "modifiers": len(ir.get("modifiers", [])),
                    "structs": len(ir.get("structs", [])),
                    "inheritance": ir.get("inheritance", []),
                },
                "conversion_time_ms": elapsed_ms,
                "template_used": template_used,
            }

            # 7. On-chain deployment (only when explicitly enabled and audit passed)
            if self._auto_deploy:
                if not audit_report.passed:
                    result["deployment"] = {
                        "status": "blocked",
                        "reason": "Glasswing audit blocked deployment",
                        "audit": audit_report.to_dict(),
                    }
                else:
                    deployment = await self._compile_and_deploy(
                        generated, ir.get("contract_name", "")
                    )
                    result["deployment"] = deployment
                    # Best-effort EAS attestation on success
                    if deployment.get("status") == "deployed":
                        try:
                            from runtime.blockchain.eas_client import EASClient
                            eas = EASClient(self._config)
                            attest = await eas.attest(
                                action="contract_deployed",
                                agent="contract_conversion",
                                details={
                                    "contract_address": deployment.get("contract_address"),
                                    "tx_hash": deployment.get("tx_hash"),
                                },
                            )
                            result["attestation"] = attest
                        except Exception as exc:
                            logger.warning("EAS attestation skipped: %s", exc)

            logger.info(
                "Conversion complete: contract=%s tier=%s chain=%s time=%.1fms audit=%s",
                ir.get("contract_name"), tier_info["tier"],
                target_chain, elapsed_ms, "PASS" if audit_report.passed else "FAIL",
            )
            return result

        except Exception as exc:
            elapsed_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error("Conversion failed: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "conversion_time_ms": elapsed_ms,
            }

    async def estimate_cost(self, source_code: str) -> dict[str, Any]:
        """Estimate the conversion cost without performing the conversion.

        Returns
        -------
        dict
            Keys: ``tier``, ``fee_eth``, ``line_count``,
            ``complexity_score``, ``is_artist``, ``category``.
        """
        tier_info = self._tier_manager.classify(source_code)
        artist_info = self._artist_classifier.classify(source_code)

        fee_display = (
            f"{tier_info['fee_eth']:.4f} ETH"
            if tier_info["fee_eth"] >= 0
            else "negotiated (contact team)"
        )

        result = {
            "tier": tier_info["tier"],
            "fee_eth": tier_info["fee_eth"],
            "fee_display": fee_display,
            "line_count": tier_info["line_count"],
            "complexity_score": tier_info["complexity_score"],
            "complexity_factors": tier_info["complexity_factors"],
            "is_artist": artist_info["is_artist"],
            "category": artist_info.get("category"),
            "recommended_template": artist_info.get("recommended_template"),
        }

        logger.info(
            "Cost estimate: tier=%s fee=%s lines=%d",
            tier_info["tier"], fee_display, tier_info["line_count"],
        )
        return result

    def get_available_templates(self) -> list[str]:
        """Return the list of available contract templates."""
        return list_templates()

    def get_template_source(self, name: str) -> str | None:
        """Return the Solidity source for a named template."""
        return get_template(name)
