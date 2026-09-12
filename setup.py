#!/usr/bin/env python3
"""
0pnMatrx — Interactive First-Boot Setup

Guides you through configuring 0pnMatrx on your machine.
Run once after cloning:

    python3 setup.py          # or ./setup.py — the file is executable

Creates a virtual environment in .venv next to this file and re-launches
itself inside it, then creates openmatrix.config.json with your settings,
installs dependencies, verifies connectivity, and boots the platform.

Why the venv: macOS ships no `python`, and its `python3` is Apple's 3.9 or a
Homebrew build marked externally managed (PEP 668) that refuses
`pip install`. Debian and Fedora do the same. A project-local .venv works
everywhere and leaves the global interpreter alone (install.sh does the same).
Set OPNMATRX_SETUP_NO_VENV=1 to opt out (containers, CI).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── Interpreter bootstrap ───────────────────────────────────────────────────

PYTHON_FLOOR = (3, 10)   # the code uses `X | None` annotations at import time
VENV_DIR = ".venv"
_BOOTSTRAP_ENV = "OPNMATRX_SETUP_BOOTSTRAPPED"   # loop guard for the re-launch
_NO_VENV_ENV = "OPNMATRX_SETUP_NO_VENV"          # opt-out (containers, CI)

# setuptools executes a project's setup.py as __main__ during every build:
# `pip install .`, `pip install -e .`, `python -m build`. Those runs arrive
# with one of these as argv[1]. The wizard must hand them to setuptools
# instead of asking the operator questions from inside pip (which is exactly
# what happened before: banner, "Checking environment", EOFError).
SETUPTOOLS_COMMANDS = frozenset({
    "egg_info", "dist_info", "bdist_wheel", "editable_wheel", "sdist",
    "build", "build_py", "build_ext", "develop", "install", "clean",
    "--name", "--version", "--help-commands",
})


def invoked_by_setuptools(argv=None):
    argv = sys.argv if argv is None else argv
    return len(argv) > 1 and argv[1] in SETUPTOOLS_COMMANDS


def in_virtualenv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or hasattr(sys, "real_prefix")


def venv_python(root):
    root = Path(root)
    if os.name == "nt":
        return root / VENV_DIR / "Scripts" / "python.exe"
    return root / VENV_DIR / "bin" / "python3"


def python_meets_floor(v=None):
    v = sys.version_info if v is None else v
    return (v[0], v[1]) >= PYTHON_FLOOR


def bootstrap_venv(root=None, _exec=os.execv, _run=subprocess.run, _env=os.environ):
    """Make sure the wizard runs inside the project's own virtual environment.

    Returns True when there is nothing to do (already inside a venv, or the
    opt-out is set). Otherwise creates .venv if it is missing and replaces
    this process with the same command under the venv's interpreter — on
    success this never returns. The `_exec`/`_run`/`_env` seams exist for the
    tests; production callers pass nothing.
    """
    if in_virtualenv() or _env.get(_NO_VENV_ENV) == "1":
        return True
    root = Path(__file__).resolve().parent if root is None else Path(root)
    target = venv_python(root)
    if _env.get(_BOOTSTRAP_ENV) == "1":
        fail(f"Re-launched under {target} but still not inside a virtual environment.")
        info(f"Run it by hand:  python3 -m venv {VENV_DIR} && {target} setup.py")
        sys.exit(1)
    if not target.exists():
        if not python_meets_floor():
            v = sys.version_info
            fail(f"Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}+ is required to create the environment; "
                 f"this is {v[0]}.{v[1]}.{v[2]} ({sys.executable}).")
            info("Install a newer Python (macOS: brew install python) and run:  python3 setup.py")
            sys.exit(1)
        info(f"Creating {VENV_DIR}/ with {sys.executable} …")
        result = _run([sys.executable, "-m", "venv", str(root / VENV_DIR)], capture_output=True, text=True)
        if result.returncode != 0 or not target.exists():
            fail("Could not create the virtual environment.")
            print(f"  {DIM}{(result.stderr or '')[-500:]}{RESET}")
            sys.exit(1)
        success(f"Virtual environment created: {root / VENV_DIR}")
    info(f"Continuing under {target}")
    _env[_BOOTSTRAP_ENV] = "1"
    argv = [str(target), str(Path(__file__).resolve()), *sys.argv[1:]]
    if os.name == "nt":   # execv on Windows spawns and returns; wait for the child instead
        sys.exit(_run(argv).returncode)
    _exec(str(target), argv)
    return False   # reached only when _exec is a test double


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
    art = [
        " ██████╗ ██████╗ ███╗   ██╗  ███╗   ███╗ █████╗ ████████╗██████╗ ██╗  ██╗",
        "██╔═████╗██╔══██╗████╗  ██║  ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗╚██╗██╔╝",
        "██║██╔██║██████╔╝██╔██╗ ██║  ██╔████╔██║███████║   ██║   ██████╔╝ ╚███╔╝ ",
        "████╔╝██║██╔═══╝ ██║╚██╗██║  ██║╚██╔╝██║██╔══██║   ██║   ██╔══██╗ ██╔██╗ ",
        "╚██████╔╝██║     ██║ ╚████║  ██║ ╚═╝ ██║██║  ██║   ██║   ██║  ██║██╔╝ ██╗",
        " ╚═════╝ ╚═╝     ╚═╝  ╚═══╝  ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝",
    ]
    w = max(len(line) for line in art)
    art = [line.ljust(w) for line in art]
    inner = w + 4
    hr = "═" * inner
    pad = " " * inner
    wel = "Welcome to the Matrix".center(inner)
    rows = "\n".join(f"    ║{line.center(inner)}║" for line in art)
    print(f"""
{CYAN}{BOLD}    ╔{hr}╗
    ║{pad}║
{rows}
    ║{pad}║
    ║{wel}║
    ║{pad}║
    ╚{hr}╝
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
    """Verify the interpreter meets the floor.

    bootstrap_venv() has already re-launched us inside .venv by the time this
    runs; an old interpreter here means .venv was created by one.
    """
    v = sys.version_info
    if python_meets_floor():
        success(f"Python {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
        return
    fail(f"Python {PYTHON_FLOOR[0]}.{PYTHON_FLOOR[1]}+ required. You have {v.major}.{v.minor}.{v.micro}")
    info(f"Delete {VENV_DIR}/ and re-run with a newer interpreter, e.g.:  python3.12 setup.py")
    sys.exit(1)


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

    # The package itself, editable, so the `openmatrix` command the closing
    # banner advertises actually exists (inside .venv). Before this, setup
    # installed only requirements.txt and the command was never created.
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "-q"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        warn("Could not install the `openmatrix` command; `python -m cli` does the same job")
        print(f"  {DIM}{result.stderr[-500:]}{RESET}")
    else:
        success("`openmatrix` command installed")
    return True


def configure_model(config):
    """Set up AI model provider."""
    print(f"""
  {BOLD}Which AI model provider do you want to use?{RESET}

  {CYAN}1{RESET}  Ollama       {DIM}(free, local, private — recommended for getting started){RESET}
  {CYAN}2{RESET}  Anthropic    {DIM}(best quality){RESET}
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


def configure_communications(config):
    """Set up notification / communication channels.

    Delegates each channel to its dedicated configurator in ``setup/``. All
    nine channels (Telegram, Discord, Slack, Email, SMS, WhatsApp, Web chat,
    iOS push, Webhook) can be added here at first boot — and any of them
    can be added or updated later with:

        python3 setup_communications.py
    """
    print(f"""
  {BOLD}How should 0pnMatrx reach you?{RESET}
  {DIM}You can enable any combination of channels. Everything is optional.{RESET}
  {DIM}Rerun `python3 setup_communications.py` anytime to add more.{RESET}
""")

    # Lazy imports so this works even before the repo is fully installed.
    from setup import telegram as cfg_telegram
    from setup import discord as cfg_discord
    from setup import slack as cfg_slack
    from setup import email as cfg_email
    from setup import sms as cfg_sms
    from setup import whatsapp as cfg_whatsapp
    from setup import web_chat as cfg_web
    from setup import ios_push as cfg_ios
    from setup import webhook as cfg_webhook

    prompts = [
        ("Telegram",   "yes", cfg_telegram.configure),
        ("Discord",    "no",  cfg_discord.configure),
        ("Slack",      "no",  cfg_slack.configure),
        ("Email",      "no",  cfg_email.configure),
        ("SMS",        "no",  cfg_sms.configure),
        ("WhatsApp",   "no",  cfg_whatsapp.configure),
        ("Web chat",   "yes", cfg_web.configure),
        ("iOS push",   "no",  cfg_ios.configure),
        ("Webhook",    "no",  cfg_webhook.configure),
    ]
    from setup import _shared
    import copy

    for label, default, fn in prompts:
        pick = ask(f"Configure {label}?", default=default, options=["yes", "no"])
        if pick.lower().startswith("y"):
            # A channel module writes its config block and stages its .env
            # values BEFORE its last step (several send a test message). An
            # interrupt or error after that point used to print "Skipped." over
            # a half-configured channel that was then written out with
            # everything else. Snapshot both, and put both back.
            config_before = copy.deepcopy(config)
            env_before = _shared.pending_env()
            try:
                # persist=False: the wizard owns the write. Channel modules
                # mutate the dict and stage .env updates; only commit_setup()
                # touches disk, and only after the operator has agreed to
                # overwrite. RUN-1 was these nine calls each writing
                # immediately — and the .env half of it survived RUN-1.
                fn(config, persist=False)
            except (KeyboardInterrupt, Exception) as exc:
                config.clear()
                config.update(config_before)
                _shared.restore_pending_env(env_before)
                if isinstance(exc, KeyboardInterrupt):
                    info("Skipped — nothing from this channel was kept.")
                else:
                    info(f"{label} setup failed ({exc}); nothing from it was kept. Continuing.")

    # Ensure the unified "notifications" block exists even if empty.
    config.setdefault("notifications", {})
    if not config["notifications"]:
        info("No channels configured. Add them later with: python3 setup_communications.py")


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


def confirm_overwrite_upfront():
    """Ask about overwriting BEFORE the wizard does any work.

    Ordering is the point. As long as the only overwrite check sat at the end,
    every step before it was an opportunity for some writer to reach disk first
    — which is exactly what RUN-1 was. Asking at the top makes the safe path
    structural rather than a property of who happens to call what.

    Returns True to proceed, False if the operator wants their config left alone.
    """
    path = Path("openmatrix.config.json")
    if not path.exists():
        return True
    overwrite = ask(
        "openmatrix.config.json already exists. Overwrite it when setup finishes?",
        default="no", options=["yes", "no"],
    )
    if overwrite.lower() != "yes":
        warn("Setup cancelled. Existing config preserved — nothing was written.")
        return False
    return True


def write_config(config):
    """Write the config file. The ONLY writer in the wizard.

    Still re-checks rather than trusting confirm_overwrite_upfront(), so this
    stays safe if it is ever called from somewhere else.
    """
    path = Path("openmatrix.config.json")
    existed = path.exists()
    if existed:
        overwrite = ask("openmatrix.config.json already exists. Overwrite?", default="no", options=["yes", "no"])
        if overwrite.lower() != "yes":
            warn("Setup cancelled. Existing config preserved.")
            return False

    from setup._shared import CONFIG_NEW_FILE_MODE, _atomic_write_text   # keeps mode and symlinks
    _atomic_write_text(path, json.dumps(config, indent=2) + "\n", new_file_mode=CONFIG_NEW_FILE_MODE)
    success(f"Config written to {path}")
    if not existed:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            info(f"{path} holds your keys and was created mode {mode:o}, readable by other local "
                 f"accounts, because the Docker image reads it as uid 1000 (see docker-compose.yml).")
            info(f"Not deploying with Docker?  chmod 600 {path}")
    return True


def commit_setup(config):
    """Everything the wizard writes, in order, only once the operator agreed.

    The config first (write_config re-asks if one exists and returns False on
    "no"); then .gitignore, so .env is covered before it can exist; then the
    .env values the channel modules staged. Declining writes none of them.
    """
    from setup import _shared
    if not write_config(config):
        return False
    setup_gitignore()
    _shared.flush_pending_env()
    return True


# Files the wizard writes credentials into. BOTH branches of setup_gitignore()
# protect every one of them — they used to disagree, and the amend branch (the
# common one) never covered .env.
SECRET_FILES = ("openmatrix.config.json", ".env")


def _gitignore_pattern(raw):
    """The pattern git reads from one .gitignore line, or None for no pattern.

    Git drops one trailing CR and trailing SPACES that are not backslash-escaped.
    It keeps leading whitespace and tabs anywhere — `  .env` and `.env<TAB>` are
    patterns for other names — so neither is stripped here. A line whose
    trailing space is escaped comes back unstripped, which can only make it
    fail to match exactly (a redundant line), never match wrongly.
    """
    line = raw[:-1] if raw.endswith("\r") else raw
    stripped = line.rstrip(" ")
    if stripped != line and stripped.endswith("\\"):
        stripped = line
    if not stripped or stripped.startswith("#"):
        return None
    return stripped


def _negation_may_match(pattern, entry):
    """Could `!pattern` re-include the root-level file *entry*? Unsure means yes.

    Only a literal (no `*`, `?`, `[` or backslash) can be ruled out: it matches
    a root file only when, less a leading and trailing `/`, it is that name.
    """
    if any(ch in pattern for ch in "*?[\\"):
        return True
    return pattern.strip("/") == entry or not pattern.strip("/")


def _gitignore_covers(lines, entry):
    """True only if these .gitignore lines certainly ignore *entry* at the root.

    Git's last matching line wins. So *entry* is covered when an exact
    `entry` / `/entry` pattern is followed by no negation that could match it.
    Everything this cannot decide — a wildcard that would cover the file, a
    negation that might re-include it — counts as NOT covered, which costs one
    redundant line at the end of the file, where it is the last match and so
    wins. That is the only direction this is allowed to be wrong in; the
    first version stripped leading whitespace and recognised only a literal
    `!.env`, and said "covered" over files git would commit.
    """
    covered = False
    for raw in lines:
        pattern = _gitignore_pattern(raw)
        if pattern is None:
            continue
        if pattern.startswith("!"):
            if _negation_may_match(pattern[1:], entry):
                covered = False
        elif pattern in (entry, "/" + entry):
            covered = True
    return covered


def setup_gitignore():
    """Ensure the files holding real keys are never committed."""
    gitignore = Path(".gitignore")
    if not gitignore.exists():
        gitignore.write_text("\n".join(SECRET_FILES) + "\n__pycache__/\n*.pyc\n")
        success(".gitignore created")
        return

    # Raw bytes, split on "\n" only: git ends a line only at LF, and a lone CR
    # inside a line is part of its pattern. read_text()'s universal newlines
    # (or splitlines()) would turn "!.env\r.env" — one literal negation to git —
    # into a `.env` line that looks like coverage. Undecodable bytes become
    # U+FFFD, which matches no entry: a redundant line, not a false "covered".
    content = gitignore.read_bytes().decode("utf-8", "replace")
    missing = [e for e in SECRET_FILES if not _gitignore_covers(content.split("\n"), e)]
    if not missing:
        return
    with open(gitignore, "a") as f:
        if content and not content.endswith("\n"):
            f.write("\n")
        f.write("\n# Real config and credentials — never commit\n")
        f.write("".join(e + "\n" for e in missing))
    success(f".gitignore updated ({', '.join(missing)})")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    os.chdir(Path(__file__).resolve().parent)
    bootstrap_venv()   # re-launches under .venv/bin/python3 unless already inside a venv
    banner()

    print(f"  {DIM}This setup will guide you through configuring 0pnMatrx.{RESET}")
    print(f"  {DIM}Press Enter to accept defaults shown in [brackets].{RESET}")
    print(f"  {DIM}You can re-run this anytime to change settings.{RESET}")

    # RUN-1: ask before doing any work, not after. Declining nine steps in is
    # both a waste of the operator's time and — until the channel modules
    # stopped writing directly — a promise the wizard could not keep.
    if not confirm_overwrite_upfront():
        return 1

    total = 9
    config = {
        "platform": "0pnMatrx",
        "database": {"path": "data/0pnmatrx.db"},
    }

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

    # Step 7: Communications
    step(7, total, "Communication Channels")
    configure_communications(config)

    # Step 8: Security
    step(8, total, "Security Settings")
    configure_security(config)

    # Step 9: Extras
    step(9, total, "Final Settings")
    configure_extras(config)

    # Write and verify
    print(f"\n{CYAN}{BOLD}{'═' * 60}{RESET}")
    step("✓", "✓", "Finalizing Setup")

    if not commit_setup(config):
        return

    verify_setup(config)

    # Done
    port = config.get('gateway', {}).get('port', 18790)
    api_key = config.get('gateway', {}).get('api_key', '<your-key>')

    print(f"""
{GREEN}{BOLD}
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║                    Setup Complete                            ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
{RESET}
  {BOLD}Activate the environment (once per terminal):{RESET}

    {CYAN}source {VENV_DIR}/bin/activate{RESET}

  {BOLD}Start the gateway:{RESET}

    {CYAN}openmatrix gateway start{RESET}        Foreground (see logs live)
    {CYAN}openmatrix gateway start -d{RESET}     Background (daemon mode)

  {BOLD}Manage the gateway:{RESET}

    {CYAN}openmatrix gateway status{RESET}       Check if running
    {CYAN}openmatrix gateway stop{RESET}         Stop the gateway
    {CYAN}openmatrix gateway restart{RESET}      Restart
    {CYAN}openmatrix gateway logs -f{RESET}      Follow logs in real time
    {CYAN}openmatrix health{RESET}               Quick health check

  {BOLD}Send a message:{RESET}

    {CYAN}curl -X POST http://localhost:{port}/chat \\
      -H "Content-Type: application/json" \\
      -H "Authorization: Bearer {api_key}" \\
      -d '{{"agent": "trinity", "message": "Hello", "session_id": "demo"}}'{RESET}

  {DIM}Run 'openmatrix setup' anytime to reconfigure.{RESET}
""")


if __name__ == "__main__":
    if invoked_by_setuptools():
        # A pip/setuptools build is running this file — hand over. All the
        # package metadata lives in pyproject.toml.
        from setuptools import setup
        setup()
    else:
        sys.exit(main() or 0)
