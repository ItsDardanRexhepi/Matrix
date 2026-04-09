#!/usr/bin/env python3
"""
0pnMatrx — Interactive First-Boot Setup

Guides you through configuring 0pnMatrx on your machine.
Run once after cloning:

    python setup.py

Creates openmatrix.config.json with your settings, installs
dependencies, verifies connectivity, and boots the platform.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── ANSI Colors ─────────────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K"


def banner():
    print(f"""
{CYAN}{BOLD}
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║     ██████╗ ██████╗ ███╗   ██╗                               ║
    ║    ██╔═████╗██╔══██╗████╗  ██║  ╔╦╗╔═╗╔╦╗╦═╗═╗ ╦            ║
    ║    ██║██╔██║██████╔╝██╔██╗ ██║  ║║║╠═╣ ║ ╠╦╝╔╩╦╝            ║
    ║    ████╔╝██║██╔═══╝ ██║╚██╗██║  ╩ ╩╩ ╩ ╩ ╩╚═╩ ╚═            ║
    ║    ╚██████╔╝██║     ██║ ╚████║                               ║
    ║     ╚═════╝ ╚═╝     ╚═╝  ╚═══╝                               ║
    ║                                                              ║
    ║              Welcome to the Matrix                           ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
{RESET}""")


def step(num, total, text):
    print(f"\n{CYAN}{BOLD}[{num}/{total}]{RESET} {BOLD}{text}{RESET}")
    print(f"{DIM}{'─' * 60}{RESET}")


def ask(prompt, default="", secret=False, required=False, options=None):
    """Interactive prompt with default values and validation."""
    suffix = ""
    if options:
        suffix = f" ({'/'.join(options)})"
    elif default:
        suffix = f" [{default}]"

    while True:
        if secret:
            import getpass
            value = getpass.getpass(f"  {YELLOW}>{RESET} {prompt}{suffix}: ")
        else:
            value = input(f"  {YELLOW}>{RESET} {prompt}{suffix}: ").strip()

        if not value and default:
            return default
        if not value and required:
            print(f"  {RED}This field is required.{RESET}")
            continue
        if options and value.lower() not in [o.lower() for o in options]:
            print(f"  {RED}Choose one of: {', '.join(options)}{RESET}")
            continue
        return value


def success(text):
    print(f"  {GREEN}✓{RESET} {text}")


def warn(text):
    print(f"  {YELLOW}!{RESET} {text}")


def fail(text):
    print(f"  {RED}✗{RESET} {text}")


def info(text):
    print(f"  {DIM}{text}{RESET}")


def spinner(text, duration=1.0):
    """Simple progress indicator."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        print(f"\r  {CYAN}{frames[i % len(frames)]}{RESET} {text}", end="", flush=True)
        time.sleep(0.08)
        i += 1
    print(f"\r{CLEAR_LINE}", end="")


# ─── Setup Steps ─────────────────────────────────────────────────────────────

def check_python():
    """Verify Python version."""
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        fail(f"Python 3.10+ required. You have {v.major}.{v.minor}.{v.micro}")
        sys.exit(1)
    success(f"Python {v.major}.{v.minor}.{v.micro}")


def install_dependencies():
    """Install Python packages."""
    spinner("Installing dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail("Dependency installation failed")
        print(f"  {DIM}{result.stderr[:500]}{RESET}")
        return False

    # Install optional but recommended packages
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "pytest", "pytest-asyncio", "-q"],
        capture_output=True, text=True,
    )
    success("All dependencies installed")
    return True


def configure_model(config):
    """Set up AI model provider."""
    print(f"""
  {BOLD}Which AI model provider do you want to use?{RESET}

  {CYAN}1{RESET}  Ollama       {DIM}(free, local, private — recommended for getting started){RESET}
  {CYAN}2{RESET}  Anthropic    {DIM}(Claude models — best quality){RESET}
  {CYAN}3{RESET}  OpenAI       {DIM}(GPT models){RESET}
  {CYAN}4{RESET}  NVIDIA       {DIM}(NVIDIA AI endpoints){RESET}
  {CYAN}5{RESET}  Google       {DIM}(Gemini models){RESET}
""")

    choice = ask("Choose provider", default="1", options=["1", "2", "3", "4", "5"])

    providers = {
        "1": ("ollama", "llama3.1:8b"),
        "2": ("anthropic", "claude-sonnet-4-20250514"),
        "3": ("openai", "gpt-4o"),
        "4": ("nvidia", "meta/llama-3.1-70b-instruct"),
        "5": ("gemini", "gemini-pro"),
    }

    provider, default_model = providers[choice]
    config["model"] = {"provider": provider, "primary": default_model}

    if provider == "ollama":
        host = ask("Ollama host", default="http://localhost:11434")
        model = ask("Ollama model", default=default_model)
        config["model"]["ollama"] = {"host": host, "model": model}
        info("Make sure Ollama is running: ollama serve")
        info(f"Pull the model if needed: ollama pull {model}")
    elif provider == "anthropic":
        key = ask("Anthropic API key", secret=True, required=True)
        model = ask("Model", default=default_model)
        config["model"]["anthropic"] = {"api_key": key, "model": model}
    elif provider == "openai":
        key = ask("OpenAI API key", secret=True, required=True)
        model = ask("Model", default=default_model)
        config["model"]["openai"] = {"api_key": key, "model": model}
    elif provider == "nvidia":
        key = ask("NVIDIA API key", secret=True, required=True)
        model = ask("Model", default=default_model)
        config["model"]["nvidia"] = {"api_key": key, "model": model}
    elif provider == "gemini":
        key = ask("Google API key", secret=True, required=True)
        model = ask("Model", default=default_model)
        config["model"]["gemini"] = {"api_key": key, "model": model}

    success(f"Model provider: {provider} ({config['model'].get(provider, {}).get('model', default_model)})")


def configure_blockchain(config):
    """Set up blockchain connection."""
    print(f"""
  {BOLD}Blockchain Network{RESET}

  0pnMatrx runs on Base (Ethereum L2). Choose your network:

  {CYAN}1{RESET}  Base Sepolia  {DIM}(testnet — free, for development){RESET}
  {CYAN}2{RESET}  Base Mainnet  {DIM}(real money — for production){RESET}
  {CYAN}3{RESET}  Skip          {DIM}(configure blockchain later){RESET}
""")

    choice = ask("Choose network", default="1", options=["1", "2", "3"])

    if choice == "3":
        config["blockchain"] = {"enabled": False}
        warn("Blockchain skipped. Some features will be unavailable.")
        return

    networks = {
        "1": {
            "network": "base-sepolia",
            "chain_id": 84532,
            "rpc_url": "https://sepolia.base.org",
        },
        "2": {
            "network": "base",
            "chain_id": 8453,
            "rpc_url": "https://mainnet.base.org",
        },
    }

    net = networks[choice]
    rpc = ask("RPC URL", default=net["rpc_url"])
    net["rpc_url"] = rpc

    wallet = ask("Platform wallet address (optional, press Enter to skip)")
    if wallet:
        net["platform_wallet"] = wallet

    private_key = ""
    if wallet:
        private_key = ask("Wallet private key (for signing transactions)", secret=True)
        if private_key:
            net["platform_wallet_private_key"] = private_key

    config["blockchain"] = net
    config["blockchain"]["enabled"] = True
    success(f"Network: {net['network']} (chain {net['chain_id']})")


def configure_agents(config):
    """Set up agent configuration."""
    print(f"""
  {BOLD}Agent Configuration{RESET}

  0pnMatrx has three agents:
  • {CYAN}Trinity{RESET}  — your AI assistant (user-facing)
  • {CYAN}Neo{RESET}      — the execution engine (backend)
  • {CYAN}Morpheus{RESET} — the guardian (safety & guidance)
""")

    config["agents"] = {
        "neo": {"enabled": True},
        "trinity": {"enabled": True},
        "morpheus": {"enabled": True},
    }

    disable = ask("Disable any agents? (comma-separated, or Enter for all)", default="")
    if disable:
        for name in disable.split(","):
            name = name.strip().lower()
            if name in config["agents"]:
                config["agents"][name]["enabled"] = False
                warn(f"{name} disabled")

    success("Agents configured")


def configure_gateway(config):
    """Set up gateway server."""
    port = ask("Gateway port", default="18790")
    api_key = ask("API key for gateway auth (Enter to auto-generate, 'none' to disable)")

    if api_key.lower() == "none":
        api_key = ""
        warn("Gateway authentication disabled. Not recommended for production.")
    elif not api_key:
        import secrets
        api_key = f"omx_{secrets.token_hex(24)}"
        success(f"Generated API key: {BOLD}{api_key}{RESET}")
        info("Save this key — you'll need it to call the API.")

    config["gateway"] = {
        "port": int(port),
        "host": "0.0.0.0",
        "cors_origins": ["*"],
        "api_key": api_key,
        "rate_limit_rpm": 60,
        "rate_limit_burst": 15,
    }

    success(f"Gateway: http://localhost:{port}")


def configure_security(config):
    """Set up security settings."""
    config["security"] = {
        "block_on_critical": True,
        "block_on_high": False,
    }

    block_high = ask("Block deployment on HIGH severity audit findings too?", default="no", options=["yes", "no"])
    if block_high.lower() == "yes":
        config["security"]["block_on_high"] = True
        success("Blocking on CRITICAL + HIGH findings")
    else:
        success("Blocking on CRITICAL findings only")


def configure_extras(config):
    """Optional extras: timezone, memory."""
    tz = ask("Timezone", default="America/Los_Angeles")
    config["timezone"] = tz
    config["memory"] = {"max_turns": 200}
    config["max_steps"] = 10
    success(f"Timezone: {tz}")


def verify_setup(config):
    """Verify the setup works."""
    spinner("Verifying configuration...")

    # Check config is valid JSON
    try:
        json.dumps(config)
        success("Configuration is valid")
    except Exception as e:
        fail(f"Config validation failed: {e}")
        return False

    # Check model provider connectivity
    provider = config.get("model", {}).get("provider", "ollama")
    if provider == "ollama":
        host = config.get("model", {}).get("ollama", {}).get("host", "http://localhost:11434")
        try:
            import urllib.request
            req = urllib.request.urlopen(f"{host}/api/tags", timeout=5)
            if req.status == 200:
                success(f"Ollama connected at {host}")
            else:
                warn(f"Ollama returned status {req.status}")
        except Exception:
            warn(f"Cannot reach Ollama at {host}. Start it with: ollama serve")

    # Check blockchain RPC
    if config.get("blockchain", {}).get("enabled"):
        rpc = config["blockchain"].get("rpc_url", "")
        try:
            import urllib.request
            body = json.dumps({"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}).encode()
            req = urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())
            chain_id = int(data.get("result", "0x0"), 16)
            success(f"Blockchain RPC connected (chain {chain_id})")
        except Exception:
            warn(f"Cannot reach RPC at {rpc}. Check your network settings.")

    return True


def write_config(config):
    """Write the config file."""
    path = Path("openmatrix.config.json")
    if path.exists():
        overwrite = ask("openmatrix.config.json already exists. Overwrite?", default="no", options=["yes", "no"])
        if overwrite.lower() != "yes":
            warn("Setup cancelled. Existing config preserved.")
            return False

    path.write_text(json.dumps(config, indent=2) + "\n")
    success(f"Config written to {path}")
    return True


def setup_gitignore():
    """Ensure config file with real keys isn't committed."""
    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text()
        if "openmatrix.config.json" not in content:
            with open(gitignore, "a") as f:
                f.write("\n# Real config with secrets — never commit\nopenmatrix.config.json\n")
            success(".gitignore updated")
    else:
        gitignore.write_text("openmatrix.config.json\n__pycache__/\n*.pyc\n.env\n")
        success(".gitignore created")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    os.chdir(Path(__file__).parent)
    banner()

    print(f"  {DIM}This setup will guide you through configuring 0pnMatrx.{RESET}")
    print(f"  {DIM}Press Enter to accept defaults shown in [brackets].{RESET}")
    print(f"  {DIM}You can re-run this anytime to change settings.{RESET}")

    total = 8
    config = {}

    # Step 1: Python check
    step(1, total, "Checking environment")
    check_python()

    # Step 2: Install deps
    step(2, total, "Installing dependencies")
    install_dependencies()

    # Step 3: Model provider
    step(3, total, "AI Model Provider")
    configure_model(config)

    # Step 4: Blockchain
    step(4, total, "Blockchain Network")
    configure_blockchain(config)

    # Step 5: Agents
    step(5, total, "Agent Configuration")
    configure_agents(config)

    # Step 6: Gateway
    step(6, total, "Gateway Server")
    configure_gateway(config)

    # Step 7: Security
    step(7, total, "Security Settings")
    configure_security(config)

    # Step 8: Extras
    step(8, total, "Final Settings")
    configure_extras(config)

    # Write and verify
    print(f"\n{CYAN}{BOLD}{'═' * 60}{RESET}")
    step("✓", "✓", "Finalizing Setup")

    if not write_config(config):
        return

    setup_gitignore()
    verify_setup(config)

    # Done
    print(f"""
{GREEN}{BOLD}
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║                    Setup Complete                            ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
{RESET}
  {BOLD}To start 0pnMatrx:{RESET}

    {CYAN}python -m gateway.server{RESET}

  {BOLD}Then send a message:{RESET}

    {CYAN}curl -X POST http://localhost:{config.get('gateway', {}).get('port', 18790)}/chat \\
      -H "Content-Type: application/json" \\
      -H "Authorization: Bearer {config.get('gateway', {}).get('api_key', '<your-key>')}" \\
      -d '{{"agent": "trinity", "message": "Hello", "session_id": "demo"}}'{RESET}

  {BOLD}Or check health:{RESET}

    {CYAN}curl http://localhost:{config.get('gateway', {}).get('port', 18790)}/health{RESET}

  {DIM}Run 'python setup.py' again anytime to reconfigure.{RESET}
""")


if __name__ == "__main__":
    main()
