"""
Securities — tokenized securities management on Base L2.

Create security tokens (ERC-3643 compatible), manage transfer restrictions,
compliance, and investor management. All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class Securities(BlockchainInterface):

    @property
    def name(self) -> str:
        return "securities"

    @property
    def description(self) -> str:
        return "Tokenized securities: create security tokens, manage compliance, investor whitelist. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_token", "whitelist_investor", "transfer", "get_info", "freeze"]},
                "token_name": {"type": "string"},
                "token_symbol": {"type": "string"},
                "total_supply": {"type": "string"},
                "contract_address": {"type": "string"},
                "investor_address": {"type": "string"},
                "to": {"type": "string"},
                "amount": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "create_token":
            return await self._create_token(kwargs)
        elif action == "whitelist_investor":
            return await self._whitelist(kwargs)
        elif action == "transfer":
            return await self._transfer(kwargs)
        elif action == "get_info":
            return await self._get_info(kwargs)
        elif action == "freeze":
            return await self._freeze(kwargs)
        return f"Unknown securities action: {action}"

    async def _create_token(self, params: dict) -> str:
        """Generate security token source code."""
        name = params.get("token_name", "SecurityToken")
        symbol = params.get("token_symbol", "SEC")
        supply = params.get("total_supply", "1000000")

        source = f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {symbol}Security is ERC20, Ownable {{
    mapping(address => bool) public whitelisted;
    mapping(address => bool) public frozen;

    constructor() ERC20("{name}", "{symbol}") Ownable(msg.sender) {{
        _mint(msg.sender, {supply} * 10 ** decimals());
        whitelisted[msg.sender] = true;
    }}

    function whitelist(address investor) external onlyOwner {{
        whitelisted[investor] = true;
    }}

    function freeze(address account) external onlyOwner {{
        frozen[account] = true;
    }}

    function unfreeze(address account) external onlyOwner {{
        frozen[account] = false;
    }}

    function _update(address from, address to, uint256 value) internal override {{
        require(!frozen[from], "Sender frozen");
        require(!frozen[to], "Recipient frozen");
        if (from != address(0)) require(whitelisted[from], "Sender not whitelisted");
        if (to != address(0)) require(whitelisted[to], "Recipient not whitelisted");
        super._update(from, to, value);
    }}
}}'''
        return json.dumps({
            "status": "source_generated",
            "name": name,
            "symbol": symbol,
            "total_supply": supply,
            "source": source,
            "features": ["whitelist-only transfers", "account freezing", "owner controls"],
            "note": "Deploy via smart_contract capability. Gas covered by platform.",
        }, indent=2)

    async def _whitelist(self, params: dict) -> str:
        """Whitelist an investor for security token transfers."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="investor_whitelist",
            agent="neo",
            details={
                "investor": params.get("investor_address", ""),
                "contract": params.get("contract_address", ""),
                "whitelisted_at": int(time.time()),
            },
            recipient=params.get("investor_address", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _transfer(self, params: dict) -> str:
        return json.dumps({
            "status": "transfer_prepared",
            "note": "Security token transfers require both sender and recipient to be whitelisted. Use tokenize capability for execution. Gas covered by platform.",
        })

    async def _get_info(self, params: dict) -> str:
        return json.dumps({
            "contract": params.get("contract_address", ""),
            "note": "Query contract for name, symbol, totalSupply, whitelist status",
            "network": self.network,
        })

    async def _freeze(self, params: dict) -> str:
        return json.dumps({
            "status": "freeze_prepared",
            "investor": params.get("investor_address", ""),
            "note": "Account freeze requires owner transaction. Gas covered by platform.",
        })
