"""
Intent-to-Action Mapping — bridges natural language to platform_action calls.

Provides structured guidance so Trinity (or any agent) knows exactly which
action to invoke, what parameters are required, and how to ask for missing
information.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Master intent -> action mapping
# ---------------------------------------------------------------------------

INTENT_ACTION_MAP: dict[str, dict[str, Any]] = {

    # --- Smart Contracts ---
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

    # --- DeFi Loans ---
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

    # --- NFTs ---
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
            {"name": "price", "type": "number", "description": "Sale price in the marketplace's native currency.", "example": 1.5},
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

    # --- Token Swaps ---
    "swap_tokens": {
        "action_name": "swap_tokens",
        "description": "Swap one token for another on a decentralized exchange.",
        "required_params": [
            {"name": "token_in", "type": "string", "description": "Token to swap from.", "example": "ETH"},
            {"name": "token_out", "type": "string", "description": "Token to swap to.", "example": "USDC"},
            {"name": "amount", "type": "number", "description": "Amount of token_in to swap.", "example": 1.0},
        ],
        "optional_params": [
            {"name": "slippage", "type": "number", "description": "Maximum slippage tolerance as a percentage.", "default": 0.5},
            {"name": "route", "type": "string", "description": "Preferred DEX route.", "default": "auto"},
        ],
        "keywords": ["swap tokens", "exchange tokens", "trade tokens", "swap", "convert tokens", "swap ETH", "swap USDC", "trade"],
        "follow_up": "What token would you like to swap, what would you like to receive, and how much?",
        "example_conversation": (
            "User: Swap 1 ETH for USDC\n"
            "Trinity: [calls platform_action with action='swap_tokens', params={token_in: 'ETH', token_out: 'USDC', amount: 1.0}]"
        ),
    },

    # --- Payments ---
    "send_payment": {
        "action_name": "send_payment",
        "description": "Send a payment or transfer tokens to a recipient.",
        "required_params": [
            {"name": "recipient", "type": "string", "description": "Recipient wallet address, ENS name, or DID.", "example": "0xabc... or alice.eth"},
            {"name": "amount", "type": "number", "description": "Amount to send.", "example": 100},
            {"name": "currency", "type": "string", "description": "Token or currency to send.", "example": "USDC"},
        ],
        "optional_params": [
            {"name": "memo", "type": "string", "description": "Optional memo or note.", "default": ""},
        ],
        "keywords": ["send money", "transfer", "pay", "send tokens", "send to", "transfer funds", "wire", "send payment", "pay someone"],
        "follow_up": "Who would you like to send money to, how much, and in what currency?",
        "example_conversation": (
            "User: Send 100 USDC to alice.eth\n"
            "Trinity: [calls platform_action with action='send_payment', params={recipient: 'alice.eth', amount: 100, currency: 'USDC'}]"
        ),
    },

    # --- Staking ---
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
            "Trinity: I'll stake that for you. Which staking pool would you like to use? I can show you available options.\n"
            "User: The main ETH pool\n"
            "Trinity: [calls platform_action with action='stake', params={amount: 10.0, pool_id: 'eth-staking-v2'}]"
        ),
    },

    "unstake": {
        "action_name": "unstake",
        "description": "Unstake tokens from a staking pool.",
        "required_params": [
            {"name": "amount", "type": "number", "description": "Amount to unstake.", "example": 5.0},
            {"name": "pool_id", "type": "string", "description": "ID of the staking pool.", "example": "eth-staking-v2"},
        ],
        "optional_params": [],
        "keywords": ["unstake", "withdraw stake", "remove stake", "stop staking", "unstake tokens"],
        "follow_up": "How much would you like to unstake, and from which pool?",
        "example_conversation": (
            "User: Unstake 5 ETH from the main pool\n"
            "Trinity: [calls platform_action with action='unstake', params={amount: 5.0, pool_id: 'eth-staking-v2'}]"
        ),
    },

    "claim_staking_rewards": {
        "action_name": "claim_staking_rewards",
        "description": "Claim accumulated staking rewards from a pool.",
        "required_params": [
            {"name": "pool_id", "type": "string", "description": "ID of the staking pool.", "example": "eth-staking-v2"},
        ],
        "optional_params": [],
        "keywords": ["claim rewards", "collect rewards", "get rewards", "staking rewards", "harvest rewards", "claim my rewards"],
        "follow_up": "Which staking pool would you like to claim rewards from?",
        "example_conversation": (
            "User: Claim my staking rewards\n"
            "Trinity: Which staking pool would you like to claim rewards from?\n"
            "User: The ETH pool\n"
            "Trinity: [calls platform_action with action='claim_staking_rewards', params={pool_id: 'eth-staking-v2'}]"
        ),
    },

    # --- Dashboard ---
    "get_dashboard": {
        "action_name": "get_dashboard",
        "description": "Show the user's portfolio overview, balances, and positions.",
        "required_params": [],
        "optional_params": [],
        "keywords": ["check balance", "my balance", "portfolio", "dashboard", "how much do I have", "my account", "show my assets", "what do I own", "my holdings"],
        "follow_up": "",
        "example_conversation": (
            "User: What's my balance?\n"
            "Trinity: [calls platform_action with action='get_dashboard', params={}]"
        ),
    },

    # --- Insurance ---
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
            {"name": "evidence", "type": "string", "description": "Description or hash of evidence supporting the claim.", "example": "Contract exploited on block 18234567, tx hash 0x..."},
        ],
        "optional_params": [
            {"name": "claim_amount", "type": "number", "description": "Specific amount being claimed.", "default": None},
        ],
        "keywords": ["file claim", "insurance claim", "make a claim", "claim insurance", "report incident"],
        "follow_up": "Which policy is this claim for, and what evidence do you have?",
        "example_conversation": (
            "User: I need to file an insurance claim\n"
            "Trinity: I'm sorry to hear that. Which policy is this for, and can you describe what happened?\n"
            "User: Policy pol_abc123, my contract was exploited\n"
            "Trinity: [calls platform_action with action='file_insurance_claim', params={policy_id: 'pol_abc123', evidence: 'Contract exploited...'}]"
        ),
    },

    # --- DAO ---
    "create_dao": {
        "action_name": "create_dao",
        "description": "Create a new decentralized autonomous organization.",
        "required_params": [
            {"name": "name", "type": "string", "description": "Name of the DAO.", "example": "ClimateDAO"},
            {"name": "config", "type": "object", "description": "DAO configuration (voting rules, token, quorum, etc.).", "example": {"voting_period": 72, "quorum": 0.1, "token": "CLIMATE"}},
        ],
        "optional_params": [
            {"name": "description", "type": "string", "description": "Description of the DAO's purpose.", "default": ""},
        ],
        "keywords": ["create DAO", "start a DAO", "new DAO", "set up a DAO", "make a DAO", "launch DAO"],
        "follow_up": "What would you like to name your DAO, and how should voting work (voting period, quorum, governance token)?",
        "example_conversation": (
            "User: I want to create a DAO for climate initiatives\n"
            "Trinity: Great idea! What would you like to name it, and how should governance work? For example, voting period, quorum percentage, and governance token.\n"
            "User: Call it ClimateDAO, 72 hour voting, 10% quorum\n"
            "Trinity: [calls platform_action with action='create_dao', params={name: 'ClimateDAO', config: {voting_period: 72, quorum: 0.1}}]"
        ),
    },

    # --- Governance ---
    "vote": {
        "action_name": "vote",
        "description": "Cast a vote on a governance proposal.",
        "required_params": [
            {"name": "proposal_id", "type": "string", "description": "ID of the proposal to vote on.", "example": "prop_001"},
            {"name": "support", "type": "boolean", "description": "True to vote for, False to vote against.", "example": True},
        ],
        "optional_params": [
            {"name": "reason", "type": "string", "description": "Optional reason for the vote.", "default": ""},
        ],
        "keywords": ["vote", "cast vote", "vote on proposal", "vote yes", "vote no", "vote for", "vote against"],
        "follow_up": "Which proposal would you like to vote on, and are you voting for or against?",
        "example_conversation": (
            "User: I want to vote yes on proposal 1\n"
            "Trinity: [calls platform_action with action='vote', params={proposal_id: 'prop_001', support: true}]"
        ),
    },

    "create_proposal": {
        "action_name": "create_proposal",
        "description": "Create a new governance proposal.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Title of the proposal.", "example": "Increase staking rewards by 2%"},
            {"name": "description", "type": "string", "description": "Detailed description of the proposal.", "example": "This proposal seeks to increase..."},
            {"name": "actions", "type": "array", "description": "On-chain actions to execute if the proposal passes.", "example": [{"target": "0x...", "value": 0, "calldata": "0x..."}]},
        ],
        "optional_params": [
            {"name": "dao_id", "type": "string", "description": "DAO to submit the proposal to.", "default": None},
        ],
        "keywords": ["create proposal", "new proposal", "submit proposal", "propose", "governance proposal", "make a proposal"],
        "follow_up": "What's the title and description of your proposal, and what on-chain actions should it trigger if passed?",
        "example_conversation": (
            "User: I want to create a proposal to increase staking rewards\n"
            "Trinity: Sure! What should the title be, and can you describe the details? Also, what on-chain action should execute if it passes?\n"
            "User: Title: 'Increase rewards to 5%', description is in the doc, action is to call setRewardRate(500)\n"
            "Trinity: [calls platform_action with action='create_proposal', params={title: 'Increase rewards to 5%', description: '...', actions: [...]}]"
        ),
    },

    # --- IP & Royalties ---
    "register_ip": {
        "action_name": "register_ip",
        "description": "Register intellectual property on-chain.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Title of the IP.", "example": "My Song Title"},
            {"name": "description", "type": "string", "description": "Description of the intellectual property.", "example": "Original music composition..."},
            {"name": "content_hash", "type": "string", "description": "Hash of the content for verification.", "example": "QmXyz..."},
        ],
        "optional_params": [
            {"name": "royalty_bps", "type": "integer", "description": "Royalty in basis points.", "default": 1000},
            {"name": "license_type", "type": "string", "description": "Type of license.", "default": "all_rights_reserved"},
        ],
        "keywords": ["register IP", "register intellectual property", "protect IP", "IP registration", "copyright", "register my work"],
        "follow_up": "What's the title of your IP, a description, and do you have a content hash or file to register?",
        "example_conversation": (
            "User: I want to register my song on-chain\n"
            "Trinity: I can help with that. What's the title, a brief description, and do you have the file or its content hash?\n"
            "User: 'Midnight Blues', it's an original jazz composition, hash is QmXyz...\n"
            "Trinity: [calls platform_action with action='register_ip', params={title: 'Midnight Blues', description: 'Original jazz composition', content_hash: 'QmXyz...'}]"
        ),
    },

    # --- RWA Tokenization ---
    "tokenize_asset": {
        "action_name": "tokenize_asset",
        "description": "Tokenize a real-world asset on-chain.",
        "required_params": [
            {"name": "asset_type", "type": "string", "description": "Type of asset (real_estate, art, commodity, vehicle, etc.).", "example": "real_estate"},
            {"name": "details", "type": "object", "description": "Asset details (value, location, documentation, etc.).", "example": {"value": 500000, "address": "123 Main St", "documentation_hash": "Qm..."}},
        ],
        "optional_params": [
            {"name": "fractionalize", "type": "boolean", "description": "Whether to split into fractional shares.", "default": False},
            {"name": "shares", "type": "integer", "description": "Number of fractional shares.", "default": 1},
        ],
        "keywords": ["tokenize asset", "tokenize property", "tokenize real estate", "RWA", "real world asset", "tokenize", "asset tokenization"],
        "follow_up": "What type of asset would you like to tokenize, and can you provide the key details (value, description, documentation)?",
        "example_conversation": (
            "User: I want to tokenize my property\n"
            "Trinity: Sure! What type of property is it, and what are the key details — estimated value, location, and any documentation?\n"
            "User: It's a condo worth 500k at 123 Main St\n"
            "Trinity: [calls platform_action with action='tokenize_asset', params={asset_type: 'real_estate', details: {value: 500000, address: '123 Main St'}}]"
        ),
    },

    # --- Marketplace ---
    "list_marketplace": {
        "action_name": "list_marketplace",
        "description": "List an item for sale on the marketplace.",
        "required_params": [
            {"name": "item", "type": "object", "description": "Item details (name, description, type, etc.).", "example": {"name": "Rare Sword", "type": "game_asset"}},
            {"name": "price", "type": "number", "description": "Listing price.", "example": 50},
        ],
        "optional_params": [
            {"name": "currency", "type": "string", "description": "Currency for the listing.", "default": "USDC"},
            {"name": "duration_days", "type": "integer", "description": "Listing duration.", "default": 30},
        ],
        "keywords": ["list on marketplace", "sell on marketplace", "marketplace listing", "put up for sale", "list item"],
        "follow_up": "What item would you like to list, and at what price?",
        "example_conversation": (
            "User: List my rare sword for 50 USDC on the marketplace\n"
            "Trinity: [calls platform_action with action='list_marketplace', params={item: {name: 'Rare Sword', type: 'game_asset'}, price: 50}]"
        ),
    },

    "buy_marketplace": {
        "action_name": "buy_marketplace",
        "description": "Buy an item from the marketplace.",
        "required_params": [
            {"name": "listing_id", "type": "string", "description": "ID of the marketplace listing.", "example": "listing_abc123"},
        ],
        "optional_params": [],
        "keywords": ["buy from marketplace", "purchase listing", "buy item", "marketplace buy"],
        "follow_up": "Which listing would you like to buy? I'll need the listing ID.",
        "example_conversation": (
            "User: I want to buy listing_abc123\n"
            "Trinity: [calls platform_action with action='buy_marketplace', params={listing_id: 'listing_abc123'}]"
        ),
    },

    # --- Supply Chain ---
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

    # --- DID Identity ---
    "create_did": {
        "action_name": "create_did",
        "description": "Create a decentralized identity (DID).",
        "required_params": [
            {"name": "name", "type": "string", "description": "Display name for the identity.", "example": "Alice"},
            {"name": "attributes", "type": "object", "description": "Identity attributes (email, bio, etc.).", "example": {"email": "alice@example.com", "bio": "Web3 developer"}},
        ],
        "optional_params": [
            {"name": "avatar", "type": "string", "description": "Avatar URL.", "default": None},
        ],
        "keywords": ["create identity", "create DID", "decentralized identity", "new identity", "set up identity", "register identity", "make my DID"],
        "follow_up": "What name would you like for your identity, and any attributes you'd like to include (email, bio, etc.)?",
        "example_conversation": (
            "User: I want to create a decentralized identity\n"
            "Trinity: Sure! What name should it have, and any details to include — email, bio, or other attributes?\n"
            "User: Name is Alice, email alice@example.com\n"
            "Trinity: [calls platform_action with action='create_did', params={name: 'Alice', attributes: {email: 'alice@example.com'}}]"
        ),
    },

    # --- Fundraising ---
    "create_campaign": {
        "action_name": "create_campaign",
        "description": "Create a fundraising campaign with milestones.",
        "required_params": [
            {"name": "title", "type": "string", "description": "Campaign title.", "example": "Build a Community Garden"},
            {"name": "goal", "type": "number", "description": "Fundraising goal amount.", "example": 10000},
            {"name": "milestones", "type": "array", "description": "List of milestones with targets and descriptions.", "example": [{"title": "Phase 1", "amount": 5000}]},
        ],
        "optional_params": [
            {"name": "deadline", "type": "string", "description": "Campaign deadline (ISO date).", "default": None},
            {"name": "currency", "type": "string", "description": "Currency for the campaign.", "default": "USDC"},
        ],
        "keywords": ["fundraising", "create campaign", "crowdfund", "raise money", "fundraise", "start a campaign", "crowdfunding"],
        "follow_up": "What's your campaign title, fundraising goal, and what milestones would you like to set?",
        "example_conversation": (
            "User: I want to start a fundraising campaign\n"
            "Trinity: What's the campaign about, what's your goal, and what milestones should we set?\n"
            "User: Build a Community Garden, 10k goal, two milestones at 5k and 10k\n"
            "Trinity: [calls platform_action with action='create_campaign', params={title: 'Build a Community Garden', goal: 10000, milestones: [{title: 'Phase 1', amount: 5000}, {title: 'Phase 2', amount: 10000}]}]"
        ),
    },

    # --- Subscriptions ---
    "subscribe": {
        "action_name": "subscribe",
        "description": "Subscribe to a plan or service.",
        "required_params": [
            {"name": "plan_id", "type": "string", "description": "ID of the subscription plan.", "example": "plan_premium_monthly"},
        ],
        "optional_params": [
            {"name": "auto_renew", "type": "boolean", "description": "Enable auto-renewal.", "default": True},
        ],
        "keywords": ["subscribe", "subscription", "sign up for plan", "join plan", "subscribe to", "membership"],
        "follow_up": "Which plan would you like to subscribe to?",
        "example_conversation": (
            "User: I want to subscribe to the premium plan\n"
            "Trinity: [calls platform_action with action='subscribe', params={plan_id: 'plan_premium_monthly'}]"
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
    scored: list[tuple[float, str]] = []

    for action_name, guide in INTENT_ACTION_MAP.items():
        score = 0.0
        for keyword in guide["keywords"]:
            kw = keyword.lower()
            if kw in msg:
                # Longer keyword matches are worth more
                score += len(kw.split())
                # Exact-start bonus
                if msg.startswith(kw):
                    score += 1.0
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
