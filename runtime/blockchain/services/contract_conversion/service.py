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

logger = logging.getLogger(__name__)


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

        self._parser = SourceParser(config)
        self._generator = ContractGenerator(config)
        self._tier_manager = TierManager(config)
        self._artist_classifier = ArtistClassifier(config)
        self._revenue_enforcer = RevenueEnforcer(config)

        logger.info("ContractConversionService initialised.")

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

            elapsed_ms = round((time.monotonic() - start) * 1000, 2)

            result: dict[str, Any] = {
                "status": "success",
                "generated_source": generated,
                "contract_name": ir.get("contract_name", ""),
                "target_chain": target_chain,
                "tier": tier_info,
                "artist_info": artist_info,
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

            logger.info(
                "Conversion complete: contract=%s tier=%s chain=%s time=%.1fms",
                ir.get("contract_name"), tier_info["tier"],
                target_chain, elapsed_ms,
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
