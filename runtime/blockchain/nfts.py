"""
NFTs — mint, transfer, and manage NFTs on Base L2.

Supports ERC-721 and ERC-1155 standards. All gas fees are covered by the platform.
"""

import json
import logging
from typing import Any

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

# Minimal ERC-721 ABI
ERC721_ABI = [
    {"inputs": [{"name": "to", "type": "address"}, {"name": "tokenId", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "tokenId", "type": "uint256"}], "name": "transferFrom", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "ownerOf", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "tokenId", "type": "uint256"}], "name": "tokenURI", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "to", "type": "address"}, {"name": "uri", "type": "string"}], "name": "safeMint", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]


class NFTs(BlockchainInterface):

    @property
    def name(self) -> str:
        return "nft"

    @property
    def description(self) -> str:
        return "Mint, transfer, and manage NFTs (ERC-721/ERC-1155) on Base L2. All gas fees covered by the platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["mint", "transfer", "get_owner", "get_uri", "balance", "deploy_collection"],
                    "description": "NFT action",
                },
                "contract_address": {"type": "string", "description": "NFT contract address"},
                "to": {"type": "string", "description": "Recipient address"},
                "from_address": {"type": "string", "description": "Sender address"},
                "token_id": {"type": "integer", "description": "Token ID"},
                "token_uri": {"type": "string", "description": "Token metadata URI"},
                "name": {"type": "string", "description": "Collection name (for deploy)"},
                "symbol": {"type": "string", "description": "Collection symbol (for deploy)"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        handlers = {
            "mint": self._mint,
            "transfer": self._transfer,
            "get_owner": self._get_owner,
            "get_uri": self._get_uri,
            "balance": self._balance,
            "deploy_collection": self._deploy_collection,
        }
        handler = handlers.get(action)
        if not handler:
            return f"Unknown NFT action: {action}"
        return await handler(kwargs)

    async def _mint(self, params: dict) -> str:
        """Mint an NFT. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract_address = params.get("contract_address", "")
            to = params.get("to", bc["platform_wallet"])
            token_uri = params.get("token_uri", "")

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=ERC721_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            # Try safeMint with URI first, fall back to mint with tokenId
            try:
                tx = contract.functions.safeMint(
                    Web3.to_checksum_address(to), token_uri
                ).build_transaction({
                    "from": bc["platform_wallet"],
                    "chainId": self.chain_id,
                    "gas": 500000,
                    "gasPrice": self.web3.eth.gas_price,
                    "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
                })
            except Exception:
                token_id = params.get("token_id", 1)
                tx = contract.functions.mint(
                    Web3.to_checksum_address(to), token_id
                ).build_transaction({
                    "from": bc["platform_wallet"],
                    "chainId": self.chain_id,
                    "gas": 500000,
                    "gasPrice": self.web3.eth.gas_price,
                    "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
                })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return json.dumps({
                "status": "minted" if receipt["status"] == 1 else "failed",
                "to": to,
                "contract": contract_address,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Mint failed: {e}"

    async def _transfer(self, params: dict) -> str:
        """Transfer an NFT. Gas covered by platform."""
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            contract_address = params.get("contract_address", "")
            from_addr = params.get("from_address", bc["platform_wallet"])
            to = params.get("to", "")
            token_id = params.get("token_id", 0)

            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(contract_address),
                abi=ERC721_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            tx = contract.functions.transferFrom(
                Web3.to_checksum_address(from_addr),
                Web3.to_checksum_address(to),
                token_id,
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
                "from": from_addr,
                "to": to,
                "token_id": token_id,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Transfer failed: {e}"

    async def _get_owner(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC721_ABI,
            )
            owner = contract.functions.ownerOf(params.get("token_id", 0)).call()
            return json.dumps({"owner": owner, "token_id": params.get("token_id", 0)})
        except Exception as e:
            return f"Owner lookup failed: {e}"

    async def _get_uri(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC721_ABI,
            )
            uri = contract.functions.tokenURI(params.get("token_id", 0)).call()
            return json.dumps({"token_uri": uri, "token_id": params.get("token_id", 0)})
        except Exception as e:
            return f"URI lookup failed: {e}"

    async def _balance(self, params: dict) -> str:
        try:
            from web3 import Web3
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["contract_address"]),
                abi=ERC721_ABI,
            )
            balance = contract.functions.balanceOf(
                Web3.to_checksum_address(params.get("to", self.platform_wallet))
            ).call()
            return json.dumps({"balance": balance})
        except Exception as e:
            return f"Balance check failed: {e}"

    async def _deploy_collection(self, params: dict) -> str:
        """Deploy a new ERC-721 collection. Gas covered by platform."""
        name = params.get("name", "0pnMatrx Collection")
        symbol = params.get("symbol", "MTRX")
        source = f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract {symbol}NFT is ERC721URIStorage, Ownable {{
    uint256 private _nextTokenId;

    constructor() ERC721("{name}", "{symbol}") Ownable(msg.sender) {{}}

    function safeMint(address to, string memory uri) public onlyOwner {{
        uint256 tokenId = _nextTokenId++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);
    }}
}}'''
        return json.dumps({
            "status": "source_generated",
            "name": name,
            "symbol": symbol,
            "source": source,
            "note": "Use smart_contract deploy action to deploy this contract. Gas covered by platform.",
        }, indent=2)
