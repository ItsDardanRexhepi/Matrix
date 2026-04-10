"""
Intent-to-Action Mapping — bridges natural language to platform_action calls.

Provides structured guidance so Trinity (or any agent) knows exactly which
action to invoke, what parameters are required, and how to ask for missing
information.

Covers all 89 actions across all 30 components in the ACTION_MAP.
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
