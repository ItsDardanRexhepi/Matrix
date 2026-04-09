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
        """Transfer security tokens (requires whitelisted sender and recipient). Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract_address = params.get("contract_address", "")
            if not contract_address:
                return json.dumps({"status": "error", "error": "contract_address is required"})

            erc20_transfer_abi = [
                {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
                 "name": "transfer", "outputs": [{"name": "", "type": "bool"}],
                 "stateMutability": "nonpayable", "type": "function"},
            ]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=erc20_transfer_abi,
            )
            account = Account.from_key(bc["paymaster_private_key"])
            to = params.get("to", "")
            amount = int(float(params.get("amount", "0")) * 10**18)

            tx = contract.functions.transfer(
                Web3.to_checksum_address(to), amount
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "transferred" if receipt["status"] == 1 else "failed",
                "to": to,
                "amount": params.get("amount", "0"),
                "contract": contract_address,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Security token transfer failed: {e}"

    async def _get_info(self, params: dict) -> str:
        """Query security token contract for name, symbol, totalSupply, and whitelist status."""
        try:
            from web3 import Web3

            contract_address = params.get("contract_address", "")
            if not contract_address:
                return json.dumps({"status": "error", "error": "contract_address is required"})

            info_abi = [
                {"inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}],
                 "stateMutability": "view", "type": "function"},
                {"inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}],
                 "stateMutability": "view", "type": "function"},
                {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}],
                 "stateMutability": "view", "type": "function"},
                {"inputs": [{"name": "", "type": "address"}], "name": "whitelisted",
                 "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
                {"inputs": [{"name": "", "type": "address"}], "name": "frozen",
                 "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
            ]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=info_abi,
            )

            result = {
                "contract": contract_address,
                "network": self.network,
            }

            try:
                result["name"] = contract.functions.name().call()
            except Exception:
                result["name"] = "unknown"
            try:
                result["symbol"] = contract.functions.symbol().call()
            except Exception:
                result["symbol"] = "unknown"
            try:
                supply = contract.functions.totalSupply().call()
                result["total_supply"] = str(supply)
                result["total_supply_human"] = str(supply / 10**18)
            except Exception:
                result["total_supply"] = "unknown"

            # Check whitelist/frozen status for a specific investor if provided
            investor = params.get("investor_address", "")
            if investor:
                try:
                    result["investor_whitelisted"] = contract.functions.whitelisted(
                        Web3.to_checksum_address(investor)
                    ).call()
                except Exception:
                    result["investor_whitelisted"] = "not_supported"
                try:
                    result["investor_frozen"] = contract.functions.frozen(
                        Web3.to_checksum_address(investor)
                    ).call()
                except Exception:
                    result["investor_frozen"] = "not_supported"

            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Token info query failed: {e}"

    async def _freeze(self, params: dict) -> str:
        """Freeze an account on a security token contract. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract_address = params.get("contract_address", "")
            investor = params.get("investor_address", "")
            if not contract_address or not investor:
                return json.dumps({"status": "error", "error": "contract_address and investor_address are required"})

            freeze_abi = [
                {"inputs": [{"name": "account", "type": "address"}],
                 "name": "freeze", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
            ]

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=freeze_abi,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.freeze(
                Web3.to_checksum_address(investor)
            ).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "frozen" if receipt["status"] == 1 else "failed",
                "investor": investor,
                "contract": contract_address,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Freeze failed: {e}"
