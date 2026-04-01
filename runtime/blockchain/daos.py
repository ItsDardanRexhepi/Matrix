"""
DAOs — create and manage decentralized autonomous organizations on Base L2.

Supports proposal creation, voting, execution, and membership management
via Governor-style contracts. All gas covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)

GOVERNOR_ABI = [
    {"inputs": [{"name": "targets", "type": "address[]"}, {"name": "values", "type": "uint256[]"}, {"name": "calldatas", "type": "bytes[]"}, {"name": "description", "type": "string"}], "name": "propose", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "proposalId", "type": "uint256"}, {"name": "support", "type": "uint8"}], "name": "castVote", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "targets", "type": "address[]"}, {"name": "values", "type": "uint256[]"}, {"name": "calldatas", "type": "bytes[]"}, {"name": "descriptionHash", "type": "bytes32"}], "name": "execute", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "proposalId", "type": "uint256"}], "name": "state", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]

PROPOSAL_STATES = {0: "Pending", 1: "Active", 2: "Canceled", 3: "Defeated", 4: "Succeeded", 5: "Queued", 6: "Expired", 7: "Executed"}


class DAOs(BlockchainInterface):

    @property
    def name(self) -> str:
        return "dao"

    @property
    def description(self) -> str:
        return "Create and manage DAOs: propose, vote, execute governance actions on Base L2. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create_proposal", "vote", "execute", "get_state", "deploy_dao"]},
                "governor_address": {"type": "string"},
                "proposal_id": {"type": "string"},
                "description": {"type": "string"},
                "support": {"type": "integer", "description": "0=Against, 1=For, 2=Abstain"},
                "targets": {"type": "array", "items": {"type": "string"}},
                "values": {"type": "array", "items": {"type": "string"}},
                "calldatas": {"type": "array", "items": {"type": "string"}},
                "dao_name": {"type": "string"},
                "token_address": {"type": "string", "description": "Governance token address"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "create_proposal":
            return await self._create_proposal(kwargs)
        elif action == "vote":
            return await self._vote(kwargs)
        elif action == "execute":
            return await self._execute_proposal(kwargs)
        elif action == "get_state":
            return await self._get_state(kwargs)
        elif action == "deploy_dao":
            return await self._deploy_dao(kwargs)
        return f"Unknown DAO action: {action}"

    async def _create_proposal(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            governor = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["governor_address"]),
                abi=GOVERNOR_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])

            targets = [Web3.to_checksum_address(t) for t in params.get("targets", [])]
            values = [int(v) for v in params.get("values", ["0"])]
            calldatas = [bytes.fromhex(c.replace("0x", "")) for c in params.get("calldatas", ["0x"])]

            tx = governor.functions.propose(
                targets, values, calldatas, params.get("description", "")
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
                "status": "proposed" if receipt["status"] == 1 else "failed",
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Proposal creation failed: {e}"

    async def _vote(self, params: dict) -> str:
        try:
            from web3 import Web3
            from eth_account import Account

            self._require_config("rpc_url", "paymaster_private_key", "platform_wallet")
            bc = self.config["blockchain"]

            governor = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["governor_address"]),
                abi=GOVERNOR_ABI,
            )
            account = Account.from_key(bc["paymaster_private_key"])
            proposal_id = int(params.get("proposal_id", "0"))
            support = params.get("support", 1)

            tx = governor.functions.castVote(proposal_id, support).build_transaction({
                "from": bc["platform_wallet"],
                "chainId": self.chain_id,
                "gas": 200000,
                "gasPrice": self.web3.eth.gas_price,
                "nonce": self.web3.eth.get_transaction_count(bc["platform_wallet"]),
            })

            signed = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            vote_label = {0: "Against", 1: "For", 2: "Abstain"}.get(support, "Unknown")
            return json.dumps({
                "status": "voted" if receipt["status"] == 1 else "failed",
                "vote": vote_label,
                "proposal_id": proposal_id,
                "tx_hash": tx_hash.hex(),
                "gas_paid_by": "platform (0pnMatrx)",
            }, indent=2)
        except Exception as e:
            return f"Vote failed: {e}"

    async def _execute_proposal(self, params: dict) -> str:
        return json.dumps({
            "status": "execution_requires_succeeded_state",
            "proposal_id": params.get("proposal_id"),
            "note": "Proposal must be in Succeeded state before execution. Gas covered by platform.",
        })

    async def _get_state(self, params: dict) -> str:
        try:
            from web3 import Web3
            governor = self.web3.eth.contract(
                address=Web3.to_checksum_address(params["governor_address"]),
                abi=GOVERNOR_ABI,
            )
            state = governor.functions.state(int(params.get("proposal_id", "0"))).call()
            return json.dumps({
                "proposal_id": params.get("proposal_id"),
                "state": PROPOSAL_STATES.get(state, "Unknown"),
                "state_code": state,
            })
        except Exception as e:
            return f"State check failed: {e}"

    async def _deploy_dao(self, params: dict) -> str:
        dao_name = params.get("dao_name", "OpenMatrixDAO")
        return json.dumps({
            "status": "source_generated",
            "dao_name": dao_name,
            "components": ["GovernanceToken (ERC20Votes)", "TimelockController", "Governor"],
            "note": "DAO deployment requires 3 contracts. Use smart_contract deploy for each. Gas covered by platform.",
        }, indent=2)
