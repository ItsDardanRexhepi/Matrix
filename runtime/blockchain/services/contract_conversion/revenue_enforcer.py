"""
RevenueEnforcer — inject platform fee collection logic into generated
Solidity contracts.

The fee recipient address is always read from config (``platform_wallet``),
never hardcoded.  Supports both ETH-transfer and ERC-20-transfer fee
patterns.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Template snippets injected into contracts
_FEE_STATE_VARS = """\
    // 0pnMatrx platform fee configuration
    address public platformFeeRecipient;
    uint256 public platformFeeBps;
"""

_FEE_CONSTRUCTOR_INIT = """\
        platformFeeRecipient = {fee_recipient};
        platformFeeBps = {fee_bps};
"""

_FEE_MODIFIER = """\
    modifier collectPlatformFee(uint256 amount) {{
        uint256 fee = (amount * platformFeeBps) / 10000;
        if (fee > 0) {{
            payable(platformFeeRecipient).transfer(fee);
        }}
        _;
    }}
"""

_ERC20_FEE_FUNCTION = """\
    function _collectERC20Fee(address token, uint256 amount) internal returns (uint256) {{
        uint256 fee = (amount * platformFeeBps) / 10000;
        if (fee > 0) {{
            IERC20(token).transfer(platformFeeRecipient, fee);
        }}
        return amount - fee;
    }}
"""

_SET_FEE_RECIPIENT = """\
    function setPlatformFeeRecipient(address newRecipient) external onlyOwner {{
        require(newRecipient != address(0), "Zero address");
        platformFeeRecipient = newRecipient;
    }}

    function setPlatformFeeBps(uint256 newBps) external onlyOwner {{
        require(newBps <= 1000, "Fee too high");
        platformFeeBps = newBps;
    }}
"""


class RevenueEnforcer:
    """Inject platform fee collection logic into Solidity source.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``blockchain.platform_wallet`` — fee recipient address
        - ``blockchain.platform_fee_bps`` — fee in basis points (default 250 = 2.5%)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        bc = config.get("blockchain", {})
        self._platform_wallet: str = bc.get("platform_wallet", "")
        self._fee_bps: int = int(bc.get("platform_fee_bps", 250))

    def inject_fee_logic(
        self,
        source: str,
        fee_recipient: str | None = None,
    ) -> str:
        """Inject platform fee collection into Solidity *source*.

        The method:
        1. Adds ``platformFeeRecipient`` and ``platformFeeBps`` state vars.
        2. Adds the ``collectPlatformFee`` modifier.
        3. Adds ``_collectERC20Fee`` internal helper.
        4. Adds owner-only setters for recipient and bps.
        5. Initialises fee recipient in the constructor.
        6. Applies ``collectPlatformFee`` to all ``payable`` functions.

        Parameters
        ----------
        source : str
            Complete Solidity source code.
        fee_recipient : str, optional
            Override fee recipient address.  Defaults to
            ``config["blockchain"]["platform_wallet"]``.

        Returns
        -------
        str
            Modified Solidity source with fee logic injected.

        Raises
        ------
        ValueError
            If no fee recipient is available from config or argument.
        """
        recipient = fee_recipient or self._platform_wallet
        if not recipient:
            raise ValueError(
                "No fee recipient available. Set blockchain.platform_wallet "
                "in config or pass fee_recipient explicitly."
            )

        # 1. Inject state variables after contract opening brace
        source = self._inject_after_contract_open(source, _FEE_STATE_VARS)

        # 2. Inject modifier
        source = self._inject_before_first_function(source, _FEE_MODIFIER)

        # 3. Inject ERC-20 fee helper
        source = self._inject_before_closing_brace(source, _ERC20_FEE_FUNCTION)

        # 4. Inject setters
        source = self._inject_before_closing_brace(source, _SET_FEE_RECIPIENT)

        # 5. Initialise in constructor
        init_code = _FEE_CONSTRUCTOR_INIT.format(
            fee_recipient=self._format_address(recipient),
            fee_bps=self._fee_bps,
        )
        source = self._inject_into_constructor(source, init_code)

        # 6. Apply modifier to payable functions
        source = self._apply_modifier_to_payable(source)

        logger.info(
            "Injected platform fee logic: recipient=%s bps=%d",
            recipient, self._fee_bps,
        )
        return source

    # ── Injection helpers ─────────────────────────────────────────────

    @staticmethod
    def _inject_after_contract_open(source: str, snippet: str) -> str:
        """Insert *snippet* right after the first ``contract ... {``."""
        match = re.search(r"(contract\s+\w+[^{]*\{)", source)
        if match:
            pos = match.end()
            return source[:pos] + "\n" + snippet + source[pos:]
        return source

    @staticmethod
    def _inject_before_first_function(source: str, snippet: str) -> str:
        """Insert *snippet* before the first ``function`` keyword."""
        match = re.search(r"(\n\s*function\s)", source)
        if match:
            pos = match.start()
            return source[:pos] + "\n" + snippet + source[pos:]
        # If no function found, insert before closing brace
        return RevenueEnforcer._inject_before_closing_brace(source, snippet)

    @staticmethod
    def _inject_before_closing_brace(source: str, snippet: str) -> str:
        """Insert *snippet* before the final closing brace."""
        last_brace = source.rfind("}")
        if last_brace >= 0:
            return source[:last_brace] + "\n" + snippet + "\n" + source[last_brace:]
        return source + "\n" + snippet

    @staticmethod
    def _inject_into_constructor(source: str, init_code: str) -> str:
        """Insert *init_code* at the start of the constructor body."""
        match = re.search(r"(constructor\s*\([^)]*\)[^{]*\{)", source)
        if match:
            pos = match.end()
            return source[:pos] + "\n" + init_code + source[pos:]
        # No constructor found — create one
        contract_match = re.search(r"(contract\s+\w+[^{]*\{)", source)
        if contract_match:
            pos = contract_match.end()
            constructor = f"\n    constructor() {{\n{init_code}    }}\n"
            return source[:pos] + constructor + source[pos:]
        return source

    @staticmethod
    def _apply_modifier_to_payable(source: str) -> str:
        """Add ``collectPlatformFee(msg.value)`` to payable functions."""
        pattern = re.compile(
            r"(function\s+\w+\s*\([^)]*\)\s+(?:\w+\s+)*)(payable)(\s+)"
        )
        def replacer(m: re.Match) -> str:
            # Only add if not already present
            full_line = m.group(0)
            if "collectPlatformFee" in full_line:
                return full_line
            return f"{m.group(1)}{m.group(2)} collectPlatformFee(msg.value){m.group(3)}"
        return pattern.sub(replacer, source)

    @staticmethod
    def _format_address(address: str) -> str:
        """Ensure address is properly formatted for Solidity."""
        if address.startswith("0x"):
            return address
        return f"0x{address}"
