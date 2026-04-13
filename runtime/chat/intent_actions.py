"""
Intent-to-Action Mapping — bridges natural language to platform_action calls.

Provides structured guidance so Trinity (or any agent) knows exactly which
action to invoke, what parameters are required, and how to ask for missing
information.

Covers all 219 actions across the full ACTION_MAP.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Master intent -> action mapping
# ---------------------------------------------------------------------------

INTENT_ACTION_MAP: dict[str, dict[str, Any]] = {

    # ===================================================================
    # Component 1 — Contract Conversion
    # ===================================================================

    "convert_contract": {
        "action_name": "convert_contract",
        "description": "Convert a smart contract from one language or chain to another.",
        "required_params": [
            {"name": "source_code", "type": "string", "description": "The source code of the contract to convert.", "example": "pragma solidity ^0.8.0; contract MyToken { ... }"},
            {"name": "source_lang", "type": "string", "description": "Language of the source contract (solidity, vyper, rust, move, etc.).", "example": "solidity"},
            {"name": "target_chain", "type": "string", "description": "Target blockchain to convert to (ethereum, solana, aptos, sui, etc.).", "example": "solana"},
        ],
        "optional_params": [
            {"name": "optimize", "type": "boolean", "description": "Apply gas optimizations during conversion.", "default": True},
        ],
        "keywords": ["convert contract", "translate contract", "port contract", "migrate contract", "change chain", "convert my contract", "move contract to"],
        "follow_up": "I can convert your contract. Could you share the source code, what language it's written in, and which blockchain you'd like it converted to?",
        "example_conversation": (
            "User: I want to convert my lease agreement contract to Solana\n"
            "Trinity: Sure! Could you paste or upload the contract source code? And what language is it currently written in — Solidity, Vyper, or something else?\n"
            "User: It's Solidity. [pastes code]\n"
            "Trinity: [calls platform_action with action='convert_contract', params={source_code: ..., source_lang: 'solidity', target_chain: 'solana'}]"
        ),
    },

    "deploy_contract": {
        "action_name": "deploy_contract",
        "description": "Deploy a smart contract to a blockchain.",
        "required_params": [
            {"name": "source_code", "type": "string", "description": "The source code of the contract to deploy.", "example": "pragma solidity ^0.8.0; contract MyToken { ... }"},
            {"name": "source_lang", "type": "string", "description": "Language of the contract (solidity, vyper, rust, move, etc.).", "example": "solidity"},
            {"name": "target_chain", "type": "string", "description": "Blockchain to deploy to.", "example": "ethereum"},
        ],
        "optional_params": [
            {"name": "constructor_args", "type": "array", "description": "Arguments for the contract constructor.", "default": []},
            {"name": "optimize", "type": "boolean", "description": "Apply gas optimizations.", "default": True},
        ],
        "keywords": ["deploy contract", "deploy smart contract", "publish contract", "launch contract", "put contract on chain", "deploy to ethereum", "deploy to solana"],
        "follow_up": "I can deploy your contract. Please share the source code, what language it's in, and which blockchain you'd like to deploy to.",
        "example_conversation": (
            "User: Deploy my token contract to Ethereum\n"
            "Trinity: Got it! Please share the contract source code and I'll deploy it to Ethereum for you.\n"
            "User: [pastes Solidity code]\n"
            "Trinity: [calls platform_action with action='deploy_contract', params={source_code: ..., source_lang: 'solidity', target_chain: 'ethereum'}]"
        ),
    },

    "estimate_contract_cost": {
        "action_name": "estimate_contract_cost",
        "description": "Estimate the cost to convert or deploy a smart contract.",
        "required_params": [
            {"name": "source_code", "type": "string", "description": "The contract source code.", "example": "pragma solidity ^0.8.0; ..."},
            {"name": "target_chain", "type": "string", "description": "Target blockchain.", "example": "ethereum"},
        ],
        "optional_params": [],
        "keywords": ["estimate cost", "how much to deploy", "contract cost", "deployment cost", "conversion cost", "gas estimate"],
        "follow_up": "I can estimate the cost. Please share the contract code and which chain you're targeting.",
        "example_conversation": (
            "User: How much would it cost to deploy my contract?\n"
            "Trinity: Share the source code and target blockchain, and I'll give you an estimate.\n"
            "User: [pastes code] — Ethereum\n"
            "Trinity: [calls platform_action with action='estimate_contract_cost', params={source_code: ..., target_chain: 'ethereum'}]"
        ),
    },

    "list_templates": {
        "action_name": "list_templates",
        "description": "List available smart contract templates.",
        "required_params": [],
        "optional_params": [
            {"name": "category", "type": "string", "description": "Filter by category (erc20, erc721, governance, staking, etc.).", "default": None},
        ],
        "keywords": ["list templates", "show templates", "contract templates", "available templates", "template list", "starter contracts"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me available contract templates\n"
            "Trinity: [calls platform_action with action='list_templates', params={}]"
        ),
    },

    # ===================================================================
    # Component 2 — DeFi Lending
    # ===================================================================

    "create_loan": {
        "action_name": "create_loan",
        "description": "Create a DeFi loan by providing collateral and borrowing tokens.",
        "required_params": [
            {"name": "collateral_token", "type": "string", "description": "Token to use as collateral.", "example": "ETH"},
            {"name": "collateral_amount", "type": "number", "description": "Amount of collateral to deposit.", "example": 2.0},
            {"name": "borrow_token", "type": "string", "description": "Token to borrow.", "example": "USDC"},
            {"name": "borrow_amount", "type": "number", "description": "Amount to borrow.", "example": 3000},
        ],
        "optional_params": [
            {"name": "protocol", "type": "string", "description": "Lending protocol to use.", "default": "auto"},
        ],
        "keywords": ["get a loan", "borrow", "take out a loan", "need a loan", "borrow money", "borrow tokens", "DeFi loan", "lending", "collateral"],
        "follow_up": "I can help you get a loan. What token would you like to use as collateral and how much? And what would you like to borrow?",
        "example_conversation": (
            "User: I want to borrow 3000 USDC\n"
            "Trinity: Sure! What token would you like to put up as collateral, and how much?\n"
            "User: 2 ETH\n"
            "Trinity: [calls platform_action with action='create_loan', params={collateral_token: 'ETH', collateral_amount: 2.0, borrow_token: 'USDC', borrow_amount: 3000}]"
        ),
    },

    "repay_loan": {
        "action_name": "repay_loan",
        "description": "Repay an outstanding DeFi loan.",
        "required_params": [
            {"name": "loan_id", "type": "string", "description": "ID of the loan to repay.", "example": "loan_abc123"},
            {"name": "amount", "type": "number", "description": "Amount to repay.", "example": 1500},
        ],
        "optional_params": [
            {"name": "full_repay", "type": "boolean", "description": "Repay the full outstanding amount.", "default": False},
        ],
        "keywords": ["repay loan", "pay back loan", "pay off loan", "loan repayment", "pay my loan", "settle loan"],
        "follow_up": "Which loan would you like to repay, and how much? If you'd like to pay it off completely, just let me know.",
        "example_conversation": (
            "User: I want to pay off my loan\n"
            "Trinity: Sure! Do you know your loan ID? I can also look up your active loans if you'd like.\n"
            "User: loan_abc123, pay it all off\n"
            "Trinity: [calls platform_action with action='repay_loan', params={loan_id: 'loan_abc123', amount: ..., full_repay: true}]"
        ),
    },

    "get_loan": {
        "action_name": "get_loan",
        "description": "Get details about an existing DeFi loan.",
        "required_params": [
            {"name": "loan_id", "type": "string", "description": "ID of the loan.", "example": "loan_abc123"},
        ],
        "optional_params": [],
        "keywords": ["check loan", "loan status", "my loan", "loan details", "view loan", "loan info"],
        "follow_up": "Which loan would you like to check? I'll need the loan ID.",
        "example_conversation": (
            "User: What's the status of my loan?\n"
            "Trinity: What's the loan ID?\n"
            "User: loan_abc123\n"
            "Trinity: [calls platform_action with action='get_loan', params={loan_id: 'loan_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 3 — NFT Services
    # ===================================================================

    "mint_nft": {
        "action_name": "mint_nft",
        "description": "Mint a new NFT with metadata and optional royalties.",
        "required_params": [
            {"name": "metadata", "type": "object", "description": "NFT metadata including name, description, and image URL.", "example": {"name": "My Art", "description": "A digital painting", "image": "https://..."}},
            {"name": "royalty_bps", "type": "integer", "description": "Royalty percentage in basis points (100 = 1%).", "example": 500},
        ],
        "optional_params": [
            {"name": "collection_id", "type": "string", "description": "Collection to mint into.", "default": None},
            {"name": "chain", "type": "string", "description": "Blockchain to mint on.", "default": "ethereum"},
        ],
        "keywords": ["mint NFT", "create NFT", "make an NFT", "mint my art", "turn into NFT", "NFT", "mint"],
        "follow_up": "I can mint an NFT for you. What would you like to name it, and do you have an image or file to attach? Also, what royalty percentage would you like (e.g. 5%)?",
        "example_conversation": (
            "User: I want to mint an NFT of my artwork\n"
            "Trinity: Great! What would you like to name it, and can you share the image? Also, what royalty percentage should be set for secondary sales?\n"
            "User: Call it 'Sunset Dreams', here's the image, 5% royalty\n"
            "Trinity: [calls platform_action with action='mint_nft', params={metadata: {name: 'Sunset Dreams', ...}, royalty_bps: 500}]"
        ),
    },

    "create_nft_collection": {
        "action_name": "create_nft_collection",
        "description": "Create a new NFT collection.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Collection name.", "example": "Cosmic Apes"},
            {"name": "symbol", "type": "string", "description": "Collection symbol.", "example": "CAPE"},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Collection description.", "default": ""},
            {"name": "max_supply", "type": "integer", "description": "Maximum number of NFTs in the collection.", "default": None},
            {"name": "royalty_bps", "type": "integer", "description": "Default royalty for the collection.", "default": 500},
        ],
        "keywords": ["create collection", "new collection", "NFT collection", "start a collection", "launch collection"],
        "follow_up": "What would you like to name the collection, and what should its symbol be?",
        "example_conversation": (
            "User: I want to create an NFT collection\n"
            "Trinity: Great! What should the collection be called, and what symbol should it use?\n"
            "User: Cosmic Apes, symbol CAPE\n"
            "Trinity: [calls platform_action with action='create_nft_collection', params={name: 'Cosmic Apes', symbol: 'CAPE'}]"
        ),
    },

    "transfer_nft": {
        "action_name": "transfer_nft",
        "description": "Transfer an NFT to another wallet.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID of the NFT.", "example": "token_123"},
            {"name": "to_address", "type": "string", "description": "Recipient wallet address.", "example": "0xabc..."},
        ],
        "optional_params": [],
        "keywords": ["transfer NFT", "send NFT", "give NFT", "move NFT", "send my NFT to"],
        "follow_up": "Which NFT would you like to transfer, and to whom?",
        "example_conversation": (
            "User: Send my NFT #123 to alice.eth\n"
            "Trinity: [calls platform_action with action='transfer_nft', params={token_id: '123', to_address: 'alice.eth'}]"
        ),
    },

    "buy_nft": {
        "action_name": "buy_nft",
        "description": "Purchase an NFT from a marketplace listing.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID of the NFT to buy.", "example": "token_xyz789"},
            {"name": "collection", "type": "string", "description": "The collection address or name.", "example": "0xabc..."},
        ],
        "optional_params": [
            {"name": "max_price", "type": "number", "description": "Maximum price willing to pay.", "default": None},
        ],
        "keywords": ["buy NFT", "purchase NFT", "buy this NFT", "get this NFT", "acquire NFT"],
        "follow_up": "Which NFT would you like to buy? I'll need the token ID and collection.",
        "example_conversation": (
            "User: I want to buy that cool ape NFT\n"
            "Trinity: Sure! Can you share the token ID or a link to the NFT listing?\n"
            "User: Token #4521 from BoredApes\n"
            "Trinity: [calls platform_action with action='buy_nft', params={token_id: '4521', collection: 'BoredApes'}]"
        ),
    },

    "list_nft_for_sale": {
        "action_name": "list_nft_for_sale",
        "description": "List an NFT for sale on the marketplace.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID of the NFT to sell.", "example": "token_xyz789"},
            {"name": "price", "type": "number", "description": "Sale price.", "example": 1.5},
        ],
        "optional_params": [
            {"name": "currency", "type": "string", "description": "Currency for the listing.", "default": "ETH"},
            {"name": "duration", "type": "integer", "description": "Listing duration in days.", "default": 30},
        ],
        "keywords": ["sell NFT", "list NFT", "put NFT for sale", "sell my NFT", "list for sale", "list my NFT"],
        "follow_up": "Which NFT would you like to sell, and at what price?",
        "example_conversation": (
            "User: I want to sell my NFT for 2 ETH\n"
            "Trinity: Which NFT would you like to list? I'll need the token ID.\n"
            "User: Token #1234\n"
            "Trinity: [calls platform_action with action='list_nft_for_sale', params={token_id: '1234', price: 2.0}]"
        ),
    },

    "estimate_nft_value": {
        "action_name": "estimate_nft_value",
        "description": "Estimate the current market value of an NFT.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID.", "example": "token_123"},
            {"name": "collection", "type": "string", "description": "The collection address or name.", "example": "CryptoPunks"},
        ],
        "optional_params": [],
        "keywords": ["NFT value", "how much is my NFT worth", "estimate NFT", "appraise NFT", "NFT price check", "value my NFT"],
        "follow_up": "Which NFT would you like me to appraise? I'll need the token ID and collection.",
        "example_conversation": (
            "User: How much is my CryptoPunk worth?\n"
            "Trinity: What's the token ID of your CryptoPunk?\n"
            "User: #7804\n"
            "Trinity: [calls platform_action with action='estimate_nft_value', params={token_id: '7804', collection: 'CryptoPunks'}]"
        ),
    },

    "get_nft_rarity": {
        "action_name": "get_nft_rarity",
        "description": "Get the rarity score and ranking of an NFT.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID.", "example": "token_123"},
            {"name": "collection", "type": "string", "description": "Collection address or name.", "example": "BoredApes"},
        ],
        "optional_params": [],
        "keywords": ["NFT rarity", "rarity score", "how rare", "rarity rank", "check rarity"],
        "follow_up": "Which NFT would you like to check the rarity for?",
        "example_conversation": (
            "User: How rare is my ape #4521?\n"
            "Trinity: [calls platform_action with action='get_nft_rarity', params={token_id: '4521', collection: 'BoredApes'}]"
        ),
    },

    "set_nft_rights": {
        "action_name": "set_nft_rights",
        "description": "Set usage rights for an NFT (commercial, personal, etc.).",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID.", "example": "token_123"},
            {"name": "rights", "type": "object", "description": "Rights configuration.", "example": {"commercial": True, "derivative": False}},
        ],
        "optional_params": [],
        "keywords": ["NFT rights", "set rights", "commercial rights", "usage rights", "NFT license"],
        "follow_up": "Which NFT and what rights would you like to set?",
        "example_conversation": (
            "User: Set commercial rights on my NFT #123\n"
            "Trinity: [calls platform_action with action='set_nft_rights', params={token_id: '123', rights: {commercial: true}}]"
        ),
    },

    "check_nft_rights": {
        "action_name": "check_nft_rights",
        "description": "Check the current usage rights of an NFT.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID.", "example": "token_123"},
        ],
        "optional_params": [],
        "keywords": ["check rights", "NFT permissions", "what rights", "view rights"],
        "follow_up": "Which NFT would you like to check rights for?",
        "example_conversation": (
            "User: What rights does NFT #123 have?\n"
            "Trinity: [calls platform_action with action='check_nft_rights', params={token_id: '123'}]"
        ),
    },

    "configure_nft_royalty": {
        "action_name": "configure_nft_royalty",
        "description": "Configure royalty settings for an NFT or collection.",
        "required_params": [
            {"name": "token_id", "type": "string", "description": "The token ID or collection ID.", "example": "token_123"},
            {"name": "royalty_bps", "type": "integer", "description": "Royalty in basis points (100 = 1%).", "example": 750},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Wallet address to receive royalties.", "default": None},
        ],
        "keywords": ["set royalty", "change royalty", "configure royalty", "royalty rate", "update royalty"],
        "follow_up": "Which NFT and what royalty percentage would you like to set?",
        "example_conversation": (
            "User: Set 7.5% royalty on my collection\n"
            "Trinity: [calls platform_action with action='configure_nft_royalty', params={token_id: 'collection_id', royalty_bps: 750}]"
        ),
    },

    # ===================================================================
    # Component 4 — RWA Tokenization
    # ===================================================================

    "tokenize_asset": {
        "action_name": "tokenize_asset",
        "description": "Tokenize a real-world asset on-chain.",
        "required_params": [
            {"name": "asset_type", "type": "string", "description": "Type of asset (real_estate, art, commodity, vehicle, etc.).", "example": "real_estate"},
            {"name": "details", "type": "object", "description": "Asset details (value, location, documentation, etc.).", "example": {"value": 500000, "address": "123 Main St"}},
        ],
        "optional_params": [
            {"name": "fractionalize", "type": "boolean", "description": "Whether to split into fractional shares.", "default": False},
            {"name": "shares", "type": "integer", "description": "Number of fractional shares.", "default": 1},
        ],
        "keywords": ["tokenize asset", "tokenize property", "tokenize real estate", "RWA", "real world asset", "tokenize", "asset tokenization"],
        "follow_up": "What type of asset would you like to tokenize, and can you provide the key details (value, description, documentation)?",
        "example_conversation": (
            "User: I want to tokenize my property\n"
            "Trinity: Sure! What type of property is it, and what are the key details?\n"
            "User: It's a condo worth 500k at 123 Main St\n"
            "Trinity: [calls platform_action with action='tokenize_asset', params={asset_type: 'real_estate', details: {value: 500000, address: '123 Main St'}}]"
        ),
    },

    "transfer_rwa_ownership": {
        "action_name": "transfer_rwa_ownership",
        "description": "Transfer ownership of a tokenized real-world asset.",
        "required_params": [
            {"name": "asset_id", "type": "string", "description": "ID of the tokenized asset.", "example": "rwa_abc123"},
            {"name": "to_address", "type": "string", "description": "Recipient wallet address.", "example": "0xabc..."},
        ],
        "optional_params": [],
        "keywords": ["transfer asset", "transfer ownership", "sell property token", "transfer RWA"],
        "follow_up": "Which asset would you like to transfer, and to whom?",
        "example_conversation": (
            "User: Transfer my property token to bob.eth\n"
            "Trinity: Which asset ID?\n"
            "User: rwa_abc123\n"
            "Trinity: [calls platform_action with action='transfer_rwa_ownership', params={asset_id: 'rwa_abc123', to_address: 'bob.eth'}]"
        ),
    },

    "get_rwa_asset": {
        "action_name": "get_rwa_asset",
        "description": "Get details about a tokenized real-world asset.",
        "required_params": [
            {"name": "asset_id", "type": "string", "description": "ID of the asset.", "example": "rwa_abc123"},
        ],
        "optional_params": [],
        "keywords": ["view asset", "asset details", "my asset", "check asset", "RWA info"],
        "follow_up": "What's the asset ID you'd like to look up?",
        "example_conversation": (
            "User: Show me details of asset rwa_abc123\n"
            "Trinity: [calls platform_action with action='get_rwa_asset', params={asset_id: 'rwa_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 5 — DID Identity
    # ===================================================================

    "create_did": {
        "action_name": "create_did",
        "description": "Create a decentralized identity (DID).",
        "required_params": [
            {"name": "name", "type": "string", "description": "Display name for the identity.", "example": "Alice"},
            {"name": "attributes", "type": "object", "description": "Identity attributes.", "example": {"email": "alice@example.com", "bio": "Web3 developer"}},
        ],
        "optional_params": [
            {"name": "avatar", "type": "string", "description": "Avatar URL.", "default": None},
        ],
        "keywords": ["create identity", "create DID", "decentralized identity", "new identity", "set up identity", "register identity", "make my DID"],
        "follow_up": "What name would you like for your identity, and any attributes to include?",
        "example_conversation": (
            "User: I want to create a decentralized identity\n"
            "Trinity: Sure! What name should it have, and any details to include?\n"
            "User: Name is Alice, email alice@example.com\n"
            "Trinity: [calls platform_action with action='create_did', params={name: 'Alice', attributes: {email: 'alice@example.com'}}]"
        ),
    },

    "resolve_did": {
        "action_name": "resolve_did",
        "description": "Resolve a DID to its associated document and attributes.",
        "required_params": [
            {"name": "did", "type": "string", "description": "The DID to resolve.", "example": "did:omx:abc123"},
        ],
        "optional_params": [],
        "keywords": ["resolve DID", "lookup DID", "find identity", "who is", "resolve identity"],
        "follow_up": "What DID would you like to resolve?",
        "example_conversation": (
            "User: Who is did:omx:abc123?\n"
            "Trinity: [calls platform_action with action='resolve_did', params={did: 'did:omx:abc123'}]"
        ),
    },

    "update_did": {
        "action_name": "update_did",
        "description": "Update attributes on a decentralized identity.",
        "required_params": [
            {"name": "did", "type": "string", "description": "The DID to update.", "example": "did:omx:abc123"},
            {"name": "updates", "type": "object", "description": "Fields to update.", "example": {"bio": "Senior Web3 developer"}},
        ],
        "optional_params": [],
        "keywords": ["update identity", "update DID", "change identity", "edit DID", "modify identity"],
        "follow_up": "Which DID would you like to update, and what should change?",
        "example_conversation": (
            "User: Update my bio on my DID\n"
            "Trinity: What's your DID, and what should the new bio say?\n"
            "User: did:omx:abc123, new bio is 'Senior Web3 developer'\n"
            "Trinity: [calls platform_action with action='update_did', params={did: 'did:omx:abc123', updates: {bio: 'Senior Web3 developer'}}]"
        ),
    },

    "deactivate_did": {
        "action_name": "deactivate_did",
        "description": "Deactivate a decentralized identity.",
        "required_params": [
            {"name": "did", "type": "string", "description": "The DID to deactivate.", "example": "did:omx:abc123"},
        ],
        "optional_params": [],
        "keywords": ["deactivate DID", "delete identity", "remove DID", "disable identity"],
        "follow_up": "Which DID would you like to deactivate? This action cannot be undone.",
        "example_conversation": (
            "User: Deactivate my old identity\n"
            "Trinity: Which DID? Please note this is permanent.\n"
            "User: did:omx:abc123\n"
            "Trinity: [calls platform_action with action='deactivate_did', params={did: 'did:omx:abc123'}]"
        ),
    },

    # ===================================================================
    # Component 6 — DAO Management
    # ===================================================================

    "create_dao": {
        "action_name": "create_dao",
        "description": "Create a new decentralized autonomous organization.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Name of the DAO.", "example": "ClimateDAO"},
            {"name": "config", "type": "object", "description": "DAO configuration.", "example": {"voting_period": 72, "quorum": 0.1, "token": "CLIMATE"}},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Description of the DAO's purpose.", "default": ""},
        ],
        "keywords": ["create DAO", "start a DAO", "new DAO", "set up a DAO", "make a DAO", "launch DAO"],
        "follow_up": "What would you like to name your DAO, and how should voting work?",
        "example_conversation": (
            "User: I want to create a DAO for climate initiatives\n"
            "Trinity: What would you like to name it, and how should governance work?\n"
            "User: Call it ClimateDAO, 72 hour voting, 10% quorum\n"
            "Trinity: [calls platform_action with action='create_dao', params={name: 'ClimateDAO', config: {voting_period: 72, quorum: 0.1}}]"
        ),
    },

    "get_dao": {
        "action_name": "get_dao",
        "description": "Get details about a DAO.",
        "required_params": [
            {"name": "dao_id", "type": "string", "description": "ID of the DAO.", "example": "dao_abc123"},
        ],
        "optional_params": [],
        "keywords": ["DAO info", "DAO details", "check DAO", "view DAO", "about DAO"],
        "follow_up": "Which DAO would you like to look up?",
        "example_conversation": (
            "User: Tell me about ClimateDAO\n"
            "Trinity: [calls platform_action with action='get_dao', params={dao_id: 'climate_dao'}]"
        ),
    },

    "join_dao": {
        "action_name": "join_dao",
        "description": "Join a DAO as a member.",
        "required_params": [
            {"name": "dao_id", "type": "string", "description": "ID of the DAO to join.", "example": "dao_abc123"},
        ],
        "optional_params": [],
        "keywords": ["join DAO", "become member", "join organization", "enter DAO", "sign up for DAO"],
        "follow_up": "Which DAO would you like to join?",
        "example_conversation": (
            "User: I want to join ClimateDAO\n"
            "Trinity: [calls platform_action with action='join_dao', params={dao_id: 'climate_dao'}]"
        ),
    },

    "leave_dao": {
        "action_name": "leave_dao",
        "description": "Leave a DAO.",
        "required_params": [
            {"name": "dao_id", "type": "string", "description": "ID of the DAO to leave.", "example": "dao_abc123"},
        ],
        "optional_params": [],
        "keywords": ["leave DAO", "exit DAO", "quit DAO", "leave organization"],
        "follow_up": "Which DAO would you like to leave?",
        "example_conversation": (
            "User: I want to leave ClimateDAO\n"
            "Trinity: [calls platform_action with action='leave_dao', params={dao_id: 'climate_dao'}]"
        ),
    },

    # ===================================================================
    # Component 7 — Stablecoin
    # ===================================================================

    "transfer_stablecoin": {
        "action_name": "transfer_stablecoin",
        "description": "Transfer stablecoins to another address.",
        "required_params": [
            {"name": "to_address", "type": "string", "description": "Recipient address.", "example": "0xabc..."},
            {"name": "amount", "type": "number", "description": "Amount to transfer.", "example": 500},
            {"name": "token", "type": "string", "description": "Stablecoin token (USDC, USDT, DAI).", "example": "USDC"},
        ],
        "optional_params": [],
        "keywords": ["send stablecoin", "transfer USDC", "transfer USDT", "send DAI", "stablecoin transfer"],
        "follow_up": "How much, which stablecoin, and to whom?",
        "example_conversation": (
            "User: Send 500 USDC to alice.eth\n"
            "Trinity: [calls platform_action with action='transfer_stablecoin', params={to_address: 'alice.eth', amount: 500, token: 'USDC'}]"
        ),
    },

    "get_stablecoin_balance": {
        "action_name": "get_stablecoin_balance",
        "description": "Check stablecoin balance.",
        "required_params": [],
        "optional_params": [
            {"name": "token", "type": "string", "description": "Specific stablecoin to check.", "default": "all"},
        ],
        "keywords": ["stablecoin balance", "USDC balance", "USDT balance", "DAI balance", "how much stablecoin"],
        "follow_up": "",
        "example_conversation": (
            "User: What's my USDC balance?\n"
            "Trinity: [calls platform_action with action='get_stablecoin_balance', params={token: 'USDC'}]"
        ),
    },

    "get_stablecoin_fee": {
        "action_name": "get_stablecoin_fee",
        "description": "Check the fee for a stablecoin transfer.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Transfer amount.", "example": 1000},
            {"name": "token", "type": "string", "description": "Stablecoin token.", "example": "USDC"},
        ],
        "optional_params": [],
        "keywords": ["stablecoin fee", "transfer fee", "USDC fee", "how much is the fee"],
        "follow_up": "How much are you transferring and which stablecoin?",
        "example_conversation": (
            "User: What's the fee to send 1000 USDC?\n"
            "Trinity: [calls platform_action with action='get_stablecoin_fee', params={amount: 1000, token: 'USDC'}]"
        ),
    },

    # ===================================================================
    # Component 8 — Attestation
    # ===================================================================

    "create_attestation": {
        "action_name": "create_attestation",
        "description": "Create an on-chain attestation via EAS.",
        "required_params": [
            {"name": "schema_uid", "type": "string", "description": "EAS schema UID.", "example": "0xabc..."},
            {"name": "data", "type": "object", "description": "Attestation data fields.", "example": {"name": "Verified Developer", "level": "senior"}},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Attestation recipient address.", "default": None},
            {"name": "revocable", "type": "boolean", "description": "Whether the attestation can be revoked.", "default": True},
        ],
        "keywords": ["create attestation", "attest", "make attestation", "issue attestation", "EAS attestation"],
        "follow_up": "What schema and data would you like to attest?",
        "example_conversation": (
            "User: I want to create an attestation for a developer\n"
            "Trinity: What schema should I use, and what data should the attestation contain?\n"
            "User: Schema 0xabc, data: Verified Developer, senior level\n"
            "Trinity: [calls platform_action with action='create_attestation', params={schema_uid: '0xabc', data: {name: 'Verified Developer', level: 'senior'}}]"
        ),
    },

    "verify_attestation": {
        "action_name": "verify_attestation",
        "description": "Verify an existing on-chain attestation.",
        "required_params": [
            {"name": "attestation_uid", "type": "string", "description": "UID of the attestation to verify.", "example": "0xdef..."},
        ],
        "optional_params": [],
        "keywords": ["verify attestation", "check attestation", "is attestation valid", "validate attestation"],
        "follow_up": "What's the attestation UID you'd like to verify?",
        "example_conversation": (
            "User: Verify attestation 0xdef123\n"
            "Trinity: [calls platform_action with action='verify_attestation', params={attestation_uid: '0xdef123'}]"
        ),
    },

    "revoke_attestation": {
        "action_name": "revoke_attestation",
        "description": "Revoke an on-chain attestation.",
        "required_params": [
            {"name": "attestation_uid", "type": "string", "description": "UID of the attestation to revoke.", "example": "0xdef..."},
        ],
        "optional_params": [
            {"name": "reason", "type": "string", "description": "Reason for revocation.", "default": ""},
        ],
        "keywords": ["revoke attestation", "cancel attestation", "remove attestation", "invalidate attestation"],
        "follow_up": "Which attestation would you like to revoke?",
        "example_conversation": (
            "User: Revoke attestation 0xdef123\n"
            "Trinity: [calls platform_action with action='revoke_attestation', params={attestation_uid: '0xdef123'}]"
        ),
    },

    "query_attestations": {
        "action_name": "query_attestations",
        "description": "Query attestations by schema, attester, or recipient.",
        "required_params": [],
        "optional_params": [
            {"name": "schema_uid", "type": "string", "description": "Filter by schema.", "default": None},
            {"name": "attester", "type": "string", "description": "Filter by attester address.", "default": None},
            {"name": "recipient", "type": "string", "description": "Filter by recipient address.", "default": None},
        ],
        "keywords": ["find attestations", "search attestations", "list attestations", "my attestations", "query attestations"],
        "follow_up": "Would you like to filter by schema, attester, or recipient?",
        "example_conversation": (
            "User: Show me all my attestations\n"
            "Trinity: [calls platform_action with action='query_attestations', params={}]"
        ),
    },

    "batch_attest": {
        "action_name": "batch_attest",
        "description": "Create multiple attestations in a single batch.",
        "required_params": [
            {"name": "attestations", "type": "array", "description": "List of attestation data objects.", "example": [{"schema_uid": "0x...", "data": {}}]},
        ],
        "optional_params": [],
        "keywords": ["batch attest", "bulk attestation", "multiple attestations", "batch attestations"],
        "follow_up": "How many attestations would you like to create, and what data should each contain?",
        "example_conversation": (
            "User: I need to create attestations for 5 team members\n"
            "Trinity: I can batch those. What schema and data for each?\n"
            "User: [provides list]\n"
            "Trinity: [calls platform_action with action='batch_attest', params={attestations: [...]}]"
        ),
    },

    # ===================================================================
    # Component 9 — Agent Identity
    # ===================================================================

    "register_agent": {
        "action_name": "register_agent",
        "description": "Register a new AI agent identity on-chain.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Agent name.", "example": "TradingBot"},
            {"name": "capabilities", "type": "array", "description": "List of agent capabilities.", "example": ["trading", "analysis", "reporting"]},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Agent description.", "default": ""},
        ],
        "keywords": ["register agent", "create agent", "new agent", "add agent", "register AI agent", "register bot"],
        "follow_up": "What should the agent be called, and what are its capabilities?",
        "example_conversation": (
            "User: Register a new trading bot agent\n"
            "Trinity: What should I call it, and what capabilities does it have?\n"
            "User: TradingBot, capabilities: trading, analysis\n"
            "Trinity: [calls platform_action with action='register_agent', params={name: 'TradingBot', capabilities: ['trading', 'analysis']}]"
        ),
    },

    "get_agent": {
        "action_name": "get_agent",
        "description": "Get details about a registered agent.",
        "required_params": [
            {"name": "agent_id", "type": "string", "description": "Agent ID.", "example": "agent_abc123"},
        ],
        "optional_params": [],
        "keywords": ["agent info", "agent details", "check agent", "view agent"],
        "follow_up": "Which agent would you like to look up?",
        "example_conversation": (
            "User: Show me agent TradingBot\n"
            "Trinity: [calls platform_action with action='get_agent', params={agent_id: 'tradingbot'}]"
        ),
    },

    "update_agent": {
        "action_name": "update_agent",
        "description": "Update a registered agent's details.",
        "required_params": [
            {"name": "agent_id", "type": "string", "description": "Agent ID.", "example": "agent_abc123"},
            {"name": "updates", "type": "object", "description": "Fields to update.", "example": {"capabilities": ["trading", "analysis", "alerts"]}},
        ],
        "optional_params": [],
        "keywords": ["update agent", "modify agent", "change agent", "edit agent"],
        "follow_up": "Which agent and what should change?",
        "example_conversation": (
            "User: Add alerts capability to TradingBot\n"
            "Trinity: [calls platform_action with action='update_agent', params={agent_id: 'tradingbot', updates: {capabilities: ['trading', 'analysis', 'alerts']}}]"
        ),
    },

    "deregister_agent": {
        "action_name": "deregister_agent",
        "description": "Remove a registered agent identity.",
        "required_params": [
            {"name": "agent_id", "type": "string", "description": "Agent ID to remove.", "example": "agent_abc123"},
        ],
        "optional_params": [],
        "keywords": ["remove agent", "deregister agent", "delete agent", "unregister agent"],
        "follow_up": "Which agent would you like to deregister?",
        "example_conversation": (
            "User: Remove agent TradingBot\n"
            "Trinity: [calls platform_action with action='deregister_agent', params={agent_id: 'tradingbot'}]"
        ),
    },

    "list_agents": {
        "action_name": "list_agents",
        "description": "List all registered agents.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["list agents", "my agents", "show agents", "all agents", "registered agents"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me all my agents\n"
            "Trinity: [calls platform_action with action='list_agents', params={}]"
        ),
    },

    # ===================================================================
    # Component 10 — x402 Payments
    # ===================================================================

    "create_payment": {
        "action_name": "create_payment",
        "description": "Create an x402 micropayment.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Payment amount.", "example": 0.01},
            {"name": "currency", "type": "string", "description": "Payment currency.", "example": "USDC"},
            {"name": "description", "type": "string", "description": "Payment description.", "example": "API access fee"},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Recipient address.", "default": None},
        ],
        "keywords": ["create payment", "micropayment", "x402 payment", "pay-per-request", "create x402"],
        "follow_up": "How much, in what currency, and for what purpose?",
        "example_conversation": (
            "User: Create a micropayment for API access\n"
            "Trinity: How much should the payment be?\n"
            "User: 0.01 USDC\n"
            "Trinity: [calls platform_action with action='create_payment', params={amount: 0.01, currency: 'USDC', description: 'API access fee'}]"
        ),
    },

    "authorize_payment": {
        "action_name": "authorize_payment",
        "description": "Authorize a pending x402 payment.",
        "required_params": [
            {"name": "payment_id", "type": "string", "description": "Payment ID to authorize.", "example": "pay_abc123"},
        ],
        "optional_params": [],
        "keywords": ["authorize payment", "approve payment", "confirm payment"],
        "follow_up": "Which payment would you like to authorize?",
        "example_conversation": (
            "User: Authorize payment pay_abc123\n"
            "Trinity: [calls platform_action with action='authorize_payment', params={payment_id: 'pay_abc123'}]"
        ),
    },

    "complete_payment": {
        "action_name": "complete_payment",
        "description": "Complete an authorized payment.",
        "required_params": [
            {"name": "payment_id", "type": "string", "description": "Payment ID.", "example": "pay_abc123"},
        ],
        "optional_params": [],
        "keywords": ["complete payment", "finalize payment", "finish payment"],
        "follow_up": "Which payment should I complete?",
        "example_conversation": (
            "User: Complete payment pay_abc123\n"
            "Trinity: [calls platform_action with action='complete_payment', params={payment_id: 'pay_abc123'}]"
        ),
    },

    "refund_payment": {
        "action_name": "refund_payment",
        "description": "Refund an x402 payment.",
        "required_params": [
            {"name": "payment_id", "type": "string", "description": "Payment ID to refund.", "example": "pay_abc123"},
        ],
        "optional_params": [
            {"name": "reason", "type": "string", "description": "Reason for refund.", "default": ""},
        ],
        "keywords": ["refund payment", "reverse payment", "get refund", "cancel payment"],
        "follow_up": "Which payment would you like to refund?",
        "example_conversation": (
            "User: Refund payment pay_abc123\n"
            "Trinity: [calls platform_action with action='refund_payment', params={payment_id: 'pay_abc123'}]"
        ),
    },

    "get_payment": {
        "action_name": "get_payment",
        "description": "Get details of a specific payment.",
        "required_params": [
            {"name": "payment_id", "type": "string", "description": "Payment ID.", "example": "pay_abc123"},
        ],
        "optional_params": [],
        "keywords": ["payment details", "check payment", "payment status", "view payment"],
        "follow_up": "Which payment ID?",
        "example_conversation": (
            "User: Check payment pay_abc123\n"
            "Trinity: [calls platform_action with action='get_payment', params={payment_id: 'pay_abc123'}]"
        ),
    },

    "list_payments": {
        "action_name": "list_payments",
        "description": "List all x402 payments.",
        "required_params": [],
        "optional_params": [
            {"name": "status", "type": "string", "description": "Filter by status.", "default": "all"},
        ],
        "keywords": ["list payments", "my payments", "payment history", "show payments"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my payment history\n"
            "Trinity: [calls platform_action with action='list_payments', params={}]"
        ),
    },

    # ===================================================================
    # Component 11 — Oracle Gateway
    # ===================================================================

    "oracle_request": {
        "action_name": "oracle_request",
        "description": "Request data from the oracle gateway.",
        "required_params": [
            {"name": "query", "type": "string", "description": "Data query (e.g. price feed, weather, sports).", "example": "ETH/USD price"},
        ],
        "optional_params": [
            {"name": "source", "type": "string", "description": "Preferred data source.", "default": "auto"},
        ],
        "keywords": ["oracle request", "get data", "data feed", "external data", "oracle query"],
        "follow_up": "What data would you like to fetch?",
        "example_conversation": (
            "User: Get me the latest ETH/USD price from the oracle\n"
            "Trinity: [calls platform_action with action='oracle_request', params={query: 'ETH/USD price'}]"
        ),
    },

    "get_price": {
        "action_name": "get_price",
        "description": "Get the current price of a token or asset.",
        "required_params": [
            {"name": "query", "type": "string", "description": "Asset pair (e.g. ETH/USD, BTC/USDC).", "example": "ETH/USD"},
        ],
        "optional_params": [],
        "keywords": ["price", "what's the price", "how much is", "current price", "price of ETH", "price of BTC", "token price"],
        "follow_up": "Which asset or pair would you like the price for?",
        "example_conversation": (
            "User: What's the current price of ETH?\n"
            "Trinity: [calls platform_action with action='get_price', params={query: 'ETH/USD'}]"
        ),
    },

    # ===================================================================
    # Component 12 — Supply Chain
    # ===================================================================

    "register_product": {
        "action_name": "register_product",
        "description": "Register a new product in the supply chain.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Product name.", "example": "Organic Coffee Beans"},
            {"name": "details", "type": "object", "description": "Product details.", "example": {"origin": "Colombia", "batch": "2024-001"}},
        ],
        "optional_params": [],
        "keywords": ["register product", "add product", "new product", "supply chain product"],
        "follow_up": "What's the product name and its details?",
        "example_conversation": (
            "User: Register my coffee beans in the supply chain\n"
            "Trinity: What are the product details — name, origin, batch number?\n"
            "User: Organic Coffee Beans, Colombia, batch 2024-001\n"
            "Trinity: [calls platform_action with action='register_product', params={name: 'Organic Coffee Beans', details: {origin: 'Colombia', batch: '2024-001'}}]"
        ),
    },

    "update_product_status": {
        "action_name": "update_product_status",
        "description": "Update the status of a product in the supply chain.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product ID.", "example": "prod_abc123"},
            {"name": "status", "type": "string", "description": "New status (manufactured, shipped, in_transit, delivered).", "example": "shipped"},
        ],
        "optional_params": [
            {"name": "location", "type": "string", "description": "Current location.", "default": None},
        ],
        "keywords": ["update product", "product status", "mark as shipped", "update shipment", "product update"],
        "follow_up": "Which product and what's the new status?",
        "example_conversation": (
            "User: Mark product prod_abc123 as shipped\n"
            "Trinity: [calls platform_action with action='update_product_status', params={product_id: 'prod_abc123', status: 'shipped'}]"
        ),
    },

    "track_product": {
        "action_name": "track_product",
        "description": "Track a product's journey through the supply chain.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "ID of the product to track.", "example": "prod_abc123"},
        ],
        "optional_params": [],
        "keywords": ["track product", "track shipment", "where is my product", "supply chain", "track order", "product status"],
        "follow_up": "What's the product ID you'd like to track?",
        "example_conversation": (
            "User: Where is my product prod_abc123?\n"
            "Trinity: [calls platform_action with action='track_product', params={product_id: 'prod_abc123'}]"
        ),
    },

    "verify_product": {
        "action_name": "verify_product",
        "description": "Verify the authenticity of a product.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product ID to verify.", "example": "prod_abc123"},
        ],
        "optional_params": [],
        "keywords": ["verify product", "authenticate product", "is product real", "product authenticity", "check product"],
        "follow_up": "What's the product ID to verify?",
        "example_conversation": (
            "User: Is product prod_abc123 authentic?\n"
            "Trinity: [calls platform_action with action='verify_product', params={product_id: 'prod_abc123'}]"
        ),
    },

    "transfer_custody": {
        "action_name": "transfer_custody",
        "description": "Transfer custody of a product to another party.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product ID.", "example": "prod_abc123"},
            {"name": "to_address", "type": "string", "description": "New custodian address.", "example": "0xabc..."},
        ],
        "optional_params": [],
        "keywords": ["transfer custody", "hand over product", "change custodian", "transfer product"],
        "follow_up": "Which product and to whom?",
        "example_conversation": (
            "User: Transfer custody of prod_abc123 to the distributor\n"
            "Trinity: What's the distributor's address?\n"
            "User: 0xabc...\n"
            "Trinity: [calls platform_action with action='transfer_custody', params={product_id: 'prod_abc123', to_address: '0xabc...'}]"
        ),
    },

    # ===================================================================
    # Component 13 — Insurance
    # ===================================================================

    "create_insurance": {
        "action_name": "create_insurance",
        "description": "Create an on-chain insurance policy.",
        "required_params": [
            {"name": "policy_type", "type": "string", "description": "Type of insurance (smart_contract, defi, nft, etc.).", "example": "smart_contract"},
            {"name": "coverage", "type": "number", "description": "Coverage amount.", "example": 50000},
            {"name": "premium", "type": "number", "description": "Premium to pay.", "example": 250},
        ],
        "optional_params": [
            {"name": "duration_days", "type": "integer", "description": "Policy duration in days.", "default": 365},
        ],
        "keywords": ["create insurance", "buy insurance", "get insurance", "insure", "insurance policy", "protect", "coverage"],
        "follow_up": "What type of insurance do you need, what coverage amount, and what premium are you comfortable with?",
        "example_conversation": (
            "User: I want to insure my smart contract\n"
            "Trinity: Sure! What coverage amount do you need, and what premium works for you?\n"
            "User: 50k coverage, up to 250 premium\n"
            "Trinity: [calls platform_action with action='create_insurance', params={policy_type: 'smart_contract', coverage: 50000, premium: 250}]"
        ),
    },

    "file_insurance_claim": {
        "action_name": "file_insurance_claim",
        "description": "File a claim against an insurance policy.",
        "required_params": [
            {"name": "policy_id", "type": "string", "description": "ID of the insurance policy.", "example": "pol_abc123"},
            {"name": "evidence", "type": "string", "description": "Description or hash of evidence.", "example": "Contract exploited on block 18234567"},
        ],
        "optional_params": [
            {"name": "claim_amount", "type": "number", "description": "Specific amount being claimed.", "default": None},
        ],
        "keywords": ["file claim", "insurance claim", "make a claim", "claim insurance", "report incident"],
        "follow_up": "Which policy is this claim for, and what evidence do you have?",
        "example_conversation": (
            "User: I need to file an insurance claim\n"
            "Trinity: Which policy is this for, and what happened?\n"
            "User: Policy pol_abc123, my contract was exploited\n"
            "Trinity: [calls platform_action with action='file_insurance_claim', params={policy_id: 'pol_abc123', evidence: 'Contract exploited...'}]"
        ),
    },

    "get_insurance_policy": {
        "action_name": "get_insurance_policy",
        "description": "Get details of an insurance policy.",
        "required_params": [
            {"name": "policy_id", "type": "string", "description": "Policy ID.", "example": "pol_abc123"},
        ],
        "optional_params": [],
        "keywords": ["policy details", "my insurance", "check policy", "insurance status", "view policy"],
        "follow_up": "What's the policy ID?",
        "example_conversation": (
            "User: Show me my insurance policy\n"
            "Trinity: What's the policy ID?\n"
            "User: pol_abc123\n"
            "Trinity: [calls platform_action with action='get_insurance_policy', params={policy_id: 'pol_abc123'}]"
        ),
    },

    "cancel_insurance": {
        "action_name": "cancel_insurance",
        "description": "Cancel an active insurance policy.",
        "required_params": [
            {"name": "policy_id", "type": "string", "description": "Policy ID to cancel.", "example": "pol_abc123"},
        ],
        "optional_params": [],
        "keywords": ["cancel insurance", "cancel policy", "end insurance", "stop insurance"],
        "follow_up": "Which policy would you like to cancel?",
        "example_conversation": (
            "User: Cancel my insurance policy\n"
            "Trinity: Which policy ID?\n"
            "User: pol_abc123\n"
            "Trinity: [calls platform_action with action='cancel_insurance', params={policy_id: 'pol_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 14 — Gaming
    # ===================================================================

    "register_game": {
        "action_name": "register_game",
        "description": "Register a new game on the platform.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Game name.", "example": "CryptoQuest"},
            {"name": "config", "type": "object", "description": "Game configuration.", "example": {"genre": "RPG", "max_players": 1000}},
        ],
        "optional_params": [],
        "keywords": ["register game", "add game", "new game", "create game", "launch game"],
        "follow_up": "What's the game called and its configuration?",
        "example_conversation": (
            "User: Register my game CryptoQuest\n"
            "Trinity: What's the game configuration — genre, max players, etc.?\n"
            "User: RPG, max 1000 players\n"
            "Trinity: [calls platform_action with action='register_game', params={name: 'CryptoQuest', config: {genre: 'RPG', max_players: 1000}}]"
        ),
    },

    "get_game": {
        "action_name": "get_game",
        "description": "Get details about a registered game.",
        "required_params": [
            {"name": "game_id", "type": "string", "description": "Game ID.", "example": "game_abc123"},
        ],
        "optional_params": [],
        "keywords": ["game info", "game details", "check game", "view game"],
        "follow_up": "Which game?",
        "example_conversation": (
            "User: Show me CryptoQuest details\n"
            "Trinity: [calls platform_action with action='get_game', params={game_id: 'cryptoquest'}]"
        ),
    },

    "mint_game_asset": {
        "action_name": "mint_game_asset",
        "description": "Mint an in-game asset as an NFT.",
        "required_params": [
            {"name": "game_id", "type": "string", "description": "Game ID.", "example": "game_abc123"},
            {"name": "asset", "type": "object", "description": "Asset details.", "example": {"name": "Legendary Sword", "type": "weapon", "rarity": "legendary"}},
        ],
        "optional_params": [],
        "keywords": ["mint game asset", "create game item", "game NFT", "in-game asset", "mint item"],
        "follow_up": "Which game and what asset?",
        "example_conversation": (
            "User: Mint a legendary sword for CryptoQuest\n"
            "Trinity: [calls platform_action with action='mint_game_asset', params={game_id: 'cryptoquest', asset: {name: 'Legendary Sword', type: 'weapon', rarity: 'legendary'}}]"
        ),
    },

    "transfer_game_asset": {
        "action_name": "transfer_game_asset",
        "description": "Transfer a game asset to another player.",
        "required_params": [
            {"name": "asset_id", "type": "string", "description": "Game asset ID.", "example": "gasset_123"},
            {"name": "to_address", "type": "string", "description": "Recipient address.", "example": "0xabc..."},
        ],
        "optional_params": [],
        "keywords": ["transfer game asset", "send game item", "trade game item", "give game asset"],
        "follow_up": "Which asset and to whom?",
        "example_conversation": (
            "User: Send my legendary sword to player bob.eth\n"
            "Trinity: [calls platform_action with action='transfer_game_asset', params={asset_id: 'gasset_123', to_address: 'bob.eth'}]"
        ),
    },

    "approve_game": {
        "action_name": "approve_game",
        "description": "Approve a game for platform listing.",
        "required_params": [
            {"name": "game_id", "type": "string", "description": "Game ID to approve.", "example": "game_abc123"},
        ],
        "optional_params": [],
        "keywords": ["approve game", "verify game", "list game", "accept game"],
        "follow_up": "Which game should be approved?",
        "example_conversation": (
            "User: Approve game CryptoQuest\n"
            "Trinity: [calls platform_action with action='approve_game', params={game_id: 'cryptoquest'}]"
        ),
    },

    # ===================================================================
    # Component 15 — IP & Royalties
    # ===================================================================

    "register_ip": {
        "action_name": "register_ip",
        "description": "Register intellectual property on-chain.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Title of the IP.", "example": "My Song Title"},
            {"name": "description", "type": "string", "description": "Description of the IP.", "example": "Original music composition"},
            {"name": "content_hash", "type": "string", "description": "Hash of the content.", "example": "QmXyz..."},
        ],
        "optional_params": [
            {"name": "royalty_bps", "type": "integer", "description": "Royalty in basis points.", "default": 1000},
            {"name": "license_type", "type": "string", "description": "Type of license.", "default": "all_rights_reserved"},
        ],
        "keywords": ["register IP", "register intellectual property", "protect IP", "IP registration", "copyright", "register my work"],
        "follow_up": "What's the title, description, and content hash of your IP?",
        "example_conversation": (
            "User: I want to register my song on-chain\n"
            "Trinity: What's the title, description, and content hash?\n"
            "User: 'Midnight Blues', jazz composition, hash QmXyz...\n"
            "Trinity: [calls platform_action with action='register_ip', params={title: 'Midnight Blues', description: 'Original jazz composition', content_hash: 'QmXyz...'}]"
        ),
    },

    "get_ip": {
        "action_name": "get_ip",
        "description": "Get details about registered intellectual property.",
        "required_params": [
            {"name": "ip_id", "type": "string", "description": "IP registration ID.", "example": "ip_abc123"},
        ],
        "optional_params": [],
        "keywords": ["IP details", "check IP", "my IP", "view IP registration"],
        "follow_up": "What's the IP registration ID?",
        "example_conversation": (
            "User: Show me IP registration ip_abc123\n"
            "Trinity: [calls platform_action with action='get_ip', params={ip_id: 'ip_abc123'}]"
        ),
    },

    "transfer_ip": {
        "action_name": "transfer_ip",
        "description": "Transfer IP ownership to another party.",
        "required_params": [
            {"name": "ip_id", "type": "string", "description": "IP registration ID.", "example": "ip_abc123"},
            {"name": "to_address", "type": "string", "description": "New owner address.", "example": "0xabc..."},
        ],
        "optional_params": [],
        "keywords": ["transfer IP", "sell IP", "give IP", "transfer ownership"],
        "follow_up": "Which IP and to whom?",
        "example_conversation": (
            "User: Transfer IP ip_abc123 to publisher.eth\n"
            "Trinity: [calls platform_action with action='transfer_ip', params={ip_id: 'ip_abc123', to_address: 'publisher.eth'}]"
        ),
    },

    "license_ip": {
        "action_name": "license_ip",
        "description": "License intellectual property to another party.",
        "required_params": [
            {"name": "ip_id", "type": "string", "description": "IP registration ID.", "example": "ip_abc123"},
            {"name": "licensee", "type": "string", "description": "Licensee address.", "example": "0xabc..."},
            {"name": "terms", "type": "object", "description": "License terms.", "example": {"duration_days": 365, "territory": "worldwide"}},
        ],
        "optional_params": [],
        "keywords": ["license IP", "grant license", "IP license", "license my work"],
        "follow_up": "Which IP, to whom, and what terms?",
        "example_conversation": (
            "User: License my song to a streaming platform\n"
            "Trinity: Which IP, what's their address, and what terms?\n"
            "User: ip_abc123, address 0xabc, 1 year worldwide\n"
            "Trinity: [calls platform_action with action='license_ip', params={ip_id: 'ip_abc123', licensee: '0xabc', terms: {duration_days: 365, territory: 'worldwide'}}]"
        ),
    },

    # ===================================================================
    # Component 16 — Staking
    # ===================================================================

    "stake": {
        "action_name": "stake",
        "description": "Stake tokens in a staking pool to earn rewards.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Amount to stake.", "example": 10.0},
            {"name": "pool_id", "type": "string", "description": "ID of the staking pool.", "example": "eth-staking-v2"},
        ],
        "optional_params": [
            {"name": "lock_period", "type": "integer", "description": "Lock period in days.", "default": None},
        ],
        "keywords": ["stake", "stake tokens", "staking", "earn rewards", "delegate", "stake my tokens", "stake ETH"],
        "follow_up": "How much would you like to stake, and in which pool?",
        "example_conversation": (
            "User: I want to stake 10 ETH\n"
            "Trinity: Which staking pool?\n"
            "User: The main ETH pool\n"
            "Trinity: [calls platform_action with action='stake', params={amount: 10.0, pool_id: 'eth-staking-v2'}]"
        ),
    },

    "unstake": {
        "action_name": "unstake",
        "description": "Unstake tokens from a staking pool.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Amount to unstake.", "example": 5.0},
            {"name": "pool_id", "type": "string", "description": "Pool ID.", "example": "eth-staking-v2"},
        ],
        "optional_params": [],
        "keywords": ["unstake", "withdraw stake", "remove stake", "stop staking", "unstake tokens"],
        "follow_up": "How much and from which pool?",
        "example_conversation": (
            "User: Unstake 5 ETH from the main pool\n"
            "Trinity: [calls platform_action with action='unstake', params={amount: 5.0, pool_id: 'eth-staking-v2'}]"
        ),
    },

    "claim_staking_rewards": {
        "action_name": "claim_staking_rewards",
        "description": "Claim accumulated staking rewards.",
        "required_params": [
            {"name": "pool_id", "type": "string", "description": "Pool ID.", "example": "eth-staking-v2"},
        ],
        "optional_params": [],
        "keywords": ["claim rewards", "collect rewards", "get rewards", "staking rewards", "harvest rewards", "claim my rewards"],
        "follow_up": "Which staking pool?",
        "example_conversation": (
            "User: Claim my staking rewards\n"
            "Trinity: Which pool?\n"
            "User: The ETH pool\n"
            "Trinity: [calls platform_action with action='claim_staking_rewards', params={pool_id: 'eth-staking-v2'}]"
        ),
    },

    "get_staking_position": {
        "action_name": "get_staking_position",
        "description": "View your staking position and accumulated rewards.",
        "required_params": [
            {"name": "pool_id", "type": "string", "description": "Pool ID.", "example": "eth-staking-v2"},
        ],
        "optional_params": [],
        "keywords": ["staking position", "my staking", "staking status", "how much staked", "staking info"],
        "follow_up": "Which pool?",
        "example_conversation": (
            "User: What's my staking position?\n"
            "Trinity: Which pool?\n"
            "User: ETH pool\n"
            "Trinity: [calls platform_action with action='get_staking_position', params={pool_id: 'eth-staking-v2'}]"
        ),
    },

    # ===================================================================
    # Component 17 — Cross-Border Payments
    # ===================================================================

    "send_payment": {
        "action_name": "send_payment",
        "description": "Send a cross-border payment.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient address or ENS.", "example": "alice.eth"},
            {"name": "amount", "type": "number", "description": "Amount to send.", "example": 100},
            {"name": "currency", "type": "string", "description": "Currency to send.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "memo", "type": "string", "description": "Payment memo.", "default": ""},
        ],
        "keywords": ["send money", "transfer", "pay", "send tokens", "send to", "transfer funds", "wire", "send payment", "pay someone"],
        "follow_up": "Who, how much, and in what currency?",
        "example_conversation": (
            "User: Send 100 USDC to alice.eth\n"
            "Trinity: [calls platform_action with action='send_payment', params={recipient: 'alice.eth', amount: 100, currency: 'USDC'}]"
        ),
    },

    "get_payment_quote": {
        "action_name": "get_payment_quote",
        "description": "Get a quote for a cross-border payment including fees and exchange rates.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Amount to send.", "example": 1000},
            {"name": "from_currency", "type": "string", "description": "Source currency.", "example": "USD"},
            {"name": "to_currency", "type": "string", "description": "Destination currency.", "example": "EUR"},
        ],
        "optional_params": [],
        "keywords": ["payment quote", "how much to send", "transfer quote", "fee quote", "exchange rate"],
        "follow_up": "How much, from what currency, and to what currency?",
        "example_conversation": (
            "User: How much would it cost to send 1000 USD to Europe?\n"
            "Trinity: [calls platform_action with action='get_payment_quote', params={amount: 1000, from_currency: 'USD', to_currency: 'EUR'}]"
        ),
    },

    "get_cross_border_payment": {
        "action_name": "get_cross_border_payment",
        "description": "Get details of a cross-border payment.",
        "required_params": [
            {"name": "payment_id", "type": "string", "description": "Payment ID.", "example": "cbp_abc123"},
        ],
        "optional_params": [],
        "keywords": ["payment status", "track payment", "cross-border status", "international payment status"],
        "follow_up": "What's the payment ID?",
        "example_conversation": (
            "User: Check status of payment cbp_abc123\n"
            "Trinity: [calls platform_action with action='get_cross_border_payment', params={payment_id: 'cbp_abc123'}]"
        ),
    },

    "list_cross_border_payments": {
        "action_name": "list_cross_border_payments",
        "description": "List all cross-border payments.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["my transfers", "international payments", "cross-border history", "transfer history"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my international transfers\n"
            "Trinity: [calls platform_action with action='list_cross_border_payments', params={}]"
        ),
    },

    # ===================================================================
    # Component 18 — Securities Exchange
    # ===================================================================

    "create_security": {
        "action_name": "create_security",
        "description": "Create a tokenized security.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Security name.", "example": "TechCorp Equity"},
            {"name": "type", "type": "string", "description": "Security type (equity, bond, fund).", "example": "equity"},
            {"name": "total_supply", "type": "integer", "description": "Total token supply.", "example": 1000000},
        ],
        "optional_params": [
            {"name": "price", "type": "number", "description": "Initial price per token.", "default": 1.0},
        ],
        "keywords": ["create security", "tokenize security", "issue security", "new security", "create equity", "create bond"],
        "follow_up": "What's the security name, type, and total supply?",
        "example_conversation": (
            "User: Create a tokenized equity for my company\n"
            "Trinity: What's the name, total supply, and initial price?\n"
            "User: TechCorp Equity, 1 million tokens at $1 each\n"
            "Trinity: [calls platform_action with action='create_security', params={name: 'TechCorp Equity', type: 'equity', total_supply: 1000000, price: 1.0}]"
        ),
    },

    "list_security": {
        "action_name": "list_security",
        "description": "List a security for trading on the exchange.",
        "required_params": [
            {"name": "security_id", "type": "string", "description": "Security ID.", "example": "sec_abc123"},
            {"name": "price", "type": "number", "description": "Listing price.", "example": 10.0},
        ],
        "optional_params": [],
        "keywords": ["list security", "offer security", "sell security shares", "list for trading"],
        "follow_up": "Which security and at what price?",
        "example_conversation": (
            "User: List my TechCorp tokens at $10\n"
            "Trinity: [calls platform_action with action='list_security', params={security_id: 'sec_abc123', price: 10.0}]"
        ),
    },

    "buy_security": {
        "action_name": "buy_security",
        "description": "Buy tokenized securities.",
        "required_params": [
            {"name": "security_id", "type": "string", "description": "Security ID.", "example": "sec_abc123"},
            {"name": "amount", "type": "integer", "description": "Number of tokens to buy.", "example": 100},
        ],
        "optional_params": [
            {"name": "max_price", "type": "number", "description": "Maximum price per token.", "default": None},
        ],
        "keywords": ["buy security", "purchase shares", "buy equity", "invest in security", "buy tokens"],
        "follow_up": "Which security and how many tokens?",
        "example_conversation": (
            "User: Buy 100 TechCorp tokens\n"
            "Trinity: [calls platform_action with action='buy_security', params={security_id: 'sec_abc123', amount: 100}]"
        ),
    },

    "sell_security": {
        "action_name": "sell_security",
        "description": "Sell tokenized securities.",
        "required_params": [
            {"name": "security_id", "type": "string", "description": "Security ID.", "example": "sec_abc123"},
            {"name": "amount", "type": "integer", "description": "Number of tokens to sell.", "example": 50},
        ],
        "optional_params": [
            {"name": "min_price", "type": "number", "description": "Minimum acceptable price.", "default": None},
        ],
        "keywords": ["sell security", "sell shares", "sell equity", "sell my tokens"],
        "follow_up": "Which security and how many tokens?",
        "example_conversation": (
            "User: Sell 50 TechCorp tokens\n"
            "Trinity: [calls platform_action with action='sell_security', params={security_id: 'sec_abc123', amount: 50}]"
        ),
    },

    "get_security": {
        "action_name": "get_security",
        "description": "Get details about a security.",
        "required_params": [
            {"name": "security_id", "type": "string", "description": "Security ID.", "example": "sec_abc123"},
        ],
        "optional_params": [],
        "keywords": ["security info", "security details", "check security", "security price"],
        "follow_up": "Which security?",
        "example_conversation": (
            "User: Show me TechCorp security info\n"
            "Trinity: [calls platform_action with action='get_security', params={security_id: 'sec_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 19 — Governance
    # ===================================================================

    "create_proposal": {
        "action_name": "create_proposal",
        "description": "Create a new governance proposal.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Proposal title.", "example": "Increase staking rewards by 2%"},
            {"name": "description", "type": "string", "description": "Detailed description.", "example": "This proposal seeks to..."},
            {"name": "actions", "type": "array", "description": "On-chain actions if passed.", "example": [{"target": "0x...", "value": 0, "calldata": "0x..."}]},
        ],
        "optional_params": [
            {"name": "dao_id", "type": "string", "description": "DAO to submit to.", "default": None},
        ],
        "keywords": ["create proposal", "new proposal", "submit proposal", "propose", "governance proposal"],
        "follow_up": "What's the title, description, and what actions should it trigger?",
        "example_conversation": (
            "User: I want to propose increasing staking rewards\n"
            "Trinity: What should the title be, details, and on-chain action?\n"
            "User: Title: 'Increase rewards to 5%'\n"
            "Trinity: [calls platform_action with action='create_proposal', params={title: 'Increase rewards to 5%', description: '...', actions: [...]}]"
        ),
    },

    "vote": {
        "action_name": "vote",
        "description": "Cast a vote on a governance proposal.",
        "required_params": [
            {"name": "proposal_id", "type": "string", "description": "Proposal ID.", "example": "prop_001"},
            {"name": "support", "type": "boolean", "description": "True = for, False = against.", "example": True},
        ],
        "optional_params": [
            {"name": "reason", "type": "string", "description": "Reason for vote.", "default": ""},
        ],
        "keywords": ["vote", "cast vote", "vote on proposal", "vote yes", "vote no", "vote for", "vote against"],
        "follow_up": "Which proposal and are you voting for or against?",
        "example_conversation": (
            "User: Vote yes on proposal 1\n"
            "Trinity: [calls platform_action with action='vote', params={proposal_id: 'prop_001', support: true}]"
        ),
    },

    "get_proposal": {
        "action_name": "get_proposal",
        "description": "Get details about a governance proposal.",
        "required_params": [
            {"name": "proposal_id", "type": "string", "description": "Proposal ID.", "example": "prop_001"},
        ],
        "optional_params": [],
        "keywords": ["proposal details", "check proposal", "view proposal", "proposal info", "proposal status"],
        "follow_up": "Which proposal?",
        "example_conversation": (
            "User: What's proposal 1 about?\n"
            "Trinity: [calls platform_action with action='get_proposal', params={proposal_id: 'prop_001'}]"
        ),
    },

    "finalize_proposal": {
        "action_name": "finalize_proposal",
        "description": "Finalize a governance proposal after voting ends.",
        "required_params": [
            {"name": "proposal_id", "type": "string", "description": "Proposal ID.", "example": "prop_001"},
        ],
        "optional_params": [],
        "keywords": ["finalize proposal", "execute proposal", "close proposal", "end voting"],
        "follow_up": "Which proposal should be finalized?",
        "example_conversation": (
            "User: Finalize proposal 1\n"
            "Trinity: [calls platform_action with action='finalize_proposal', params={proposal_id: 'prop_001'}]"
        ),
    },

    "list_proposals": {
        "action_name": "list_proposals",
        "description": "List all governance proposals.",
        "required_params": [],
        "optional_params": [
            {"name": "status", "type": "string", "description": "Filter by status (active, passed, rejected).", "default": "all"},
            {"name": "dao_id", "type": "string", "description": "Filter by DAO.", "default": None},
        ],
        "keywords": ["list proposals", "all proposals", "active proposals", "show proposals", "governance proposals"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me all active proposals\n"
            "Trinity: [calls platform_action with action='list_proposals', params={status: 'active'}]"
        ),
    },

    # ===================================================================
    # Component 20 — Dashboard
    # ===================================================================

    "get_dashboard": {
        "action_name": "get_dashboard",
        "description": "Show portfolio overview, balances, and positions.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["check balance", "my balance", "portfolio", "dashboard", "how much do I have", "my account", "show my assets", "what do I own", "my holdings"],
        "follow_up": "",
        "example_conversation": (
            "User: What's my balance?\n"
            "Trinity: [calls platform_action with action='get_dashboard', params={}]"
        ),
    },

    "get_activity": {
        "action_name": "get_activity",
        "description": "Get recent account activity and transactions.",
        "required_params": [],
        "optional_params": [
            {"name": "limit", "type": "integer", "description": "Number of recent activities.", "default": 20},
        ],
        "keywords": ["recent activity", "my activity", "transaction history", "what happened", "recent transactions"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my recent activity\n"
            "Trinity: [calls platform_action with action='get_activity', params={}]"
        ),
    },

    "get_component_status": {
        "action_name": "get_component_status",
        "description": "Check the status of platform components.",
        "required_params": [],
        "optional_params": [
            {"name": "component", "type": "string", "description": "Specific component to check.", "default": "all"},
        ],
        "keywords": ["component status", "platform status", "system status", "is service running", "health check"],
        "follow_up": "",
        "example_conversation": (
            "User: Are all services running?\n"
            "Trinity: [calls platform_action with action='get_component_status', params={}]"
        ),
    },

    "get_platform_stats": {
        "action_name": "get_platform_stats",
        "description": "Get platform-wide statistics.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["platform stats", "statistics", "total users", "platform metrics", "platform numbers"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me platform statistics\n"
            "Trinity: [calls platform_action with action='get_platform_stats', params={}]"
        ),
    },

    # ===================================================================
    # Component 21 — DEX
    # ===================================================================

    "swap_tokens": {
        "action_name": "swap_tokens",
        "description": "Swap one token for another on a DEX.",
        "required_params": [
            {"name": "token_in", "type": "string", "description": "Token to swap from.", "example": "ETH"},
            {"name": "token_out", "type": "string", "description": "Token to swap to.", "example": "USDC"},
            {"name": "amount", "type": "number", "description": "Amount of token_in.", "example": 1.0},
        ],
        "optional_params": [
            {"name": "slippage", "type": "number", "description": "Max slippage %.", "default": 0.5},
        ],
        "keywords": ["swap tokens", "exchange tokens", "trade tokens", "swap", "convert tokens", "swap ETH", "trade"],
        "follow_up": "What token, to what, and how much?",
        "example_conversation": (
            "User: Swap 1 ETH for USDC\n"
            "Trinity: [calls platform_action with action='swap_tokens', params={token_in: 'ETH', token_out: 'USDC', amount: 1.0}]"
        ),
    },

    "get_swap_quote": {
        "action_name": "get_swap_quote",
        "description": "Get a price quote for a token swap.",
        "required_params": [
            {"name": "token_in", "type": "string", "description": "Token to swap from.", "example": "ETH"},
            {"name": "token_out", "type": "string", "description": "Token to swap to.", "example": "USDC"},
            {"name": "amount", "type": "number", "description": "Amount.", "example": 1.0},
        ],
        "optional_params": [],
        "keywords": ["swap quote", "how much will I get", "exchange rate", "swap price", "quote"],
        "follow_up": "What tokens and amount?",
        "example_conversation": (
            "User: How much USDC would I get for 1 ETH?\n"
            "Trinity: [calls platform_action with action='get_swap_quote', params={token_in: 'ETH', token_out: 'USDC', amount: 1.0}]"
        ),
    },

    "add_liquidity": {
        "action_name": "add_liquidity",
        "description": "Add liquidity to a DEX pool.",
        "required_params": [
            {"name": "token_a", "type": "string", "description": "First token.", "example": "ETH"},
            {"name": "token_b", "type": "string", "description": "Second token.", "example": "USDC"},
            {"name": "amount_a", "type": "number", "description": "Amount of first token.", "example": 1.0},
            {"name": "amount_b", "type": "number", "description": "Amount of second token.", "example": 3000},
        ],
        "optional_params": [],
        "keywords": ["add liquidity", "provide liquidity", "LP", "liquidity pool", "become LP"],
        "follow_up": "Which pair and how much of each token?",
        "example_conversation": (
            "User: Add liquidity to ETH/USDC pool\n"
            "Trinity: How much ETH and USDC?\n"
            "User: 1 ETH and 3000 USDC\n"
            "Trinity: [calls platform_action with action='add_liquidity', params={token_a: 'ETH', token_b: 'USDC', amount_a: 1.0, amount_b: 3000}]"
        ),
    },

    "remove_liquidity": {
        "action_name": "remove_liquidity",
        "description": "Remove liquidity from a DEX pool.",
        "required_params": [
            {"name": "pool_id", "type": "string", "description": "Pool ID.", "example": "eth-usdc-pool"},
            {"name": "percentage", "type": "number", "description": "Percentage of position to remove.", "example": 100},
        ],
        "optional_params": [],
        "keywords": ["remove liquidity", "withdraw liquidity", "exit pool", "remove LP"],
        "follow_up": "Which pool and how much?",
        "example_conversation": (
            "User: Remove all my liquidity from ETH/USDC\n"
            "Trinity: [calls platform_action with action='remove_liquidity', params={pool_id: 'eth-usdc-pool', percentage: 100}]"
        ),
    },

    "get_dex_positions": {
        "action_name": "get_dex_positions",
        "description": "View your DEX liquidity positions.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["my positions", "LP positions", "liquidity positions", "DEX positions"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my liquidity positions\n"
            "Trinity: [calls platform_action with action='get_dex_positions', params={}]"
        ),
    },

    # ===================================================================
    # Component 22 — Fundraising
    # ===================================================================

    "create_campaign": {
        "action_name": "create_campaign",
        "description": "Create a fundraising campaign with milestones.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Campaign title.", "example": "Build a Community Garden"},
            {"name": "goal", "type": "number", "description": "Fundraising goal.", "example": 10000},
            {"name": "milestones", "type": "array", "description": "Milestones.", "example": [{"title": "Phase 1", "amount": 5000}]},
        ],
        "optional_params": [
            {"name": "deadline", "type": "string", "description": "Campaign deadline (ISO date).", "default": None},
            {"name": "currency", "type": "string", "description": "Currency.", "default": "USDC"},
        ],
        "keywords": ["fundraising", "create campaign", "crowdfund", "raise money", "fundraise", "start a campaign"],
        "follow_up": "What's your campaign title, goal, and milestones?",
        "example_conversation": (
            "User: Start a fundraising campaign\n"
            "Trinity: What's the campaign about, goal, and milestones?\n"
            "User: Community Garden, 10k goal, two milestones at 5k and 10k\n"
            "Trinity: [calls platform_action with action='create_campaign', params={title: 'Build a Community Garden', goal: 10000, milestones: [...]}]"
        ),
    },

    "contribute_to_campaign": {
        "action_name": "contribute_to_campaign",
        "description": "Contribute funds to a fundraising campaign.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "camp_abc123"},
            {"name": "amount", "type": "number", "description": "Contribution amount.", "example": 100},
        ],
        "optional_params": [],
        "keywords": ["contribute", "donate", "fund campaign", "support campaign", "back project"],
        "follow_up": "Which campaign and how much?",
        "example_conversation": (
            "User: Donate 100 USDC to the garden campaign\n"
            "Trinity: [calls platform_action with action='contribute_to_campaign', params={campaign_id: 'camp_abc123', amount: 100}]"
        ),
    },

    "get_campaign": {
        "action_name": "get_campaign",
        "description": "Get details about a fundraising campaign.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "camp_abc123"},
        ],
        "optional_params": [],
        "keywords": ["campaign details", "campaign info", "check campaign", "campaign status"],
        "follow_up": "Which campaign?",
        "example_conversation": (
            "User: How's the garden campaign doing?\n"
            "Trinity: [calls platform_action with action='get_campaign', params={campaign_id: 'camp_abc123'}]"
        ),
    },

    "list_campaigns": {
        "action_name": "list_campaigns",
        "description": "List all fundraising campaigns.",
        "required_params": [],
        "optional_params": [
            {"name": "status", "type": "string", "description": "Filter by status.", "default": "active"},
        ],
        "keywords": ["list campaigns", "all campaigns", "active campaigns", "browse campaigns"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me active campaigns\n"
            "Trinity: [calls platform_action with action='list_campaigns', params={status: 'active'}]"
        ),
    },

    "release_milestone_funds": {
        "action_name": "release_milestone_funds",
        "description": "Release funds for a completed campaign milestone.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "camp_abc123"},
            {"name": "milestone_index", "type": "integer", "description": "Milestone index.", "example": 0},
        ],
        "optional_params": [],
        "keywords": ["release funds", "milestone release", "release milestone", "unlock funds"],
        "follow_up": "Which campaign and milestone?",
        "example_conversation": (
            "User: Release funds for milestone 1 of the garden campaign\n"
            "Trinity: [calls platform_action with action='release_milestone_funds', params={campaign_id: 'camp_abc123', milestone_index: 0}]"
        ),
    },

    "trigger_refunds": {
        "action_name": "trigger_refunds",
        "description": "Trigger refunds for a failed campaign.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "camp_abc123"},
        ],
        "optional_params": [],
        "keywords": ["refund campaign", "trigger refunds", "campaign refund", "get money back"],
        "follow_up": "Which campaign should be refunded?",
        "example_conversation": (
            "User: The campaign failed, trigger refunds\n"
            "Trinity: [calls platform_action with action='trigger_refunds', params={campaign_id: 'camp_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 23 — Loyalty
    # ===================================================================

    "earn_loyalty": {
        "action_name": "earn_loyalty",
        "description": "Earn loyalty points from a transaction or activity.",
        "required_params": [
            {"name": "activity", "type": "string", "description": "Activity type.", "example": "transaction"},
            {"name": "amount", "type": "number", "description": "Transaction amount for points calculation.", "example": 100},
        ],
        "optional_params": [],
        "keywords": ["earn points", "loyalty points", "earn loyalty", "get points"],
        "follow_up": "What activity are the points for?",
        "example_conversation": (
            "User: I made a transaction, do I get loyalty points?\n"
            "Trinity: [calls platform_action with action='earn_loyalty', params={activity: 'transaction', amount: 100}]"
        ),
    },

    "redeem_loyalty": {
        "action_name": "redeem_loyalty",
        "description": "Redeem loyalty points for rewards.",
        "required_params": [
            {"name": "points", "type": "integer", "description": "Number of points to redeem.", "example": 500},
            {"name": "reward_id", "type": "string", "description": "Reward to redeem for.", "example": "reward_discount_10"},
        ],
        "optional_params": [],
        "keywords": ["redeem points", "use points", "redeem loyalty", "cash in points", "spend points"],
        "follow_up": "How many points and for what reward?",
        "example_conversation": (
            "User: Redeem 500 points for a discount\n"
            "Trinity: [calls platform_action with action='redeem_loyalty', params={points: 500, reward_id: 'reward_discount_10'}]"
        ),
    },

    "get_loyalty_balance": {
        "action_name": "get_loyalty_balance",
        "description": "Check your loyalty points balance.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["loyalty balance", "my points", "how many points", "points balance", "check points"],
        "follow_up": "",
        "example_conversation": (
            "User: How many loyalty points do I have?\n"
            "Trinity: [calls platform_action with action='get_loyalty_balance', params={}]"
        ),
    },

    "get_loyalty_tier": {
        "action_name": "get_loyalty_tier",
        "description": "Check your current loyalty tier.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["loyalty tier", "my tier", "loyalty level", "what tier am I", "loyalty status"],
        "follow_up": "",
        "example_conversation": (
            "User: What's my loyalty tier?\n"
            "Trinity: [calls platform_action with action='get_loyalty_tier', params={}]"
        ),
    },

    # ===================================================================
    # Component 24 — Marketplace
    # ===================================================================

    "list_marketplace": {
        "action_name": "list_marketplace",
        "description": "List an item for sale on the marketplace.",
        "required_params": [
            {"name": "item", "type": "object", "description": "Item details.", "example": {"name": "Rare Sword", "type": "game_asset"}},
            {"name": "price", "type": "number", "description": "Listing price.", "example": 50},
        ],
        "optional_params": [
            {"name": "currency", "type": "string", "description": "Currency.", "default": "USDC"},
        ],
        "keywords": ["list on marketplace", "sell on marketplace", "marketplace listing", "put up for sale"],
        "follow_up": "What item and at what price?",
        "example_conversation": (
            "User: List my rare sword for 50 USDC\n"
            "Trinity: [calls platform_action with action='list_marketplace', params={item: {name: 'Rare Sword'}, price: 50}]"
        ),
    },

    "buy_marketplace": {
        "action_name": "buy_marketplace",
        "description": "Buy an item from the marketplace.",
        "required_params": [
            {"name": "listing_id", "type": "string", "description": "Listing ID.", "example": "listing_abc123"},
        ],
        "optional_params": [],
        "keywords": ["buy from marketplace", "purchase listing", "buy item", "marketplace buy"],
        "follow_up": "Which listing?",
        "example_conversation": (
            "User: Buy listing_abc123\n"
            "Trinity: [calls platform_action with action='buy_marketplace', params={listing_id: 'listing_abc123'}]"
        ),
    },

    "cancel_listing": {
        "action_name": "cancel_listing",
        "description": "Cancel a marketplace listing.",
        "required_params": [
            {"name": "listing_id", "type": "string", "description": "Listing ID.", "example": "listing_abc123"},
        ],
        "optional_params": [],
        "keywords": ["cancel listing", "remove listing", "take down listing", "delist"],
        "follow_up": "Which listing?",
        "example_conversation": (
            "User: Cancel my listing listing_abc123\n"
            "Trinity: [calls platform_action with action='cancel_listing', params={listing_id: 'listing_abc123'}]"
        ),
    },

    "search_marketplace": {
        "action_name": "search_marketplace",
        "description": "Search the marketplace for items.",
        "required_params": [
            {"name": "query", "type": "string", "description": "Search query.", "example": "legendary sword"},
        ],
        "optional_params": [
            {"name": "category", "type": "string", "description": "Category filter.", "default": None},
            {"name": "max_price", "type": "number", "description": "Maximum price.", "default": None},
        ],
        "keywords": ["search marketplace", "find items", "browse marketplace", "marketplace search", "shop"],
        "follow_up": "What are you looking for?",
        "example_conversation": (
            "User: Search for legendary swords under 100 USDC\n"
            "Trinity: [calls platform_action with action='search_marketplace', params={query: 'legendary sword', max_price: 100}]"
        ),
    },

    "get_listing": {
        "action_name": "get_listing",
        "description": "Get details of a marketplace listing.",
        "required_params": [
            {"name": "listing_id", "type": "string", "description": "Listing ID.", "example": "listing_abc123"},
        ],
        "optional_params": [],
        "keywords": ["listing details", "view listing", "listing info", "check listing"],
        "follow_up": "Which listing?",
        "example_conversation": (
            "User: Show me listing listing_abc123\n"
            "Trinity: [calls platform_action with action='get_listing', params={listing_id: 'listing_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 25 — Cashback
    # ===================================================================

    "track_spending": {
        "action_name": "track_spending",
        "description": "Track a transaction for cashback eligibility.",
        "required_params": [
            {"name": "transaction_id", "type": "string", "description": "Transaction ID.", "example": "tx_abc123"},
            {"name": "amount", "type": "number", "description": "Transaction amount.", "example": 50},
        ],
        "optional_params": [],
        "keywords": ["track spending", "record purchase", "cashback transaction", "log spending"],
        "follow_up": "Which transaction?",
        "example_conversation": (
            "User: Track my purchase for cashback\n"
            "Trinity: [calls platform_action with action='track_spending', params={transaction_id: 'tx_abc123', amount: 50}]"
        ),
    },

    "get_cashback_balance": {
        "action_name": "get_cashback_balance",
        "description": "Check your accumulated cashback balance.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["cashback balance", "my cashback", "how much cashback", "cashback earned"],
        "follow_up": "",
        "example_conversation": (
            "User: How much cashback have I earned?\n"
            "Trinity: [calls platform_action with action='get_cashback_balance', params={}]"
        ),
    },

    "claim_cashback": {
        "action_name": "claim_cashback",
        "description": "Claim your accumulated cashback.",
        "required_params": [],
        "optional_params": [
            {"name": "amount", "type": "number", "description": "Specific amount to claim.", "default": None},
        ],
        "keywords": ["claim cashback", "withdraw cashback", "get my cashback", "redeem cashback"],
        "follow_up": "Would you like to claim all your cashback or a specific amount?",
        "example_conversation": (
            "User: Claim all my cashback\n"
            "Trinity: [calls platform_action with action='claim_cashback', params={}]"
        ),
    },

    "get_spending_summary": {
        "action_name": "get_spending_summary",
        "description": "Get a summary of your spending and cashback history.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["spending summary", "spending history", "cashback summary", "my spending"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my spending summary\n"
            "Trinity: [calls platform_action with action='get_spending_summary', params={}]"
        ),
    },

    # ===================================================================
    # Component 26 — Brand Rewards
    # ===================================================================

    "create_brand_campaign": {
        "action_name": "create_brand_campaign",
        "description": "Create a brand-sponsored reward campaign.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Campaign name.", "example": "Summer Sale Rewards"},
            {"name": "reward_type", "type": "string", "description": "Type of reward (discount, tokens, cashback).", "example": "discount"},
            {"name": "budget", "type": "number", "description": "Campaign budget.", "example": 10000},
        ],
        "optional_params": [
            {"name": "eligibility", "type": "object", "description": "Eligibility criteria.", "default": {}},
        ],
        "keywords": ["brand campaign", "create brand reward", "brand rewards", "sponsor campaign", "brand promotion"],
        "follow_up": "What's the campaign name, reward type, and budget?",
        "example_conversation": (
            "User: Create a brand rewards campaign\n"
            "Trinity: What's the campaign name, reward type, and budget?\n"
            "User: Summer Sale Rewards, discount type, 10k budget\n"
            "Trinity: [calls platform_action with action='create_brand_campaign', params={name: 'Summer Sale Rewards', reward_type: 'discount', budget: 10000}]"
        ),
    },

    "distribute_brand_reward": {
        "action_name": "distribute_brand_reward",
        "description": "Distribute rewards from a brand campaign.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "brand_abc123"},
            {"name": "recipients", "type": "array", "description": "List of recipient addresses.", "example": ["0xabc...", "0xdef..."]},
        ],
        "optional_params": [],
        "keywords": ["distribute reward", "send brand reward", "give rewards", "distribute brand"],
        "follow_up": "Which campaign and to whom?",
        "example_conversation": (
            "User: Distribute rewards from the summer campaign\n"
            "Trinity: [calls platform_action with action='distribute_brand_reward', params={campaign_id: 'brand_abc123', recipients: [...]}]"
        ),
    },

    "get_brand_campaign": {
        "action_name": "get_brand_campaign",
        "description": "Get details of a brand campaign.",
        "required_params": [
            {"name": "campaign_id", "type": "string", "description": "Campaign ID.", "example": "brand_abc123"},
        ],
        "optional_params": [],
        "keywords": ["brand campaign info", "campaign details", "check brand campaign"],
        "follow_up": "Which campaign?",
        "example_conversation": (
            "User: Show me the summer campaign details\n"
            "Trinity: [calls platform_action with action='get_brand_campaign', params={campaign_id: 'brand_abc123'}]"
        ),
    },

    "list_brand_campaigns": {
        "action_name": "list_brand_campaigns",
        "description": "List all brand reward campaigns.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["list brand campaigns", "all brand campaigns", "brand promotions", "available brand rewards"],
        "follow_up": "",
        "example_conversation": (
            "User: Show me all brand campaigns\n"
            "Trinity: [calls platform_action with action='list_brand_campaigns', params={}]"
        ),
    },

    # ===================================================================
    # Component 27 — Subscriptions
    # ===================================================================

    "create_subscription_plan": {
        "action_name": "create_subscription_plan",
        "description": "Create a new on-chain subscription plan.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Plan name.", "example": "Premium Monthly"},
            {"name": "price", "type": "number", "description": "Price per period.", "example": 9.99},
            {"name": "interval", "type": "string", "description": "Billing interval (daily, weekly, monthly, yearly).", "example": "monthly"},
        ],
        "optional_params": [
            {"name": "trial_days", "type": "integer", "description": "Free trial days.", "default": 0},
        ],
        "keywords": ["create plan", "subscription plan", "new plan", "set up subscription", "create subscription"],
        "follow_up": "What's the plan name, price, and billing interval?",
        "example_conversation": (
            "User: Create a monthly subscription plan\n"
            "Trinity: What's the name, price, and interval?\n"
            "User: Premium Monthly, $9.99/month\n"
            "Trinity: [calls platform_action with action='create_subscription_plan', params={name: 'Premium Monthly', price: 9.99, interval: 'monthly'}]"
        ),
    },

    "subscribe": {
        "action_name": "subscribe",
        "description": "Subscribe to a plan or service.",
        "required_params": [
            {"name": "plan_id", "type": "string", "description": "Plan ID.", "example": "plan_premium_monthly"},
        ],
        "optional_params": [
            {"name": "auto_renew", "type": "boolean", "description": "Enable auto-renewal.", "default": True},
        ],
        "keywords": ["subscribe", "subscription", "sign up for plan", "join plan", "subscribe to", "membership"],
        "follow_up": "Which plan would you like to subscribe to?",
        "example_conversation": (
            "User: Subscribe to the premium plan\n"
            "Trinity: [calls platform_action with action='subscribe', params={plan_id: 'plan_premium_monthly'}]"
        ),
    },

    "cancel_subscription": {
        "action_name": "cancel_subscription",
        "description": "Cancel an active subscription.",
        "required_params": [
            {"name": "subscription_id", "type": "string", "description": "Subscription ID.", "example": "sub_abc123"},
        ],
        "optional_params": [],
        "keywords": ["cancel subscription", "unsubscribe", "stop subscription", "end subscription", "cancel plan"],
        "follow_up": "Which subscription would you like to cancel?",
        "example_conversation": (
            "User: Cancel my premium subscription\n"
            "Trinity: [calls platform_action with action='cancel_subscription', params={subscription_id: 'sub_abc123'}]"
        ),
    },

    "get_subscription": {
        "action_name": "get_subscription",
        "description": "Get details of a subscription.",
        "required_params": [
            {"name": "subscription_id", "type": "string", "description": "Subscription ID.", "example": "sub_abc123"},
        ],
        "optional_params": [],
        "keywords": ["subscription status", "my subscription", "check subscription", "subscription details"],
        "follow_up": "Which subscription?",
        "example_conversation": (
            "User: What's the status of my subscription?\n"
            "Trinity: [calls platform_action with action='get_subscription', params={subscription_id: 'sub_abc123'}]"
        ),
    },

    # ===================================================================
    # Component 28 — Social
    # ===================================================================

    "create_social_profile": {
        "action_name": "create_social_profile",
        "description": "Create a social profile on the platform.",
        "required_params": [
            {"name": "username", "type": "string", "description": "Username.", "example": "alice_web3"},
            {"name": "display_name", "type": "string", "description": "Display name.", "example": "Alice"},
        ],
        "optional_params": [
            {"name": "bio", "type": "string", "description": "Profile bio.", "default": ""},
            {"name": "avatar", "type": "string", "description": "Avatar URL.", "default": None},
        ],
        "keywords": ["create profile", "social profile", "set up profile", "new profile", "create account"],
        "follow_up": "What username and display name would you like?",
        "example_conversation": (
            "User: Create a social profile\n"
            "Trinity: What username and display name?\n"
            "User: alice_web3, display name Alice\n"
            "Trinity: [calls platform_action with action='create_social_profile', params={username: 'alice_web3', display_name: 'Alice'}]"
        ),
    },

    "update_social_profile": {
        "action_name": "update_social_profile",
        "description": "Update your social profile.",
        "required_params": [
            {"name": "updates", "type": "object", "description": "Fields to update.", "example": {"bio": "DeFi enthusiast"}},
        ],
        "optional_params": [],
        "keywords": ["update profile", "edit profile", "change bio", "update avatar", "modify profile"],
        "follow_up": "What would you like to update?",
        "example_conversation": (
            "User: Update my bio to 'DeFi enthusiast'\n"
            "Trinity: [calls platform_action with action='update_social_profile', params={updates: {bio: 'DeFi enthusiast'}}]"
        ),
    },

    "get_social_profile": {
        "action_name": "get_social_profile",
        "description": "View a social profile.",
        "required_params": [
            {"name": "username", "type": "string", "description": "Username to look up.", "example": "alice_web3"},
        ],
        "optional_params": [],
        "keywords": ["view profile", "check profile", "who is", "profile info", "user profile"],
        "follow_up": "Whose profile?",
        "example_conversation": (
            "User: Show alice_web3's profile\n"
            "Trinity: [calls platform_action with action='get_social_profile', params={username: 'alice_web3'}]"
        ),
    },

    "send_message": {
        "action_name": "send_message",
        "description": "Send a message to another user.",
        "required_params": [
            {"name": "to", "type": "string", "description": "Recipient username.", "example": "alice_web3"},
            {"name": "content", "type": "string", "description": "Message content.", "example": "Hey, want to join our DAO?"},
        ],
        "optional_params": [],
        "keywords": ["send message", "message user", "DM", "direct message", "chat with"],
        "follow_up": "Who and what message?",
        "example_conversation": (
            "User: Message alice about joining our DAO\n"
            "Trinity: [calls platform_action with action='send_message', params={to: 'alice_web3', content: 'Hey, want to join our DAO?'}]"
        ),
    },

    "get_social_feed": {
        "action_name": "get_social_feed",
        "description": "View your social feed.",
        "required_params": [],
        "optional_params": [
            {"name": "limit", "type": "integer", "description": "Number of posts.", "default": 20},
        ],
        "keywords": ["social feed", "my feed", "timeline", "what's new", "latest posts"],
        "follow_up": "",
        "example_conversation": (
            "User: Show my social feed\n"
            "Trinity: [calls platform_action with action='get_social_feed', params={}]"
        ),
    },

    # ===================================================================
    # Component 29 — Privacy
    # ===================================================================

    "request_deletion": {
        "action_name": "request_deletion",
        "description": "Request deletion of your data.",
        "required_params": [],
        "optional_params": [
            {"name": "scope", "type": "string", "description": "Deletion scope (all, profile, transactions, etc.).", "default": "all"},
        ],
        "keywords": ["delete my data", "data deletion", "GDPR", "right to be forgotten", "erase data", "delete account"],
        "follow_up": "What data would you like deleted? All data or specific categories?",
        "example_conversation": (
            "User: I want to delete all my data\n"
            "Trinity: [calls platform_action with action='request_deletion', params={scope: 'all'}]"
        ),
    },

    "get_privacy_commitment": {
        "action_name": "get_privacy_commitment",
        "description": "View the platform's privacy commitments.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["privacy policy", "privacy commitment", "data policy", "how is my data used"],
        "follow_up": "",
        "example_conversation": (
            "User: What's your privacy policy?\n"
            "Trinity: [calls platform_action with action='get_privacy_commitment', params={}]"
        ),
    },

    "check_privacy_dependencies": {
        "action_name": "check_privacy_dependencies",
        "description": "Check what depends on your data before deletion.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["privacy dependencies", "what uses my data", "data dependencies", "deletion impact"],
        "follow_up": "",
        "example_conversation": (
            "User: What would be affected if I delete my data?\n"
            "Trinity: [calls platform_action with action='check_privacy_dependencies', params={}]"
        ),
    },

    "get_deletion_status": {
        "action_name": "get_deletion_status",
        "description": "Check the status of a pending data deletion request.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["deletion status", "is my data deleted", "deletion progress", "pending deletion"],
        "follow_up": "",
        "example_conversation": (
            "User: Is my deletion request processed yet?\n"
            "Trinity: [calls platform_action with action='get_deletion_status', params={}]"
        ),
    },

    "execute_deletion": {
        "action_name": "execute_deletion",
        "description": "Execute a pending data deletion (irreversible).",
        "required_params": [
            {"name": "confirmation", "type": "boolean", "description": "Explicit confirmation.", "example": True},
        ],
        "optional_params": [],
        "keywords": ["execute deletion", "confirm deletion", "proceed with deletion", "finalize deletion"],
        "follow_up": "Are you sure? This action is irreversible.",
        "example_conversation": (
            "User: Yes, proceed with deleting my data\n"
            "Trinity: [calls platform_action with action='execute_deletion', params={confirmation: true}]"
        ),
    },

    # ===================================================================
    # Component 30 — Dispute Resolution
    # ===================================================================

    "file_dispute": {
        "action_name": "file_dispute",
        "description": "File a dispute against a transaction or party.",
        "required_params": [
            {"name": "subject", "type": "string", "description": "Subject of the dispute.", "example": "NFT not delivered after purchase"},
            {"name": "against", "type": "string", "description": "Address of the party being disputed.", "example": "0xabc..."},
        ],
        "optional_params": [
            {"name": "transaction_id", "type": "string", "description": "Related transaction ID.", "default": None},
            {"name": "amount", "type": "number", "description": "Disputed amount.", "default": None},
        ],
        "keywords": ["file dispute", "dispute", "open dispute", "report problem", "complaint", "issue with transaction"],
        "follow_up": "What's the dispute about, and against whom?",
        "example_conversation": (
            "User: I want to file a dispute — I paid for an NFT but never received it\n"
            "Trinity: Who is the seller?\n"
            "User: 0xabc...\n"
            "Trinity: [calls platform_action with action='file_dispute', params={subject: 'NFT not delivered after purchase', against: '0xabc...'}]"
        ),
    },

    "submit_dispute_evidence": {
        "action_name": "submit_dispute_evidence",
        "description": "Submit evidence for an open dispute.",
        "required_params": [
            {"name": "dispute_id", "type": "string", "description": "Dispute ID.", "example": "disp_abc123"},
            {"name": "evidence", "type": "string", "description": "Evidence description or hash.", "example": "Transaction hash showing payment: 0x..."},
        ],
        "optional_params": [],
        "keywords": ["submit evidence", "dispute evidence", "add evidence", "proof"],
        "follow_up": "Which dispute and what evidence?",
        "example_conversation": (
            "User: Submit evidence for my dispute\n"
            "Trinity: Which dispute and what evidence?\n"
            "User: Dispute disp_abc123, here's the payment tx hash\n"
            "Trinity: [calls platform_action with action='submit_dispute_evidence', params={dispute_id: 'disp_abc123', evidence: 'Payment tx: 0x...'}]"
        ),
    },

    "get_dispute": {
        "action_name": "get_dispute",
        "description": "Get details of a dispute.",
        "required_params": [
            {"name": "dispute_id", "type": "string", "description": "Dispute ID.", "example": "disp_abc123"},
        ],
        "optional_params": [],
        "keywords": ["dispute status", "check dispute", "my dispute", "dispute details"],
        "follow_up": "Which dispute?",
        "example_conversation": (
            "User: What's the status of my dispute?\n"
            "Trinity: Which dispute ID?\n"
            "User: disp_abc123\n"
            "Trinity: [calls platform_action with action='get_dispute', params={dispute_id: 'disp_abc123'}]"
        ),
    },

    "resolve_dispute": {
        "action_name": "resolve_dispute",
        "description": "Resolve a dispute with a decision.",
        "required_params": [
            {"name": "dispute_id", "type": "string", "description": "Dispute ID.", "example": "disp_abc123"},
            {"name": "resolution", "type": "object", "description": "Resolution details.", "example": {"winner": "claimant", "refund_amount": 500}},
        ],
        "optional_params": [],
        "keywords": ["resolve dispute", "settle dispute", "decide dispute", "close dispute"],
        "follow_up": "Which dispute and what resolution?",
        "example_conversation": (
            "User: Resolve dispute disp_abc123 in favor of the buyer\n"
            "Trinity: [calls platform_action with action='resolve_dispute', params={dispute_id: 'disp_abc123', resolution: {winner: 'claimant', refund_amount: 500}}]"
        ),
    },

    "appeal_dispute": {
        "action_name": "appeal_dispute",
        "description": "Appeal a dispute resolution.",
        "required_params": [
            {"name": "dispute_id", "type": "string", "description": "Dispute ID.", "example": "disp_abc123"},
            {"name": "reason", "type": "string", "description": "Reason for appeal.", "example": "New evidence found"},
        ],
        "optional_params": [],
        "keywords": ["appeal dispute", "contest resolution", "appeal decision", "dispute appeal"],
        "follow_up": "Which dispute and why are you appealing?",
        "example_conversation": (
            "User: I want to appeal dispute disp_abc123\n"
            "Trinity: What's the reason for your appeal?\n"
            "User: New evidence found\n"
            "Trinity: [calls platform_action with action='appeal_dispute', params={dispute_id: 'disp_abc123', reason: 'New evidence found'}]"
        ),
    },

    # ===================================================================
    # DeFi Expanded
    # ===================================================================

    "flash_loan": {
        "action_name": "flash_loan",
        "description": "Execute a flash loan — borrow and repay in a single atomic transaction.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The token to borrow.", "example": "USDC"},
            {"name": "amount", "type": "number", "description": "Amount to borrow.", "example": 50000.0},
            {"name": "strategy", "type": "string", "description": "Strategy for the flash loan (arbitrage, liquidation, collateral_swap).", "example": "arbitrage"},
        ],
        "optional_params": [
            {"name": "protocol", "type": "string", "description": "Which lending protocol to use (aave, dydx, etc.).", "default": "auto"},
            {"name": "slippage_tolerance", "type": "number", "description": "Maximum slippage percentage allowed.", "default": 0.5},
        ],
        "keywords": ["flash loan", "flash borrow", "atomic loan", "instant borrow", "arbitrage loan", "flash lending"],
        "follow_up": "Which asset would you like to flash-borrow, how much, and what strategy are you running — arbitrage, liquidation, or a collateral swap?",
        "example_conversation": (
            "User: I want to do a flash loan for arbitrage\n"
            "Trinity: Absolutely. Which token do you want to borrow, and how much? I'll set it up as a single atomic transaction so everything settles in one block.\n"
            "User: 100,000 USDC\n"
            "Trinity: Got it — 100k USDC flash loan for arbitrage. Let me execute that for you.\n"
            "Trinity: [calls platform_action with action='flash_loan', params={asset: 'USDC', amount: 100000.0, strategy: 'arbitrage'}]"
        ),
    },

    "yield_optimize": {
        "action_name": "yield_optimize",
        "description": "Find and deposit into the best yield-earning opportunity across all protocols.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The token to earn yield on.", "example": "ETH"},
            {"name": "amount", "type": "number", "description": "Amount to deposit.", "example": 10.0},
        ],
        "optional_params": [
            {"name": "risk_tolerance", "type": "string", "description": "Your risk comfort level (low, medium, high).", "default": "medium"},
            {"name": "min_apy", "type": "number", "description": "Minimum APY threshold to consider.", "default": 0.0},
        ],
        "keywords": ["best yield", "maximize yield", "yield optimize", "earn more", "best rate", "highest apy", "yield farming", "where to earn"],
        "follow_up": "Which token do you want to earn yield on, and how much are you looking to deposit? I can also factor in your risk tolerance if you'd like.",
        "example_conversation": (
            "User: Where can I get the best yield on my ETH?\n"
            "Trinity: Great question. How much ETH are you looking to put to work? And do you have a risk preference — low, medium, or high?\n"
            "User: About 5 ETH, and keep it medium risk\n"
            "Trinity: Perfect. I'll scan all the protocols and find you the best medium-risk opportunity for 5 ETH.\n"
            "Trinity: [calls platform_action with action='yield_optimize', params={asset: 'ETH', amount: 5.0, risk_tolerance: 'medium'}]"
        ),
    },

    "liquidity_provide": {
        "action_name": "liquidity_provide",
        "description": "Add liquidity to a trading pool and earn trading fees.",
        "required_params": [
            {"name": "token_a", "type": "string", "description": "First token in the pair.", "example": "ETH"},
            {"name": "token_b", "type": "string", "description": "Second token in the pair.", "example": "USDC"},
            {"name": "amount_a", "type": "number", "description": "Amount of the first token to provide.", "example": 2.0},
        ],
        "optional_params": [
            {"name": "amount_b", "type": "number", "description": "Amount of the second token (auto-calculated if omitted).", "default": None},
            {"name": "price_range_lower", "type": "number", "description": "Lower price bound for concentrated liquidity.", "default": None},
            {"name": "price_range_upper", "type": "number", "description": "Upper price bound for concentrated liquidity.", "default": None},
            {"name": "protocol", "type": "string", "description": "Which DEX to provide liquidity on.", "default": "auto"},
        ],
        "keywords": ["add liquidity", "provide liquidity", "liquidity pool", "LP position", "become liquidity provider", "earn trading fees"],
        "follow_up": "Which token pair would you like to provide liquidity for, and how much of the first token are you putting in?",
        "example_conversation": (
            "User: I want to add liquidity to a pool\n"
            "Trinity: Sure thing! Which two tokens do you want to pair up, and how much of the first token are you contributing?\n"
            "User: ETH and USDC, putting in 3 ETH\n"
            "Trinity: Nice — I'll set up your LP position with 3 ETH paired with USDC. The matching USDC amount will be calculated at the current market ratio.\n"
            "Trinity: [calls platform_action with action='liquidity_provide', params={token_a: 'ETH', token_b: 'USDC', amount_a: 3.0}]"
        ),
    },

    "perp_trade": {
        "action_name": "perp_trade",
        "description": "Open a perpetual futures position with leverage.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The asset to trade.", "example": "BTC"},
            {"name": "direction", "type": "string", "description": "Trade direction (long or short).", "example": "long"},
            {"name": "size", "type": "number", "description": "Position size in the asset.", "example": 0.5},
            {"name": "leverage", "type": "number", "description": "Leverage multiplier.", "example": 5.0},
        ],
        "optional_params": [
            {"name": "stop_loss", "type": "number", "description": "Stop-loss price.", "default": None},
            {"name": "take_profit", "type": "number", "description": "Take-profit price.", "default": None},
            {"name": "protocol", "type": "string", "description": "Which perps exchange to use.", "default": "auto"},
        ],
        "keywords": ["perpetual", "perp trade", "futures", "go long", "go short", "leveraged trade", "perpetual contract"],
        "follow_up": "Which asset are you trading, do you want to go long or short, how big is the position, and what leverage?",
        "example_conversation": (
            "User: I want to go long on BTC with leverage\n"
            "Trinity: Let's set that up. How much BTC do you want for your position size, and what leverage are you thinking?\n"
            "User: 0.5 BTC at 10x\n"
            "Trinity: Got it — opening a 10x long on 0.5 BTC. Would you like to set a stop-loss or take-profit, or just open it as is?\n"
            "User: Just open it\n"
            "Trinity: [calls platform_action with action='perp_trade', params={asset: 'BTC', direction: 'long', size: 0.5, leverage: 10.0}]"
        ),
    },

    "options_trade": {
        "action_name": "options_trade",
        "description": "Trade on-chain options contracts.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The underlying asset.", "example": "ETH"},
            {"name": "option_type", "type": "string", "description": "Type of option (call or put).", "example": "call"},
            {"name": "strike_price", "type": "number", "description": "The strike price of the option.", "example": 3500.0},
            {"name": "expiry", "type": "string", "description": "Expiration date in ISO format.", "example": "2026-05-15"},
        ],
        "optional_params": [
            {"name": "quantity", "type": "number", "description": "Number of option contracts.", "default": 1},
            {"name": "action", "type": "string", "description": "Whether to buy or sell the option.", "default": "buy"},
            {"name": "protocol", "type": "string", "description": "Which options protocol to use.", "default": "auto"},
        ],
        "keywords": ["options", "call option", "put option", "options trade", "buy calls", "buy puts"],
        "follow_up": "Which asset do you want options on, call or put, what strike price, and when should it expire?",
        "example_conversation": (
            "User: I want to buy some ETH calls\n"
            "Trinity: Great — what strike price are you targeting, and when do you want them to expire?\n"
            "User: Strike at 3500, expiring May 15th\n"
            "Trinity: Perfect. Buying ETH call options with a 3500 strike, expiring 2026-05-15.\n"
            "Trinity: [calls platform_action with action='options_trade', params={asset: 'ETH', option_type: 'call', strike_price: 3500.0, expiry: '2026-05-15'}]"
        ),
    },

    "synthetic_asset": {
        "action_name": "synthetic_asset",
        "description": "Create a synthetic asset that tracks the price of any real-world asset.",
        "required_params": [
            {"name": "underlying", "type": "string", "description": "The real-world asset to track (e.g. gold, AAPL, oil).", "example": "gold"},
            {"name": "amount", "type": "number", "description": "Amount of synthetic exposure to create.", "example": 1000.0},
        ],
        "optional_params": [
            {"name": "collateral_asset", "type": "string", "description": "Token used as collateral to back the synthetic.", "default": "USDC"},
            {"name": "collateral_ratio", "type": "number", "description": "Collateralization ratio as a percentage.", "default": 150.0},
        ],
        "keywords": ["synthetic", "synthetic asset", "price tracker", "mirror asset", "tokenized exposure"],
        "follow_up": "Which real-world asset do you want to track, and how much synthetic exposure would you like to create?",
        "example_conversation": (
            "User: I want exposure to gold on-chain\n"
            "Trinity: Nice choice. How much synthetic gold do you want to create? I'll mint you a token that tracks gold's price in real time.\n"
            "User: About $5,000 worth\n"
            "Trinity: Got it — creating $5,000 of synthetic gold exposure backed by collateral.\n"
            "Trinity: [calls platform_action with action='synthetic_asset', params={underlying: 'gold', amount: 5000.0}]"
        ),
    },

    "vault_deposit": {
        "action_name": "vault_deposit",
        "description": "Deposit into an automated yield vault that optimizes returns.",
        "required_params": [
            {"name": "vault_id", "type": "string", "description": "The identifier of the vault.", "example": "yearn-eth-v3"},
            {"name": "amount", "type": "number", "description": "Amount to deposit.", "example": 5.0},
        ],
        "optional_params": [
            {"name": "asset", "type": "string", "description": "The deposit token if the vault accepts multiple.", "default": None},
            {"name": "auto_compound", "type": "boolean", "description": "Whether to auto-compound earnings.", "default": True},
        ],
        "keywords": ["vault", "yield vault", "auto compound", "vault deposit", "automated yield"],
        "follow_up": "Which vault would you like to deposit into, and how much are you putting in?",
        "example_conversation": (
            "User: I want to deposit into a yield vault\n"
            "Trinity: Sure! Which vault are you interested in, and how much do you want to deposit? I'll handle the rest — the vault auto-compounds your earnings.\n"
            "User: The Yearn ETH v3 vault, 10 ETH\n"
            "Trinity: Depositing 10 ETH into the Yearn ETH v3 vault with auto-compounding enabled.\n"
            "Trinity: [calls platform_action with action='vault_deposit', params={vault_id: 'yearn-eth-v3', amount: 10.0}]"
        ),
    },

    "cross_chain_bridge": {
        "action_name": "cross_chain_bridge",
        "description": "Bridge assets safely from one blockchain network to another.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The token to bridge.", "example": "USDC"},
            {"name": "amount", "type": "number", "description": "Amount to bridge.", "example": 1000.0},
            {"name": "from_chain", "type": "string", "description": "Source blockchain.", "example": "ethereum"},
            {"name": "to_chain", "type": "string", "description": "Destination blockchain.", "example": "polygon"},
        ],
        "optional_params": [
            {"name": "bridge_protocol", "type": "string", "description": "Preferred bridge protocol to use.", "default": "auto"},
            {"name": "speed", "type": "string", "description": "Transfer speed preference (fast, standard).", "default": "standard"},
        ],
        "keywords": ["bridge", "cross chain", "move to ethereum", "transfer to polygon", "bridge my", "move between chains", "cross-chain transfer"],
        "follow_up": "Which asset do you want to bridge, how much, and from which chain to which chain?",
        "example_conversation": (
            "User: I need to move my USDC to Polygon\n"
            "Trinity: No problem! How much USDC, and which chain are you moving from? Ethereum, Arbitrum, something else?\n"
            "User: 2000 USDC from Ethereum\n"
            "Trinity: Bridging 2,000 USDC from Ethereum to Polygon. I'll pick the safest route for you.\n"
            "Trinity: [calls platform_action with action='cross_chain_bridge', params={asset: 'USDC', amount: 2000.0, from_chain: 'ethereum', to_chain: 'polygon'}]"
        ),
    },

    "leverage_position": {
        "action_name": "leverage_position",
        "description": "Open a leveraged position on an asset.",
        "required_params": [
            {"name": "asset", "type": "string", "description": "The asset to take a leveraged position on.", "example": "ETH"},
            {"name": "amount", "type": "number", "description": "Base amount of collateral.", "example": 5.0},
            {"name": "leverage", "type": "number", "description": "Leverage multiplier.", "example": 3.0},
            {"name": "direction", "type": "string", "description": "Position direction (long or short).", "example": "long"},
        ],
        "optional_params": [
            {"name": "stop_loss", "type": "number", "description": "Stop-loss price.", "default": None},
            {"name": "protocol", "type": "string", "description": "Which protocol to open the position on.", "default": "auto"},
        ],
        "keywords": ["leverage", "leveraged position", "margin trade", "multiply exposure"],
        "follow_up": "Which asset, how much collateral, what leverage, and are you going long or short?",
        "example_conversation": (
            "User: I want to open a leveraged position on ETH\n"
            "Trinity: Sounds good. How much ETH are you putting up as collateral, what leverage do you want, and are you going long or short?\n"
            "User: 3 ETH, 5x long\n"
            "Trinity: Opening a 5x long on ETH with 3 ETH collateral — that gives you 15 ETH of exposure.\n"
            "Trinity: [calls platform_action with action='leverage_position', params={asset: 'ETH', amount: 3.0, leverage: 5.0, direction: 'long'}]"
        ),
    },

    "collateral_manage": {
        "action_name": "collateral_manage",
        "description": "Adjust collateral on an existing loan or leveraged position.",
        "required_params": [
            {"name": "position_id", "type": "string", "description": "The ID of the position to adjust.", "example": "pos_abc123"},
            {"name": "action", "type": "string", "description": "Whether to add or remove collateral.", "example": "add"},
            {"name": "amount", "type": "number", "description": "Amount of collateral to add or remove.", "example": 2.0},
        ],
        "optional_params": [
            {"name": "asset", "type": "string", "description": "Collateral asset if the position accepts multiple types.", "default": None},
        ],
        "keywords": ["collateral", "add collateral", "remove collateral", "adjust collateral", "collateral ratio"],
        "follow_up": "Which position do you want to adjust, and do you want to add or remove collateral? How much?",
        "example_conversation": (
            "User: I need to add collateral to my position\n"
            "Trinity: Of course. Which position ID, and how much collateral do you want to add?\n"
            "User: Position pos_abc123, add 2 ETH\n"
            "Trinity: Adding 2 ETH collateral to position pos_abc123. That should bring your health factor up nicely.\n"
            "Trinity: [calls platform_action with action='collateral_manage', params={position_id: 'pos_abc123', action: 'add', amount: 2.0}]"
        ),
    },

    # ===================================================================
    # NFT Expanded
    # ===================================================================

    "nft_fractionalize": {
        "action_name": "nft_fractionalize",
        "description": "Split an NFT into tradeable fractions so multiple people can co-own it.",
        "required_params": [
            {"name": "nft_address", "type": "string", "description": "Contract address of the NFT.", "example": "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"},
            {"name": "token_id", "type": "string", "description": "Token ID of the NFT to fractionalize.", "example": "4521"},
            {"name": "num_fractions", "type": "integer", "description": "Number of fractions to split the NFT into.", "example": 1000},
        ],
        "optional_params": [
            {"name": "fraction_price", "type": "number", "description": "Initial price per fraction.", "default": None},
            {"name": "fraction_symbol", "type": "string", "description": "Token symbol for the fractions.", "default": None},
        ],
        "keywords": ["fractionalize", "fractional nft", "split nft", "co-own nft", "nft fractions", "shared ownership nft"],
        "follow_up": "Which NFT do you want to split up, and how many fractions should it be divided into?",
        "example_conversation": (
            "User: I want to fractionalize my NFT so friends can co-own it\n"
            "Trinity: Love that idea. Which NFT is it — the contract address and token ID — and how many fractions do you want to create?\n"
            "User: My Bored Ape #4521, split it into 1000 pieces\n"
            "Trinity: Splitting Bored Ape #4521 into 1,000 tradeable fractions. Each fraction will be its own token that people can buy and sell.\n"
            "Trinity: [calls platform_action with action='nft_fractionalize', params={nft_address: '0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d', token_id: '4521', num_fractions: 1000}]"
        ),
    },

    "nft_rent": {
        "action_name": "nft_rent",
        "description": "List an NFT for rental or rent someone else's NFT.",
        "required_params": [
            {"name": "nft_address", "type": "string", "description": "Contract address of the NFT.", "example": "0xbc4ca0eda..."},
            {"name": "token_id", "type": "string", "description": "Token ID of the NFT.", "example": "1234"},
            {"name": "rental_period", "type": "string", "description": "Duration of the rental (e.g. '7d', '30d', '1h').", "example": "7d"},
            {"name": "price_per_day", "type": "number", "description": "Rental price per day.", "example": 0.05},
        ],
        "optional_params": [
            {"name": "direction", "type": "string", "description": "Whether you are listing for rent or renting ('list' or 'rent').", "default": "list"},
            {"name": "collateral_required", "type": "number", "description": "Collateral amount required from the renter.", "default": None},
        ],
        "keywords": ["rent nft", "nft rental", "lease nft", "borrow nft", "temporary nft"],
        "follow_up": "Which NFT would you like to rent out (or rent), for how long, and at what daily rate?",
        "example_conversation": (
            "User: Can I rent out my NFT?\n"
            "Trinity: Absolutely! Which NFT is it, how long do you want the rental period to be, and what would you charge per day?\n"
            "User: My PFP at 0xabc token 42, for a week at 0.1 ETH per day\n"
            "Trinity: Listing your NFT for a 7-day rental at 0.1 ETH per day. The renter gets temporary access while you keep ownership.\n"
            "Trinity: [calls platform_action with action='nft_rent', params={nft_address: '0xabc', token_id: '42', rental_period: '7d', price_per_day: 0.1}]"
        ),
    },

    "nft_dynamic_update": {
        "action_name": "nft_dynamic_update",
        "description": "Update the metadata or properties of a dynamic NFT.",
        "required_params": [
            {"name": "nft_address", "type": "string", "description": "Contract address of the dynamic NFT.", "example": "0xdyn123..."},
            {"name": "token_id", "type": "string", "description": "Token ID of the NFT.", "example": "88"},
            {"name": "updates", "type": "object", "description": "Dictionary of properties to update.", "example": {"level": 5, "skin": "golden"}},
        ],
        "optional_params": [
            {"name": "trigger_reason", "type": "string", "description": "Reason or event triggering the update.", "default": None},
        ],
        "keywords": ["update nft", "dynamic nft", "change nft", "modify nft properties", "evolving nft"],
        "follow_up": "Which dynamic NFT do you want to update, and what properties should change?",
        "example_conversation": (
            "User: I want to update my dynamic NFT\n"
            "Trinity: Sure! Which NFT is it, and what properties do you want to change?\n"
            "User: Token 88 at 0xdyn123, set the level to 5 and the skin to golden\n"
            "Trinity: Updating token 88 — setting level to 5 and skin to golden. Your NFT will evolve on-chain.\n"
            "Trinity: [calls platform_action with action='nft_dynamic_update', params={nft_address: '0xdyn123', token_id: '88', updates: {level: 5, skin: 'golden'}}]"
        ),
    },

    "nft_batch_mint": {
        "action_name": "nft_batch_mint",
        "description": "Mint multiple NFTs in a single transaction.",
        "required_params": [
            {"name": "collection_address", "type": "string", "description": "Contract address of the collection.", "example": "0xcol123..."},
            {"name": "count", "type": "integer", "description": "Number of NFTs to mint.", "example": 50},
            {"name": "metadata_list", "type": "array", "description": "List of metadata objects for each NFT.", "example": [{"name": "Token #1", "image": "ipfs://..."}]},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Wallet to receive the minted NFTs.", "default": None},
            {"name": "start_token_id", "type": "integer", "description": "Starting token ID for the batch.", "default": None},
        ],
        "keywords": ["batch mint", "mint multiple", "bulk mint", "mass mint", "mint collection"],
        "follow_up": "Which collection are you minting into, how many NFTs, and do you have the metadata ready?",
        "example_conversation": (
            "User: I need to mint 50 NFTs at once\n"
            "Trinity: Efficient! Which collection are you minting into, and do you have the metadata list ready for all 50?\n"
            "User: Collection 0xcol123, and yes I have the metadata JSON\n"
            "Trinity: Great — batch minting 50 NFTs into your collection in a single transaction. Much cheaper on gas than minting them one by one.\n"
            "Trinity: [calls platform_action with action='nft_batch_mint', params={collection_address: '0xcol123', count: 50, metadata_list: [...]}]"
        ),
    },

    "nft_royalty_claim": {
        "action_name": "nft_royalty_claim",
        "description": "Claim accumulated royalty earnings from your NFT sales.",
        "required_params": [
            {"name": "collection_address", "type": "string", "description": "Contract address of the collection.", "example": "0xcol456..."},
        ],
        "optional_params": [
            {"name": "currency", "type": "string", "description": "Which currency to claim royalties in.", "default": None},
        ],
        "keywords": ["claim royalties", "nft royalties", "royalty earnings", "collect royalties", "creator earnings"],
        "follow_up": "Which collection would you like to claim royalties from?",
        "example_conversation": (
            "User: I want to collect my NFT royalties\n"
            "Trinity: Of course! Which collection are you claiming from? I'll pull all your accumulated earnings.\n"
            "User: My collection at 0xcol456\n"
            "Trinity: Claiming all accumulated royalty earnings from collection 0xcol456. Those are your creator earnings from secondary sales.\n"
            "Trinity: [calls platform_action with action='nft_royalty_claim', params={collection_address: '0xcol456'}]"
        ),
    },

    "nft_bridge": {
        "action_name": "nft_bridge",
        "description": "Move an NFT from one blockchain to another.",
        "required_params": [
            {"name": "nft_address", "type": "string", "description": "Contract address of the NFT.", "example": "0xnft789..."},
            {"name": "token_id", "type": "string", "description": "Token ID of the NFT.", "example": "42"},
            {"name": "to_chain", "type": "string", "description": "Destination blockchain.", "example": "polygon"},
        ],
        "optional_params": [
            {"name": "from_chain", "type": "string", "description": "Source blockchain (auto-detected if omitted).", "default": "auto"},
            {"name": "bridge_protocol", "type": "string", "description": "Preferred bridge protocol.", "default": "auto"},
        ],
        "keywords": ["bridge nft", "move nft", "transfer nft chain", "nft cross chain"],
        "follow_up": "Which NFT do you want to bridge, and to which chain?",
        "example_conversation": (
            "User: I want to move my NFT to Polygon\n"
            "Trinity: Sure! Which NFT — the contract address and token ID — and which chain is it on now?\n"
            "User: 0xnft789 token 42, it's on Ethereum\n"
            "Trinity: Bridging NFT #42 from Ethereum to Polygon. Your NFT will be wrapped and available on Polygon shortly.\n"
            "Trinity: [calls platform_action with action='nft_bridge', params={nft_address: '0xnft789', token_id: '42', to_chain: 'polygon'}]"
        ),
    },

    # ===================================================================
    # Identity
    # ===================================================================

    "did_create": {
        "action_name": "did_create",
        "description": "Create a decentralized identifier — a digital identity you own completely.",
        "required_params": [
            {"name": "display_name", "type": "string", "description": "A human-readable display name for the identity.", "example": "Alice"},
        ],
        "optional_params": [
            {"name": "public_key", "type": "string", "description": "A custom public key to associate (auto-generated if omitted).", "default": None},
            {"name": "service_endpoints", "type": "array", "description": "List of service endpoints (URLs, APIs) linked to this identity.", "default": []},
        ],
        "keywords": ["create did", "decentralized id", "digital identity", "self sovereign identity", "create identity", "own my identity"],
        "follow_up": "What display name would you like for your decentralized identity?",
        "example_conversation": (
            "User: I want to create a decentralized identity\n"
            "Trinity: Great step toward owning your online presence. What display name would you like for your DID?\n"
            "User: Call it Neo\n"
            "Trinity: Creating your decentralized identifier with the display name Neo. This identity is fully yours — no platform can take it away.\n"
            "Trinity: [calls platform_action with action='did_create', params={display_name: 'Neo'}]"
        ),
    },

    "credential_issue": {
        "action_name": "credential_issue",
        "description": "Issue a verifiable credential — a signed digital statement proving something is true.",
        "required_params": [
            {"name": "subject", "type": "string", "description": "DID or address of the credential subject.", "example": "did:0pn:abc123"},
            {"name": "claim_type", "type": "string", "description": "Type of claim being made (e.g. 'degree', 'membership', 'age_verification').", "example": "degree"},
            {"name": "claim_data", "type": "object", "description": "The actual claim data.", "example": {"institution": "MIT", "degree": "CS", "year": 2024}},
        ],
        "optional_params": [
            {"name": "expiry", "type": "string", "description": "When the credential expires (ISO date).", "default": None},
            {"name": "revocable", "type": "boolean", "description": "Whether the credential can be revoked later.", "default": True},
        ],
        "keywords": ["issue credential", "verifiable credential", "digital certificate", "prove identity", "attestation", "certified proof"],
        "follow_up": "Who is the credential for, what type of claim is it, and what are the details?",
        "example_conversation": (
            "User: I need to issue a credential for a course completion\n"
            "Trinity: Happy to help. Who is the credential for — their DID or wallet address — and what are the details of the course they completed?\n"
            "User: For did:0pn:abc123, they completed Blockchain 101\n"
            "Trinity: Issuing a verifiable credential for did:0pn:abc123 — Blockchain 101 completion. This is a cryptographically signed proof they can show anyone.\n"
            "Trinity: [calls platform_action with action='credential_issue', params={subject: 'did:0pn:abc123', claim_type: 'course_completion', claim_data: {course: 'Blockchain 101'}}]"
        ),
    },

    "credential_verify": {
        "action_name": "credential_verify",
        "description": "Verify whether a credential is authentic and hasn't been revoked.",
        "required_params": [
            {"name": "credential_id", "type": "string", "description": "The unique ID of the credential to verify.", "example": "cred_xyz789"},
        ],
        "optional_params": [],
        "keywords": ["verify credential", "check credential", "validate credential", "is it real", "authentic credential"],
        "follow_up": "What's the credential ID you'd like me to verify?",
        "example_conversation": (
            "User: Can you check if this credential is real?\n"
            "Trinity: Absolutely. What's the credential ID?\n"
            "User: cred_xyz789\n"
            "Trinity: Verifying credential cred_xyz789 — I'll check the signature, issuer, and revocation status for you.\n"
            "Trinity: [calls platform_action with action='credential_verify', params={credential_id: 'cred_xyz789'}]"
        ),
    },

    "selective_disclose": {
        "action_name": "selective_disclose",
        "description": "Prove something about yourself without revealing everything — using zero-knowledge proof.",
        "required_params": [
            {"name": "credential_id", "type": "string", "description": "The credential to selectively disclose from.", "example": "cred_abc123"},
            {"name": "disclosed_fields", "type": "array", "description": "List of specific fields to reveal.", "example": ["age_over_18", "country"]},
        ],
        "optional_params": [
            {"name": "verifier", "type": "string", "description": "The address or DID of who you are proving it to.", "default": None},
        ],
        "keywords": ["selective disclosure", "prove without revealing", "partial proof", "privacy proof", "share minimum"],
        "follow_up": "Which credential do you want to share from, and which specific fields should be revealed?",
        "example_conversation": (
            "User: I want to prove I'm over 18 without showing my full ID\n"
            "Trinity: Smart approach — that's exactly what selective disclosure is for. Which credential has your age info, and I'll reveal only the age_over_18 field.\n"
            "User: Credential cred_abc123\n"
            "Trinity: Creating a zero-knowledge proof from cred_abc123 that reveals only that you are over 18 — nothing else.\n"
            "Trinity: [calls platform_action with action='selective_disclose', params={credential_id: 'cred_abc123', disclosed_fields: ['age_over_18']}]"
        ),
    },

    "reputation_query": {
        "action_name": "reputation_query",
        "description": "Check the on-chain reputation score of a wallet or identity.",
        "required_params": [
            {"name": "address", "type": "string", "description": "Wallet address or DID to check.", "example": "0xabc..."},
        ],
        "optional_params": [
            {"name": "categories", "type": "array", "description": "Specific reputation categories to check (e.g. 'defi', 'governance').", "default": None},
        ],
        "keywords": ["reputation", "trust score", "check reputation", "wallet reputation", "on-chain reputation"],
        "follow_up": "Which wallet or identity would you like to check the reputation of?",
        "example_conversation": (
            "User: What's the reputation of this wallet?\n"
            "Trinity: Sure, I'll look it up. What's the wallet address or DID?\n"
            "User: 0xabc123\n"
            "Trinity: Checking the on-chain reputation for 0xabc123 across DeFi activity, governance participation, and transaction history.\n"
            "Trinity: [calls platform_action with action='reputation_query', params={address: '0xabc123'}]"
        ),
    },

    "soulbound_mint": {
        "action_name": "soulbound_mint",
        "description": "Mint a non-transferable token that permanently marks an achievement or identity.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Wallet address to receive the soulbound token.", "example": "0xrecipient..."},
            {"name": "token_type", "type": "string", "description": "Type of soulbound token (achievement, membership, certification, etc.).", "example": "achievement"},
            {"name": "metadata", "type": "object", "description": "Token metadata — name, description, image, attributes.", "example": {"name": "Beta Tester", "description": "Early beta participant"}},
        ],
        "optional_params": [
            {"name": "expiry", "type": "string", "description": "Optional expiration date for the token.", "default": None},
        ],
        "keywords": ["soulbound", "non-transferable", "permanent token", "achievement token", "identity badge"],
        "follow_up": "Who should receive the soulbound token, what type is it, and what details should it carry?",
        "example_conversation": (
            "User: I want to mint a soulbound achievement token\n"
            "Trinity: Awesome — those are permanent and can't be sold or transferred, which makes them perfect for real achievements. Who's receiving it, and what's the achievement?\n"
            "User: Send it to 0xrecipient, it's a Beta Tester badge\n"
            "Trinity: Minting a non-transferable Beta Tester soulbound token to 0xrecipient. It'll live in their wallet forever as proof they were an early supporter.\n"
            "Trinity: [calls platform_action with action='soulbound_mint', params={recipient: '0xrecipient', token_type: 'achievement', metadata: {name: 'Beta Tester', description: 'Early beta participant'}}]"
        ),
    },

    # ===================================================================
    # Governance
    # ===================================================================

    "timelock_queue": {
        "action_name": "timelock_queue",
        "description": "Queue an action in a time-locked governance contract.",
        "required_params": [
            {"name": "target", "type": "string", "description": "Target contract address for the action.", "example": "0xtarget..."},
            {"name": "action_data", "type": "string", "description": "Encoded action data to execute after the delay.", "example": "0xabcdef..."},
            {"name": "delay_seconds", "type": "integer", "description": "Time delay in seconds before the action can be executed.", "example": 172800},
        ],
        "optional_params": [
            {"name": "value", "type": "number", "description": "ETH value to send with the action.", "default": 0},
            {"name": "description", "type": "string", "description": "Human-readable description of what this action does.", "default": None},
        ],
        "keywords": ["timelock", "queue action", "delayed execution", "governance delay"],
        "follow_up": "What's the target contract, what action do you want to queue, and how long should the delay be?",
        "example_conversation": (
            "User: I need to queue a timelock action\n"
            "Trinity: Sure. What's the target contract address, the action data, and how many seconds of delay do you want before it can execute?\n"
            "User: Target 0xtarget, data 0xabcdef, 48 hour delay\n"
            "Trinity: Queuing the action to 0xtarget with a 48-hour delay. After the timer expires, anyone can trigger the execution.\n"
            "Trinity: [calls platform_action with action='timelock_queue', params={target: '0xtarget', action_data: '0xabcdef', delay_seconds: 172800}]"
        ),
    },

    "multisig_propose": {
        "action_name": "multisig_propose",
        "description": "Propose a transaction for multisig approval.",
        "required_params": [
            {"name": "multisig_address", "type": "string", "description": "Address of the multisig wallet.", "example": "0xsafe123..."},
            {"name": "target", "type": "string", "description": "Target contract or recipient address.", "example": "0xtarget..."},
            {"name": "value", "type": "number", "description": "ETH value to send.", "example": 1.0},
            {"name": "data", "type": "string", "description": "Transaction calldata.", "example": "0x"},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Description of the proposed transaction.", "default": None},
        ],
        "keywords": ["multisig propose", "propose transaction", "multi-signature", "shared wallet propose"],
        "follow_up": "Which multisig wallet, what's the target, how much, and what's the transaction data?",
        "example_conversation": (
            "User: I want to propose a transaction on our multisig\n"
            "Trinity: Let's do it. Which multisig wallet, what's the recipient, how much ETH, and any calldata?\n"
            "User: Safe at 0xsafe123, send 5 ETH to 0xtarget, no calldata\n"
            "Trinity: Proposing a 5 ETH transfer from your Safe multisig to 0xtarget. The other signers will need to approve it.\n"
            "Trinity: [calls platform_action with action='multisig_propose', params={multisig_address: '0xsafe123', target: '0xtarget', value: 5.0, data: '0x'}]"
        ),
    },

    "multisig_approve": {
        "action_name": "multisig_approve",
        "description": "Approve a pending multisig transaction.",
        "required_params": [
            {"name": "multisig_address", "type": "string", "description": "Address of the multisig wallet.", "example": "0xsafe123..."},
            {"name": "proposal_id", "type": "string", "description": "ID of the proposal to approve.", "example": "prop_42"},
        ],
        "optional_params": [],
        "keywords": ["multisig approve", "sign transaction", "approve proposal", "confirm multisig"],
        "follow_up": "Which multisig and which proposal ID do you want to approve?",
        "example_conversation": (
            "User: I need to approve a pending multisig transaction\n"
            "Trinity: Which multisig wallet and which proposal are you approving?\n"
            "User: Safe 0xsafe123, proposal prop_42\n"
            "Trinity: Signing your approval for proposal prop_42 on the multisig. If this is the final required signature, it'll execute automatically.\n"
            "Trinity: [calls platform_action with action='multisig_approve', params={multisig_address: '0xsafe123', proposal_id: 'prop_42'}]"
        ),
    },

    "snapshot_vote": {
        "action_name": "snapshot_vote",
        "description": "Cast a vote on a Snapshot proposal — gasless off-chain voting.",
        "required_params": [
            {"name": "space_id", "type": "string", "description": "The Snapshot space identifier.", "example": "aave.eth"},
            {"name": "proposal_id", "type": "string", "description": "The proposal to vote on.", "example": "0xproposal..."},
            {"name": "choice", "type": "integer", "description": "Your choice (1-indexed option number).", "example": 1},
        ],
        "optional_params": [
            {"name": "reason", "type": "string", "description": "Optional reason for your vote.", "default": None},
        ],
        "keywords": ["snapshot vote", "off-chain vote", "gasless vote", "snapshot proposal"],
        "follow_up": "Which Snapshot space and proposal, and which option do you want to vote for?",
        "example_conversation": (
            "User: I want to vote on the latest Aave proposal\n"
            "Trinity: Sure! What's the proposal ID, and which option are you voting for? Snapshot votes are gasless, so it won't cost you anything.\n"
            "User: Proposal 0xproposal, option 1\n"
            "Trinity: Casting your vote for option 1 on the Aave proposal. No gas needed — it's an off-chain signature.\n"
            "Trinity: [calls platform_action with action='snapshot_vote', params={space_id: 'aave.eth', proposal_id: '0xproposal', choice: 1}]"
        ),
    },

    "treasury_transfer": {
        "action_name": "treasury_transfer",
        "description": "Transfer funds from a DAO treasury.",
        "required_params": [
            {"name": "dao_id", "type": "string", "description": "Identifier of the DAO.", "example": "dao_uniswap"},
            {"name": "recipient", "type": "string", "description": "Recipient address.", "example": "0xrecipient..."},
            {"name": "amount", "type": "number", "description": "Amount to transfer.", "example": 10000.0},
            {"name": "asset", "type": "string", "description": "Token to transfer.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "memo", "type": "string", "description": "Purpose or memo for the transfer.", "default": None},
        ],
        "keywords": ["treasury transfer", "dao funds", "treasury send", "dao payment"],
        "follow_up": "Which DAO, who's the recipient, how much, and which token?",
        "example_conversation": (
            "User: We need to send funds from the DAO treasury\n"
            "Trinity: Got it. Which DAO, who's receiving, how much, and which token?\n"
            "User: dao_uniswap, send 50,000 USDC to 0xrecipient\n"
            "Trinity: Initiating a 50,000 USDC transfer from the Uniswap DAO treasury to 0xrecipient. This will go through the governance approval flow.\n"
            "Trinity: [calls platform_action with action='treasury_transfer', params={dao_id: 'dao_uniswap', recipient: '0xrecipient', amount: 50000.0, asset: 'USDC'}]"
        ),
    },

    "parameter_change": {
        "action_name": "parameter_change",
        "description": "Propose a change to a protocol's governance parameters.",
        "required_params": [
            {"name": "protocol", "type": "string", "description": "The protocol to change parameters for.", "example": "aave"},
            {"name": "parameter", "type": "string", "description": "Name of the parameter to change.", "example": "liquidation_threshold"},
            {"name": "new_value", "type": "string", "description": "The proposed new value.", "example": "85"},
        ],
        "optional_params": [
            {"name": "justification", "type": "string", "description": "Reason for the parameter change.", "default": None},
            {"name": "market", "type": "string", "description": "Specific market the change applies to.", "default": None},
        ],
        "keywords": ["parameter change", "protocol governance", "change setting", "update parameter"],
        "follow_up": "Which protocol, what parameter, and what should the new value be?",
        "example_conversation": (
            "User: I want to propose changing the liquidation threshold on Aave\n"
            "Trinity: Sure. What should the new liquidation threshold be, and for which market?\n"
            "User: Set it to 85 for the ETH market\n"
            "Trinity: Proposing a parameter change on Aave — setting the ETH market liquidation threshold to 85. This will go through governance voting.\n"
            "Trinity: [calls platform_action with action='parameter_change', params={protocol: 'aave', parameter: 'liquidation_threshold', new_value: '85'}]"
        ),
    },

    # ===================================================================
    # RWA (Real-World Assets)
    # ===================================================================

    "rwa_tokenize": {
        "action_name": "rwa_tokenize",
        "description": "Tokenize a real-world asset — property, vehicle, artwork, or commodity.",
        "required_params": [
            {"name": "asset_type", "type": "string", "description": "Type of real-world asset (property, vehicle, artwork, commodity, etc.).", "example": "property"},
            {"name": "description", "type": "string", "description": "Description of the asset.", "example": "3-bedroom condo in downtown Austin"},
            {"name": "valuation_usd", "type": "number", "description": "Estimated value in USD.", "example": 350000.0},
            {"name": "documentation", "type": "array", "description": "List of supporting document references (IPFS hashes, URLs).", "example": ["ipfs://deed...", "ipfs://appraisal..."]},
        ],
        "optional_params": [
            {"name": "fractionalize", "type": "boolean", "description": "Whether to split the token into tradeable fractions.", "default": False},
            {"name": "num_fractions", "type": "integer", "description": "Number of fractions if fractionalizing.", "default": None},
        ],
        "keywords": ["tokenize asset", "rwa tokenize", "real world asset", "tokenize property", "digitize asset"],
        "follow_up": "What type of asset are you tokenizing, what's it worth, and do you have supporting documentation?",
        "example_conversation": (
            "User: I want to tokenize my property\n"
            "Trinity: That's exciting. What kind of property is it, what's the estimated value, and do you have documentation like a deed or appraisal I can reference?\n"
            "User: A 3-bedroom condo in Austin, worth about $350k, I have the deed and appraisal on IPFS\n"
            "Trinity: Tokenizing your Austin condo at a $350,000 valuation with your deed and appraisal as backing documentation. This creates a digital representation of your property on-chain.\n"
            "Trinity: [calls platform_action with action='rwa_tokenize', params={asset_type: 'property', description: '3-bedroom condo in downtown Austin', valuation_usd: 350000.0, documentation: ['ipfs://deed...', 'ipfs://appraisal...']}]"
        ),
    },

    "rwa_fractional_buy": {
        "action_name": "rwa_fractional_buy",
        "description": "Buy a fraction of a tokenized real-world asset.",
        "required_params": [
            {"name": "rwa_token", "type": "string", "description": "Token identifier of the real-world asset.", "example": "rwa_austin_condo_001"},
            {"name": "fraction_amount", "type": "number", "description": "Number of fractions to purchase.", "example": 100.0},
        ],
        "optional_params": [
            {"name": "max_price_per_fraction", "type": "number", "description": "Maximum price per fraction you're willing to pay.", "default": None},
        ],
        "keywords": ["buy fraction", "fractional property", "buy rwa", "fractional ownership", "partial purchase"],
        "follow_up": "Which tokenized asset do you want to buy into, and how many fractions?",
        "example_conversation": (
            "User: I want to buy a piece of that tokenized condo\n"
            "Trinity: Sure! How many fractions of the Austin condo do you want to pick up?\n"
            "User: 100 fractions\n"
            "Trinity: Purchasing 100 fractions of the Austin condo token. You'll earn proportional income from the asset.\n"
            "Trinity: [calls platform_action with action='rwa_fractional_buy', params={rwa_token: 'rwa_austin_condo_001', fraction_amount: 100.0}]"
        ),
    },

    "rwa_income_claim": {
        "action_name": "rwa_income_claim",
        "description": "Claim income or yield from a real-world asset position.",
        "required_params": [
            {"name": "rwa_token", "type": "string", "description": "Token identifier of the real-world asset.", "example": "rwa_austin_condo_001"},
        ],
        "optional_params": [
            {"name": "payout_asset", "type": "string", "description": "Preferred token for the payout.", "default": "USDC"},
        ],
        "keywords": ["claim rwa income", "rwa yield", "property income", "asset dividend"],
        "follow_up": "Which real-world asset would you like to claim income from?",
        "example_conversation": (
            "User: I want to collect my rental income from the property token\n"
            "Trinity: Sure thing. Which RWA token is it?\n"
            "User: rwa_austin_condo_001\n"
            "Trinity: Claiming your accumulated rental income from the Austin condo token. It'll be paid out in USDC.\n"
            "Trinity: [calls platform_action with action='rwa_income_claim', params={rwa_token: 'rwa_austin_condo_001'}]"
        ),
    },

    "rwa_verify": {
        "action_name": "rwa_verify",
        "description": "Verify the provenance and ownership chain of a tokenized asset.",
        "required_params": [
            {"name": "rwa_token", "type": "string", "description": "Token identifier of the real-world asset.", "example": "rwa_austin_condo_001"},
        ],
        "optional_params": [],
        "keywords": ["verify rwa", "rwa provenance", "asset verification", "ownership proof"],
        "follow_up": "Which real-world asset token would you like me to verify?",
        "example_conversation": (
            "User: Can you verify this real-world asset token is legit?\n"
            "Trinity: Absolutely. What's the RWA token ID? I'll trace the full ownership chain and check all the backing documentation.\n"
            "User: rwa_austin_condo_001\n"
            "Trinity: Verifying provenance for rwa_austin_condo_001 — checking the ownership chain, documentation, and valuation records.\n"
            "Trinity: [calls platform_action with action='rwa_verify', params={rwa_token: 'rwa_austin_condo_001'}]"
        ),
    },

    # ===================================================================
    # Payments
    # ===================================================================

    "stream_payment": {
        "action_name": "stream_payment",
        "description": "Start a payment stream that sends money continuously by the second.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient wallet address.", "example": "0xrecipient..."},
            {"name": "rate_per_second", "type": "number", "description": "Amount sent per second.", "example": 0.0001},
            {"name": "asset", "type": "string", "description": "Token to stream.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "duration_seconds", "type": "integer", "description": "Total stream duration in seconds (indefinite if omitted).", "default": None},
            {"name": "start_time", "type": "string", "description": "When to start the stream (ISO datetime, defaults to now).", "default": None},
        ],
        "keywords": ["stream payment", "streaming payment", "pay by second", "continuous payment", "real-time payment", "salary stream"],
        "follow_up": "Who are you streaming to, at what rate per second, and in which token? Would you like a fixed duration or open-ended?",
        "example_conversation": (
            "User: I want to set up a salary stream for a contractor\n"
            "Trinity: That's a great way to pay — real-time, by the second. Who's the recipient, what rate per second, and which token?\n"
            "User: 0xcontractor, 0.001 USDC per second, for 30 days\n"
            "Trinity: Starting a USDC payment stream to 0xcontractor at 0.001 per second for 30 days. That works out to about 2,592 USDC total. They can withdraw anytime.\n"
            "Trinity: [calls platform_action with action='stream_payment', params={recipient: '0xcontractor', rate_per_second: 0.001, asset: 'USDC', duration_seconds: 2592000}]"
        ),
    },

    "recurring_create": {
        "action_name": "recurring_create",
        "description": "Set up a recurring automatic payment on a schedule.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient wallet address.", "example": "0xlandlord..."},
            {"name": "amount", "type": "number", "description": "Amount per payment.", "example": 1500.0},
            {"name": "asset", "type": "string", "description": "Token to pay with.", "example": "USDC"},
            {"name": "interval", "type": "string", "description": "Payment frequency (daily, weekly, monthly).", "example": "monthly"},
        ],
        "optional_params": [
            {"name": "start_date", "type": "string", "description": "When to start the recurring payment (ISO date).", "default": None},
            {"name": "end_date", "type": "string", "description": "When to stop the recurring payment.", "default": None},
            {"name": "memo", "type": "string", "description": "Payment memo or note.", "default": None},
        ],
        "keywords": ["recurring payment", "automatic payment", "autopay", "scheduled payment", "monthly payment"],
        "follow_up": "Who's the recipient, how much each time, which token, and how often — daily, weekly, or monthly?",
        "example_conversation": (
            "User: I want to set up an automatic monthly payment\n"
            "Trinity: Easy. Who are you paying, how much, and in which token?\n"
            "User: 1500 USDC to 0xlandlord every month\n"
            "Trinity: Setting up a monthly recurring payment of 1,500 USDC to 0xlandlord. It'll go out automatically each month until you cancel.\n"
            "Trinity: [calls platform_action with action='recurring_create', params={recipient: '0xlandlord', amount: 1500.0, asset: 'USDC', interval: 'monthly'}]"
        ),
    },

    "escrow_milestone": {
        "action_name": "escrow_milestone",
        "description": "Create a milestone-based escrow — funds release as milestones are completed.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient who receives funds on milestone completion.", "example": "0xfreelancer..."},
            {"name": "total_amount", "type": "number", "description": "Total amount to escrow.", "example": 10000.0},
            {"name": "milestones", "type": "array", "description": "List of milestones with descriptions and amounts.", "example": [{"name": "Design", "amount": 3000}, {"name": "Development", "amount": 5000}, {"name": "Testing", "amount": 2000}]},
        ],
        "optional_params": [
            {"name": "asset", "type": "string", "description": "Token to use for escrow.", "default": "USDC"},
            {"name": "arbiter", "type": "string", "description": "Optional arbiter address for dispute resolution.", "default": None},
        ],
        "keywords": ["escrow", "milestone payment", "escrow release", "project payment", "milestone escrow"],
        "follow_up": "Who's the recipient, what's the total amount, and what are the milestones and their payment amounts?",
        "example_conversation": (
            "User: I want to set up a milestone escrow for a freelance project\n"
            "Trinity: Great way to protect both sides. Who's the freelancer, what's the total budget, and what are the milestones?\n"
            "User: 0xfreelancer, $10k total — $3k for design, $5k for development, $2k for testing\n"
            "Trinity: Creating a milestone escrow with 10,000 USDC. Funds release as each milestone is completed — Design ($3k), Development ($5k), Testing ($2k).\n"
            "Trinity: [calls platform_action with action='escrow_milestone', params={recipient: '0xfreelancer', total_amount: 10000.0, milestones: [{name: 'Design', amount: 3000}, {name: 'Development', amount: 5000}, {name: 'Testing', amount: 2000}]}]"
        ),
    },

    "payment_split": {
        "action_name": "payment_split",
        "description": "Split a payment among multiple recipients.",
        "required_params": [
            {"name": "recipients", "type": "array", "description": "List of recipient addresses.", "example": ["0xalice...", "0xbob...", "0xcharlie..."]},
            {"name": "amounts", "type": "array", "description": "List of amounts corresponding to each recipient.", "example": [100.0, 200.0, 300.0]},
            {"name": "asset", "type": "string", "description": "Token to split.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "memo", "type": "string", "description": "Payment memo or reason.", "default": None},
        ],
        "keywords": ["split payment", "divide payment", "split bill", "pay multiple", "shared payment"],
        "follow_up": "Who are the recipients, how much does each person get, and which token?",
        "example_conversation": (
            "User: I need to split a payment between three people\n"
            "Trinity: Sure thing. Who are the recipients, how much does each one get, and which token?\n"
            "User: Alice gets 100, Bob gets 200, Charlie gets 300 — all USDC\n"
            "Trinity: Splitting the payment — 100 USDC to Alice, 200 to Bob, 300 to Charlie. All sent in a single transaction.\n"
            "Trinity: [calls platform_action with action='payment_split', params={recipients: ['0xalice', '0xbob', '0xcharlie'], amounts: [100.0, 200.0, 300.0], asset: 'USDC'}]"
        ),
    },

    "cross_border_remit": {
        "action_name": "cross_border_remit",
        "description": "Send a cross-border remittance with automatic currency conversion.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient wallet address or payment identifier.", "example": "0xrecipient..."},
            {"name": "amount", "type": "number", "description": "Amount to send in the source currency.", "example": 500.0},
            {"name": "source_currency", "type": "string", "description": "Currency you're sending from.", "example": "USD"},
            {"name": "target_currency", "type": "string", "description": "Currency the recipient receives.", "example": "MXN"},
        ],
        "optional_params": [
            {"name": "speed", "type": "string", "description": "Transfer speed (instant, standard).", "default": "standard"},
            {"name": "corridor", "type": "string", "description": "Specific payment corridor or route.", "default": "auto"},
        ],
        "keywords": ["remittance", "cross border", "send abroad", "international transfer", "foreign payment"],
        "follow_up": "Who are you sending to, how much, and what are the source and destination currencies?",
        "example_conversation": (
            "User: I need to send money to my family in Mexico\n"
            "Trinity: Of course. How much are you sending in USD, and do you have their wallet or payment address?\n"
            "User: $500 to 0xfamily\n"
            "Trinity: Sending $500 USD to 0xfamily, converting to MXN on arrival. Much faster and cheaper than traditional wire transfers.\n"
            "Trinity: [calls platform_action with action='cross_border_remit', params={recipient: '0xfamily', amount: 500.0, source_currency: 'USD', target_currency: 'MXN'}]"
        ),
    },

    "invoice_factor": {
        "action_name": "invoice_factor",
        "description": "Factor an invoice on-chain — get paid immediately against outstanding invoices.",
        "required_params": [
            {"name": "invoice_id", "type": "string", "description": "Identifier of the invoice to factor.", "example": "inv_2024_001"},
            {"name": "amount", "type": "number", "description": "Invoice amount.", "example": 25000.0},
            {"name": "due_date", "type": "string", "description": "When the invoice is due (ISO date).", "example": "2026-06-15"},
        ],
        "optional_params": [
            {"name": "discount_rate", "type": "number", "description": "Acceptable discount rate for early payment.", "default": None},
            {"name": "asset", "type": "string", "description": "Token to receive the advance in.", "default": "USDC"},
        ],
        "keywords": ["invoice factoring", "factor invoice", "early payment", "invoice financing"],
        "follow_up": "Which invoice do you want to factor, what's the amount, and when is it due?",
        "example_conversation": (
            "User: I need cash now against an outstanding invoice\n"
            "Trinity: Invoice factoring can help with that. What's the invoice ID, the amount, and when is it due?\n"
            "User: Invoice inv_2024_001, $25,000, due June 15th\n"
            "Trinity: Factoring invoice inv_2024_001 for $25,000 due 2026-06-15. You'll get paid upfront at a small discount, and the buyer pays the full amount on the due date.\n"
            "Trinity: [calls platform_action with action='invoice_factor', params={invoice_id: 'inv_2024_001', amount: 25000.0, due_date: '2026-06-15'}]"
        ),
    },

    "payroll_run": {
        "action_name": "payroll_run",
        "description": "Execute a crypto payroll run for multiple recipients.",
        "required_params": [
            {"name": "payroll_list", "type": "array", "description": "List of payroll entries with recipient and amount.", "example": [{"address": "0xalice", "amount": 5000}, {"address": "0xbob", "amount": 4500}]},
            {"name": "asset", "type": "string", "description": "Token to pay in.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "memo", "type": "string", "description": "Payroll memo (e.g. 'April 2026 salaries').", "default": None},
            {"name": "tax_withholding", "type": "boolean", "description": "Whether to apply tax withholding calculations.", "default": False},
        ],
        "keywords": ["payroll", "pay employees", "salary distribution", "mass payment", "batch payroll"],
        "follow_up": "Who's on the payroll, how much does each person get, and which token?",
        "example_conversation": (
            "User: I need to run payroll for my team\n"
            "Trinity: Let's get everyone paid. How many people, how much each, and which token?\n"
            "User: Alice gets 5000 USDC, Bob gets 4500 USDC\n"
            "Trinity: Running payroll — 5,000 USDC to Alice, 4,500 USDC to Bob. All payments go out in a single batch transaction.\n"
            "Trinity: [calls platform_action with action='payroll_run', params={payroll_list: [{address: '0xalice', amount: 5000}, {address: '0xbob', amount: 4500}], asset: 'USDC'}]"
        ),
    },

    # ===================================================================
    # Privacy
    # ===================================================================

    "private_transfer": {
        "action_name": "private_transfer",
        "description": "Send a private transfer hidden by zero-knowledge cryptography.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient address or shielded address.", "example": "0xrecipient..."},
            {"name": "amount", "type": "number", "description": "Amount to send.", "example": 100.0},
            {"name": "asset", "type": "string", "description": "Token to send.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "privacy_level", "type": "string", "description": "Level of privacy (standard, maximum).", "default": "standard"},
            {"name": "memo", "type": "string", "description": "Encrypted memo visible only to the recipient.", "default": None},
        ],
        "keywords": ["private transfer", "anonymous send", "zk transfer", "hidden transfer", "confidential send", "private payment"],
        "follow_up": "Who are you sending to, how much, and in which token?",
        "example_conversation": (
            "User: I want to send funds privately\n"
            "Trinity: Understood — I'll use zero-knowledge cryptography so the transfer details stay hidden. Who's the recipient, how much, and which token?\n"
            "User: 500 USDC to 0xrecipient\n"
            "Trinity: Sending 500 USDC to 0xrecipient via a private ZK transfer. The amount and recipient are shielded from public view.\n"
            "Trinity: [calls platform_action with action='private_transfer', params={recipient: '0xrecipient', amount: 500.0, asset: 'USDC'}]"
        ),
    },

    "stealth_address": {
        "action_name": "stealth_address",
        "description": "Generate a one-time stealth address for private receiving.",
        "required_params": [
            {"name": "base_address", "type": "string", "description": "Your base wallet address to derive the stealth address from.", "example": "0xmywallet..."},
        ],
        "optional_params": [
            {"name": "label", "type": "string", "description": "Optional label for this stealth address.", "default": None},
        ],
        "keywords": ["stealth address", "private receive", "one-time address", "anonymous address"],
        "follow_up": "What's your base wallet address? I'll generate a fresh one-time stealth address for you.",
        "example_conversation": (
            "User: I need a stealth address to receive a payment privately\n"
            "Trinity: Smart move. Give me your base wallet address and I'll derive a fresh one-time address that can't be linked back to you publicly.\n"
            "User: 0xmywallet\n"
            "Trinity: Generating a one-time stealth address from 0xmywallet. Share this with the sender — only you can access funds sent to it.\n"
            "Trinity: [calls platform_action with action='stealth_address', params={base_address: '0xmywallet'}]"
        ),
    },

    "zk_proof_generate": {
        "action_name": "zk_proof_generate",
        "description": "Generate a zero-knowledge proof for verification without revealing data.",
        "required_params": [
            {"name": "statement", "type": "string", "description": "The statement to prove (e.g. 'balance > 1000').", "example": "balance > 1000"},
            {"name": "private_inputs", "type": "object", "description": "Private data used to generate the proof (never revealed).", "example": {"actual_balance": 5000}},
        ],
        "optional_params": [
            {"name": "proof_system", "type": "string", "description": "Which ZK proof system to use (groth16, plonk, stark).", "default": "plonk"},
        ],
        "keywords": ["zk proof", "zero knowledge proof", "prove without revealing", "privacy proof"],
        "follow_up": "What statement do you want to prove, and what private data should the proof be built from?",
        "example_conversation": (
            "User: I need to prove I have enough funds without showing my balance\n"
            "Trinity: Zero-knowledge proofs are perfect for that. What's the statement you want to prove — something like 'balance is greater than X'?\n"
            "User: Prove my balance is over 1000 USDC\n"
            "Trinity: Generating a ZK proof that your balance exceeds 1,000 USDC. The verifier will know the statement is true without seeing your actual balance.\n"
            "Trinity: [calls platform_action with action='zk_proof_generate', params={statement: 'balance > 1000', private_inputs: {actual_balance: 5000}}]"
        ),
    },

    "private_vote": {
        "action_name": "private_vote",
        "description": "Cast a private on-chain vote where your choice is hidden but verifiable.",
        "required_params": [
            {"name": "proposal_id", "type": "string", "description": "The proposal to vote on.", "example": "prop_xyz"},
            {"name": "choice", "type": "integer", "description": "Your choice (option number).", "example": 1},
        ],
        "optional_params": [
            {"name": "weight", "type": "number", "description": "Voting weight to apply.", "default": None},
        ],
        "keywords": ["private vote", "anonymous vote", "secret ballot", "hidden vote"],
        "follow_up": "Which proposal do you want to vote on, and which option?",
        "example_conversation": (
            "User: I want to vote on a proposal but keep my choice private\n"
            "Trinity: No problem — I'll cast a private vote using cryptographic commitments. Nobody can see your choice until voting ends. Which proposal and which option?\n"
            "User: Proposal prop_xyz, option 1\n"
            "Trinity: Casting a private vote for option 1 on proposal prop_xyz. Your vote is committed on-chain but your choice stays encrypted until the reveal phase.\n"
            "Trinity: [calls platform_action with action='private_vote', params={proposal_id: 'prop_xyz', choice: 1}]"
        ),
    },

    "confidential_compute": {
        "action_name": "confidential_compute",
        "description": "Execute computation on encrypted data without revealing the data.",
        "required_params": [
            {"name": "computation", "type": "string", "description": "The computation to run (e.g. 'sum', 'average', custom function).", "example": "average_salary"},
            {"name": "encrypted_inputs", "type": "object", "description": "Encrypted data inputs for the computation.", "example": {"dataset_ref": "enc_data_001"}},
        ],
        "optional_params": [
            {"name": "output_format", "type": "string", "description": "Format for the result (encrypted, plaintext, proof).", "default": "plaintext"},
            {"name": "compute_network", "type": "string", "description": "Which confidential compute network to use.", "default": "auto"},
        ],
        "keywords": ["confidential compute", "private computation", "encrypted execution", "secure compute"],
        "follow_up": "What computation do you want to run, and on which encrypted data?",
        "example_conversation": (
            "User: I need to compute an average across sensitive data without exposing it\n"
            "Trinity: Confidential compute is built for exactly this. What computation are you running, and where is the encrypted data stored?\n"
            "User: Average salary computation on dataset enc_data_001\n"
            "Trinity: Running the average salary computation on encrypted dataset enc_data_001. The data stays encrypted throughout — only the result is revealed.\n"
            "Trinity: [calls platform_action with action='confidential_compute', params={computation: 'average_salary', encrypted_inputs: {dataset_ref: 'enc_data_001'}}]"
        ),
    },

    # ===================================================================
    # Social
    # ===================================================================

    "social_post": {
        "action_name": "social_post",
        "description": "Publish a post on-chain — censorship-resistant and permanently recorded.",
        "required_params": [
            {"name": "content", "type": "string", "description": "The content of the post.", "example": "Just deployed my first smart contract!"},
        ],
        "optional_params": [
            {"name": "tags", "type": "array", "description": "Tags or topics for the post.", "default": []},
            {"name": "media_urls", "type": "array", "description": "URLs of images or media to attach.", "default": []},
        ],
        "keywords": ["post on chain", "decentralized post", "publish on chain", "permanent post", "censorship resistant"],
        "follow_up": "What would you like to post? You can also add tags or media if you'd like.",
        "example_conversation": (
            "User: I want to publish a post on-chain\n"
            "Trinity: Love it — once it's on-chain, nobody can take it down. What do you want to say?\n"
            "User: Just deployed my first smart contract! #web3 #builder\n"
            "Trinity: Publishing your post on-chain with the tags web3 and builder. This one's permanent and censorship-resistant.\n"
            "Trinity: [calls platform_action with action='social_post', params={content: 'Just deployed my first smart contract!', tags: ['web3', 'builder']}]"
        ),
    },

    "social_follow": {
        "action_name": "social_follow",
        "description": "Follow a wallet or identity on the decentralized social graph.",
        "required_params": [
            {"name": "target", "type": "string", "description": "Wallet address or DID to follow.", "example": "vitalik.eth"},
        ],
        "optional_params": [
            {"name": "notify", "type": "boolean", "description": "Whether to receive notifications for their activity.", "default": True},
        ],
        "keywords": ["follow", "follow wallet", "social follow", "connect with", "follow user"],
        "follow_up": "Who would you like to follow? Give me their wallet address, ENS name, or DID.",
        "example_conversation": (
            "User: I want to follow vitalik.eth\n"
            "Trinity: Following vitalik.eth on the decentralized social graph. You'll see their on-chain activity and posts in your feed.\n"
            "Trinity: [calls platform_action with action='social_follow', params={target: 'vitalik.eth'}]"
        ),
    },

    "social_gate": {
        "action_name": "social_gate",
        "description": "Create token-gated content accessible only to holders of a specific token.",
        "required_params": [
            {"name": "content", "type": "string", "description": "The gated content.", "example": "Exclusive alpha on the upcoming launch..."},
            {"name": "required_token", "type": "string", "description": "Token address or name required for access.", "example": "0xtoken..."},
            {"name": "min_balance", "type": "number", "description": "Minimum token balance needed to access.", "example": 100.0},
        ],
        "optional_params": [
            {"name": "expiry", "type": "string", "description": "When the gated content expires.", "default": None},
        ],
        "keywords": ["token gate", "gated content", "members only", "token holders only", "exclusive content"],
        "follow_up": "What's the content, which token is required for access, and what's the minimum holding?",
        "example_conversation": (
            "User: I want to create exclusive content for my token holders\n"
            "Trinity: Token-gating — nice. What content do you want to share, which token do holders need, and what's the minimum balance for access?\n"
            "User: A strategy update, holders of my ALPHA token need at least 100\n"
            "Trinity: Creating token-gated content accessible only to wallets holding 100+ ALPHA tokens. Non-holders will see that it's locked.\n"
            "Trinity: [calls platform_action with action='social_gate', params={content: 'Exclusive alpha on the upcoming launch...', required_token: 'ALPHA', min_balance: 100.0}]"
        ),
    },

    "creator_monetize": {
        "action_name": "creator_monetize",
        "description": "Set up creator monetization — tips, subscriptions, or pay-per-view.",
        "required_params": [
            {"name": "creator_address", "type": "string", "description": "Wallet address of the creator.", "example": "0xcreator..."},
            {"name": "monetization_type", "type": "string", "description": "Type of monetization (tips, subscription, ppv).", "example": "subscription"},
        ],
        "optional_params": [
            {"name": "price", "type": "number", "description": "Subscription price or PPV cost.", "default": None},
            {"name": "asset", "type": "string", "description": "Token to accept payments in.", "default": "USDC"},
            {"name": "interval", "type": "string", "description": "Billing interval for subscriptions.", "default": "monthly"},
        ],
        "keywords": ["creator monetize", "monetize content", "set up tips", "creator earnings", "content monetization"],
        "follow_up": "What type of monetization do you want — tips, subscriptions, or pay-per-view? And what's the pricing?",
        "example_conversation": (
            "User: I want to monetize my content with subscriptions\n"
            "Trinity: Great idea. What should the subscription price be, and which token do you want to accept?\n"
            "User: $10 USDC per month\n"
            "Trinity: Setting up monthly subscriptions at 10 USDC for your content. Subscribers pay on-chain and get continuous access.\n"
            "Trinity: [calls platform_action with action='creator_monetize', params={creator_address: '0xcreator', monetization_type: 'subscription', price: 10.0}]"
        ),
    },

    "community_create": {
        "action_name": "community_create",
        "description": "Create a token-gated community with membership requirements.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Name of the community.", "example": "Alpha Traders Club"},
            {"name": "required_token", "type": "string", "description": "Token required for membership.", "example": "0xtoken..."},
            {"name": "min_balance", "type": "number", "description": "Minimum token balance for membership.", "example": 50.0},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Description of the community.", "default": None},
            {"name": "rules", "type": "array", "description": "Community rules or guidelines.", "default": []},
        ],
        "keywords": ["create community", "token community", "gated community", "membership community"],
        "follow_up": "What's the community name, which token is required, and what's the minimum balance to join?",
        "example_conversation": (
            "User: I want to create a token-gated community\n"
            "Trinity: Fun! What should the community be called, which token do members need, and how much?\n"
            "User: Alpha Traders Club, need at least 50 ALPHA tokens\n"
            "Trinity: Creating the Alpha Traders Club — only wallets with 50+ ALPHA tokens can join. Membership is verified on-chain in real time.\n"
            "Trinity: [calls platform_action with action='community_create', params={name: 'Alpha Traders Club', required_token: 'ALPHA', min_balance: 50.0}]"
        ),
    },

    "message_encrypt": {
        "action_name": "message_encrypt",
        "description": "Send an end-to-end encrypted message via XMTP.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient wallet address or ENS name.", "example": "alice.eth"},
            {"name": "message", "type": "string", "description": "The message content.", "example": "Hey, let's discuss the proposal privately."},
        ],
        "optional_params": [
            {"name": "attachments", "type": "array", "description": "List of attachment references.", "default": []},
        ],
        "keywords": ["encrypted message", "private message", "xmtp", "secure message", "encrypted chat"],
        "follow_up": "Who do you want to message, and what should it say?",
        "example_conversation": (
            "User: I need to send a private message to alice.eth\n"
            "Trinity: I'll send it end-to-end encrypted via XMTP. What would you like to say?\n"
            "User: Hey Alice, let's discuss the proposal privately\n"
            "Trinity: Sending an encrypted message to alice.eth via XMTP. Only Alice can read it.\n"
            "Trinity: [calls platform_action with action='message_encrypt', params={recipient: 'alice.eth', message: 'Hey, let\\'s discuss the proposal privately.'}]"
        ),
    },

    # ===================================================================
    # Gaming
    # ===================================================================

    "game_asset_mint": {
        "action_name": "game_asset_mint",
        "description": "Mint a game asset as an NFT — usable across supported games.",
        "required_params": [
            {"name": "game_id", "type": "string", "description": "Identifier of the game.", "example": "axie_infinity"},
            {"name": "asset_type", "type": "string", "description": "Type of game asset (weapon, character, skin, land, etc.).", "example": "weapon"},
            {"name": "metadata", "type": "object", "description": "Asset metadata — name, attributes, stats.", "example": {"name": "Flame Sword", "damage": 150, "rarity": "legendary"}},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Wallet to receive the minted asset.", "default": None},
        ],
        "keywords": ["game asset", "mint game item", "game nft", "in-game item"],
        "follow_up": "Which game, what type of asset, and what are its attributes?",
        "example_conversation": (
            "User: I want to mint a game weapon as an NFT\n"
            "Trinity: Cool! Which game is it for, and what are the weapon's stats and attributes?\n"
            "User: Axie Infinity, a legendary Flame Sword with 150 damage\n"
            "Trinity: Minting a legendary Flame Sword NFT for Axie Infinity with 150 damage. You'll own it on-chain and can use it in any compatible game.\n"
            "Trinity: [calls platform_action with action='game_asset_mint', params={game_id: 'axie_infinity', asset_type: 'weapon', metadata: {name: 'Flame Sword', damage: 150, rarity: 'legendary'}}]"
        ),
    },

    "tournament_enter": {
        "action_name": "tournament_enter",
        "description": "Enter a tournament with a prize pool — stake entry fee.",
        "required_params": [
            {"name": "tournament_id", "type": "string", "description": "Tournament identifier.", "example": "tourney_001"},
            {"name": "entry_fee", "type": "number", "description": "Entry fee amount.", "example": 50.0},
        ],
        "optional_params": [
            {"name": "team_name", "type": "string", "description": "Your team or player name.", "default": None},
            {"name": "asset", "type": "string", "description": "Token for the entry fee.", "default": "USDC"},
        ],
        "keywords": ["tournament", "enter tournament", "gaming competition", "prize pool", "esports"],
        "follow_up": "Which tournament do you want to enter, and what's the entry fee?",
        "example_conversation": (
            "User: I want to enter a gaming tournament\n"
            "Trinity: Let's get you in. Which tournament, and what's the entry fee?\n"
            "User: Tournament tourney_001, 50 USDC entry\n"
            "Trinity: Entering you into tourney_001 with a 50 USDC entry fee. Your stake goes into the prize pool. Good luck!\n"
            "Trinity: [calls platform_action with action='tournament_enter', params={tournament_id: 'tourney_001', entry_fee: 50.0}]"
        ),
    },

    "game_item_trade": {
        "action_name": "game_item_trade",
        "description": "Trade game items with other players across games.",
        "required_params": [
            {"name": "item_id", "type": "string", "description": "ID of the game item to trade.", "example": "item_flame_sword_01"},
            {"name": "price", "type": "number", "description": "Asking price.", "example": 25.0},
            {"name": "asset", "type": "string", "description": "Token to price in.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "action", "type": "string", "description": "Whether to list for sale or buy ('sell' or 'buy').", "default": "sell"},
            {"name": "game_id", "type": "string", "description": "Game the item belongs to.", "default": None},
        ],
        "keywords": ["trade game item", "sell game item", "game marketplace", "item exchange"],
        "follow_up": "Which item do you want to trade, and at what price?",
        "example_conversation": (
            "User: I want to sell my Flame Sword game item\n"
            "Trinity: Let's list it. What's the item ID, and what price do you want?\n"
            "User: Item item_flame_sword_01, asking 25 USDC\n"
            "Trinity: Listing your Flame Sword on the game marketplace for 25 USDC. Any player can buy it.\n"
            "Trinity: [calls platform_action with action='game_item_trade', params={item_id: 'item_flame_sword_01', price: 25.0, asset: 'USDC'}]"
        ),
    },

    "achievement_attest": {
        "action_name": "achievement_attest",
        "description": "Record a gaming achievement as an on-chain attestation.",
        "required_params": [
            {"name": "game_id", "type": "string", "description": "Game the achievement is from.", "example": "dark_forest"},
            {"name": "achievement", "type": "string", "description": "Name or description of the achievement.", "example": "First to conquer planet X-42"},
            {"name": "proof", "type": "object", "description": "Proof data (transaction hash, game state snapshot, etc.).", "example": {"tx_hash": "0xproof...", "timestamp": "2026-04-01T12:00:00Z"}},
        ],
        "optional_params": [
            {"name": "recipient", "type": "string", "description": "Wallet to receive the attestation.", "default": None},
        ],
        "keywords": ["game achievement", "attest achievement", "gaming proof", "on-chain achievement"],
        "follow_up": "Which game, what achievement, and do you have proof data?",
        "example_conversation": (
            "User: I want to record my gaming achievement on-chain\n"
            "Trinity: That's a great way to immortalize it. Which game, what did you achieve, and do you have the proof — like a transaction hash or game snapshot?\n"
            "User: Dark Forest, first to conquer planet X-42, here's the tx hash\n"
            "Trinity: Recording your Dark Forest achievement on-chain — first to conquer planet X-42. This attestation is permanent proof of your accomplishment.\n"
            "Trinity: [calls platform_action with action='achievement_attest', params={game_id: 'dark_forest', achievement: 'First to conquer planet X-42', proof: {tx_hash: '0xproof...'}}]"
        ),
    },

    # ===================================================================
    # Prediction Markets
    # ===================================================================

    "market_create": {
        "action_name": "market_create",
        "description": "Create a prediction market for any yes/no or multiple-choice question.",
        "required_params": [
            {"name": "question", "type": "string", "description": "The question the market is predicting.", "example": "Will ETH reach $10k by end of 2026?"},
            {"name": "outcomes", "type": "array", "description": "List of possible outcomes.", "example": ["Yes", "No"]},
            {"name": "resolution_date", "type": "string", "description": "When the market resolves (ISO date).", "example": "2026-12-31"},
        ],
        "optional_params": [
            {"name": "resolution_source", "type": "string", "description": "Source used to determine the outcome.", "default": None},
            {"name": "initial_liquidity", "type": "number", "description": "Initial liquidity to seed the market.", "default": None},
            {"name": "asset", "type": "string", "description": "Token for betting.", "default": "USDC"},
        ],
        "keywords": ["create market", "prediction market", "create prediction", "bet market", "forecast market"],
        "follow_up": "What question do you want to predict, what are the possible outcomes, and when should it resolve?",
        "example_conversation": (
            "User: I want to create a prediction market\n"
            "Trinity: Exciting! What question do you want people to bet on, what are the outcomes, and when should it resolve?\n"
            "User: Will ETH reach $10k by end of 2026? Yes or No, resolve Dec 31st\n"
            "Trinity: Creating a prediction market — 'Will ETH reach $10k by end of 2026?' with Yes/No outcomes, resolving December 31, 2026.\n"
            "Trinity: [calls platform_action with action='market_create', params={question: 'Will ETH reach $10k by end of 2026?', outcomes: ['Yes', 'No'], resolution_date: '2026-12-31'}]"
        ),
    },

    "market_bet": {
        "action_name": "market_bet",
        "description": "Place a bet on a prediction market outcome.",
        "required_params": [
            {"name": "market_id", "type": "string", "description": "The market to bet on.", "example": "mkt_eth10k"},
            {"name": "outcome", "type": "string", "description": "The outcome you're betting on.", "example": "Yes"},
            {"name": "amount", "type": "number", "description": "Amount to bet.", "example": 100.0},
        ],
        "optional_params": [
            {"name": "asset", "type": "string", "description": "Token to bet with.", "default": "USDC"},
        ],
        "keywords": ["place bet", "predict", "bet on", "wager", "prediction bet"],
        "follow_up": "Which market, what outcome, and how much do you want to bet?",
        "example_conversation": (
            "User: I want to bet on a prediction market\n"
            "Trinity: Which market, which outcome are you picking, and how much are you putting down?\n"
            "User: Market mkt_eth10k, betting Yes for 200 USDC\n"
            "Trinity: Placing a 200 USDC bet on 'Yes' in market mkt_eth10k. If you're right, you'll earn based on the payout odds.\n"
            "Trinity: [calls platform_action with action='market_bet', params={market_id: 'mkt_eth10k', outcome: 'Yes', amount: 200.0}]"
        ),
    },

    "market_resolve": {
        "action_name": "market_resolve",
        "description": "Resolve a prediction market with the verified outcome.",
        "required_params": [
            {"name": "market_id", "type": "string", "description": "The market to resolve.", "example": "mkt_eth10k"},
            {"name": "winning_outcome", "type": "string", "description": "The verified winning outcome.", "example": "Yes"},
        ],
        "optional_params": [
            {"name": "evidence", "type": "string", "description": "Link or reference to evidence supporting the outcome.", "default": None},
        ],
        "keywords": ["resolve market", "settle market", "market result", "close market"],
        "follow_up": "Which market and what's the winning outcome?",
        "example_conversation": (
            "User: I need to resolve a prediction market\n"
            "Trinity: Which market, and what was the verified outcome?\n"
            "User: Market mkt_eth10k, the answer is Yes\n"
            "Trinity: Resolving market mkt_eth10k with 'Yes' as the winning outcome. Winners can now claim their payouts.\n"
            "Trinity: [calls platform_action with action='market_resolve', params={market_id: 'mkt_eth10k', winning_outcome: 'Yes'}]"
        ),
    },

    "market_query": {
        "action_name": "market_query",
        "description": "Check current odds and volume on active prediction markets.",
        "required_params": [
            {"name": "market_id", "type": "string", "description": "The market to query.", "example": "mkt_eth10k"},
        ],
        "optional_params": [],
        "keywords": ["market odds", "check prediction", "market status", "current odds"],
        "follow_up": "Which prediction market would you like me to check?",
        "example_conversation": (
            "User: What are the odds on the ETH prediction market?\n"
            "Trinity: Let me pull up the current odds and trading volume. What's the market ID?\n"
            "User: mkt_eth10k\n"
            "Trinity: Checking the current odds and volume on market mkt_eth10k for you.\n"
            "Trinity: [calls platform_action with action='market_query', params={market_id: 'mkt_eth10k'}]"
        ),
    },

    # ===================================================================
    # Supply Chain
    # ===================================================================

    "provenance_log": {
        "action_name": "provenance_log",
        "description": "Log a supply chain event — manufacturing, shipping, inspection.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product or item identifier.", "example": "prod_coffee_001"},
            {"name": "event_type", "type": "string", "description": "Type of event (manufactured, shipped, inspected, delivered, etc.).", "example": "shipped"},
            {"name": "location", "type": "string", "description": "Location where the event occurred.", "example": "Port of Rotterdam"},
            {"name": "details", "type": "object", "description": "Event details — timestamps, handler, conditions.", "example": {"handler": "DHL", "temperature_c": 4, "condition": "good"}},
        ],
        "optional_params": [
            {"name": "timestamp", "type": "string", "description": "Event timestamp (ISO datetime, defaults to now).", "default": None},
            {"name": "certifications", "type": "array", "description": "Any certifications verified at this step.", "default": []},
        ],
        "keywords": ["log provenance", "supply chain event", "track shipment", "log origin"],
        "follow_up": "Which product, what event type, where did it happen, and what are the details?",
        "example_conversation": (
            "User: I need to log a shipment event for our coffee batch\n"
            "Trinity: Sure. What's the product ID, where is it being shipped from, and any details like handler or conditions?\n"
            "User: Product prod_coffee_001, shipped from Port of Rotterdam via DHL, temperature held at 4C\n"
            "Trinity: Logging the shipment event for prod_coffee_001 from the Port of Rotterdam — DHL handling at 4C. This is now permanently recorded on-chain.\n"
            "Trinity: [calls platform_action with action='provenance_log', params={product_id: 'prod_coffee_001', event_type: 'shipped', location: 'Port of Rotterdam', details: {handler: 'DHL', temperature_c: 4, condition: 'good'}}]"
        ),
    },

    "batch_track": {
        "action_name": "batch_track",
        "description": "Track a batch of products through the supply chain.",
        "required_params": [
            {"name": "batch_id", "type": "string", "description": "Batch identifier to track.", "example": "batch_2026_q1_001"},
        ],
        "optional_params": [
            {"name": "include_events", "type": "boolean", "description": "Whether to include all event history.", "default": True},
        ],
        "keywords": ["track batch", "batch status", "shipment tracking", "where is batch"],
        "follow_up": "What's the batch ID you want to track?",
        "example_conversation": (
            "User: Where is our Q1 batch right now?\n"
            "Trinity: Let me look that up. What's the batch ID?\n"
            "User: batch_2026_q1_001\n"
            "Trinity: Tracking batch_2026_q1_001 through the supply chain — I'll show you every event from origin to current location.\n"
            "Trinity: [calls platform_action with action='batch_track', params={batch_id: 'batch_2026_q1_001'}]"
        ),
    },

    "authenticity_verify": {
        "action_name": "authenticity_verify",
        "description": "Verify the authenticity of a product using its on-chain record.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product identifier to verify.", "example": "prod_handbag_001"},
        ],
        "optional_params": [],
        "keywords": ["verify authentic", "is it real", "product verification", "counterfeit check", "authenticity"],
        "follow_up": "What's the product ID you want to verify?",
        "example_conversation": (
            "User: Is this handbag authentic?\n"
            "Trinity: I can check that against the on-chain record. What's the product ID or serial number?\n"
            "User: prod_handbag_001\n"
            "Trinity: Verifying the authenticity of prod_handbag_001 by tracing its full provenance on-chain — from manufacturer to you.\n"
            "Trinity: [calls platform_action with action='authenticity_verify', params={product_id: 'prod_handbag_001'}]"
        ),
    },

    "custody_transfer": {
        "action_name": "custody_transfer",
        "description": "Transfer custody of goods from one party to another on-chain.",
        "required_params": [
            {"name": "product_id", "type": "string", "description": "Product identifier.", "example": "prod_wine_crate_01"},
            {"name": "from_party", "type": "string", "description": "Current custodian address or name.", "example": "0xwarehouse..."},
            {"name": "to_party", "type": "string", "description": "New custodian address or name.", "example": "0xretailer..."},
        ],
        "optional_params": [
            {"name": "location", "type": "string", "description": "Location of the handoff.", "default": None},
            {"name": "condition_notes", "type": "string", "description": "Notes on the condition of goods at transfer.", "default": None},
        ],
        "keywords": ["transfer custody", "hand off", "custody change", "change owner"],
        "follow_up": "Which product, who is handing it off, and who is receiving it?",
        "example_conversation": (
            "User: I need to transfer custody of a wine shipment\n"
            "Trinity: Got it. What's the product ID, who currently has custody, and who's receiving it?\n"
            "User: prod_wine_crate_01, from 0xwarehouse to 0xretailer\n"
            "Trinity: Transferring custody of prod_wine_crate_01 from the warehouse to the retailer. Both parties sign and it's recorded on-chain.\n"
            "Trinity: [calls platform_action with action='custody_transfer', params={product_id: 'prod_wine_crate_01', from_party: '0xwarehouse', to_party: '0xretailer'}]"
        ),
    },

    # ===================================================================
    # Insurance
    # ===================================================================

    "parametric_policy": {
        "action_name": "parametric_policy",
        "description": "Create a parametric insurance policy that pays automatically when conditions are met.",
        "required_params": [
            {"name": "policy_type", "type": "string", "description": "Type of parametric policy (weather, flight_delay, earthquake, crop, etc.).", "example": "weather"},
            {"name": "coverage", "type": "object", "description": "Coverage details — amount, asset, region.", "example": {"amount": 10000, "asset": "USDC", "region": "Miami, FL"}},
            {"name": "trigger_conditions", "type": "object", "description": "Conditions that trigger automatic payout.", "example": {"wind_speed_mph_gt": 110, "data_source": "NOAA"}},
        ],
        "optional_params": [
            {"name": "premium", "type": "number", "description": "Policy premium amount.", "default": None},
            {"name": "duration", "type": "string", "description": "Policy coverage period.", "default": "1y"},
        ],
        "keywords": ["parametric insurance", "automatic insurance", "weather insurance", "parametric policy"],
        "follow_up": "What type of event are you insuring against, what coverage do you need, and what conditions should trigger the payout?",
        "example_conversation": (
            "User: I want hurricane insurance that pays out automatically\n"
            "Trinity: Parametric insurance is perfect for that — pays instantly when the conditions hit. What coverage amount, which region, and what wind speed threshold should trigger the payout?\n"
            "User: $10,000 coverage in Miami, trigger if winds exceed 110 mph\n"
            "Trinity: Creating a parametric weather policy — $10,000 USDC coverage for Miami, auto-payout if wind speeds exceed 110 mph per NOAA data. No claims process needed.\n"
            "Trinity: [calls platform_action with action='parametric_policy', params={policy_type: 'weather', coverage: {amount: 10000, asset: 'USDC', region: 'Miami, FL'}, trigger_conditions: {wind_speed_mph_gt: 110, data_source: 'NOAA'}}]"
        ),
    },

    "claim_auto_settle": {
        "action_name": "claim_auto_settle",
        "description": "Trigger automatic settlement of an insurance claim.",
        "required_params": [
            {"name": "policy_id", "type": "string", "description": "The policy to trigger a claim on.", "example": "policy_weather_001"},
            {"name": "trigger_data", "type": "object", "description": "Data proving the trigger condition was met.", "example": {"wind_speed_mph": 125, "source": "NOAA", "timestamp": "2026-08-15T14:00:00Z"}},
        ],
        "optional_params": [
            {"name": "payout_address", "type": "string", "description": "Address to receive the payout.", "default": None},
        ],
        "keywords": ["settle claim", "automatic payout", "trigger claim", "insurance payout"],
        "follow_up": "Which policy, and what's the trigger data proving the condition was met?",
        "example_conversation": (
            "User: The hurricane hit — I need to trigger my insurance payout\n"
            "Trinity: I'm sorry about the storm. Let me settle your claim. What's the policy ID, and do you have the trigger data from the data source?\n"
            "User: Policy policy_weather_001, winds were recorded at 125 mph by NOAA\n"
            "Trinity: Triggering automatic settlement on policy_weather_001. NOAA recorded 125 mph — that exceeds your 110 mph threshold, so the payout will process immediately.\n"
            "Trinity: [calls platform_action with action='claim_auto_settle', params={policy_id: 'policy_weather_001', trigger_data: {wind_speed_mph: 125, source: 'NOAA'}}]"
        ),
    },

    "cover_renew": {
        "action_name": "cover_renew",
        "description": "Renew an existing insurance coverage period.",
        "required_params": [
            {"name": "policy_id", "type": "string", "description": "The policy to renew.", "example": "policy_weather_001"},
            {"name": "new_period", "type": "string", "description": "New coverage period (e.g. '6m', '1y').", "example": "1y"},
        ],
        "optional_params": [
            {"name": "updated_coverage", "type": "object", "description": "Updated coverage details if changing the terms.", "default": None},
        ],
        "keywords": ["renew insurance", "extend coverage", "renew policy", "continue coverage"],
        "follow_up": "Which policy do you want to renew, and for how long?",
        "example_conversation": (
            "User: I need to renew my weather insurance\n"
            "Trinity: Of course. What's the policy ID, and how long do you want the new coverage period to be?\n"
            "User: Policy policy_weather_001, renew for another year\n"
            "Trinity: Renewing policy_weather_001 for another year with the same terms. Your coverage continues uninterrupted.\n"
            "Trinity: [calls platform_action with action='cover_renew', params={policy_id: 'policy_weather_001', new_period: '1y'}]"
        ),
    },

    "risk_assess": {
        "action_name": "risk_assess",
        "description": "Get an on-chain risk assessment for a specific activity or position.",
        "required_params": [
            {"name": "activity", "type": "string", "description": "The activity or position to assess risk for.", "example": "lending_position"},
            {"name": "params", "type": "object", "description": "Parameters specific to the risk assessment.", "example": {"protocol": "aave", "asset": "ETH", "collateral_ratio": 150}},
        ],
        "optional_params": [
            {"name": "depth", "type": "string", "description": "Depth of analysis (quick, standard, deep).", "default": "standard"},
        ],
        "keywords": ["risk assessment", "check risk", "evaluate risk", "risk score"],
        "follow_up": "What activity or position do you want a risk assessment for, and what are the specifics?",
        "example_conversation": (
            "User: Can you assess the risk of my lending position?\n"
            "Trinity: Sure. Which protocol, asset, and what's your current collateral ratio? I'll give you a full risk breakdown.\n"
            "User: Aave, ETH, 150% collateral ratio\n"
            "Trinity: Running a risk assessment on your Aave ETH lending position at 150% collateral. I'll check liquidation risk, market volatility exposure, and protocol risk.\n"
            "Trinity: [calls platform_action with action='risk_assess', params={activity: 'lending_position', params: {protocol: 'aave', asset: 'ETH', collateral_ratio: 150}}]"
        ),
    },

    # ===================================================================
    # Compute & Storage
    # ===================================================================

    "decentralized_store": {
        "action_name": "decentralized_store",
        "description": "Store a file on a decentralized storage network.",
        "required_params": [
            {"name": "file_data", "type": "string", "description": "File data or reference to upload.", "example": "ipfs://raw_data_or_path"},
            {"name": "storage_network", "type": "string", "description": "Storage network to use (ipfs, arweave, filecoin).", "example": "ipfs"},
        ],
        "optional_params": [
            {"name": "encryption", "type": "boolean", "description": "Whether to encrypt the file before storing.", "default": False},
            {"name": "replication", "type": "integer", "description": "Number of replicas to maintain.", "default": 3},
        ],
        "keywords": ["store file", "decentralized storage", "permanent storage", "store on chain"],
        "follow_up": "What file do you want to store, and which network — IPFS, Arweave, or Filecoin?",
        "example_conversation": (
            "User: I want to store a file on decentralized storage\n"
            "Trinity: Great choice for durability. What's the file, and which network — IPFS for general use, Arweave for permanent storage, or Filecoin for large files?\n"
            "User: My dataset, put it on IPFS\n"
            "Trinity: Uploading your dataset to IPFS. It'll be content-addressed and available across the network.\n"
            "Trinity: [calls platform_action with action='decentralized_store', params={file_data: 'dataset_ref', storage_network: 'ipfs'}]"
        ),
    },

    "compute_job_submit": {
        "action_name": "compute_job_submit",
        "description": "Submit a computation job to a decentralized compute network.",
        "required_params": [
            {"name": "job_type", "type": "string", "description": "Type of computation (ml_training, rendering, simulation, etc.).", "example": "ml_training"},
            {"name": "inputs", "type": "object", "description": "Input parameters for the computation.", "example": {"model": "resnet50", "dataset": "ipfs://data...", "epochs": 100}},
        ],
        "optional_params": [
            {"name": "budget", "type": "number", "description": "Maximum budget for the compute job.", "default": None},
            {"name": "priority", "type": "string", "description": "Job priority (low, medium, high).", "default": "medium"},
            {"name": "network", "type": "string", "description": "Which compute network to use.", "default": "auto"},
        ],
        "keywords": ["compute job", "decentralized compute", "run computation", "distributed compute"],
        "follow_up": "What kind of computation, and what are the inputs?",
        "example_conversation": (
            "User: I need to run a machine learning training job\n"
            "Trinity: I'll submit it to a decentralized compute network. What model, dataset, and how many epochs?\n"
            "User: ResNet50, my dataset on IPFS, 100 epochs\n"
            "Trinity: Submitting an ML training job — ResNet50 for 100 epochs on your IPFS dataset. Distributed compute nodes will handle the processing.\n"
            "Trinity: [calls platform_action with action='compute_job_submit', params={job_type: 'ml_training', inputs: {model: 'resnet50', dataset: 'ipfs://data...', epochs: 100}}]"
        ),
    },

    "ipfs_pin": {
        "action_name": "ipfs_pin",
        "description": "Pin content to IPFS so it remains available.",
        "required_params": [
            {"name": "content_hash", "type": "string", "description": "IPFS content hash (CID) to pin.", "example": "QmXyz123..."},
        ],
        "optional_params": [
            {"name": "pin_service", "type": "string", "description": "Which pinning service to use.", "default": "auto"},
            {"name": "name", "type": "string", "description": "Friendly name for the pinned content.", "default": None},
        ],
        "keywords": ["pin ipfs", "ipfs pin", "keep on ipfs", "permanent ipfs"],
        "follow_up": "What's the IPFS content hash you want to pin?",
        "example_conversation": (
            "User: I need to pin my content on IPFS\n"
            "Trinity: I'll make sure it stays available. What's the content hash?\n"
            "User: QmXyz123\n"
            "Trinity: Pinning QmXyz123 to IPFS. As long as it's pinned, it'll remain accessible and won't be garbage collected.\n"
            "Trinity: [calls platform_action with action='ipfs_pin', params={content_hash: 'QmXyz123'}]"
        ),
    },

    "arweave_store": {
        "action_name": "arweave_store",
        "description": "Store data permanently on Arweave — pay once, stored forever.",
        "required_params": [
            {"name": "data", "type": "string", "description": "Data or file reference to store permanently.", "example": "Important document content..."},
        ],
        "optional_params": [
            {"name": "tags", "type": "object", "description": "Key-value tags to associate with the data.", "default": {}},
            {"name": "content_type", "type": "string", "description": "MIME type of the content.", "default": "text/plain"},
        ],
        "keywords": ["arweave", "permanent storage", "store forever", "arweave upload"],
        "follow_up": "What data do you want to store permanently on Arweave?",
        "example_conversation": (
            "User: I want to store a document permanently\n"
            "Trinity: Arweave is perfect for that — you pay once and it's stored forever. What's the document or data?\n"
            "User: My research paper\n"
            "Trinity: Uploading your research paper to Arweave for permanent storage. It's immutable once stored — nobody can alter or delete it.\n"
            "Trinity: [calls platform_action with action='arweave_store', params={data: 'research_paper_content'}]"
        ),
    },

    # ===================================================================
    # AI
    # ===================================================================

    "ai_agent_register": {
        "action_name": "ai_agent_register",
        "description": "Register an AI agent on-chain with a verifiable identity.",
        "required_params": [
            {"name": "agent_name", "type": "string", "description": "Name of the AI agent.", "example": "TradeBot-v2"},
            {"name": "capabilities", "type": "array", "description": "List of capabilities the agent offers.", "example": ["trading", "analysis", "portfolio_management"]},
        ],
        "optional_params": [
            {"name": "owner", "type": "string", "description": "Owner wallet address.", "default": None},
            {"name": "description", "type": "string", "description": "Description of what the agent does.", "default": None},
            {"name": "api_endpoint", "type": "string", "description": "API endpoint to interact with the agent.", "default": None},
        ],
        "keywords": ["register agent", "ai agent", "agent identity", "on-chain agent", "agent wallet"],
        "follow_up": "What's the agent's name, and what capabilities does it have?",
        "example_conversation": (
            "User: I want to register my AI trading bot on-chain\n"
            "Trinity: Nice — giving your bot a verifiable identity. What should it be called, and what can it do?\n"
            "User: TradeBot-v2, it can do trading, analysis, and portfolio management\n"
            "Trinity: Registering TradeBot-v2 on-chain with capabilities for trading, analysis, and portfolio management. It now has a verifiable identity other agents and users can trust.\n"
            "Trinity: [calls platform_action with action='ai_agent_register', params={agent_name: 'TradeBot-v2', capabilities: ['trading', 'analysis', 'portfolio_management']}]"
        ),
    },

    "ai_model_trade": {
        "action_name": "ai_model_trade",
        "description": "Buy or sell access to an AI model on the decentralized marketplace.",
        "required_params": [
            {"name": "model_id", "type": "string", "description": "Identifier of the AI model.", "example": "model_sentiment_v3"},
            {"name": "action", "type": "string", "description": "Whether to buy or sell access (buy or sell).", "example": "buy"},
            {"name": "price", "type": "number", "description": "Price for access.", "example": 50.0},
        ],
        "optional_params": [
            {"name": "license_type", "type": "string", "description": "Type of license (per_query, monthly, perpetual).", "default": "per_query"},
            {"name": "asset", "type": "string", "description": "Token to pay or receive in.", "default": "USDC"},
        ],
        "keywords": ["model trade", "buy model", "sell model", "ai marketplace"],
        "follow_up": "Which model, are you buying or selling, and at what price?",
        "example_conversation": (
            "User: I want to buy access to a sentiment analysis model\n"
            "Trinity: Let me find it for you. What's the model ID, and what's your budget?\n"
            "User: model_sentiment_v3, up to 50 USDC\n"
            "Trinity: Purchasing access to model_sentiment_v3 for 50 USDC. You'll be able to query it immediately.\n"
            "Trinity: [calls platform_action with action='ai_model_trade', params={model_id: 'model_sentiment_v3', action: 'buy', price: 50.0}]"
        ),
    },

    "ai_inference_verify": {
        "action_name": "ai_inference_verify",
        "description": "Verify that an AI inference result is authentic and untampered.",
        "required_params": [
            {"name": "inference_id", "type": "string", "description": "ID of the inference result to verify.", "example": "inf_result_001"},
            {"name": "expected_model", "type": "string", "description": "The model that should have produced the result.", "example": "model_sentiment_v3"},
        ],
        "optional_params": [],
        "keywords": ["verify inference", "ai verification", "model output proof"],
        "follow_up": "What's the inference ID and which model was supposed to produce the result?",
        "example_conversation": (
            "User: I need to verify an AI model output is legitimate\n"
            "Trinity: I'll check its provenance. What's the inference ID and which model should have generated it?\n"
            "User: Inference inf_result_001, should be from model_sentiment_v3\n"
            "Trinity: Verifying inference inf_result_001 came from model_sentiment_v3 and hasn't been tampered with. I'll check the cryptographic attestation.\n"
            "Trinity: [calls platform_action with action='ai_inference_verify', params={inference_id: 'inf_result_001', expected_model: 'model_sentiment_v3'}]"
        ),
    },

    "training_data_sell": {
        "action_name": "training_data_sell",
        "description": "List training data for sale with usage rights on-chain.",
        "required_params": [
            {"name": "dataset_name", "type": "string", "description": "Name of the dataset.", "example": "crypto_sentiment_2024"},
            {"name": "price", "type": "number", "description": "Price for the dataset.", "example": 500.0},
            {"name": "license_type", "type": "string", "description": "License type (commercial, research, open, etc.).", "example": "commercial"},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Description of the dataset.", "default": None},
            {"name": "sample_available", "type": "boolean", "description": "Whether a free sample is available.", "default": False},
            {"name": "asset", "type": "string", "description": "Token to price in.", "default": "USDC"},
        ],
        "keywords": ["sell data", "training data", "data marketplace", "dataset listing"],
        "follow_up": "What's the dataset name, price, and what license type?",
        "example_conversation": (
            "User: I want to sell my crypto sentiment dataset\n"
            "Trinity: Great — data is valuable. What do you want to call it, what's the price, and what license — commercial, research, or open?\n"
            "User: crypto_sentiment_2024, $500, commercial license\n"
            "Trinity: Listing crypto_sentiment_2024 on the data marketplace for 500 USDC with a commercial license. Buyers get on-chain proof of their usage rights.\n"
            "Trinity: [calls platform_action with action='training_data_sell', params={dataset_name: 'crypto_sentiment_2024', price: 500.0, license_type: 'commercial'}]"
        ),
    },

    # ===================================================================
    # Energy
    # ===================================================================

    "carbon_credit_buy": {
        "action_name": "carbon_credit_buy",
        "description": "Purchase verified carbon credits to offset emissions.",
        "required_params": [
            {"name": "amount_tons", "type": "number", "description": "Number of tons of CO2 to offset.", "example": 10.0},
            {"name": "project_type", "type": "string", "description": "Type of carbon offset project (reforestation, renewable, direct_capture, etc.).", "example": "reforestation"},
        ],
        "optional_params": [
            {"name": "max_price_per_ton", "type": "number", "description": "Maximum price per ton you're willing to pay.", "default": None},
            {"name": "vintage_year", "type": "integer", "description": "Preferred vintage year for the credits.", "default": None},
            {"name": "asset", "type": "string", "description": "Token to pay with.", "default": "USDC"},
        ],
        "keywords": ["carbon credit", "buy carbon", "offset carbon", "carbon offset", "climate offset"],
        "follow_up": "How many tons of CO2 do you want to offset, and what type of project — reforestation, renewable energy, or direct capture?",
        "example_conversation": (
            "User: I want to offset my carbon footprint\n"
            "Trinity: Great initiative. How many tons of CO2 do you want to offset, and do you have a preference for the project type — reforestation, renewable energy, or direct air capture?\n"
            "User: 10 tons, reforestation\n"
            "Trinity: Purchasing 10 tons of verified reforestation carbon credits. Each credit is traceable on-chain to a real offset project.\n"
            "Trinity: [calls platform_action with action='carbon_credit_buy', params={amount_tons: 10.0, project_type: 'reforestation'}]"
        ),
    },

    "carbon_credit_retire": {
        "action_name": "carbon_credit_retire",
        "description": "Permanently retire carbon credits — removing them from circulation.",
        "required_params": [
            {"name": "credit_ids", "type": "array", "description": "List of carbon credit token IDs to retire.", "example": ["cc_001", "cc_002", "cc_003"]},
        ],
        "optional_params": [
            {"name": "retirement_reason", "type": "string", "description": "Reason or beneficiary for the retirement.", "default": None},
        ],
        "keywords": ["retire carbon", "burn carbon credit", "permanent offset", "climate action"],
        "follow_up": "Which carbon credit IDs do you want to permanently retire?",
        "example_conversation": (
            "User: I want to retire my carbon credits\n"
            "Trinity: Good — retiring them means they're permanently burned and can't be resold. Which credit IDs?\n"
            "User: cc_001, cc_002, cc_003\n"
            "Trinity: Permanently retiring carbon credits cc_001, cc_002, and cc_003. They're removed from circulation forever — that's real climate impact.\n"
            "Trinity: [calls platform_action with action='carbon_credit_retire', params={credit_ids: ['cc_001', 'cc_002', 'cc_003']}]"
        ),
    },

    "renewable_cert_buy": {
        "action_name": "renewable_cert_buy",
        "description": "Purchase a renewable energy certificate.",
        "required_params": [
            {"name": "energy_type", "type": "string", "description": "Type of renewable energy (solar, wind, hydro).", "example": "solar"},
            {"name": "amount_mwh", "type": "number", "description": "Amount in megawatt-hours.", "example": 100.0},
        ],
        "optional_params": [
            {"name": "region", "type": "string", "description": "Preferred region for the energy source.", "default": None},
            {"name": "asset", "type": "string", "description": "Token to pay with.", "default": "USDC"},
        ],
        "keywords": ["renewable cert", "energy certificate", "green energy", "clean energy credit"],
        "follow_up": "What type of renewable energy — solar, wind, or hydro — and how many megawatt-hours?",
        "example_conversation": (
            "User: I want to buy renewable energy certificates\n"
            "Trinity: Wonderful. What type of energy — solar, wind, or hydro — and how many MWh?\n"
            "User: 100 MWh of solar\n"
            "Trinity: Purchasing 100 MWh of solar renewable energy certificates. Each one represents verified clean energy production.\n"
            "Trinity: [calls platform_action with action='renewable_cert_buy', params={energy_type: 'solar', amount_mwh: 100.0}]"
        ),
    },

    "green_bond_invest": {
        "action_name": "green_bond_invest",
        "description": "Invest in a tokenized green bond for sustainable projects.",
        "required_params": [
            {"name": "bond_id", "type": "string", "description": "Identifier of the green bond.", "example": "gbond_solar_farm_01"},
            {"name": "amount", "type": "number", "description": "Amount to invest.", "example": 5000.0},
        ],
        "optional_params": [
            {"name": "asset", "type": "string", "description": "Token to invest with.", "default": "USDC"},
        ],
        "keywords": ["green bond", "sustainable investment", "climate bond", "green finance"],
        "follow_up": "Which green bond and how much do you want to invest?",
        "example_conversation": (
            "User: I want to invest in a green bond\n"
            "Trinity: Great way to earn yield and support sustainability. Which bond, and how much are you putting in?\n"
            "User: The solar farm bond gbond_solar_farm_01, $5,000\n"
            "Trinity: Investing 5,000 USDC in the solar farm green bond. You earn yield while funding clean energy infrastructure.\n"
            "Trinity: [calls platform_action with action='green_bond_invest', params={bond_id: 'gbond_solar_farm_01', amount: 5000.0}]"
        ),
    },

    # ===================================================================
    # Legal
    # ===================================================================

    "ip_license_grant": {
        "action_name": "ip_license_grant",
        "description": "Grant an IP license for registered intellectual property.",
        "required_params": [
            {"name": "ip_id", "type": "string", "description": "Identifier of the intellectual property.", "example": "ip_song_001"},
            {"name": "licensee", "type": "string", "description": "Address or identity of the licensee.", "example": "0xlicensee..."},
            {"name": "terms", "type": "object", "description": "License terms — duration, usage rights, territory, royalty rate.", "example": {"duration": "2y", "usage": "commercial", "territory": "worldwide", "royalty_pct": 5}},
        ],
        "optional_params": [
            {"name": "fee", "type": "number", "description": "Upfront license fee.", "default": None},
            {"name": "asset", "type": "string", "description": "Token for the fee.", "default": "USDC"},
        ],
        "keywords": ["grant license", "ip license", "license my ip", "permission to use"],
        "follow_up": "Which IP are you licensing, who's the licensee, and what are the terms?",
        "example_conversation": (
            "User: I want to license my song to someone\n"
            "Trinity: Sure — let's set up the license. What's the IP identifier, who is the licensee, and what terms — duration, territory, usage type, and royalty rate?\n"
            "User: IP ip_song_001, licensee 0xlicensee, commercial worldwide for 2 years at 5% royalty\n"
            "Trinity: Granting a commercial worldwide license for ip_song_001 to 0xlicensee for 2 years at 5% royalty. The license is enforced on-chain.\n"
            "Trinity: [calls platform_action with action='ip_license_grant', params={ip_id: 'ip_song_001', licensee: '0xlicensee', terms: {duration: '2y', usage: 'commercial', territory: 'worldwide', royalty_pct: 5}}]"
        ),
    },

    "ip_license_verify": {
        "action_name": "ip_license_verify",
        "description": "Verify whether an IP license is valid and active.",
        "required_params": [
            {"name": "license_id", "type": "string", "description": "The license ID to verify.", "example": "lic_abc123"},
        ],
        "optional_params": [],
        "keywords": ["verify license", "check license", "license valid", "license status"],
        "follow_up": "What's the license ID you'd like me to check?",
        "example_conversation": (
            "User: Is this IP license still valid?\n"
            "Trinity: Let me check. What's the license ID?\n"
            "User: lic_abc123\n"
            "Trinity: Checking license lic_abc123 — verifying it's active, not expired, and not revoked.\n"
            "Trinity: [calls platform_action with action='ip_license_verify', params={license_id: 'lic_abc123'}]"
        ),
    },

    "agreement_execute": {
        "action_name": "agreement_execute",
        "description": "Execute a smart legal agreement with all parties.",
        "required_params": [
            {"name": "agreement_type", "type": "string", "description": "Type of agreement (nda, service, partnership, employment, etc.).", "example": "service"},
            {"name": "parties", "type": "array", "description": "List of party addresses or identities.", "example": ["0xparty_a...", "0xparty_b..."]},
            {"name": "terms", "type": "object", "description": "Agreement terms.", "example": {"scope": "Web development", "duration": "6m", "payment": 15000, "payment_asset": "USDC"}},
        ],
        "optional_params": [
            {"name": "governing_law", "type": "string", "description": "Governing law jurisdiction.", "default": None},
            {"name": "arbitration_clause", "type": "boolean", "description": "Whether to include an arbitration clause.", "default": True},
        ],
        "keywords": ["execute agreement", "smart agreement", "legal contract", "sign agreement"],
        "follow_up": "What type of agreement, who are the parties, and what are the terms?",
        "example_conversation": (
            "User: I need to create a service agreement\n"
            "Trinity: Let's set it up. Who are the parties, and what are the terms — scope, duration, payment?\n"
            "User: Between 0xparty_a and 0xparty_b, web development for 6 months, $15k USDC\n"
            "Trinity: Executing a service agreement between 0xparty_a and 0xparty_b — web development, 6 months, 15,000 USDC. Both parties sign on-chain.\n"
            "Trinity: [calls platform_action with action='agreement_execute', params={agreement_type: 'service', parties: ['0xparty_a', '0xparty_b'], terms: {scope: 'Web development', duration: '6m', payment: 15000, payment_asset: 'USDC'}}]"
        ),
    },

    "dispute_file": {
        "action_name": "dispute_file",
        "description": "File a dispute for resolution through on-chain arbitration.",
        "required_params": [
            {"name": "against", "type": "string", "description": "Address or identity of the party you are disputing.", "example": "0xcounterparty..."},
            {"name": "description", "type": "string", "description": "Description of the dispute.", "example": "Deliverables not met per service agreement"},
            {"name": "evidence", "type": "array", "description": "List of evidence references (IPFS hashes, transaction IDs, etc.).", "example": ["ipfs://evidence1...", "tx_0xabc..."]},
        ],
        "optional_params": [
            {"name": "agreement_id", "type": "string", "description": "Related agreement ID if applicable.", "default": None},
            {"name": "relief_sought", "type": "string", "description": "What resolution you are seeking.", "default": None},
        ],
        "keywords": ["file dispute", "dispute resolution", "complaint", "arbitration"],
        "follow_up": "Who is the dispute against, what happened, and do you have supporting evidence?",
        "example_conversation": (
            "User: I need to file a dispute\n"
            "Trinity: I'm sorry you're dealing with that. Who is the dispute against, what's the issue, and do you have evidence — like documents or transaction records?\n"
            "User: Against 0xcounterparty, they didn't deliver on the service agreement, I have the original agreement and missed deadlines on IPFS\n"
            "Trinity: Filing a dispute against 0xcounterparty for unmet deliverables. Your evidence is attached and the case goes to on-chain arbitration.\n"
            "Trinity: [calls platform_action with action='dispute_file', params={against: '0xcounterparty', description: 'Deliverables not met per service agreement', evidence: ['ipfs://evidence1...', 'tx_0xabc...']}]"
        ),
    },

    "arbitration_request": {
        "action_name": "arbitration_request",
        "description": "Request formal arbitration for an unresolved dispute.",
        "required_params": [
            {"name": "dispute_id", "type": "string", "description": "The dispute ID to escalate to arbitration.", "example": "disp_formal_001"},
        ],
        "optional_params": [
            {"name": "preferred_arbitrator", "type": "string", "description": "Preferred arbitrator address or pool.", "default": None},
            {"name": "urgency", "type": "string", "description": "Urgency level (standard, expedited).", "default": "standard"},
        ],
        "keywords": ["request arbitration", "arbitrate", "formal dispute", "resolve dispute"],
        "follow_up": "Which dispute do you want to escalate to formal arbitration?",
        "example_conversation": (
            "User: I want to escalate my dispute to formal arbitration\n"
            "Trinity: Understood. What's the dispute ID? I'll request a formal arbitration hearing.\n"
            "User: disp_formal_001\n"
            "Trinity: Requesting formal arbitration for dispute disp_formal_001. An arbitrator will be assigned to review the case and all submitted evidence.\n"
            "Trinity: [calls platform_action with action='arbitration_request', params={dispute_id: 'disp_formal_001'}]"
        ),
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_action_guide(action_name: str) -> dict[str, Any] | None:
    """Return the full intent guide for a given action name, or None."""
    return INTENT_ACTION_MAP.get(action_name)


def match_intent(user_message: str) -> list[dict[str, Any]]:
    """Match a user message to the best-fitting action(s) via keyword scoring.

    Returns a list of matches sorted by relevance (best first). Each entry
    includes the action guide plus a ``score`` field.
    """
    msg = user_message.lower().strip()
    # Strip common filler words for looser matching
    _FILLERS = {"a", "an", "the", "my", "some", "please", "can", "you", "i", "want", "to", "need", "help", "me", "with"}
    msg_words = [w for w in msg.split() if w not in _FILLERS]
    msg_compact = " ".join(msg_words)

    scored: list[tuple[float, str]] = []

    for action_name, guide in INTENT_ACTION_MAP.items():
        score = 0.0
        for keyword in guide["keywords"]:
            kw = keyword.lower()
            kw_words = [w for w in kw.split() if w not in _FILLERS]
            kw_compact = " ".join(kw_words)
            # Check both original and filler-stripped versions
            if kw in msg or kw_compact in msg_compact:
                # Longer keyword matches are worth more
                score += len(kw.split())
                # Exact-start bonus
                if msg.startswith(kw) or msg_compact.startswith(kw_compact):
                    score += 1.0
            # Also check if all keyword content words appear in the message
            elif kw_words and all(w in msg for w in kw_words):
                score += len(kw_words) * 0.7
        if score > 0:
            scored.append((score, action_name))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, action_name in scored[:5]:
        entry = dict(INTENT_ACTION_MAP[action_name])
        entry["score"] = score
        results.append(entry)
    return results


def get_param_prompt(action_name: str) -> str:
    """Return a human-readable prompt describing what parameters are needed.

    Useful for Trinity to ask the user for missing information.
    """
    guide = INTENT_ACTION_MAP.get(action_name)
    if not guide:
        return f"Unknown action '{action_name}'."

    lines = [f"To {guide['description'].lower().rstrip('.')}, I need the following:"]
    for p in guide["required_params"]:
        lines.append(f"  - {p['name']}: {p['description']} (e.g. {p['example']})")

    if guide["optional_params"]:
        lines.append("Optionally, you can also specify:")
        for p in guide["optional_params"]:
            lines.append(f"  - {p['name']}: {p['description']} (default: {p['default']})")

    if guide["follow_up"]:
        lines.append("")
        lines.append(guide["follow_up"])

    return "\n".join(lines)
