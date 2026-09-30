#!/usr/bin/env python3
"""
The Matrix Live Demo — Smart Contract Conversion, and a Deployment From Your Own Wallet

What it does:
  1. Parses a contract written as structured pseudocode (a `contract` line,
     `state name: type` lines and `function name(params)` lines) into an
     intermediate representation. A paragraph of prose is not read.
  2. Generates Solidity from what it parsed, and prints it
  3. Tries to compile that source with solc 0.8.24
  4. Deploys the compiled contract to Base Sepolia from the demo wallet in
     matrix.config.json (your key, your gas)
  5. Prints the contract address and a block explorer link

When the generated source does not compile, the demo prints the compiler's
error and deploys a hand-written stand-in instead: SimpleVault when the
parsed functions include deposit or withdraw, an ERC-20 otherwise. The
stand-in is not the contract the converter generated, and the demo says so
beside the result and in demo_deployment.json. A template (--template) is
deployed only if it compiles on its own; every template imports
OpenZeppelin, which this demo does not supply, so only erc20 falls back to
the ERC-20 stand-in, and any other template stops there.

Usage:
    python demo.py                    # Interactive mode — type your own pseudocode
    python demo.py --example          # Run with the built-in SimpleVault pseudocode
    python demo.py --template erc20   # Try a template (see above)

Requirements:
    pip install web3 eth-account py-solc-x
"""

import argparse
import json
import sys
import os
import time

# Ensure repo root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Load config ──────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrix.config.json")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: Config file not found at {CONFIG_PATH}")
        print("Copy matrix.config.json.example to matrix.config.json and fill in your credentials.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def validate_config(config: dict) -> list[str]:
    """Return list of missing/placeholder config keys needed for the demo."""
    bc = config.get("blockchain", {})
    required = {
        "rpc_url": bc.get("rpc_url", ""),
        "demo_wallet_private_key": bc.get("demo_wallet_private_key", ""),
        "demo_wallet_address": bc.get("demo_wallet_address", ""),
    }
    missing = []
    for key, val in required.items():
        if not val or str(val).startswith("YOUR_"):
            missing.append(key)
    return missing


# ── Pretty printing ─────────────────────────────────────────────────

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


def banner():
    print(f"""
{CYAN}{BOLD}
    ███╗   ███╗ █████╗ ████████╗██████╗ ██╗██╗  ██╗
    ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██║╚██╗██╔╝
    ██╔████╔██║███████║   ██║   ██████╔╝██║ ╚███╔╝
    ██║╚██╔╝██║██╔══██║   ██║   ██╔══██╗██║ ██╔██╗
    ██║ ╚═╝ ██║██║  ██║   ██║   ██║  ██║██║██╔╝ ██╗
    ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝
{RESET}
    {DIM}Smart Contract Conversion — Live Demo on Base Sepolia{RESET}
    {DIM}Structured pseudocode in, Solidity out; you deploy it from your own demo wallet.{RESET}
""")


def step(num: int, text: str):
    print(f"\n{CYAN}{BOLD}[Step {num}]{RESET} {text}")


def ok(text: str):
    print(f"  {GREEN}✓{RESET} {text}")


def warn(text: str):
    print(f"  {YELLOW}⚠{RESET} {text}")


def fail(text: str):
    print(f"  {RED}✗{RESET} {text}")


# ── Example pseudocode contracts ────────────────────────────────────

EXAMPLE_PSEUDOCODE = """\
contract SimpleVault

    state owner: address
    state balances: map
    state totalDeposited: number

    event Deposited(address indexed depositor, uint256 amount)
    event Withdrawn(address indexed withdrawer, uint256 amount)

    function constructor()
        owner = msg.sender
        totalDeposited = 0

    payable function deposit()
        require(msg.value > 0, "Must send ETH")
        balances[msg.sender] += msg.value
        totalDeposited += msg.value
        emit Deposited(msg.sender, msg.value)

    function withdraw(amount: uint256)
        require(balances[msg.sender] >= amount, "Insufficient balance")
        balances[msg.sender] -= amount
        totalDeposited -= amount
        payable(msg.sender).transfer(amount)
        emit Withdrawn(msg.sender, amount)

    view function getBalance(account: address) -> uint256
        return balances[account]

    view function getTotalDeposited() -> uint256
        return totalDeposited
"""


# ── Core demo pipeline ─────────────────────────────────────────────

def run_demo(config: dict, source: str, source_lang: str = "pseudocode", template_name: str | None = None):
    """Execute the full contract conversion + deployment pipeline."""

    bc = config.get("blockchain", {})
    rpc_url = bc["rpc_url"]
    print("WARNING: demo.py uses your configured demo_wallet_private_key.")
    print("Never use a wallet with significant funds for demos.")
    print("Use a dedicated testnet wallet only.")
    print()
    private_key = bc["demo_wallet_private_key"]
    wallet_address = bc["demo_wallet_address"]
    chain_id = bc.get("chain_id", 84532)
    network = bc.get("network", "base-sepolia")

    # ── Step 1: Connect to Base Sepolia ──────────────────────────────
    step(1, "Connecting to Base Sepolia...")

    try:
        from web3 import Web3
        from eth_account import Account
    except ImportError:
        fail("Missing dependencies. Run: pip install web3 eth-account py-solc-x")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        fail(f"Cannot connect to RPC: {rpc_url}")
        fail("Check your rpc_url in matrix.config.json")
        sys.exit(1)

    ok(f"Connected to {network} (chain ID {chain_id})")

    block = w3.eth.block_number
    ok(f"Current block: {block:,}")

    # Check wallet balance
    balance_wei = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
    balance_eth = w3.from_wei(balance_wei, "ether")
    ok(f"Wallet: {wallet_address}")
    ok(f"Balance: {balance_eth:.6f} ETH")

    if balance_eth < 0.001:
        fail(f"Insufficient balance ({balance_eth:.6f} ETH). Need at least 0.001 ETH for gas.")
        fail("Get test ETH from: https://www.alchemy.com/faucets/base-sepolia")
        sys.exit(1)

    # ── Step 2: Parse / Generate Solidity ────────────────────────────
    step(2, "Generating Solidity from the parsed source...")

    from runtime.blockchain.services.contract_conversion.parser import SourceParser
    from runtime.blockchain.services.contract_conversion.generator import ContractGenerator
    from runtime.blockchain.services.contract_conversion.templates import get_template

    ir = None  # Will be set if parsing pseudocode/source

    if template_name:
        # Use a pre-built template
        solidity_source = get_template(template_name)
        if not solidity_source:
            fail(f"Unknown template: {template_name}")
            from runtime.blockchain.services.contract_conversion.templates import list_templates
            warn(f"Available: {', '.join(list_templates())}")
            sys.exit(1)

        # Fill in template placeholders
        contract_name = template_name.upper() + "Demo"
        solidity_source = solidity_source.replace("{{NAME}}", contract_name)
        solidity_source = solidity_source.replace("{{SYMBOL}}", template_name.upper()[:5])
        solidity_source = solidity_source.replace("{{MAX_SUPPLY}}", "1000000000000000000000000")  # 1M tokens (18 decimals)

        ok(f"Using template: {template_name}")
        ok(f"Contract name: {contract_name}")
    else:
        # Parse pseudocode/source into IR, then generate Solidity
        parser = SourceParser(config)
        generator = ContractGenerator(config)

        t0 = time.monotonic()
        ir = parser.parse(source, source_lang)
        solidity_source = generator.generate(ir, "base")
        elapsed = (time.monotonic() - t0) * 1000

        contract_name = ir.get("contract_name", "GeneratedContract")
        ok(f"Contract name: {contract_name}")
        ok(f"Functions: {len(ir.get('functions', []))}")
        ok(f"State variables: {len(ir.get('state_variables', []))}")
        ok(f"Events: {len(ir.get('events', []))}")
        ok(f"Conversion time: {elapsed:.1f}ms")

    print(f"\n{DIM}{'─' * 60}")
    print(f"Generated Solidity ({len(solidity_source.splitlines())} lines):")
    print(f"{'─' * 60}{RESET}")
    for i, line in enumerate(solidity_source.splitlines(), 1):
        print(f"  {DIM}{i:3d}{RESET}  {line}")
    print(f"{DIM}{'─' * 60}{RESET}")

    # ── Step 3: Compile with solc ────────────────────────────────────
    step(3, "Compiling with solc 0.8.24...")

    try:
        from solcx import compile_source, install_solc
    except ImportError:
        fail("py-solc-x not installed. Run: pip install py-solc-x")
        sys.exit(1)

    try:
        install_solc("0.8.24", show_progress=True)
        ok("solc 0.8.24 ready")
    except Exception as e:
        warn(f"solc install note: {e}")

    def _compile(source_text):
        return compile_source(source_text, output_values=["abi", "bin"], solc_version="0.8.24")

    choice = _source_to_deploy(solidity_source, _compile, contract_name,
                               ir=ir if not template_name else None, template_name=template_name)
    if choice["compile_error"]:
        fail(f"The generated source does not compile: {choice['compile_error']}")
    if choice["source"] is None:
        fail(choice["note"])
        sys.exit(1)
    stand_in = choice["stand_in"]
    solidity_source = choice["source"]
    compiled = choice["compiled"]
    if stand_in:
        warn(choice["note"])
        print(f"\n{DIM}{'─' * 60}")
        print("Stand-in Solidity (hand-written, not the converter's output):")
        print(f"{'─' * 60}{RESET}")
        for i, line in enumerate(solidity_source.splitlines(), 1):
            print(f"  {DIM}{i:3d}{RESET}  {line}")
        print(f"{DIM}{'─' * 60}{RESET}")

    # Get the first (or matching) contract
    contract_key = None
    for key in compiled:
        if contract_name in key:
            contract_key = key
            break
    if not contract_key:
        contract_key = next(iter(compiled))

    abi = compiled[contract_key]["abi"]
    bytecode = compiled[contract_key]["bin"]

    ok(f"Compiled: {contract_key}")
    ok(f"ABI entries: {len(abi)}")
    ok(f"Bytecode size: {len(bytecode) // 2} bytes")

    # ── Step 4: Deploy to Base Sepolia ───────────────────────────────
    step(4, "Deploying to Base Sepolia...")

    account = Account.from_key(private_key)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    try:
        # Build constructor transaction
        # For standalone contracts, constructor may need args
        # Our standalone ERC20 takes no args (owner is set in constructor)
        tx = contract.constructor().build_transaction({
            "from": Web3.to_checksum_address(wallet_address),
            "chainId": chain_id,
            "gas": 3_000_000,
            "gasPrice": w3.eth.gas_price,
            "nonce": w3.eth.get_transaction_count(Web3.to_checksum_address(wallet_address)),
        })

        ok("Transaction built")

        signed = account.sign_transaction(tx)
        ok("Transaction signed")

        print(f"  {YELLOW}...{RESET} Broadcasting transaction...")
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        ok(f"Tx hash: {tx_hash.hex()}")

        print(f"  {YELLOW}...{RESET} Waiting for confirmation...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if receipt["status"] == 1:
            ok(f"Deployment CONFIRMED in block {receipt['blockNumber']:,}")
        else:
            fail("Transaction reverted!")
            sys.exit(1)

    except Exception as e:
        fail(f"Deployment failed: {e}")
        sys.exit(1)

    contract_address = receipt["contractAddress"]
    gas_used = receipt["gasUsed"]
    gas_cost_wei = gas_used * receipt.get("effectiveGasPrice", w3.eth.gas_price)
    gas_cost_eth = w3.from_wei(gas_cost_wei, "ether")

    # ── Step 5: Results ──────────────────────────────────────────────
    step(5, "Deployment Complete!")

    explorer_base = "https://sepolia.basescan.org"

    print(f"""
{GREEN}{BOLD}{'=' * 60}
  {_deployment_headline(stand_in)}
{'=' * 60}{RESET}

  {BOLD}Contract:{RESET}    {contract_address}
  {BOLD}Network:{RESET}     Base Sepolia (chain {chain_id})
  {BOLD}Block:{RESET}       {receipt['blockNumber']:,}
  {BOLD}Gas used:{RESET}    {gas_used:,} ({gas_cost_eth:.6f} ETH)
  {BOLD}Tx hash:{RESET}     {tx_hash.hex()}

  {BOLD}Explorer:{RESET}    {explorer_base}/address/{contract_address}
  {BOLD}Tx link:{RESET}     {explorer_base}/tx/{tx_hash.hex()}

{DIM}  {_deployment_footnote(stand_in)}{RESET}
{GREEN}{'=' * 60}{RESET}
""")

    # Save deployment artifact
    artifact = {
        "contract_name": contract_name,
        "deployed_source": "stand-in" if stand_in else "converted",
        "contract_address": contract_address,
        "network": network,
        "chain_id": chain_id,
        "tx_hash": tx_hash.hex(),
        "block_number": receipt["blockNumber"],
        "gas_used": gas_used,
        "gas_cost_eth": str(gas_cost_eth),
        "abi": abi,
        "deployer": wallet_address,
        "timestamp": int(time.time()),
        "explorer_url": f"{explorer_base}/address/{contract_address}",
    }

    artifact_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_deployment.json")
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2)
    ok(f"Deployment artifact saved to: demo_deployment.json")

    return artifact


def _source_to_deploy(generated: str, compile_fn, contract_name: str, *,
                      ir: dict | None = None, template_name: str | None = None) -> dict:
    """Decide what the demo deploys: the generated source if it compiles, and
    otherwise a hand-written stand-in, named as one, or nothing.

    Returns ``source`` (None when nothing is deployed), ``compiled``,
    ``stand_in``, ``compile_error`` and a ``note`` saying what happened.
    """
    try:
        return {"source": generated, "compiled": compile_fn(generated), "stand_in": False,
                "compile_error": "", "note": "Deploying the converted contract."}
    except Exception as exc:  # the compiler's refusal, reported as it came
        error = str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__
    if template_name and template_name != "erc20":
        return {"source": None, "compiled": None, "stand_in": False, "compile_error": error,
                "note": (f"The {template_name} template imports OpenZeppelin, which this demo does "
                         "not supply, and the demo has no stand-in for it. Nothing was deployed. "
                         "Compile it with forge (remappings.txt) and deploy it yourself.")}
    stand_in = _make_standalone_contract(contract_name, "", ir)
    kind = "SimpleVault" if _wants_a_vault(ir) else "ERC-20"
    return {"source": stand_in, "compiled": compile_fn(stand_in), "stand_in": True,
            "compile_error": error,
            "note": (f"Deploying a hand-written {kind} stand-in instead. It is not the contract "
                     "the converter generated; the converted source is printed above.")}


def _deployment_headline(stand_in: bool) -> str:
    return ("STAND-IN CONTRACT DEPLOYED (not the converted contract)" if stand_in
            else "CONVERTED CONTRACT DEPLOYED")


def _deployment_footnote(stand_in: bool) -> str:
    return ("The converted source did not compile; this address holds the demo's hand-written "
            "stand-in." if stand_in else "Generated by The Matrix's contract converter; "
            "deployed from your demo wallet.")


def _make_standalone_contract(name: str, owner_address: str, ir: dict | None = None) -> str:
    """Generate a standalone deployable contract.

    If IR is provided and contains vault/deposit/withdraw patterns, generates a
    SimpleVault. Otherwise generates an ERC-20 token. All contracts compile
    standalone without OpenZeppelin.
    """
    if _wants_a_vault(ir):
        return _make_standalone_vault(name)
    return _make_standalone_erc20(name)


def _wants_a_vault(ir: dict | None) -> bool:
    """The parsed functions include deposit or withdraw."""
    func_names = {f["name"] for f in (ir or {}).get("functions", [])}
    return bool({"deposit", "withdraw"} & func_names)


def _make_standalone_vault(name: str) -> str:
    """Generate a standalone Vault/ETH store contract."""
    return f'''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title {name}
 * @notice ETH vault deployed via The Matrix on Base Sepolia.
 *         Users can deposit and withdraw ETH. Fully self-contained.
 */
contract {name} {{
    address public owner;
    uint256 public totalDeposited;

    mapping(address => uint256) public balanceOf;

    event Deposited(address indexed depositor, uint256 amount);
    event Withdrawn(address indexed withdrawer, uint256 amount);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {{
        require(msg.sender == owner, "Not owner");
        _;
    }}

    constructor() {{
        owner = msg.sender;
    }}

    function deposit() external payable {{
        require(msg.value > 0, "Must send ETH");
        balanceOf[msg.sender] += msg.value;
        totalDeposited += msg.value;
        emit Deposited(msg.sender, msg.value);
    }}

    function withdraw(uint256 amount) external {{
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        totalDeposited -= amount;
        (bool ok, ) = payable(msg.sender).call{{value: amount}}("");
        require(ok, "Transfer failed");
        emit Withdrawn(msg.sender, amount);
    }}

    function getBalance(address account) external view returns (uint256) {{
        return balanceOf[account];
    }}

    function getTotalDeposited() external view returns (uint256) {{
        return totalDeposited;
    }}

    receive() external payable {{
        balanceOf[msg.sender] += msg.value;
        totalDeposited += msg.value;
        emit Deposited(msg.sender, msg.value);
    }}
}}
'''


def _make_standalone_erc20(name: str) -> str:
    """Generate a standalone ERC-20 token that compiles without OpenZeppelin."""
    return f'''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title {name}
 * @notice Standalone ERC-20 token deployed via The Matrix on Base Sepolia.
 *         No external dependencies — fully self-contained.
 */
contract {name} {{
    string public name;
    string public symbol;
    uint8 public decimals = 18;
    uint256 public totalSupply;
    address public owner;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {{
        require(msg.sender == owner, "Not owner");
        _;
    }}

    constructor() {{
        name = "{name}";
        symbol = "{name[:5].upper()}";
        owner = msg.sender;

        // Mint 1,000,000 tokens to deployer
        uint256 initialSupply = 1_000_000 * 10 ** 18;
        totalSupply = initialSupply;
        balanceOf[msg.sender] = initialSupply;
        emit Transfer(address(0), msg.sender, initialSupply);
    }}

    function transfer(address to, uint256 amount) external returns (bool) {{
        require(to != address(0), "Transfer to zero");
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");

        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }}

    function approve(address spender, uint256 amount) external returns (bool) {{
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }}

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {{
        require(to != address(0), "Transfer to zero");
        require(balanceOf[from] >= amount, "Insufficient balance");
        require(allowance[from][msg.sender] >= amount, "Insufficient allowance");

        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
        return true;
    }}

    function mint(address to, uint256 amount) external onlyOwner {{
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
    }}

    function burn(uint256 amount) external {{
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        totalSupply -= amount;
        emit Transfer(msg.sender, address(0), amount);
    }}
}}
'''


# ── CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="The Matrix Live Demo — Smart Contract Conversion & Deployment",
    )
    parser.add_argument(
        "--example", action="store_true",
        help="Use the built-in SimpleVault example contract",
    )
    parser.add_argument(
        "--template", type=str, default=None,
        help="Try a template: deployed only if it compiles on its own (erc20 falls back to the ERC-20 stand-in)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and generate Solidity but don't deploy (no wallet needed)",
    )
    args = parser.parse_args()

    banner()

    # Load and validate config
    config = load_config()

    if not args.dry_run:
        missing = validate_config(config)
        if missing:
            fail("Missing config values in matrix.config.json:")
            for key in missing:
                fail(f"  blockchain.{key}")
            print(f"""
{YELLOW}To fix this, edit matrix.config.json and fill in:{RESET}

  "blockchain": {{
    "rpc_url": "https://base-sepolia.g.alchemy.com/v2/YOUR_KEY",
    "demo_wallet_private_key": "0xYOUR_PRIVATE_KEY",
    "demo_wallet_address": "0xYOUR_WALLET_ADDRESS",
    ...
  }}

{BOLD}Quick setup:{RESET}
  1. Get a free RPC URL:     https://www.alchemy.com/ (create app -> Base Sepolia)
  2. Create a demo wallet:   python -c "from eth_account import Account; a = Account.create(); print(f'Address: {{a.address}}\\nPrivate key: {{a.key.hex()}}')"
  3. Get test ETH:           https://www.alchemy.com/faucets/base-sepolia
  4. Paste into config and re-run: python demo.py --example
""")
            sys.exit(1)

    # Determine source
    if args.template:
        print(f"  Mode: {BOLD}Template deployment{RESET} ({args.template})")
        run_demo(config, "", template_name=args.template)
    elif args.example:
        print(f"  Mode: {BOLD}Example contract{RESET} (SimpleVault)")
        print(f"\n{DIM}  Input pseudocode:{RESET}")
        for line in EXAMPLE_PSEUDOCODE.strip().splitlines():
            print(f"    {DIM}{line}{RESET}")
        run_demo(config, EXAMPLE_PSEUDOCODE, source_lang="pseudocode")
    elif args.dry_run:
        print(f"  Mode: {BOLD}Dry run{RESET} (no deployment)")
        source = EXAMPLE_PSEUDOCODE
        print(f"\n{DIM}  Using built-in SimpleVault example...{RESET}")

        from runtime.blockchain.services.contract_conversion.parser import SourceParser
        from runtime.blockchain.services.contract_conversion.generator import ContractGenerator

        parser_obj = SourceParser(config)
        generator = ContractGenerator(config)

        ir = parser_obj.parse(source, "pseudocode")
        solidity = generator.generate(ir, "base")

        step(1, "Parsed pseudocode into IR")
        ok(f"Contract: {ir.get('contract_name')}")
        ok(f"Functions: {len(ir.get('functions', []))}")
        ok(f"State vars: {len(ir.get('state_variables', []))}")
        ok(f"Events: {len(ir.get('events', []))}")

        step(2, "Generated Solidity")
        print(f"\n{DIM}{'─' * 60}{RESET}")
        for i, line in enumerate(solidity.splitlines(), 1):
            print(f"  {DIM}{i:3d}{RESET}  {line}")
        print(f"{DIM}{'─' * 60}{RESET}")

        step(3, "Compilation check")
        try:
            from solcx import compile_source, install_solc
            install_solc("0.8.24", show_progress=False)
            compiled = compile_source(solidity, output_values=["abi", "bin"], solc_version="0.8.24")
            for key, data in compiled.items():
                ok(f"Compiled: {key} (bytecode: {len(data['bin']) // 2} bytes)")
            ok("Ready for deployment! Remove --dry-run to deploy.")
        except Exception as e:
            warn(f"Compilation: {e}")
            warn("Some pseudocode-generated contracts may need manual tweaks before compiling.")

        print(f"\n{GREEN}Dry run complete. No transactions were sent.{RESET}\n")
    else:
        # Interactive mode
        print(f"  Mode: {BOLD}Interactive{RESET}")
        print("\n  Write your contract as structured pseudocode: a `contract` line, `state name: type`")
        print("  lines and `function name(params)` lines. A paragraph of prose is not read.")
        print(f"  Type your contract below, then press {BOLD}Ctrl+D{RESET} (or {BOLD}Ctrl+Z{RESET} on Windows) when done:\n")

        try:
            lines = []
            while True:
                try:
                    line = input("  > ")
                    lines.append(line)
                except EOFError:
                    break
            source = "\n".join(lines)
        except KeyboardInterrupt:
            print(f"\n\n{YELLOW}Cancelled.{RESET}")
            sys.exit(0)

        if not source.strip():
            fail("No input provided. Try: python demo.py --example")
            sys.exit(1)

        print()
        run_demo(config, source, source_lang="pseudocode")


if __name__ == "__main__":
    main()
